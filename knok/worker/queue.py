"""Cola de tareas sobre Postgres, sin Redis.

- `enqueue()` guarda una fila en `tasks` dentro de la transacción del que llama: si esa transacción
  falla, la tarea tampoco existe (no hay tareas "fantasma").
- El worker reclama tareas con `SELECT … FOR UPDATE SKIP LOCKED`, así varios workers pueden
  trabajar a la vez sin pisarse.
- Reintentos con espera creciente; `Reschedule` permite aplazar sin contar como fallo
  (p. ej. límite diario de envíos alcanzado → mañana).
- Con KNOK_TASKS_EAGER=1 las tareas se ejecutan en el acto, en la misma sesión (tests y demos).
"""
import logging
import os
import socket
import traceback
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from knok.db import session as dbs
from knok.db.models import Task, utcnow
from knok.settings import get_settings

log = logging.getLogger("knok.worker")

TaskFn = Callable[[Session, dict], dict | None]
REGISTRY: dict[str, TaskFn] = {}
STALE_AFTER = timedelta(minutes=15)


class Reschedule(Exception):
    """Lánzala desde una tarea para aplazarla sin gastar un intento."""

    def __init__(self, run_after: datetime, reason: str = ""):
        super().__init__(reason)
        self.run_after = run_after
        self.reason = reason


def task(name: str):
    def deco(fn: TaskFn) -> TaskFn:
        REGISTRY[name] = fn
        return fn
    return deco


def enqueue(session: Session, name: str, payload: dict | None = None, *, user_id: int | None = None,
            run_after: datetime | None = None, max_attempts: int = 3) -> Task:
    if name not in REGISTRY:
        _load_tasks()
        if name not in REGISTRY:
            raise KeyError(f"tarea desconocida: {name}")
    t = Task(name=name, payload=payload or {}, user_id=user_id, run_after=run_after or utcnow(),
             max_attempts=max_attempts)
    session.add(t)
    session.flush()
    if get_settings().tasks_eager:
        _run_inline(session, t)
    return t


def _run_inline(session: Session, t: Task) -> None:
    t.status, t.attempts, t.locked_at = "running", 1, utcnow()
    try:
        with session.begin_nested():
            t.result = REGISTRY[t.name](session, dict(t.payload)) or {}
        t.status = "done"
    except Reschedule as r:
        t.status, t.run_after, t.last_error = "queued", r.run_after, r.reason
    except Exception as ex:  # en modo inmediato el fallo queda registrado, no rompe al que llama
        t.status, t.last_error = "failed", f"{type(ex).__name__}: {ex}"
        log.exception("tarea %s falló", t.name)
    t.finished_at = utcnow() if t.status != "queued" else None
    session.flush()


def _load_tasks() -> None:
    import knok.worker.tasks  # noqa: F401  registra las tareas


# ------------------------------------------------------------------------------------- worker

def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def claim(session: Session, wid: str) -> Task | None:
    q = (select(Task).where(Task.status == "queued", Task.run_after <= utcnow())
         .order_by(Task.run_after, Task.id).limit(1))
    if session.bind.dialect.name == "postgresql":
        q = q.with_for_update(skip_locked=True)
    t = session.scalars(q).first()
    if t is None:
        return None
    t.status, t.locked_at, t.locked_by = "running", utcnow(), wid
    t.attempts += 1
    session.commit()
    return t


def run_one(wid: str | None = None) -> bool:
    """Ejecuta una tarea pendiente. Devuelve False si no había ninguna."""
    _load_tasks()
    wid = wid or worker_id()
    with dbs.new_session() as s:
        t = claim(s, wid)
        if t is None:
            return False
        task_id, name, payload = t.id, t.name, dict(t.payload)

    s = dbs.new_session()
    try:
        result = REGISTRY[name](s, payload) or {}
        s.commit()
        _finish(task_id, status="done", result=result)
    except Reschedule as r:
        s.rollback()
        _finish(task_id, status="queued", run_after=r.run_after, error=r.reason, refund=True)
    except Exception as ex:
        s.rollback()
        log.error("tarea %s (#%s) falló: %s", name, task_id, ex)
        _fail(task_id, f"{type(ex).__name__}: {ex}\n{traceback.format_exc(limit=5)}")
    finally:
        s.close()
    return True


def _finish(task_id: int, *, status: str, result: dict | None = None, run_after: datetime | None = None,
            error: str = "", refund: bool = False) -> None:
    with dbs.session_scope() as s:
        t = s.get(Task, task_id)
        t.status = status
        t.locked_at, t.locked_by = None, ""
        if result is not None:
            t.result = result
        if run_after:
            t.run_after = run_after
        if refund:
            t.attempts = max(0, t.attempts - 1)
        t.last_error = error
        t.finished_at = utcnow() if status in ("done", "failed") else None


def _fail(task_id: int, error: str) -> None:
    with dbs.session_scope() as s:
        t = s.get(Task, task_id)
        t.last_error = error[:4000]
        t.locked_at, t.locked_by = None, ""
        if t.attempts >= t.max_attempts:
            t.status, t.finished_at = "failed", utcnow()
        else:
            t.status = "queued"
            t.run_after = utcnow() + timedelta(seconds=30 * 2 ** (t.attempts - 1))


def requeue_stale(session: Session) -> int:
    """Tareas que un worker caído dejó 'running': vuelven a la cola."""
    limite = utcnow() - STALE_AFTER
    res = session.execute(update(Task).where(Task.status == "running", Task.locked_at < limite)
                          .values(status="queued", locked_at=None, locked_by=""))
    return res.rowcount or 0


def pending_exists(session: Session, name: str) -> bool:
    return session.scalar(select(Task.id).where(Task.name == name, Task.status.in_(("queued", "running")))
                          .limit(1)) is not None


def ensure_periodic(session: Session, name: str, every: timedelta, last_run: dict[str, datetime]) -> None:
    """Encola una tarea periódica si toca y no hay ya una pendiente."""
    ahora = datetime.now(timezone.utc)
    if ahora - last_run.get(name, datetime.min.replace(tzinfo=timezone.utc)) < every:
        return
    last_run[name] = ahora
    if not pending_exists(session, name):
        enqueue(session, name, {})
