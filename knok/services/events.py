"""Registro de actividad visible para el usuario (como el panel de eventos del programa antiguo)."""
import logging

from sqlalchemy.orm import Session

from knok.db.models import Event

log = logging.getLogger("knok")


def log_event(session: Session, user_id: int | None, message: str, level: str = "info", **data) -> None:
    session.add(Event(user_id=user_id, message=message, level=level, data=data))
    log.info("[%s] user=%s %s", level, user_id, message)
