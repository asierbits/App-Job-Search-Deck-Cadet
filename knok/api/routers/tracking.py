"""Seguimiento (mini-CRM), respuestas, recordatorios, exportación CSV y reenvío de respuestas."""
import hmac
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from knok.api.deps import ApiError, current_profile, current_user, get_db, not_found
from knok.core.mail.classify import CATEGORIES
from knok.core.mail.inbound import gmail_filter_xml, parse
from knok.db import models as m
from knok.services import tracking
from knok.services.mailer import SendingBlocked, record_reply
from knok.settings import get_settings

router = APIRouter(tags=["tracking"])
inbound = APIRouter(tags=["tracking"])


def _own_app(db: Session, user_id: int, aid: int) -> m.Application:
    a = db.get(m.Application, aid)
    if a is None or a.user_id != user_id:
        raise not_found("Candidatura")
    return a


@router.get("/tracking/summary", summary="Resumen: estados, respuestas, tasa de respuesta y actividad de 14 días")
def summary(profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    return tracking.summary(db, profile)


@router.get("/tracking", summary="Mis candidaturas (filtros por estado, vía, texto y seguimientos pendientes)")
def list_tracking(status: str | None = Query(None, description="Uno o varios separados por comas"),
                  route: str | None = None, q: str | None = None, due: bool = False,
                  limit: int = Query(100, le=1000), offset: int = 0,
                  profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    total, filas = tracking.list_applications(db, profile, status, route, q, due, limit, offset)
    return {"total": total, "items": [tracking.item(db, a) for a in filas]}


@router.get("/tracking/export.csv", summary="Exportar el seguimiento a CSV", response_class=Response)
def export(profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    return Response(tracking.export_csv(db, profile), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="knok-seguimiento.csv"'})


class StatusIn(BaseModel):
    status: Literal["prepared", "confirmed", "sent", "replied", "interview", "discarded"]


@router.post("/applications/{aid}/status", summary="Cambiar el estado a mano (p. ej. 'entrevista')")
def set_status(aid: int, data: StatusIn, profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    return tracking.item(db, tracking.set_status(db, profile, _own_app(db, profile.user_id, aid), data.status))


class ReplyIn(BaseModel):
    body: str = Field(default="", max_length=50000, description="Pega el texto de la respuesta (opcional)")
    subject: str = ""
    from_addr: str = ""
    category: Literal["interview", "info", "rejection", "auto", "other"] | None = Field(
        default=None, description="Si no la das, se clasifica por palabras clave")


@router.post("/applications/{aid}/replies", status_code=201, summary="Anotar una respuesta recibida (marcado manual)")
def add_reply(aid: int, data: ReplyIn, profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    app = _own_app(db, profile.user_id, aid)
    r = record_reply(db, user_id=profile.user_id, app=app, mode=app.mode, source="manual", from_addr=data.from_addr,
                     subject=data.subject, body=data.body, category=data.category)
    r.read = True
    return {"reply": _reply_out(r), "application": tracking.item(db, app)}


def _reply_out(r: m.Reply) -> dict:
    return {"id": r.id, "application_id": r.application_id, "source": r.source, "from": r.from_addr,
            "subject": r.subject, "body": r.body, "category": r.category, "read": r.read,
            "received_at": r.received_at.isoformat()}


@router.get("/replies", summary="Respuestas recibidas")
def list_replies(unread: bool = False, limit: int = Query(100, le=500), profile: m.Profile = Depends(current_profile),
                 db: Session = Depends(get_db)):
    q = select(m.Reply).where(m.Reply.user_id == profile.user_id, m.Reply.mode == profile.mode)
    if unread:
        q = q.where(m.Reply.read.is_(False))
    return [_reply_out(r) for r in db.scalars(q.order_by(m.Reply.received_at.desc()).limit(limit))]


class ReplyPatch(BaseModel):
    read: bool | None = None
    category: Literal["interview", "info", "rejection", "auto", "other"] | None = None


@router.patch("/replies/{rid}", summary="Marcar como leída o corregir la clasificación")
def patch_reply(rid: int, data: ReplyPatch, profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    r = db.get(m.Reply, rid)
    if r is None or r.user_id != profile.user_id:
        raise not_found("Respuesta")
    if data.read is not None:
        r.read = data.read
    if data.category and data.category in CATEGORIES and data.category != r.category:
        r.category = data.category
        app = db.get(m.Application, r.application_id) if r.application_id else None
        if app:
            from knok.core.mail.classify import application_status_for
            app.status = application_status_for(data.category)
    return _reply_out(r)


@router.get("/applications/{aid}/followup", summary="Borrador del correo de seguimiento (no envía nada)")
def followup_draft(aid: int, profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    return tracking.followup_draft(db, profile, _own_app(db, profile.user_id, aid))


class FollowupIn(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)


@router.post("/applications/{aid}/followup", summary="EL CLIC: enviar el seguimiento revisado")
def followup_send(aid: int, data: FollowupIn, profile: m.Profile = Depends(current_profile),
                  db: Session = Depends(get_db)):
    try:
        e = tracking.queue_followup(db, profile, _own_app(db, profile.user_id, aid), data.subject, data.body)
    except SendingBlocked as ex:
        raise ApiError(409, "sending_blocked", str(ex))
    except ValueError as ex:
        raise ApiError(409, "followup_not_allowed", str(ex))
    return {"email_id": e.id, "status": db.get(m.Email, e.id).status}


@router.get("/events", summary="Actividad reciente (lo que ha hecho el motor)")
def events(limit: int = Query(50, le=500), user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": e.id, "ts": e.ts.isoformat(), "level": e.level, "message": e.message, "data": e.data}
            for e in db.scalars(select(m.Event).where(m.Event.user_id == user.id).order_by(m.Event.id.desc()).limit(limit))]


# ------------------------------------------------------------------------------------- reenvío de respuestas

@router.get("/me/reply-forwarding", tags=["me"], summary="Cómo reenviar a knok las respuestas de las empresas")
def reply_forwarding(profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    s = get_settings()
    direccion = f"u-{profile.inbound_token}@{s.inbound_domain}"
    return {"address": direccion, "domains": tracking.forwarding_domains(db, profile),
            "filter_xml_url": "/me/reply-forwarding/filters.xml",
            "steps": {
                "es": ["Gmail → Ajustes → Reenvío y correo POP/IMAP → Añadir una dirección de reenvío: " + direccion,
                       "Gmail enviará un código a knok: aparecerá en tu actividad. Introdúcelo en Gmail.",
                       "Gmail → Ajustes → Filtros → Importar filtros: sube el archivo filters.xml de knok.",
                       "Vuelve a descargar el archivo cuando escribas a empresas nuevas."],
                "en": ["Gmail → Settings → Forwarding and POP/IMAP → Add a forwarding address: " + direccion,
                       "Gmail will send a code to knok: it will appear in your activity. Enter it in Gmail.",
                       "Gmail → Settings → Filters → Import filters: upload knok's filters.xml.",
                       "Download the file again after writing to new companies."]}}


@router.get("/me/reply-forwarding/filters.xml", tags=["me"], summary="Filtros de Gmail para importar",
            response_class=Response)
def reply_filters(profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    dominios = tracking.forwarding_domains(db, profile)
    if not dominios:
        raise ApiError(404, "no_domains", "Aún no has escrito a ninguna empresa")
    xml = gmail_filter_xml(dominios, f"u-{profile.inbound_token}@{get_settings().inbound_domain}")
    return Response(xml, media_type="application/xml",
                    headers={"Content-Disposition": 'attachment; filename="knok-filters.xml"'})


@inbound.post("/inbound/email", status_code=202, summary="Receptor de correo reenviado (lo llama tu receptor de email)")
async def inbound_email(request: Request, x_knok_inbound_secret: str = Header(""),
                        x_envelope_to: str = Header(""), db: Session = Depends(get_db)):
    secreto = get_settings().inbound_secret
    if not secreto or not hmac.compare_digest(secreto, x_knok_inbound_secret):
        raise ApiError(401, "bad_secret", "Secreto del receptor no válido")
    raw = await request.body()
    if not raw or len(raw) > 25 * 1024 * 1024:
        raise ApiError(413, "bad_size", "Correo vacío o demasiado grande")
    return tracking.process_inbound(db, parse(raw, x_envelope_to))
