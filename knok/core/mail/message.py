"""Construcción del correo (RFC 5322) con adjuntos."""
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid


def new_message_id(sender_email: str) -> str:
    return make_msgid(domain=(sender_email or "knok.local").split("@")[-1])


def build(*, sender_name: str, sender_email: str, to: str, subject: str, body: str, message_id: str,
          attachments: list[tuple[str, str, bytes]] = (), in_reply_to: str = "", reply_to: str = "") -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((sender_name, sender_email)) if sender_name else sender_email
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    for filename, mime, data in attachments:
        main, _, sub = (mime or "application/octet-stream").partition("/")
        msg.add_attachment(data, maintype=main, subtype=sub or "octet-stream", filename=filename)
    return msg
