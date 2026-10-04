"""Búsqueda real por el worker (sin modo inmediato): fuentes → rastreo en directo → resultados, y Detener."""
import pytest
from sqlalchemy import select

from knok.core.http import FakeHttp, set_default_http
from knok.core.sources import osm
from knok.db.models import Search, SearchResult
from tests.conftest import register

WEB_A = ("<html><head><title>Consultora Alfa</title></head><body><a href='/empleo'>Trabaja con nosotros</a>"
         "<p>rrhh@alfa-consultora.com</p></body></html>")
WEB_B = "<html><body>Contacto: info@beta-ingenieria.es · Director: pedro.ruiz@beta-ingenieria.es</body></html>"


@pytest.fixture
def worker_real(monkeypatch):
    monkeypatch.setenv("KNOK_TASKS_EAGER", "0")
    monkeypatch.setenv("KNOK_OFFLINE_SOURCES", "0")   # este test prueba el camino real (con red simulada)
    monkeypatch.setattr(osm.time, "sleep", lambda s: None)
    from knok.settings import get_settings
    get_settings.cache_clear()
    http = FakeHttp({
        osm.NOMINATIM: [{"lat": "43.26", "lon": "-2.93", "display_name": "Bilbao, España", "address": {"country_code": "es"}}],
        osm.OVERPASS[0]: {"elements": [
            {"type": "node", "id": 1, "tags": {"name": "Consultora Alfa", "office": "consulting", "website": "https://alfa-consultora.com"}},
            {"type": "node", "id": 2, "tags": {"name": "Beta Ingeniería", "office": "engineer", "website": "https://beta-ingenieria.es"}},
        ]},
        "https://alfa-consultora.com/robots.txt": (404, "", "text/plain"),
        "https://alfa-consultora.com/empleo": "<html><body>Envía tu CV a rrhh@alfa-consultora.com</body></html>",
        "https://alfa-consultora.com": WEB_A,
        "https://beta-ingenieria.es/robots.txt": (404, "", "text/plain"),
        "https://beta-ingenieria.es": WEB_B,
    })
    set_default_http(http)
    yield http
    set_default_http(None)


def test_busqueda_en_directo_con_el_worker(client, worker_real, db):
    from knok.worker import queue
    h = register(client, email="real@example.com", pack="general")
    s = client.post("/searches", headers=h, json={"countries": ["es"], "cities": ["Bilbao"],
                                                  "sources": ["companies"], "max_webs": 50}).json()
    assert s["status"] == "queued"                        # no se ejecuta en la petición: lo hace el worker
    assert queue.run_one() is True
    d = client.get(f"/searches/{s['id']}", headers=h).json()
    assert d["status"] == "done", d
    prog = d["stats"]["progress"]
    assert prog["phase"] == "Terminado" and prog["done"] == 2
    resumenes = {r["name"]: r["summary"] for r in prog["recent"]}
    assert "rrhh@alfa-consultora.com" in resumenes["Consultora Alfa"] and "página de empleo" in resumenes["Consultora Alfa"]
    assert "info@beta-ingenieria.es" in resumenes["Beta Ingeniería"]
    assert d["stats"]["crawl"]["crawled"] == 2
    res = client.get(f"/searches/{s['id']}/results", headers=h).json()
    correos = {i["company"]["name"]: i for i in res["items"]}
    assert correos["Consultora Alfa"]["route"] == "email"
    eventos = [e["message"] for e in client.get("/events", headers=h).json()]
    assert any("OpenStreetMap: Bilbao: 2 empresas" in m for m in eventos)
    assert any(m.startswith("Búsqueda terminada") for m in eventos)


def test_detener_antes_de_empezar(client, worker_real):
    from knok.worker import queue
    h = register(client, email="stop@example.com", pack="general")
    s = client.post("/searches", headers=h, json={"cities": ["Bilbao"], "sources": ["companies"]}).json()
    assert client.post(f"/searches/{s['id']}/cancel", headers=h).json()["status"] == "cancelling"
    queue.run_one()
    assert client.get(f"/searches/{s['id']}", headers=h).json()["status"] == "cancelled"


def test_detener_a_mitad_conserva_lo_rastreado(client, worker_real, db, monkeypatch):
    """Al pulsar Detener durante el rastreo, se para y lo ya encontrado queda guardado."""
    from knok.services import progress as prog
    from knok.worker import queue
    h = register(client, email="mitad@example.com", pack="general")
    s = client.post("/searches", headers=h, json={"cities": ["Bilbao"], "sources": ["companies"]}).json()
    original = prog.Progress.check_cancel
    llamadas = {"n": 0}

    def cancelar_tras_la_primera_web(self):
        llamadas["n"] += 1
        if self.data["phase"] == "Rastreando webs" and self.data["done"] >= 1:
            raise prog.Cancelled()
        return original(self)

    monkeypatch.setattr(prog.Progress, "check_cancel", cancelar_tras_la_primera_web)
    queue.run_one()
    d = client.get(f"/searches/{s['id']}", headers=h).json()
    assert d["status"] == "cancelled" and d["stats"]["progress"]["done"] >= 1
