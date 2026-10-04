"""Envío de correos con los tres modos, límites diarios y pausas.

  simulation  no sale nada: el correo se guarda como .eml y llegan respuestas simuladas.
  test        sale de verdad pero SOLO al propio usuario, con el asunto "[PRUEBA → empresa@…]".
  live        sale a la empresa.

Garantías:
  - Solo se encolan candidaturas CONFIRMADAS por el usuario (el clic). Nada se envía solo.
  - Límite diario: el del usuario y, por cuenta de Google, el tope de Gmail (500 en cuentas personales).
  - Pausa mínima entre envíos del mismo usuario, aunque haya varios workers (bloqueo de fila).
  - Si se pasa el límite, el correo se aplaza a mañana (no se pierde ni cuenta como fallo).
"""
import random
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knok import storage
from knok.core.http import default_http
from knok.core.mail import gmail, simulator
from knok.core.mail.classify import application_status_for, classify
from knok.core.mail.message import build, new_message_id
from knok.db.models import Application, Document, Email, OAuthAccount, Profile, Reply, SimulatedReply, utcnow
from knok.packs.loader import pack_or_default
from knok.security import decrypt, encrypt
from knok.services.events import log_event
from knok.services.readiness import sending_problems
from knok.settings import get_settings
from knok.worker.queue import Reschedule, enqueue, task

SIM_REPLY_PROBABILITY = 0.6
SIM_DELAY = (8, 45)


class SendingBlocked(ValueError):
    def __init__(self, problems: list[dict]):
        super().__init__("; ".join(p["message"] for p in problems))
        self.problems = problems


# ------------------------------------------------------------------------------------- Gmail

def google_access(db: Session, user_id: int) -> tuple[str, str]:
    """(access_token vigente, email de la cuenta). Refresca si hace falta."""
    acc = db.scalar(select(OAuthAccount).where(OAuthAccount.user_id == user_id, OAuthAccount.provider == "google"))
    if acc is None:
        raise gmail.GmailError("Gmail no está conectado", reconnect=True)
    exp = acc.expires_at
    token = decrypt(acc.access_token_enc)
    if not token or exp is None or exp <= utcnow() + timedelta(seconds=30):
        s = get_settings()
        t = gmail.refresh(default_http(), s.google_client_id, s.google_client_secret, decrypt(acc.refresh_token_enc))
        acc.access_token_enc, acc.expires_at = encrypt(t["access_token"]), t["expires_at"]
        token = t["access_token"]
    return token, acc.account_email


# ------------------------------------------------------------------------------------- contadores

def _start_of_day() -> datetime:
    return utcnow().replace(hour=0, minute=0, second=0, microsecond=0)


def sent_today(db: Session, user_id: int, mode: str) -> int:
    return db.scalar(select(func.count(Email.id)).where(Email.user_id == user_id, Email.mode == mode,
                                                        Email.status == "sent", Email.sent_at >= _start_of_day())) or 0


def sent_today_by_account(db: Session, sender: str) -> int:
    """Lo enviado hoy desde una cuenta de Google (aunque la usen varios usuarios de knok)."""
    return db.scalar(select(func.count(Email.id)).where(Email.sender == sender, Email.mode.in_(("test", "live")),
                                                        Email.status == "sent", Email.sent_at >= _start_of_day())) or 0


def last_sent_at(db: Session, user_id: int) -> datetime | None:
    return db.scalar(select(func.max(Email.sent_at)).where(Email.user_id == user_id, Email.mode.in_(("test", "live")),
                                                            Email.status == "sent"))


def _tomorrow_morning() -> datetime:
    return _start_of_day() + timedelta(days=1, hours=7, seconds=random.randint(0, 900))


# ------------------------------------------------------------------------------------- encolar (tras el clic)

def default_attachments(db: Session, user_id: int, language: str) -> list[int]:
    """El CV por defecto del idioma (o uno sin idioma)."""
    docs = list(db.scalars(select(Document).where(Document.user_id == user_id, Document.kind == "cv")
                           .order_by(Document.is_default.desc(), Document.id)))
    for d in docs:
        if d.language == language:
            return [d.id]
    for d in docs:
        if d.language == "":
            return [d.id]
    return [docs[0].id] if docs else []


def queue_application_emails(db: Session, profile: Profile, apps: list[Application], kind: str = "application") -> list[Email]:
    """Crea los correos de candidaturas YA CONFIRMADAS y los programa respetando la pausa."""
    problemas = sending_problems(db, profile)
    if problemas:
        raise SendingBlocked(problemas)
    acc = db.scalar(select(OAuthAccount).where(OAuthAccount.user_id == profile.user_id, OAuthAccount.provider == "google"))
    remitente = acc.account_email if acc else (profile.email or "simulacion@knok.local")
    pausa = 1 if profile.mode == "simulation" else max(5, profile.pause_seconds)
    ahora = utcnow()
    out = []
    for i, app in enumerate(apps):
        if app.status not in ("confirmed",) or app.route != "email" or not app.contact_email:
            continue
        destino = profile.email if profile.mode == "test" else app.contact_email
        e = Email(user_id=profile.user_id, application_id=app.id, mode=profile.mode, kind=kind, to_addr=destino,
                  intended_to=app.contact_email, subject=app.subject, body=app.body,
                  attachments=app.document_ids or default_attachments(db, profile.user_id, app.language),
                  message_id=new_message_id(remitente), sender=remitente, status="queued")
        db.add(e)
        db.flush()
        enqueue(db, "send_email", {"email_id": e.id}, user_id=profile.user_id,
                run_after=ahora + timedelta(seconds=i * pausa))
        out.append(e)
    return out


# ------------------------------------------------------------------------------------- enviar (worker)

def _attachments(db: Session, ids: list[int], user_id: int) -> list[tuple[str, str, bytes]]:
    out = []
    for d in db.scalars(select(Document).where(Document.id.in_(ids or []), Document.user_id == user_id)):
        out.append((d.filename, d.mime, storage.read(d.storage_key)))
    return out


@task("send_email")
def send_email_task(db: Session, payload: dict) -> dict:
    e = db.get(Email, payload["email_id"])
    if e is None or e.status != "queued":
        return {"skipped": True}
    # Bloqueo de la fila del perfil: dos workers no envían a la vez para el mismo usuario
    profile = db.get(Profile, e.user_id, with_for_update=db.bind.dialect.name == "postgresql")
    app = db.get(Application, e.application_id)
    if app is None or app.status not in ("confirmed", "sent"):
        e.status = "cancelled"
        return {"cancelled": True}

    if e.mode != "simulation":
        s = get_settings()
        if sent_today(db, e.user_id, e.mode) >= min(profile.daily_limit, s.gmail_daily_cap):
            raise Reschedule(_tomorrow_morning(), "límite diario alcanzado: se envía mañana")
        if sent_today_by_account(db, e.sender) >= s.gmail_daily_cap:
            raise Reschedule(_tomorrow_morning(), "tope diario de Gmail alcanzado en esta cuenta")
        ultimo = last_sent_at(db, e.user_id)
        siguiente = ultimo + timedelta(seconds=max(5, profile.pause_seconds)) if ultimo else None
        if siguiente and siguiente > utcnow() and not s.tasks_eager:
            raise Reschedule(siguiente, "pausa entre envíos")

    asunto, cuerpo = e.subject, e.body
    if e.mode == "test":
        asunto = f"[PRUEBA → {e.intended_to}] {e.subject}"
        cuerpo = (f"(Modo prueba: este correo iba para {e.intended_to}. Respóndelo haciéndote pasar por la empresa "
                  f"y reenvía la respuesta a tu dirección de seguimiento de knok, o márcala a mano.)\n\n{e.body}")
    nombre = " ".join(x for x in (profile.first_name, profile.last_name) if x)
    msg = build(sender_name=nombre, sender_email=e.sender, to=e.to_addr, subject=asunto, body=cuerpo,
                message_id=e.message_id, attachments=_attachments(db, e.attachments, e.user_id),
                in_reply_to=payload.get("in_reply_to", ""))
    raw = msg.as_bytes()

    if e.mode == "simulation":
        storage.save(f"users/{e.user_id}/outbox", f"{e.id}_{e.intended_to}.eml", raw)
        _schedule_simulated_reply(db, e)
    else:
        try:
            token, _ = google_access(db, e.user_id)
            res = gmail.send(default_http(), token, raw)
        except gmail.GmailError as ex:
            if ex.retryable:
                raise Reschedule(utcnow() + timedelta(minutes=30), str(ex))
            e.status, e.error = "error", str(ex)
            log_event(db, e.user_id, f"No se pudo enviar a {e.intended_to}: {ex}", "error", email_id=e.id)
            if not ex.reconnect:
                app.status, app.last_status_at = "error", utcnow()
            return {"error": str(ex)}
        e.gmail_id, e.thread_id = res.get("id", ""), res.get("threadId", "")

    e.status, e.sent_at = "sent", utcnow()
    if e.kind == "application":
        app.status, app.sent_at, app.last_status_at = "sent", e.sent_at, e.sent_at
        app.follow_up_at = e.sent_at + timedelta(days=profile.followup_days)
    else:
        app.follow_up_at = None
    etiqueta = {"simulation": "simulado", "test": "a tu correo (prueba)", "live": "enviado"}[e.mode]
    log_event(db, e.user_id, f"Correo a {e.intended_to} — {etiqueta}", "ok", email_id=e.id, application_id=app.id)
    return {"sent": True}


# ------------------------------------------------------------------------------------- simulación

def _schedule_simulated_reply(db: Session, e: Email) -> None:
    rng = random.Random(e.id * 7919)
    tipo = simulator.pick_kind(rng, SIM_REPLY_PROBABILITY)
    if tipo is None:
        return
    db.add(SimulatedReply(email_id=e.id, kind=tipo, due_at=utcnow() + timedelta(seconds=rng.uniform(*SIM_DELAY))))


def record_reply(db: Session, *, user_id: int, app: Application | None, mode: str, source: str, from_addr: str,
                 subject: str, body: str, category: str | None = None) -> Reply:
    pack = pack_or_default((db.get(Profile, user_id) or Profile(pack="")).pack)
    cat = category or classify(subject, body, pack.reply_keywords)
    r = Reply(user_id=user_id, application_id=app.id if app else None, mode=mode, source=source, from_addr=from_addr,
              subject=subject, body=body, category=cat)
    db.add(r)
    nuevo = application_status_for(cat)
    if app is not None and app.status not in ("discarded",) and nuevo is not None:
        # Un acuse automático no es una respuesta: no cambia el estado ni quita el recordatorio
        if not (app.status == "interview" and nuevo == "replied"):
            app.status = nuevo
        app.last_status_at, app.follow_up_at = utcnow(), None
    db.flush()
    return r


def deliver_due_simulated(db: Session, now: datetime | None = None) -> int:
    now = now or utcnow()
    n = 0
    for sr in list(db.scalars(select(SimulatedReply).where(SimulatedReply.due_at <= now))):
        e = db.get(Email, sr.email_id)
        db.delete(sr)
        if e is None:
            continue
        app = db.get(Application, e.application_id)
        profile = db.get(Profile, e.user_id)
        empresa = (app.company.name if app and app.company else e.intended_to.split("@")[-1])
        asunto, cuerpo = simulator.compose(sr.kind, app.language if app else "en",
                                           {"asunto": e.subject, "nombre": profile.first_name or "", "empresa": empresa},
                                           random.Random(e.id))
        record_reply(db, user_id=e.user_id, app=app, mode="simulation", source="simulated",
                     from_addr=f"{empresa} <{e.intended_to}>", subject=asunto, body=cuerpo)
        log_event(db, e.user_id, f"Respuesta (simulada) de {empresa}", "ok")
        n += 1
    return n


@task("deliver_simulated_replies")
def deliver_simulated_replies_task(db: Session, payload: dict) -> dict:
    return {"delivered": deliver_due_simulated(db)}
