"""Búsquedas: 1) ingesta compartida de las fuentes, 2) consulta y puntuación para el usuario, 3) enrutado.

La búsqueda NO envía nada: deja resultados con la vía decidida para que el usuario cree una tanda.
"""
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from knok.core.http import default_http
from knok.core.matching import score_job
from knok.core.routing.router import RouteInput, decide
from knok.db.models import Application, Job, OAuthAccount, Profile, Search, SearchResult, utcnow
from knok.packs.loader import pack_or_default
from knok.packs.schema import Pack
from knok.services import sources
from knok.services.companies import best_emails
from knok.services.events import log_event
from knok.settings import get_settings
from knok.worker.queue import task

ALL_SOURCES = ("ats", "adzuna", "infojobs", "companies", "sample")
JOB_MAX_AGE = timedelta(days=60)
CANDIDATE_CAP = 5000


def default_sources() -> list[str]:
    if get_settings().offline_sources:
        return ["sample"]
    return ["ats", "adzuna", "infojobs", "companies"]


def run_ingest(db: Session, search: Search, pack: Pack) -> dict:
    p = search.params
    http = default_http()
    stats = {}
    fuentes = p.get("sources") or default_sources()
    if get_settings().offline_sources:
        fuentes = [f for f in fuentes if f in ("sample",)] or ["sample"]
    countries, keywords = p.get("countries") or [], p.get("keywords") or []
    for f in fuentes:
        try:
            with db.begin_nested():
                if f == "ats":
                    stats["ats"] = sources.ingest_ats(db, http, pack)
                elif f == "adzuna":
                    stats["adzuna"] = sources.ingest_adzuna(db, http, pack, countries, keywords)
                elif f == "infojobs":
                    stats["infojobs"] = sources.ingest_infojobs(db, http, pack, countries, keywords)
                elif f == "sample":
                    stats["sample"] = sources.ingest_sample(db, pack)
                elif f == "companies":
                    from knok.services.prospecting import ingest_companies
                    stats["companies"] = ingest_companies(db, http, pack, p)
        except Exception as ex:  # una fuente caída no para la búsqueda
            stats[f] = {"error": f"{type(ex).__name__}: {ex}"}
            log_event(db, search.user_id, f"Fuente {f}: no disponible ahora ({ex})", "warning")
    return stats


def _excluded_jobs(db: Session, user_id: int, mode: str) -> set[int]:
    return set(db.scalars(select(Application.job_id).where(Application.user_id == user_id, Application.mode == mode,
                                                           Application.job_id.is_not(None))))


def rank_jobs(db: Session, search: Search, pack: Pack, profile: Profile) -> list[SearchResult]:
    p = search.params
    countries, cities, keywords = p.get("countries") or [], p.get("cities") or [], p.get("keywords") or []
    include_remote = p.get("include_remote", True)
    q = select(Job).where(Job.canonical_job_id.is_(None), Job.closed_at.is_(None),
                          Job.last_seen_at >= utcnow() - JOB_MAX_AGE)
    if countries:
        q = q.where(or_(Job.country.in_(countries), Job.country == "", Job.remote.is_(True)))
    if get_settings().offline_sources or "sample" in (p.get("sources") or []):
        pass  # en Simulación sin red se incluyen los datos de ejemplo
    else:
        q = q.where(Job.source != "sample")
    q = q.order_by(Job.last_seen_at.desc()).limit(CANDIDATE_CAP)
    ya = _excluded_jobs(db, search.user_id, profile.mode)
    ij = db.scalar(select(OAuthAccount.id).where(OAuthAccount.user_id == search.user_id,
                                                 OAuthAccount.provider == "infojobs")) is not None
    roles = frozenset(pack.crawl.extra_generic + pack.crawl.mailbox_priority)
    out = []
    for j in db.scalars(q):
        if j.id in ya:
            continue
        m = score_job(title=j.title, description=j.description, country=j.country, city=j.city, remote=j.remote,
                      posted_at=j.posted_at, match=pack.match, keywords=keywords, countries=countries,
                      cities=cities, include_remote=include_remote)
        if not m.matched:
            continue
        d = decide(RouteInput(has_job=True, source=j.source, apply_url=j.apply_url, url=j.url,
                              easy_apply=j.easy_apply, apply_email=j.apply_email,
                              company_emails=best_emails(db, j.company, pack), infojobs_connected=ij,
                              extra_roles=roles))
        # Las que se pueden preparar (formulario, API o correo) van antes que las manuales
        bonus = {"ats_extension": 15, "portal_api": 12, "email": 10, "portal_copilot": 5}.get(d.route, 0)
        out.append(SearchResult(search_id=search.id, job_id=j.id, company_id=j.company_id, score=m.score + bonus,
                                route=d.route, platform=d.platform, reasons=m.reasons + [d.reason]))
    return out


def create_search(db: Session, profile: Profile, params: dict) -> Search:
    pack = pack_or_default(params.get("pack") or profile.pack)
    params = {**params, "pack": pack.slug}
    if not params.get("countries"):
        params["countries"] = pack.sources.default_countries
    s = Search(user_id=profile.user_id, params=params, status="queued")
    db.add(s)
    db.flush()
    from knok.worker.queue import enqueue
    enqueue(db, "run_search", {"search_id": s.id}, user_id=profile.user_id, max_attempts=1)
    return s


@task("run_search")
def run_search_task(db: Session, payload: dict) -> dict:
    search = db.get(Search, payload["search_id"])
    if search is None:
        return {"missing": True}
    profile = db.get(Profile, search.user_id)
    pack = pack_or_default(search.params.get("pack"))
    search.status = "running"
    db.flush()
    try:
        with db.begin_nested():  # si algo falla, se deshace solo lo de esta búsqueda y queda marcada con error
            ingest_stats = run_ingest(db, search, pack)
            resultados = rank_jobs(db, search, pack, profile)
            if search.params.get("include_companies", True):
                from knok.services.prospecting import rank_companies
                resultados += rank_companies(db, search, pack, profile)
            resultados.sort(key=lambda r: -r.score)
            maximo = int(search.params.get("max_results") or 200)
            rutas: dict[str, int] = {}
            for r in resultados[:maximo]:
                db.add(r)
                rutas[r.route] = rutas.get(r.route, 0) + 1
            search.stats = {"sources": ingest_stats, "results": min(len(resultados), maximo),
                            "matched": len(resultados), "routes": rutas}
            search.status = "done"
            search.finished_at = utcnow()
        log_event(db, search.user_id, f"Búsqueda terminada: {search.stats['results']} resultados.", "ok",
                  search_id=search.id)
    except Exception as ex:
        search.status, search.error, search.finished_at = "error", f"{type(ex).__name__}: {ex}", utcnow()
        log_event(db, search.user_id, f"La búsqueda falló: {ex}", "error", search_id=search.id)
        return {"error": search.error}
    return {"results": search.stats.get("results", 0)}


@task("refresh_ats_boards")
def refresh_ats_boards_task(db: Session, payload: dict) -> dict:
    """Periódica: mantiene frescos los tableros del catálogo aunque nadie busque."""
    if get_settings().offline_sources:
        return {"skipped": "offline"}
    return sources.ingest_ats(db, default_http(), pack_or_default("general"), budget=int(payload.get("budget", 50)))
