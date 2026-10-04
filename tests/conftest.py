"""Fixtures de tests.

Por defecto los tests usan SQLite en memoria (rápido, sin nada instalado). Para probar contra Postgres:
    KNOK_TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/knok_test pytest
Nunca hay red: las fuentes y Gmail se sustituyen por dobles con datos de ejemplo.
"""
import os
import pathlib

os.environ.setdefault("KNOK_ENV", "test")
os.environ["KNOK_TASKS_EAGER"] = "1"
os.environ["KNOK_OFFLINE_SOURCES"] = "1"
os.environ.setdefault("KNOK_SECRET_KEY", "test-secret")

import pytest  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from knok.db import session as dbs  # noqa: E402
from knok.db.models import Base  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
TEST_DB = os.environ.get("KNOK_TEST_DATABASE_URL", "")


@pytest.fixture(autouse=True)
def _settings(tmp_path, monkeypatch):
    from knok.settings import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("KNOK_STORAGE_DIR", str(tmp_path / "storage"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def db_engine():
    if TEST_DB:
        engine = dbs.configure(TEST_DB)
        Base.metadata.drop_all(engine)
    else:
        from sqlalchemy import create_engine
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        dbs._engine = engine
        from sqlalchemy.orm import sessionmaker
        dbs._factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def db(db_engine):
    s = dbs.new_session()
    yield s
    s.rollback()
    s.close()


@pytest.fixture
def client(db_engine):
    from fastapi.testclient import TestClient
    from knok.api.main import create_app
    return TestClient(create_app())


def fixture_text(rel: str) -> str:
    return (FIXTURES / rel).read_text(encoding="utf-8")


def fixture_json(rel: str):
    import json
    return json.loads(fixture_text(rel))


def register(client, email="ana@example.com", password="contraseña-segura", pack="marina_mercante"):
    r = client.post("/auth/register", json={"email": email, "password": password, "pack": pack})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def auth(client):
    return register(client)
