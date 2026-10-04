"""Gmail con contraseña de aplicación (SMTP para enviar, IMAP para leer respuestas).

Solo para el modo local de un usuario (KNOK_LOCAL_SINGLE_USER): la contraseña se guarda cifrada en
TU ordenador. En el servidor multiusuario se usa OAuth con el permiso gmail.send (core/mail/gmail.py).
Al leer se usa BODY.PEEK: los correos no se marcan como leídos.
"""
import imaplib
import re
import smtplib
import socket
import ssl
from datetime import date

SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 465
IMAP_HOST, IMAP_PORT = "imap.gmail.com", 993
TIMEOUT = 30


class MailboxError(Exception):
    def __init__(self, message: str, retryable: bool = False, reconnect: bool = False):
        super().__init__(message)
        self.retryable, self.reconnect = retryable, reconnect


def clean_password(p: str) -> str:
    return re.sub(r"\s+", "", p or "")


def _auth_error() -> MailboxError:
    return MailboxError("Gmail no acepta esa dirección y contraseña de aplicación. Comprueba que tienes la verificación "
                        "en dos pasos activada y que has copiado las 16 letras de la contraseña de aplicación "
                        "(no tu contraseña normal).", reconnect=True)


def _smtp(user: str, password: str) -> smtplib.SMTP_SSL:
    s = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=TIMEOUT, context=ssl.create_default_context())
    try:
        s.login(user, clean_password(password))
    except smtplib.SMTPAuthenticationError:
        s.close()
        raise _auth_error()
    return s


def _imap(user: str, password: str) -> imaplib.IMAP4_SSL:
    m = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ssl.create_default_context(), timeout=TIMEOUT)
    try:
        m.login(user, clean_password(password))
    except imaplib.IMAP4.error:
        m.logout()
        raise _auth_error()
    return m


def check_login(user: str, password: str) -> None:
    """Prueba enviar (SMTP) y leer (IMAP) sin enviar nada."""
    try:
        _smtp(user, password).quit()
        m = _imap(user, password)
        m.logout()
    except MailboxError:
        raise
    except (OSError, smtplib.SMTPException, imaplib.IMAP4.error) as ex:
        raise MailboxError(f"No se pudo conectar con Gmail: {ex}", retryable=True)


def send(user: str, password: str, raw: bytes, to_addrs: list[str]) -> None:
    try:
        s = _smtp(user, password)
        try:
            s.sendmail(user, to_addrs, raw)
        finally:
            s.quit()
    except MailboxError:
        raise
    except smtplib.SMTPRecipientsRefused as ex:
        raise MailboxError(f"Gmail rechaza el destinatario: {ex}")
    except (OSError, socket.timeout, smtplib.SMTPException) as ex:
        raise MailboxError(f"Gmail no responde ahora: {ex}", retryable=True)


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _imap_date(d: date) -> str:
    return f"{d.day:02d}-{MONTHS[d.month - 1]}-{d.year}"


def fetch_since(user: str, password: str, since: date, wanted, limit: int = 300) -> list[bytes]:
    """Correos de la bandeja de entrada desde `since` cuyas cabeceras pasan `wanted(cabeceras_bytes)`.

    Primero se leen solo las cabeceras (From, In-Reply-To, References…) y después el correo completo de
    los que interesan: no se descarga el resto del buzón.
    """
    try:
        m = _imap(user, password)
    except MailboxError:
        raise
    except OSError as ex:
        raise MailboxError(f"Gmail no responde ahora: {ex}", retryable=True)
    try:
        m.select("INBOX", readonly=True)
        typ, data = m.uid("search", None, f"SINCE {_imap_date(since)}")
        uids = (data[0] or b"").split()[-limit:] if typ == "OK" else []
        if not uids:
            return []
        typ, data = m.uid("fetch", b",".join(uids).decode(),
                          "(BODY.PEEK[HEADER.FIELDS (FROM MESSAGE-ID IN-REPLY-TO REFERENCES AUTO-SUBMITTED)])")
        elegidos = []
        for parte in data or []:
            if isinstance(parte, tuple) and wanted(parte[1]):
                uid = re.search(rb"UID (\d+)", parte[0])
                if uid:
                    elegidos.append(uid.group(1))
        out = []
        for uid in elegidos:
            typ, data = m.uid("fetch", uid.decode(), "(BODY.PEEK[])")
            for parte in data or []:
                if isinstance(parte, tuple):
                    out.append(parte[1])
        return out
    except imaplib.IMAP4.error as ex:
        raise MailboxError(f"Error leyendo el correo: {ex}", retryable=True)
    finally:
        try:
            m.logout()
        except Exception:
            pass
