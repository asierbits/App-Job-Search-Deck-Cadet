"""Motor y sesiones de SQLAlchemy."""
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from knok.settings import get_settings

_engine: Engine | None = None
_factory: sessionmaker | None = None


def configure(url: str | None = None) -> Engine:
    """Crea (o recrea) el motor. Los tests lo llaman con su propia URL."""
    global _engine, _factory
    url = url or get_settings().database_url
    kwargs = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        # Modo local sin Postgres: la API y el worker integrado comparten el archivo
        kwargs = {"connect_args": {"check_same_thread": False, "timeout": 30}}
    _engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def _pragmas(conn, _):
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()
    _factory = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine


def engine() -> Engine:
    if _engine is None:
        configure()
    return _engine


def new_session() -> Session:
    if _factory is None:
        configure()
    return _factory()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Commit si todo va bien, rollback si falla, cierre siempre."""
    s = new_session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
