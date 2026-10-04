"""Búsquedas: 1) ingesta compartida de las fuentes, 2) consulta y puntuación para el usuario, 3) enrutado.

La búsqueda NO envía nada: deja resultados con la vía decidida para que el usuario cree una tanda.
"""
import time
from datetime import timedelta

from sqlalchemy import delete, or_, select
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
from knok.services.progress import Cancelled, Progress
from knok.settings import get_settings
from knok.worker.queue import task

ALL_SOURCES = ("ats", "adzuna", "infojobs", "companies", "sample")
JOB_MAX_AGE = timedelta(days=60)
CANDIDATE_CAP = 5000


def default_sources() -> list[str]:
    if get_settings().offline_sources:
        return ["sample"]
    return ["ats", "adzuna", "infojobs", "companies"]


SOURCE_NAMES = {"ats": "tableros de empresas (Greenhouse, Lever, Ashby)", "adzuna": "Adzuna", "infojobs": "InfoJobs",
                "sample": "datos de ejemplo", "companies": "fuentes de empresas del nicho"}


def run_ingest(db: Session, search: Search, pack: Pack, progress: Progress | None = None) -> dict:
    p = search.params
    http = default_http()
    stats = {}
    fuentes = p.get("sources") or default_sources()
    if get_settings().offline_sources:
        fuentes = [f for f in fuentes if f in ("sample",)] or ["sample"]
    countries, keywords = p.get("countries") or [], p.get("keywords") or []
    for f in fuentes:
        if progress:
            progress.phase(f"Buscando en {SOURCE_NAMES.get(f, f)}")
            progress.check_cancel()
        def leer(f=f):
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
                stats["companies"] = ingest_companies(db, http, pack, p, progress)

        try:
            if progress and not progress.eager:
                leer()
                db.commit()          # cada fuente se guarda en cuanto termina
            else:
                with db.begin_nested():
                    leer()
        except Cancelled:
            raise
        except Exception as ex:  # una fuente caída no para la búsqueda (se deshace solo lo de esa fuente)
            if progress and not progress.eager:
                db.rollback()
            stats[f] = {"error": f"{type(ex).__name__}: {ex}"}
            log_event(db, search.user_id, f"Fuente {f}: no disponible ahora ({ex})", "warning")
        if progress:
            progress.checkpoint(force=True)
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


def save_results(db: Session, search: Search, pack: Pack, profile: Profile) -> dict:
    """(Re)calcula los resultados de la búsqueda con lo que hay ahora en la base común."""
    db.execute(delete(SearchResult).where(SearchResult.search_id == search.id))
    resultados = rank_jobs(db, search, pack, profile)
    if search.params.get("include_companies", True):
        from knok.services.prospecting import rank_companies
        resultados += rank_companies(db, search, pack, profile, {r.company_id for r in resultados if r.company_id})
    resultados.sort(key=lambda r: -r.score)
    maximo = int(search.params.get("max_results") or 500)
    rutas: dict[str, int] = {}
    for r in resultados[:maximo]:
        db.add(r)
        rutas[r.route] = rutas.get(r.route, 0) + 1
    db.flush()
    return {"results": min(len(resultados), maximo), "matched": len(resultados), "routes": rutas}


def _execute(db: Session, search: Search, pack: Pack, profile: Profile, progress: Progress) -> None:
    ingest_stats = run_ingest(db, search, pack, progress)
    search.stats = {**(search.stats or {}), "sources": ingest_stats, **save_results(db, search, pack, profile)}
    progress.checkpoint(force=True)

    p = search.params
    crawl_stats = {}
    max_webs = int(p.get("max_webs", 200) or 0)
    if "companies" in (p.get("sources") or default_sources()) and max_webs > 0 \
            and not get_settings().offline_sources:
        from knok.services.prospecting import crawl_pending
        progress.check_cancel()
        ultimo = [time.monotonic()]

        def refrescar_resultados():
            # Mientras rastrea, los resultados se recalculan cada poco para que el panel los vaya viendo
            if time.monotonic() - ultimo[0] > 15:
                search.stats = {**search.stats, **save_results(db, search, pack, profile)}
                ultimo[0] = time.monotonic()

        progress.on_checkpoint = refrescar_resultados
        crawl_stats = crawl_pending(db, default_http(), pack, p.get("countries") or [], max_webs, progress)
        progress.on_checkpoint = None
    search.stats = {**search.stats, "crawl": crawl_stats, **save_results(db, search, pack, profile)}
    search.status, search.finished_at = "done", utcnow()
    progress.data.update(phase="Terminado", done=progress.data["total"])
    pendientes = crawl_stats.get("pending_after", 0)
    log_event(db, search.user_id, f"Búsqueda terminada: {search.stats['results']} resultados"
              + (f" ({crawl_stats.get('crawled', 0)} webs rastreadas; quedan {pendientes} para la próxima búsqueda)"
                 if crawl_stats else "") + ".", "ok", search_id=search.id)
    progress.checkpoint(force=True)


@task("run_search")
def run_search_task(db: Session, payload: dict) -> dict:
    search = db.get(Search, payload["search_id"])
    if search is None:
        return {"missing": True}
    if search.status == "cancelling":
        search.status, search.finished_at = "cancelled", utcnow()
        return {"cancelled": True}
    profile = db.get(Profile, search.user_id)
    pack = pack_or_default(search.params.get("pack"))
    search.status = "running"
    progress = Progress(db, search)
    progress.checkpoint(force=True)
    try:
        if progress.eager:   # tests / demos: todo en una transacción que se deshace entera si falla
            with db.begin_nested():
                _execute(db, search, pack, profile, progress)
        else:
            _execute(db, search, pack, profile, progress)
    except Cancelled:
        search.stats = {**(search.stats or {}), **save_results(db, search, pack, profile)}
        search.status, search.finished_at = "cancelled", utcnow()
        progress.data.update(phase="Detenida")
        log_event(db, search.user_id, "Búsqueda detenida. Lo ya rastreado se conserva.", "warning", search_id=search.id)
        progress.checkpoint(force=True)
        return {"cancelled": True}
    except Exception as ex:
        if not progress.eager:
            db.rollback()
            search = db.get(Search, payload["search_id"])
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
