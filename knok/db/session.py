"""Motor y sesiones de SQLAlchemy."""
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
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
        kwargs = {"connect_args": {"check_same_thread": False}}
    _engine = create_engine(url, **kwargs)
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
