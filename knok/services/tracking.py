"""Seguimiento (mini-CRM): estados, resumen, recordatorios de seguimiento, CSV y respuestas.

Estados: prepared → confirmed → sent → replied / interview / discarded (y error).
Respuestas, sin leer Gmail:
  A) marcado manual (con texto opcional, que se clasifica por palabras clave);
  B) reenvío a knok mediante un filtro de Gmail (POST /inbound/email).
"""
import csv
import io
from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from knok.core.domains import FREE_PROVIDERS, domain_of
from knok.core.mail.inbound import Inbound
from knok.core.mail.message import new_message_id
from knok.db.models import Application, Email, Event, Profile, Reply, utcnow
from knok.services.events import log_event
from knok.services.mailer import record_reply, sent_today
from knok.services.templates import render_for
from knok.worker.queue import enqueue, task

STATUSES = ("prepared", "confirmed", "sent", "replied", "interview", "discarded", "error")
MANUAL_TRANSITIONS = {"sent", "replied", "interview", "discarded", "confirmed", "prepared"}


def summary(db: Session, profile: Profile) -> dict:
    uid, mode = profile.user_id, profile.mode
    por_estado = dict(db.execute(select(Application.status, func.count()).where(
        Application.user_id == uid, Application.mode == mode).group_by(Application.status)).all())
    por_ruta = dict(db.execute(select(Application.route, func.count()).where(
        Application.user_id == uid, Application.mode == mode).group_by(Application.route)).all())
    categorias = dict(db.execute(select(Reply.category, func.count()).where(
        Reply.user_id == uid, Reply.mode == mode).group_by(Reply.category)).all())
    ahora = utcnow()
    pendientes = db.scalar(select(func.count(Application.id)).where(
        Application.user_id == uid, Application.mode == mode, Application.status == "sent",
        Application.follow_up_at.is_not(None), Application.follow_up_at <= ahora)) or 0
    no_leidas = db.scalar(select(func.count(Reply.id)).where(Reply.user_id == uid, Reply.mode == mode,
                                                             Reply.read.is_(False))) or 0
    desde = (ahora - timedelta(days=13)).replace(hour=0, minute=0, second=0, microsecond=0)
    enviados = [r[0] for r in db.execute(select(Email.sent_at).where(Email.user_id == uid, Email.mode == mode,
                                                                    Email.status == "sent", Email.sent_at >= desde))]
    otras = [r[0] for r in db.execute(select(Application.sent_at).where(
        Application.user_id == uid, Application.mode == mode, Application.route != "email",
        Application.sent_at >= desde))]
    respuestas = [r[0] for r in db.execute(select(Reply.received_at).where(Reply.user_id == uid, Reply.mode == mode,
                                                                          Reply.received_at >= desde))]
    dias = [(desde + timedelta(days=i)).date().isoformat() for i in range(14)]
    cuenta = lambda fechas: {d: sum(1 for f in fechas if f and f.date().isoformat() == d) for d in dias}
    e, o, r = cuenta(enviados), cuenta(otras), cuenta(respuestas)
    total_enviadas = sum(por_estado.get(s, 0) for s in ("sent", "replied", "interview", "discarded"))
    respondidas = sum(por_estado.get(s, 0) for s in ("replied", "interview")) + \
        (db.scalar(select(func.count(func.distinct(Reply.application_id))).where(
            Reply.user_id == uid, Reply.mode == mode, Reply.category == "rejection")) or 0)
    return {
        "mode": mode, "by_status": por_estado, "by_route": por_ruta, "replies_by_category": categorias,
        "followups_due": pendientes, "unread_replies": no_leidas,
        "sent_today": sent_today(db, uid, mode) if mode != "simulation" else None,
        "daily_limit": profile.daily_limit,
        "response_rate": round(respondidas / total_enviadas, 3) if total_enviadas else None,
        "daily": [{"day": d, "sent": e[d] + o[d], "replies": r[d]} for d in dias],
    }


def list_applications(db: Session, profile: Profile, status: str | None = None, route: str | None = None,
                      q: str | None = None, due: bool = False, limit: int = 100, offset: int = 0):
    from knok.db.models import Company, Job
    s = select(Application).where(Application.user_id == profile.user_id, Application.mode == profile.mode)
    if status:
        s = s.where(Application.status.in_(status.split(",")))
    if route:
        s = s.where(Application.route == route)
    if due:
        s = s.where(Application.status == "sent", Application.follow_up_at <= utcnow())
    if q:
        like = f"%{q.lower()}%"
        s = s.outerjoin(Job, Job.id == Application.job_id).outerjoin(Company, Company.id == Application.company_id)
        s = s.where(or_(func.lower(Job.title).like(like), func.lower(Company.name).like(like),
                        func.lower(Application.contact_email).like(like)))
    total = db.scalar(select(func.count()).select_from(s.subquery()))
    filas = list(db.scalars(s.order_by(Application.last_status_at.desc(), Application.id.desc()).offset(offset).limit(limit)))
    return total, filas


def item(db: Session, a: Application) -> dict:
    ultima = db.scalars(select(Reply).where(Reply.application_id == a.id).order_by(Reply.received_at.desc()).limit(1)).first()
    return {
        "id": a.id, "status": a.status, "route": a.route, "platform": a.platform,
        "title": a.job.title if a.job else "", "company": (a.company.name if a.company else (a.job.company_name if a.job else "")),
        "country": (a.job.country if a.job else "") or (a.company.country if a.company else ""),
        "contact_email": a.contact_email, "apply_url": a.apply_url,
        "sent_at": a.sent_at.isoformat() if a.sent_at else None,
        "follow_up_at": a.follow_up_at.isoformat() if a.follow_up_at else None,
        "follow_up_due": bool(a.status == "sent" and a.follow_up_at and a.follow_up_at <= utcnow()),
        "last_reply": {"id": ultima.id, "category": ultima.category, "subject": ultima.subject,
                       "received_at": ultima.received_at.isoformat(), "read": ultima.read} if ultima else None,
        "notes": a.notes, "updated_at": a.last_status_at.isoformat() if a.last_status_at else None,
    }


CSV_COLUMNS = ["id", "status", "route", "platform", "title", "company", "country", "contact_email", "apply_url",
               "sent_at", "follow_up_at", "last_reply_category", "last_reply_at", "notes"]


def export_csv(db: Session, profile: Profile) -> str:
    _, apps = list_applications(db, profile, limit=100_000)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for a in apps:
        d = item(db, a)
        lr = d["last_reply"] or {}
        w.writerow([d["id"], d["status"], d["route"], d["platform"], d["title"], d["company"], d["country"],
                    d["contact_email"], d["apply_url"], d["sent_at"] or "", d["follow_up_at"] or "",
                    lr.get("category", ""), lr.get("received_at", ""), (d["notes"] or "").replace("\n", " ")[:500]])
    return "﻿" + buf.getvalue()   # BOM: Excel abre bien las tildes


def set_status(db: Session, profile: Profile, app: Application, status: str) -> Application:
    if status not in MANUAL_TRANSITIONS:
        raise ValueError(f"Estado no válido: {status}")
    ahora = utcnow()
    if status == "sent" and not app.sent_at:
        app.sent_at = ahora
        app.follow_up_at = ahora + timedelta(days=profile.followup_days)
    if status in ("replied", "interview", "discarded"):
        app.follow_up_at = None
    app.status, app.last_status_at = status, ahora
    return app


# ------------------------------------------------------------------------------------- seguimiento (follow-up)

def followup_draft(db: Session, profile: Profile, app: Application) -> dict:
    original = db.scalars(select(Email).where(Email.application_id == app.id, Email.kind == "application",
                                              Email.status == "sent").order_by(Email.sent_at)).first()
    empresa = {"name": app.company.name} if app.company else {"name": app.job.company_name if app.job else ""}
    puesto = {"title": app.job.title} if app.job else None
    r = render_for(db, profile, "followup", "company", app.language, empresa, puesto,
                   extra={"asunto": original.subject if original else app.subject})
    return {"to": app.contact_email, "subject": r.subject if r else "", "body": r.body if r else "",
            "in_reply_to": original.message_id if original else "", "available": app.route == "email" and bool(original)}


def queue_followup(db: Session, profile: Profile, app: Application, subject: str, body: str) -> Email:
    """El clic del seguimiento: se encola UN correo de seguimiento a la misma dirección."""
    from knok.services.readiness import sending_problems
    from knok.services.mailer import SendingBlocked
    if app.status != "sent" or app.route != "email":
        raise ValueError("Solo se hace seguimiento por correo de candidaturas enviadas por correo y sin respuesta")
    problemas = [p for p in sending_problems(db, profile) if p["code"] != "missing_cv"]
    if problemas:
        raise SendingBlocked(problemas)
    original = db.scalars(select(Email).where(Email.application_id == app.id, Email.kind == "application",
                                              Email.status == "sent").order_by(Email.sent_at)).first()
    if original is None:
        raise ValueError("No hay correo original al que hacer seguimiento")
    ya = db.scalar(select(func.count(Email.id)).where(Email.application_id == app.id, Email.kind == "followup",
                                                      Email.status.in_(("queued", "sent"))))
    if ya:
        raise ValueError("Ya se hizo un seguimiento de esta candidatura")
    e = Email(user_id=profile.user_id, application_id=app.id, mode=profile.mode, kind="followup",
              to_addr=original.to_addr, intended_to=original.intended_to, subject=subject, body=body, attachments=[],
              message_id=new_message_id(original.sender), sender=original.sender, status="queued")
    db.add(e)
    db.flush()
    enqueue(db, "send_email", {"email_id": e.id, "in_reply_to": original.message_id}, user_id=profile.user_id)
    return e


@task("mark_followups_due")
def mark_followups_due_task(db: Session, payload: dict) -> dict:
    """Periódica: un aviso al día por usuario con seguimientos pendientes (nunca envía nada)."""
    ahora = utcnow()
    inicio = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    filas = db.execute(select(Application.user_id, func.count()).where(
        Application.status == "sent", Application.follow_up_at <= ahora).group_by(Application.user_id)).all()
    avisados = 0
    for uid, n in filas:
        ya = db.scalar(select(Event.id).where(Event.user_id == uid, Event.ts >= inicio,
                                              Event.message.like("Seguimiento pendiente%")).limit(1))
        if not ya:
            log_event(db, uid, f"Seguimiento pendiente: {n} candidatura(s) sin respuesta tras el plazo.", "info", count=n)
            avisados += 1
    db.flush()
    return {"users": avisados}


# ------------------------------------------------------------------------------------- respuestas reenviadas

def process_inbound(db: Session, inbound: Inbound) -> dict:
    perfil = None
    for t in inbound.tokens:
        perfil = db.scalar(select(Profile).where(Profile.inbound_token == t))
        if perfil:
            break
    if perfil is None:
        return {"ignored": "destinatario desconocido"}
    if inbound.gmail_confirmation:
        log_event(db, perfil.user_id, f"Gmail pide confirmar el reenvío a knok. Código de confirmación: "
                  f"{inbound.gmail_confirmation}", "warning", code=inbound.gmail_confirmation)
        return {"gmail_confirmation": True}

    uid = perfil.user_id
    remitente = inbound.original_from or inbound.from_addr
    app = None
    if inbound.references:   # 1) responde directamente a un correo nuestro
        e = db.scalar(select(Email).where(Email.user_id == uid, Email.message_id.in_(inbound.references)))
        if e:
            app = db.get(Application, e.application_id)
    if app is None and remitente:   # 2) viene de la dirección o del dominio de una empresa contactada
        dom = domain_of(remitente)
        # También las descartadas: una empresa puede volver a escribir (su estado no cambia)
        candidatas = list(db.scalars(select(Application).where(
            Application.user_id == uid, Application.status.in_(("sent", "replied", "interview", "discarded")))
                                     .order_by(Application.sent_at.desc())))
        for a in candidatas:
            if a.contact_email and a.contact_email.lower() == remitente:
                app = a
                break
        if app is None and dom and dom not in FREE_PROVIDERS:
            for a in candidatas:
                doms = {domain_of(a.contact_email)} | ({a.company.domain} if a.company and a.company.domain else set())
                if dom in doms:
                    app = a
                    break
    if app is None:
        return {"ignored": "no corresponde a ninguna candidatura"}
    r = record_reply(db, user_id=uid, app=app, mode=app.mode, source="forward", from_addr=remitente,
                     subject=inbound.subject, body=inbound.body, category="auto" if inbound.auto_submitted else None)
    log_event(db, uid, f"Respuesta de {remitente} ({r.category}).", "ok", application_id=app.id, reply_id=r.id)
    return {"application_id": app.id, "reply_id": r.id, "category": r.category}


def forwarding_domains(db: Session, profile: Profile) -> list[str]:
    doms = set()
    for a in db.scalars(select(Application).where(Application.user_id == profile.user_id,
                                                  Application.status.in_(("sent", "replied", "interview")))):
        for d in (domain_of(a.contact_email), a.company.domain if a.company else ""):
            if d and d not in FREE_PROVIDERS:
                doms.add(d)
    return sorted(doms)
