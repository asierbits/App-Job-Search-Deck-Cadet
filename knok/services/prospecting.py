"""Empresas sin oferta publicada → correo directo.

Fuentes del pack (Wikidata, directorios, OpenStreetMap alrededor de las ciudades), con caché compartida,
y después rastreo de sus webs para encontrar el buzón genérico. El rastreo de la búsqueda tiene un
presupuesto pequeño; el resto se encola en segundo plano y aparece en las siguientes búsquedas.
"""
import re
from datetime import timedelta

from sqlalchemy import String, cast, or_, select
from sqlalchemy.orm import Session

from knok.core.geo import city_key
from knok.core.http import Http
from knok.core.routing.router import RouteInput, decide
from knok.core.sources import directories, osm, wikidata
from knok.db.models import Application, Company, Crawl, Profile, Search, SearchResult, utcnow
from knok.packs.schema import Pack
from knok.services import ingest, sources
from knok.services.companies import best_emails
from knok.settings import get_settings
from knok.worker.queue import enqueue

CACHE = {"wikidata": timedelta(days=7), "directory": timedelta(days=7), "osm": timedelta(days=30)}
CRAWL_BUDGET = 12          # webs rastreadas durante la búsqueda; el resto, en segundo plano
BACKGROUND_CHUNK = 20


def _cached_or_run(db: Session, source: str, query: dict, fn) -> dict:
    key = sources.query_key(source, query)
    if sources.recent_run(db, source, key, CACHE[source]):
        return {"cached": True}
    try:
        empresas = fn()
    except Exception as ex:
        sources.record_run(db, source, query, status="error", calls=1, error=str(ex))
        return {"error": str(ex)[:200]}
    for c in empresas:
        ingest.upsert_company(db, c, query["pack"])
    sources.record_run(db, source, query, calls=1, stats={"companies": len(empresas)})
    return {"companies": len(empresas)}


def is_excluded(pack: Pack, nombre: str) -> bool:
    if not pack.crawl.exclude_names:
        return False
    return bool(re.search(r"\b(?:" + "|".join(pack.crawl.exclude_names) + r")\b", nombre or "", re.I))


def ingest_companies(db: Session, http: Http, pack: Pack, params: dict) -> dict:
    stats: dict = {}
    s = pack.sources
    ua = get_settings().crawler_user_agent
    if s.wikidata.queries:
        stats["wikidata"] = _cached_or_run(db, "wikidata", {"pack": pack.slug, "countries": sorted(s.wikidata.countries)},
                                           lambda: wikidata.search(http, s.wikidata))
    for d in s.directories:
        stats[f"directory:{d.url[:60]}"] = _cached_or_run(
            db, "directory", {"pack": pack.slug, "url": d.url},
            lambda d=d: directories.read_directory(http, d.url, d.country, pack.crawl.exclude_domains,
                                                   pack.crawl.allowed_countries, ua))
    if s.osm.tags:
        for ciudad in params.get("cities") or []:
            radio = float(params.get("radius_km") or 10)
            stats[f"osm:{ciudad}"] = _cached_or_run(db, "osm", {"pack": pack.slug, "city": ciudad.lower(), "radius": radio},
                                                    lambda c=ciudad: osm.search_city(http, c, radio, s.osm))
    stats["crawl"] = crawl_pending(db, http, pack, params.get("countries") or [])
    return stats


def _pack_filter(slug: str):
    return cast(Company.packs, String).like(f'%"{slug}"%')


def crawl_pending(db: Session, http: Http, pack: Pack, countries: list[str], budget: int = CRAWL_BUDGET) -> dict:
    """Rastrea las webs aún no rastreadas para este pack (primero las de los países pedidos)."""
    from knok.services.crawling import crawl_companies
    rastreadas = select(Crawl.domain).where(Crawl.pack == pack.slug, Crawl.fetched_at >= utcnow() - timedelta(days=30))
    q = select(Company).where(_pack_filter(pack.slug), Company.domain.is_not(None), Company.website != "",
                              Company.domain.not_in(rastreadas))
    if countries:
        q = q.where(or_(Company.country.in_(countries), Company.country == ""))
    candidatas = [c for c in db.scalars(q.order_by(Company.id).limit(500)) if not is_excluded(pack, c.name)]
    ahora, despues = candidatas[:budget], candidatas[budget:]
    stats = crawl_companies(db, ahora, pack, http) if ahora else {"crawled": 0}
    for i in range(0, len(despues), BACKGROUND_CHUNK):
        enqueue(db, "crawl_companies", {"pack": pack.slug, "company_ids": [c.id for c in despues[i:i + BACKGROUND_CHUNK]]})
    stats["queued"] = len(despues)
    return stats


def rank_companies(db: Session, search: Search, pack: Pack, profile: Profile,
                   with_jobs: set[int] | None = None) -> list[SearchResult]:
    """with_jobs: empresas que ya salen en la búsqueda con una oferta (no se repiten como 'solo empresa')."""
    p = search.params
    countries, cities = p.get("countries") or [], p.get("cities") or []
    offline = get_settings().offline_sources or "sample" in (p.get("sources") or [])
    q = select(Company).where(_pack_filter(pack.slug))
    if countries:
        q = q.where(or_(Company.country.in_(countries), Company.country == ""))
    ya = set(db.scalars(select(Application.company_id).where(Application.user_id == profile.user_id,
                                                             Application.mode == profile.mode)))
    con_oferta = with_jobs or set()
    claves_ciudad = {city_key(c) for c in cities}
    out = []
    for c in db.scalars(q.order_by(Company.id).limit(5000)):
        if c.id in ya or c.id in con_oferta or is_excluded(pack, c.name):
            continue
        if not offline and c.sources == ["sample"]:
            continue
        emails = best_emails(db, c, pack)
        d = decide(RouteInput(has_job=False, company_emails=emails, careers_url=c.careers_url,
                              extra_roles=frozenset(pack.crawl.extra_generic + pack.crawl.mailbox_priority)))
        if d.route == "manual" and not d.apply_url:
            continue
        flags = (c.flags or {}).get(pack.slug, {})
        puntos, motivos = 10, []
        if d.route == "email":
            puntos += 20
            motivos.append(f"buzón genérico: {d.contact_email}")
            prioridad = pack.crawl.mailbox_priority[:6]
            if any(d.contact_email.split("@")[0].startswith(x) for x in prioridad):
                puntos += 10
                motivos.append("buzón preferido del nicho")
        for m in flags.get("mentions", [])[:2]:
            puntos += 15
            motivos.append(f"su web menciona «{m}»")
        for s in flags.get("signals", [])[:1]:
            puntos += 10
            motivos.append(s)
        if flags.get("warnings"):
            puntos -= 30
            motivos.append("⚠ revisar: " + ", ".join(sorted({w["type"] for w in flags["warnings"]})))
        if claves_ciudad and city_key(c.city) in claves_ciudad:
            puntos += 15
            motivos.append(f"en {c.city}")
        out.append(SearchResult(search_id=search.id, job_id=None, company_id=c.id, score=puntos, route=d.route,
                                platform=d.platform, reasons=motivos + [d.reason]))
    return out
