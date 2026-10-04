"""Rastreo de webs de empresas con caché compartida por (dominio, pack) durante 30 días.

Las descargas se hacen en paralelo (cada web es de un servidor distinto, así no se carga a ninguno);
las escrituras en la base de datos, en el hilo principal.
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from knok.core.crawl.website import CrawlRules, crawl
from knok.core.domains import domain_of, pretty_name
from knok.core.http import Http, default_http
from knok.db.models import Company, CompanyEmail, Crawl, utcnow
from knok.packs.loader import pack_or_default
from knok.packs.schema import Pack
from knok.services import ingest
from knok.settings import get_settings
from knok.worker.queue import task

log = logging.getLogger("knok.crawl")
CRAWL_TTL = timedelta(days=30)
PARALLEL = 6


def cached(db: Session, dom: str, pack: str) -> Crawl | None:
    c = db.get(Crawl, (dom, pack))
    if c and c.fetched_at and c.fetched_at >= utcnow() - CRAWL_TTL:
        return c
    return None


def apply_result(db: Session, company: Company, pack: Pack, res: dict) -> dict:
    """Vuelca un rastreo en la empresa: buzones genéricos, página de empleo, ATS y señales del pack."""
    roles = frozenset(pack.crawl.extra_generic + pack.crawl.mailbox_priority)
    actuales = lambda: set(db.scalars(select(CompanyEmail.email).where(CompanyEmail.company_id == company.id)))
    antes = actuales()
    for e in res.get("emails", []):
        ingest.add_company_email(db, company, e["email"], e.get("url", ""), "crawl", e.get("on_careers_page", False), roles)
    db.flush()
    nuevos = len(actuales() - antes)
    if res.get("careers_url") and not company.careers_url:
        company.careers_url = res["careers_url"]
    if res.get("name") and company.name == pretty_name(company.domain or ""):
        company.name = res["name"]
    for a in res.get("ats", []):
        ingest.register_board(db, a["platform"], a["slug"], company, "crawl")
    flags = dict(company.flags or {})
    flags[pack.slug] = {"mentions": res.get("mentions", []), "signals": res.get("signals", []),
                        "warnings": res.get("warnings", []), "crawled_at": utcnow().isoformat()}
    flags["blocked"] = bool(res.get("blocked") or res.get("robots_blocked"))
    company.flags = flags
    return {"new_emails": nuevos, "careers": bool(res.get("careers_url")), "ats": len(res.get("ats", [])),
            "warnings": len(res.get("warnings", []))}


def crawl_companies(db: Session, companies: list[Company], pack: Pack, http: Http | None = None,
                    reuse: bool = True) -> dict:
    http = http or default_http()
    rules = CrawlRules.for_pack(pack)
    ua = get_settings().crawler_user_agent
    stats = {"crawled": 0, "reused": 0, "new_emails": 0, "careers": 0, "ats": 0, "blocked": 0, "warnings": 0}
    pendientes = []
    for c in companies:
        dom = c.domain or domain_of(c.website)
        if not dom:
            continue
        previo = cached(db, dom, pack.slug) if reuse else None
        if previo is not None:
            r = apply_result(db, c, pack, previo.result)
            stats["reused"] += 1
            for k in ("new_emails", "ats", "warnings"):
                stats[k] += r[k]
            stats["careers"] += int(r["careers"])
        else:
            pendientes.append((c, dom))

    def uno(par):
        c, dom = par
        try:
            return par, crawl(http, c.website or f"https://{dom}/", rules, ua)
        except Exception as ex:  # una web rota no para las demás
            log.warning("rastreo %s: %s", dom, ex)
            return par, None

    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        for (c, dom), res in pool.map(uno, pendientes):
            if res is None:
                continue
            if res.get("read") or res.get("blocked") or res.get("robots_blocked"):
                estado = "robots" if res.get("robots_blocked") else "blocked" if res.get("blocked") else "ok"
                fila = db.get(Crawl, (dom, pack.slug)) or Crawl(domain=dom, pack=pack.slug, status=estado)
                fila.status, fila.result, fila.fetched_at = estado, res, utcnow()
                db.add(fila)
            r = apply_result(db, c, pack, res)
            stats["crawled"] += 1
            stats["blocked"] += int(bool(res.get("blocked") or res.get("robots_blocked")))
            for k in ("new_emails", "ats", "warnings"):
                stats[k] += r[k]
            stats["careers"] += int(r["careers"])
    db.flush()
    return stats


@task("crawl_companies")
def crawl_companies_task(db: Session, payload: dict) -> dict:
    pack = pack_or_default(payload.get("pack"))
    ids = payload.get("company_ids") or []
    companies = list(db.scalars(select(Company).where(Company.id.in_(ids))))
    return crawl_companies(db, companies, pack, reuse=not payload.get("force"))
