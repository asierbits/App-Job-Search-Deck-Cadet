"""Tandas, revisión y envío. Nada sale sin POST /batches/{id}/send o /applications/{id}/send."""
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knok.api.deps import ApiError, current_profile, current_user, get_db, not_found
from knok.db import models as m
from knok.services import applications as svc

router = APIRouter(tags=["review"])


class BatchIn(BaseModel):
    search_id: int | None = None
    result_ids: list[int] = Field(default=[], description="Resultados concretos (si no, los mejores de la búsqueda)")
    size: int = Field(default=40, ge=1, le=100)
    routes: list[Literal["ats_extension", "portal_api", "portal_copilot", "email", "manual"]] = []
    include_manual: bool = False


class FieldChange(BaseModel):
    id: str
    value: Any
    remember: bool = Field(default=True, description="Guardar la respuesta en tu banco para la próxima vez")


class ApplicationPatch(BaseModel):
    subject: str | None = None
    body: str | None = None
    contact_email: str | None = None
    document_ids: list[int] | None = None
    fields: list[FieldChange] = []
    notes: str | None = None


class SendIn(BaseModel):
    application_ids: list[int] = Field(min_length=1, description="Las candidaturas que TÚ has seleccionado")


def _own_batch(db: Session, user_id: int, bid: int) -> m.Batch:
    b = db.get(m.Batch, bid)
    if b is None or b.user_id != user_id:
        raise not_found("Tanda")
    return b


def _own_app(db: Session, user_id: int, aid: int) -> m.Application:
    a = db.get(m.Application, aid)
    if a is None or a.user_id != user_id:
        raise not_found("Candidatura")
    return a


def batch_out(db: Session, b: m.Batch, items: bool = True) -> dict:
    apps = list(db.scalars(select(m.Application).where(m.Application.batch_id == b.id).order_by(m.Application.id)))
    d = {"id": b.id, "search_id": b.search_id, "mode": b.mode, "status": b.status, "created_at": b.created_at.isoformat(),
         "counts": {}}
    for a in apps:
        d["counts"][a.status] = d["counts"].get(a.status, 0) + 1
    d["routes"] = {}
    for a in apps:
        d["routes"][a.route] = d["routes"].get(a.route, 0) + 1
    if items:
        d["items"] = [svc.review_item(db, a) for a in apps]
    return d


@router.post("/batches", status_code=201, summary="Preparar una tanda (~40) de candidaturas para revisar")
def new_batch(data: BatchIn, profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    if data.search_id:
        s = db.get(m.Search, data.search_id)
        if s is None or s.user_id != profile.user_id:
            raise not_found("Búsqueda")
        if s.status != "done":
            raise ApiError(409, "search_not_done", "La búsqueda aún no ha terminado")
    if data.result_ids:
        ajenos = db.scalar(select(func.count(m.SearchResult.id)).join(m.Search, m.Search.id == m.SearchResult.search_id)
                           .where(m.SearchResult.id.in_(data.result_ids), m.Search.user_id != profile.user_id))
        if ajenos:
            raise not_found("Resultado")
    try:
        b = svc.create_batch(db, profile, data.search_id, data.result_ids or None, data.size, data.routes or None,
                             data.include_manual)
    except svc.ApplicationError as ex:
        raise ApiError(422, ex.code, str(ex))
    return batch_out(db, b)


@router.get("/batches", summary="Mis tandas")
def list_batches(limit: int = Query(20, le=100), user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return [batch_out(db, b, items=False) for b in db.scalars(select(m.Batch).where(m.Batch.user_id == user.id)
                                                              .order_by(m.Batch.id.desc()).limit(limit))]


@router.get("/batches/{bid}", summary="Revisar una tanda: oferta, lo rellenado, qué se dedujo y qué falta")
def get_batch(bid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return batch_out(db, _own_batch(db, user.id, bid))


@router.post("/batches/{bid}/send", summary="EL CLIC: confirmar y enviar las candidaturas seleccionadas de la tanda")
def send_batch(bid: int, data: SendIn, profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    _own_batch(db, profile.user_id, bid)
    apps = [_own_app(db, profile.user_id, i) for i in data.application_ids]
    if any(a.batch_id != bid for a in apps):
        raise ApiError(422, "wrong_batch", "Alguna candidatura no pertenece a esta tanda")
    return {"results": svc.send_selected(db, profile, apps)}


@router.post("/applications", status_code=201, summary="Crear una candidatura suelta (a una oferta o a una empresa)")
def create_application(job_id: int | None = None, company_id: int | None = None,
                       profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    job = db.get(m.Job, job_id) if job_id else None
    company = db.get(m.Company, company_id) if company_id else (job.company if job else None)
    if job is None and company is None:
        raise ApiError(422, "bad_request", "Indica job_id o company_id")
    return svc.review_item(db, svc.new_application(db, profile, job, company))


@router.get("/applications/{aid}", summary="Una candidatura (para revisar)")
def get_application(aid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.review_item(db, _own_app(db, user.id, aid))


@router.patch("/applications/{aid}", summary="Corregir una candidatura (texto, adjuntos, respuestas)")
def patch_application(aid: int, data: ApplicationPatch, profile: m.Profile = Depends(current_profile),
                      db: Session = Depends(get_db)):
    app = _own_app(db, profile.user_id, aid)
    try:
        svc.update(db, app, profile, data.model_dump(exclude_unset=True))
    except svc.ApplicationError as ex:
        raise ApiError(422, ex.code, str(ex))
    return svc.review_item(db, app)


@router.post("/applications/{aid}/send", summary="EL CLIC para una sola candidatura")
def send_one(aid: int, profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    return {"results": svc.send_selected(db, profile, [_own_app(db, profile.user_id, aid)])}


@router.post("/applications/{aid}/prepare", summary="Volver a rellenar (tras cambiar el perfil o el banco)")
def reprepare(aid: int, profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    app = _own_app(db, profile.user_id, aid)
    if app.status not in svc.OPEN:
        raise ApiError(409, "not_open", "Solo se pueden volver a preparar las candidaturas aún no enviadas")
    svc.prepare(db, app, profile)
    return svc.review_item(db, app)


@router.post("/applications/{aid}/mark-sent", summary="Marcar como enviada (la hiciste tú en la web o en la extensión)")
def mark_sent(aid: int, profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    try:
        return svc.review_item(db, svc.mark_sent(db, profile, _own_app(db, profile.user_id, aid)))
    except svc.ApplicationError as ex:
        raise ApiError(409, ex.code, str(ex))


@router.post("/applications/{aid}/discard", summary="Descartar")
def discard(aid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    app = _own_app(db, user.id, aid)
    app.status, app.follow_up_at, app.last_status_at = "discarded", None, m.utcnow()
    for e in db.scalars(select(m.Email).where(m.Email.application_id == app.id, m.Email.status == "queued")):
        e.status = "cancelled"
    return svc.review_item(db, app)
