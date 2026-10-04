"""Progreso en directo de una búsqueda (lo que el panel enseña mientras trabaja).

Guarda en `search.stats["progress"]` la fase, cuántas webs lleva, cuáles se están rastreando ahora y las
últimas rastreadas con lo que se encontró. Fuera del modo inmediato (tests) hace commit por pasos, así lo
encontrado aparece en el panel mientras la búsqueda sigue, y se puede detener.
"""
import threading
import time
from collections import deque

from sqlalchemy import select
from sqlalchemy.orm import Session

from knok.db.models import Search
from knok.settings import get_settings


class Cancelled(Exception):
    """El usuario pulsó Detener."""


class Progress:
    COMMIT_EVERY = 1.0   # segundos entre commits (no más a menudo: la base de datos también la usa la API)

    def __init__(self, db: Session, search: Search):
        self.db, self.search = db, search
        self.eager = get_settings().tasks_eager
        self.lock = threading.Lock()
        self.now: dict[int, str] = {}
        self.recent: deque = deque(maxlen=20)
        self.data = {"phase": "Preparando", "done": 0, "total": 0, "found": {"emails": 0, "careers": 0, "mentions": 0,
                                                                              "warnings": 0, "blocked": 0}}
        self._last = 0.0
        self.on_checkpoint = None   # función opcional antes de cada commit (p. ej. recalcular resultados)

    # --- llamados desde los hilos de rastreo (solo memoria)
    def started(self, cid: int, name: str) -> None:
        with self.lock:
            self.now[cid] = name

    def finished(self, cid: int) -> None:
        with self.lock:
            self.now.pop(cid, None)

    # --- llamados desde el hilo principal
    def phase(self, text: str, total: int = 0) -> None:
        self.data.update(phase=text, done=0, total=total)
        self.checkpoint(force=True)

    def step(self, n: int = 1) -> None:
        self.data["done"] += n

    def crawled(self, name: str, summary: str, found: dict) -> None:
        self.recent.appendleft({"name": name, "summary": summary})
        for k, v in found.items():
            self.data["found"][k] = self.data["found"].get(k, 0) + int(bool(v))
        self.step()

    def snapshot(self) -> dict:
        with self.lock:
            ahora = list(self.now.values())
        return {**self.data, "now": ahora, "recent": list(self.recent)}

    def checkpoint(self, force: bool = False) -> None:
        stats = dict(self.search.stats or {})
        stats["progress"] = self.snapshot()
        self.search.stats = stats
        if self.eager:
            self.db.flush()
            return
        if force or time.monotonic() - self._last >= self.COMMIT_EVERY:
            if self.on_checkpoint:
                self.on_checkpoint()
            self.db.commit()
            self._last = time.monotonic()

    def check_cancel(self) -> None:
        if self.eager:
            return
        estado = self.db.scalar(select(Search.status).where(Search.id == self.search.id).execution_options(
            populate_existing=True))
        if estado == "cancelling":
            raise Cancelled()
