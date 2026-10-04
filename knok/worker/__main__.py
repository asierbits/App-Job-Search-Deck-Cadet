"""Worker: `python -m knok.worker` (o `knok-worker`). Puedes arrancar varios a la vez."""
import logging
import signal
import threading
import time
from datetime import timedelta

from knok.db import session as dbs
from knok.worker import queue

# Tareas periódicas: nombre → cada cuánto
PERIODIC = {
    "deliver_simulated_replies": timedelta(seconds=15),
    "mark_followups_due": timedelta(hours=1),
    "refresh_ats_boards": timedelta(hours=6),
}

_stop = threading.Event()


def _parar(*_):
    _stop.set()


def run_loop(stop: threading.Event, wid: str | None = None) -> None:
    """Bucle del worker. Lo usa el proceso `python -m knok.worker` y el worker integrado en la API."""
    queue._load_tasks()
    wid = wid or queue.worker_id()
    logging.info("worker %s arrancado (%d tareas registradas)", wid, len(queue.REGISTRY))
    last_run: dict = {}
    ultima_limpieza = 0.0
    while not stop.is_set():
        try:
            if time.monotonic() - ultima_limpieza > 10:
                with dbs.session_scope() as s:
                    queue.requeue_stale(s)
                    for name, every in PERIODIC.items():
                        queue.ensure_periodic(s, name, every, last_run)
                ultima_limpieza = time.monotonic()
            if not queue.run_one(wid):
                stop.wait(1.0)
        except Exception:  # el worker no se cae por un error puntual de BD
            logging.exception("error en el bucle del worker")
            stop.wait(5)
    logging.info("worker %s detenido", wid)


def start_embedded() -> threading.Event:
    """Worker en un hilo dentro de la API (KNOK_EMBEDDED_WORKER=true)."""
    stop = threading.Event()
    threading.Thread(target=run_loop, args=(stop, queue.worker_id() + ":embebido"), daemon=True,
                     name="knok-worker").start()
    return stop


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    signal.signal(signal.SIGTERM, _parar)
    signal.signal(signal.SIGINT, _parar)
    run_loop(_stop)


if __name__ == "__main__":
    main()
