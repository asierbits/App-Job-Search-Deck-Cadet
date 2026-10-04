"""Búsquedas, resultados y base común (ofertas, empresas, catálogo de ATS, plataformas)."""
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knok.api.deps import ApiError, current_profile, current_user, get_db, not_found
from knok.core.sources.adzuna import ATTRIBUTION
from knok.core.sources.ats.detect import PLATFORMS, detect
from knok.db import models as m
from knok.packs.loader import all_packs
from knok.services import ingest
from knok.services.companies import company_summary
from knok.services.search import ALL_SOURCES, create_search

router = APIRouter(tags=["search"])
catalog = APIRouter(tags=["catalog"])


class SearchIn(BaseModel):
    pack: str = Field(default="", description="Por defecto, el del perfil")
    countries: list[str] = Field(default=[], description="ISO alfa-2; vacío = los del pack")
    cities: list[str] = Field(default=[], description="También se buscan empresas en OpenStreetMap alrededor de ellas")
    radius_km: float = Field(default=10, ge=1, le=100)
    keywords: list[str] = Field(default=[], description="Si las das, cada oferta debe contener alguna")
    sources: list[Literal["ats", "adzuna", "infojobs", "companies", "sample"]] = Field(
        default=[], description="Vacío = todas las disponibles")
    include_remote: bool = True
    include_companies: bool = Field(default=True, description="Incluir empresas sin oferta (correo directo)")
    max_results: int = Field(default=500, ge=1, le=2000)
    max_webs: int = Field(default=200, ge=0, le=2000, description="Webs de empresas a rastrear como mucho en esta búsqueda")


def search_out(s: m.Search) -> dict:
    return {"id": s.id, "status": s.status, "params": s.params, "stats": s.stats, "error": s.error,
            "created_at": s.created_at.isoformat(), "finished_at": s.finished_at.isoformat() if s.finished_at else None}


def job_summary(j: m.Job | None, full: bool = False) -> dict | None:
    if j is None:
        return None
    d = {"id": j.id, "title": j.title, "company_name": j.company_name, "city": j.city, "country": j.country,
         "remote": j.remote, "source": j.source, "url": j.url, "apply_url": j.apply_url, "platform": j.apply_platform,
         "salary": j.salary, "posted_at": j.posted_at.isoformat() if j.posted_at else None,
         "closed": j.closed_at is not None}
    if j.source == "adzuna":
        d["attribution"] = ATTRIBUTION
    if full:
        d["description"] = j.description
        d["questions"] = j.questions
    else:
        d["snippet"] = (j.description or "")[:280]
    return d


@router.post("/searches", status_code=202, summary="Lanzar una búsqueda (no envía nada)")
def new_search(data: SearchIn, profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    if data.pack and data.pack not in all_packs():
        raise ApiError(422, "unknown_pack", f"Pack desconocido: {data.pack}")
    params = data.model_dump()
    params["countries"] = [c.lower() for c in data.countries]
    s = create_search(db, profile, params)
    return search_out(s)


@router.get("/searches", summary="Mis búsquedas")
def list_searches(limit: int = Query(20, le=100), user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return [search_out(s) for s in db.scalars(select(m.Search).where(m.Search.user_id == user.id)
                                              .order_by(m.Search.id.desc()).limit(limit))]


def _own_search(db: Session, user_id: int, sid: int) -> m.Search:
    s = db.get(m.Search, sid)
    if s is None or s.user_id != user_id:
        raise not_found("Búsqueda")
    return s


@router.get("/searches/{sid}", summary="Estado de una búsqueda")
def get_search(sid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return search_out(_own_search(db, user.id, sid))


@router.post("/searches/{sid}/cancel", summary="Detener una búsqueda en marcha (lo ya encontrado se conserva)")
def cancel_search(sid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    s = _own_search(db, user.id, sid)
    if s.status in ("queued", "running"):
        s.status = "cancelling"
    return search_out(s)


@router.get("/searches/{sid}/results", summary="Resultados (mejores primero) con la vía decidida para cada uno")
def search_results(sid: int, route: str | None = None, limit: int = Query(50, le=500), offset: int = 0,
                   user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    _own_search(db, user.id, sid)
    q = select(m.SearchResult).where(m.SearchResult.search_id == sid)
    if route:
        q = q.where(m.SearchResult.route == route)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    items = []
    for r in db.scalars(q.order_by(m.SearchResult.score.desc(), m.SearchResult.id).offset(offset).limit(limit)):
        job = db.get(m.Job, r.job_id) if r.job_id else None
        comp = db.get(m.Company, r.company_id) if r.company_id else None
        items.append({"result_id": r.id, "score": r.score, "route": r.route, "platform": r.platform,
                      "reasons": r.reasons, "job": job_summary(job), "company": company_summary(comp)})
    return {"total": total, "items": items}


# ------------------------------------------------------------------------------------- catálogo

@catalog.get("/jobs/{job_id}", summary="Oferta completa (descripción y preguntas conocidas)")
def get_job(job_id: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    j = db.get(m.Job, job_id)
    if j is None:
        raise not_found("Oferta")
    d = job_summary(j, full=True)
    d["company"] = company_summary(j.company)
    d["duplicates"] = [x.id for x in db.scalars(select(m.Job).where(m.Job.canonical_job_id == j.id))]
    d["original_id"] = j.canonical_job_id
    return d


@catalog.get("/companies/{cid}", summary="Empresa de la base común (solo buzones genéricos)")
def get_company(cid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(m.Company, cid)
    if c is None:
        raise not_found("Empresa")
    d = company_summary(c)
    d["emails"] = [{"email": e.email, "found_on_url": e.found_on_url, "on_careers_page": e.on_careers_page}
                   for e in c.emails]
    d["open_jobs"] = db.scalar(select(func.count(m.Job.id)).where(m.Job.company_id == c.id, m.Job.closed_at.is_(None)))
    return d


class BoardIn(BaseModel):
    url: str = Field(description="URL del tablero o de una oferta (p. ej. https://boards.greenhouse.io/acme)")


@catalog.post("/catalog/ats-boards", status_code=201, summary="Añadir un tablero de ATS al catálogo común")
def add_board(data: BoardIn, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    ref = detect(data.url)
    if ref is None or not ref.slug or not ref.info.public_api:
        raise ApiError(422, "unsupported_board", "No reconozco un tablero de Greenhouse, Lever, Ashby u otro ATS con API pública")
    b = ingest.register_board(db, ref.platform, ref.slug, None, "manual")
    return {"id": b.id, "ats": b.ats, "slug": b.slug, "status": b.status}


@catalog.get("/catalog/ats-boards", summary="Catálogo de tableros de ATS")
def list_boards(ats: str | None = None, limit: int = Query(100, le=1000), offset: int = 0,
                user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(m.AtsBoard)
    if ats:
        q = q.where(m.AtsBoard.ats == ats)
    return [{"id": b.id, "ats": b.ats, "slug": b.slug, "status": b.status, "jobs_count": b.jobs_count,
             "discovered_from": b.discovered_from,
             "last_checked_at": b.last_checked_at.isoformat() if b.last_checked_at else None}
            for b in db.scalars(q.order_by(m.AtsBoard.id).offset(offset).limit(limit))]


@catalog.get("/platforms", summary="Plataformas conocidas y qué sabe hacer knok en cada una")
def platforms():
    return [{"name": p.name, "kind": p.kind, "phase": p.phase, "extension": p.extension, "api_apply": p.api_apply,
             "autofill_allowed": p.autofill_allowed} for p in PLATFORMS.values()]


@catalog.get("/sources", summary="Fuentes de búsqueda disponibles")
def list_sources():
    return list(ALL_SOURCES)
