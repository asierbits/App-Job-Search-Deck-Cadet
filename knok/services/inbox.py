"""Leer las respuestas del propio Gmail por IMAP (solo con contraseña de aplicación, uso local).

Solo se descargan completos los correos que responden a uno nuestro o que vienen de una empresa a la
que has escrito; el resto del buzón no se toca (y nada se marca como leído).
"""
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knok.core.domains import FREE_PROVIDERS, domain_of
from knok.core.mail import apppassword
from knok.core.mail.inbound import parse
from knok.db.models import Email, OAuthAccount, Profile, Reply, utcnow
from knok.security import decrypt
from knok.services.events import log_event
from knok.services.mailer import APP_PASSWORD
from knok.services.tracking import forwarding_domains, record_inbound
from knok.worker.queue import task

LAST_CHECK: dict[int, datetime] = {}   # user_id → última revisión (lo enseña el panel)
LOOKBACK = timedelta(days=45)


def _ya_guardada(db: Session, uid: int, inbound) -> bool:
    return db.scalar(select(func.count(Reply.id)).where(
        Reply.user_id == uid, Reply.from_addr == (inbound.original_from or inbound.from_addr),
        Reply.subject == inbound.subject, Reply.body == inbound.body)) > 0


def check_user(db: Session, profile: Profile, acc: OAuthAccount) -> int:
    uid = profile.user_id
    nuestros = set(db.scalars(select(Email.message_id).where(Email.user_id == uid, Email.mode != "simulation")))
    if not nuestros:
        LAST_CHECK[uid] = utcnow()
        return 0
    primero = db.scalar(select(func.min(Email.sent_at)).where(Email.user_id == uid, Email.mode != "simulation",
                                                              Email.status == "sent")) or utcnow()
    desde = (max(primero, utcnow() - LOOKBACK) - timedelta(days=1)).date()
    dominios = set(forwarding_domains(db, profile))
    yo = acc.account_email.lower()

    def interesa(cabeceras: bytes) -> bool:
        texto = cabeceras.decode("utf-8", "replace")
        ids = set(re.findall(r"<[^>]+>", texto))
        m = re.search(r"^Message-ID:\s*(<[^>]+>)", texto, re.I | re.M)
        if m and m.group(1) in nuestros:          # es uno de los nuestros (p. ej. en modo prueba te llegan a ti)
            return False
        if ids & nuestros:
            return True
        de = re.search(r"^From:.*?([\w.+'-]+@[\w.-]+)", texto, re.I | re.M)
        if not de:
            return False
        dom = domain_of(de.group(1).lower())
        return de.group(1).lower() != yo and dom not in FREE_PROVIDERS and dom in dominios

    nuevas = 0
    for raw in apppassword.fetch_since(acc.account_email, decrypt(acc.access_token_enc), desde, interesa):
        inbound = parse(raw)
        if inbound.message_id in nuestros or _ya_guardada(db, uid, inbound):
            continue
        res = record_inbound(db, uid, inbound, "imap")
        if res.get("reply_id"):
            nuevas += 1
    LAST_CHECK[uid] = utcnow()
    return nuevas


def check_all(db: Session) -> dict:
    out = {"users": 0, "new": 0, "errors": 0}
    for acc in db.scalars(select(OAuthAccount).where(OAuthAccount.provider == "google",
                                                     OAuthAccount.scopes == APP_PASSWORD)):
        profile = db.get(Profile, acc.user_id)
        if profile is None or profile.mode == "simulation":
            continue
        out["users"] += 1
        try:
            out["new"] += check_user(db, profile, acc)
        except apppassword.MailboxError as ex:
            out["errors"] += 1
            if ex.reconnect:
                log_event(db, acc.user_id, f"No se pudo leer tu correo: {ex}", "error")
    return out


@task("check_inbox")
def check_inbox_task(db: Session, payload: dict) -> dict:
    """Periódica: busca respuestas en los Gmail conectados con contraseña de aplicación."""
    return check_all(db)


def last_check(user_id: int) -> str | None:
    t = LAST_CHECK.get(user_id)
    return t.astimezone(timezone.utc).isoformat() if t else None
