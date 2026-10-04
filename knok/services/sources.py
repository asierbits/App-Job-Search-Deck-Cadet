"""Lectura de fuentes hacia la base común, compartida entre usuarios y con control de cuotas.

Cada lectura queda en `source_runs` con una clave (fuente + consulta). Si otra búsqueda pide lo mismo
dentro del periodo de validez, se reutiliza lo ya guardado sin volver a llamar a la fuente.
"""
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from knok.core.http import Http, HttpError
from knok.core.sources import adzuna, infojobs
from knok.core.sources.ats import FETCHERS
from knok.core.sources.base import RawCompany, RawJob, parse_dt
from knok.db.models import AtsBoard, SourceRun, utcnow
from knok.packs.loader import PACKS_DIR
from knok.packs.schema import Pack
from knok.services import ingest
from knok.settings import get_settings

log = logging.getLogger("knok.sources")

BOARD_MAX_AGE = timedelta(hours=6)
CACHE = {"adzuna": timedelta(hours=24), "infojobs": timedelta(hours=12), "sample": timedelta(minutes=1)}


def query_key(source: str, query: dict) -> str:
    return hashlib.sha1((source + json.dumps(query, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()


def recent_run(db: Session, source: str, key: str, max_age: timedelta) -> SourceRun | None:
    return db.scalars(select(SourceRun).where(SourceRun.source == source, SourceRun.query_key == key,
                                              SourceRun.status == "ok", SourceRun.ran_at >= utcnow() - max_age)
                      .order_by(SourceRun.ran_at.desc()).limit(1)).first()


def record_run(db: Session, source: str, query: dict, status: str = "ok", calls: int = 0, stats: dict | None = None,
               error: str = "") -> SourceRun:
    r = SourceRun(source=source, query_key=query_key(source, query), query=query, status=status, calls_used=calls,
                  stats=stats or {}, error=error[:2000])
    db.add(r)
    db.flush()
    return r


def calls_this_month(db: Session, source: str) -> int:
    inicio = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return db.scalar(select(func.coalesce(func.sum(SourceRun.calls_used), 0))
                     .where(SourceRun.source == source, SourceRun.ran_at >= inicio)) or 0


# ------------------------------------------------------------------------------------- ATS

def refresh_board(db: Session, http: Http, board: AtsBoard, pack: str = "") -> dict:
    fetch = FETCHERS.get(board.ats)
    if fetch is None:
        return {"skipped": True}
    board.last_checked_at = utcnow()
    try:
        nombre, jobs = fetch(http, board.slug)
    except HttpError as ex:
        if ex.status == 404:
            board.status = "invalid"
            return {"invalid": True}
        raise
    for j in jobs:
        if nombre and not j.company_name:
            j.company_name = nombre
        ingest.upsert_job(db, j, pack)
    cerradas = ingest.close_missing(db, board.ats, f"{board.slug}:", {j.source_job_id for j in jobs})
    board.jobs_count = len(jobs)
    board.status = "active" if jobs else "empty"
    return {"jobs": len(jobs), "closed": cerradas}


def ingest_ats(db: Session, http: Http, pack: Pack, budget: int = 25) -> dict:
    """Refresca los tableros más antiguos del catálogo (y los semilla del pack), hasta `budget` tableros."""
    for seed in pack.sources.ats.seed_boards:
        ingest.register_board(db, seed.get("ats", ""), seed.get("slug", ""), None, "seed")
    limite = utcnow() - BOARD_MAX_AGE
    boards = list(db.scalars(
        select(AtsBoard).where(AtsBoard.status.in_(("pending", "active", "empty")),
                               or_(AtsBoard.last_checked_at.is_(None), AtsBoard.last_checked_at < limite))
        .order_by(AtsBoard.last_checked_at.is_not(None), AtsBoard.last_checked_at).limit(budget)))
    stats = {"boards": 0, "jobs": 0, "errors": 0, "invalid": 0}
    for b in boards:
        try:
            with db.begin_nested():
                r = refresh_board(db, http, b, pack.slug)
            stats["boards"] += 1
            stats["jobs"] += r.get("jobs", 0)
            stats["invalid"] += int(bool(r.get("invalid")))
        except Exception as ex:  # un tablero caído no para el resto
            stats["errors"] += 1
            log.warning("tablero %s/%s: %s", b.ats, b.slug, ex)
    record_run(db, "ats", {"pack": pack.slug, "budget": budget}, calls=stats["boards"], stats=stats)
    return stats


# ------------------------------------------------------------------------------------- Adzuna

def ingest_adzuna(db: Session, http: Http, pack: Pack, countries: list[str], keywords: list[str],
                  max_calls: int = 6) -> dict:
    s = get_settings()
    if not (s.adzuna_app_id and s.adzuna_app_key):
        return {"skipped": "sin credenciales (KNOK_ADZUNA_APP_ID / KNOK_ADZUNA_APP_KEY)"}
    terminos = list(dict.fromkeys((keywords or []) + pack.sources.adzuna.what))[:3]
    paises = [c for c in (countries or pack.sources.adzuna.countries) if c in adzuna.COUNTRIES][:3]
    stats = {"calls": 0, "jobs": 0, "cached": 0, "quota_left": 0}
    for pais in paises:
        for what in terminos:
            consulta = {"country": pais, "what": what}
            key = query_key("adzuna", consulta)
            if recent_run(db, "adzuna", key, CACHE["adzuna"]):
                stats["cached"] += 1
                continue
            usadas = calls_this_month(db, "adzuna")
            if usadas >= s.adzuna_monthly_quota or stats["calls"] >= max_calls:
                stats["quota_left"] = max(0, s.adzuna_monthly_quota - usadas)
                stats["stopped"] = "cuota mensual o límite por búsqueda"
                return stats
            try:
                jobs = adzuna.search(http, s.adzuna_app_id, s.adzuna_app_key, pais, what)
                for j in jobs:
                    ingest.upsert_job(db, j, pack.slug)
                record_run(db, "adzuna", consulta, calls=1, stats={"jobs": len(jobs)})
                stats["jobs"] += len(jobs)
            except Exception as ex:
                record_run(db, "adzuna", consulta, status="error", calls=1, error=str(ex))
            stats["calls"] += 1
    stats["quota_left"] = max(0, s.adzuna_monthly_quota - calls_this_month(db, "adzuna"))
    return stats


# ------------------------------------------------------------------------------------- InfoJobs

def ingest_infojobs(db: Session, http: Http, pack: Pack, countries: list[str], keywords: list[str]) -> dict:
    s = get_settings()
    if countries and "es" not in countries:
        return {"skipped": "InfoJobs solo cubre España"}
    if not (s.infojobs_client_id and s.infojobs_client_secret):
        return {"skipped": "sin credenciales (KNOK_INFOJOBS_CLIENT_ID / KNOK_INFOJOBS_CLIENT_SECRET)"}
    stats = {"calls": 0, "jobs": 0, "cached": 0}
    for q in list(dict.fromkeys((keywords or []) + pack.sources.infojobs.q))[:3]:
        consulta = {"q": q}
        key = query_key("infojobs", consulta)
        if recent_run(db, "infojobs", key, CACHE["infojobs"]):
            stats["cached"] += 1
            continue
        try:
            jobs = infojobs.search(http, s.infojobs_client_id, s.infojobs_client_secret, q)
            for j in jobs:
                ingest.upsert_job(db, j, pack.slug)
            record_run(db, "infojobs", consulta, calls=1, stats={"jobs": len(jobs)})
            stats["jobs"] += len(jobs)
        except Exception as ex:
            record_run(db, "infojobs", consulta, status="error", calls=1, error=str(ex))
        stats["calls"] += 1
    return stats


# ------------------------------------------------------------------------------------- datos de ejemplo

def load_sample(pack: Pack) -> tuple[list[RawJob], list[RawCompany]]:
    if not pack.sample_data:
        return [], []
    f = PACKS_DIR / pack.slug / pack.sample_data
    if not f.exists():
        return [], []
    data = json.loads(f.read_text(encoding="utf-8"))
    ahora = datetime.now(timezone.utc)
    jobs = []
    for j in data.get("jobs", []):
        j = dict(j)
        dias = j.pop("days_ago", 3)
        j["posted_at"] = parse_dt(j.get("posted_at")) or ahora - timedelta(days=dias)
        jobs.append(RawJob(source="sample", **j))
    companies = [RawCompany(source="sample", **c) for c in data.get("companies", [])]
    return jobs, companies


def ingest_sample(db: Session, pack: Pack) -> dict:
    jobs, companies = load_sample(pack)
    for j in jobs:
        ingest.upsert_job(db, j, pack.slug)
    for c in companies:
        ingest.upsert_company(db, c, pack.slug)
    return {"jobs": len(jobs), "companies": len(companies)}
