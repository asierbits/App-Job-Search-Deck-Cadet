"""Ofertas guardadas desde LinkedIn: guardar la página en lote y pasar al formulario de la empresa si lo tiene."""
import pytest

from knok.core.http import FakeHttp, set_default_http
from knok.services.ats_discovery import same_company, slug_candidates
from tests.conftest import fixture_json, register

GH = "https://boards-api.greenhouse.io/v1/boards"


def test_nombres_de_tablero_posibles():
    assert slug_candidates("Acme Corp, S.L.") == ["acmecorp", "acme-corp"]
    assert slug_candidates("Nordsee Reederei GmbH") == ["nordseereederei", "nordsee-reederei"]
    assert slug_candidates("S.A.") == []
    assert same_company("Acme Corp", "ACME Corp S.L.") is True
    assert same_company("Otra Empresa", "Acme Corp") is False
    assert same_company("", "Acme Corp") is None


@pytest.fixture
def red(monkeypatch):
    """Greenhouse responde para «acmecorp»; todo lo demás no existe (404)."""
    monkeypatch.setenv("KNOK_OFFLINE_SOURCES", "0")
    from knok.settings import get_settings
    get_settings.cache_clear()
    http = FakeHttp({f"{GH}/acmecorp/jobs": fixture_json("ats/greenhouse_jobs.json"),
                     f"{GH}/acmecorp": fixture_json("ats/greenhouse_board.json")})
    set_default_http(http)
    yield http
    set_default_http(None)


def linkedin(n: int, titulo: str, empresa: str, easy: bool = False) -> dict:
    return {"url": f"https://www.linkedin.com/jobs/view/{4000 + n}/", "title": titulo, "company": empresa,
            "location": "Madrid, Comunidad de Madrid, España", "easy_apply": easy}


def test_guardar_la_pagina_y_pasar_al_formulario_de_la_empresa(client, red):
    h = register(client, pack="general")
    client.patch("/me/profile", headers=h, json={"first_name": "Ana", "last_name": "Pérez"})
    r = client.post("/extension/captures/bulk", headers=h, json={"items": [
        linkedin(1, "Backend Engineer (m/f/d)", "Acme Corp"),            # está en su Greenhouse → piloto
        linkedin(2, "Diseñadora de producto", "Estudio Sin Tablero"),     # no se encuentra: queda a mano
        linkedin(3, "Data Analyst", "Otra Firma", easy=True),             # solicitud sencilla: de una en una
    ]}).json()
    assert r["saved"] == 3 and r["errors"] == 0 and r["one_by_one"] == 1 and r["locating"] == 3

    cola = {q["title"]: q for q in client.get("/extension/queue", headers=h).json()}
    acme = cola["Backend Engineer (m/f/d)"]
    assert acme["route"] == "ats_extension" and acme["apply_url"].startswith("https://boards.greenhouse.io/")
    assert cola["Data Analyst"]["route"] == "portal_copilot"
    assert "Diseñadora de producto" not in cola
    llamadas = [c[1] for c in red.calls]
    assert any("/estudiosintablero" in u for u in llamadas)                # se probó, no existe
    assert not any("linkedin.com" in u for u in llamadas)                 # nunca se pide nada a LinkedIn
    eventos = [e["message"] for e in client.get("/events", headers=h).json()]
    assert any("Acme Corp: tiene sus ofertas en Greenhouse" in m for m in eventos)

    # Volver a guardar la misma página no duplica nada ni vuelve a preguntar por tableros que no existen
    antes = len(red.calls)
    r2 = client.post("/extension/captures/bulk", headers=h, json={"items": [linkedin(2, "Diseñadora de producto", "Estudio Sin Tablero")]}).json()
    assert r2["saved"] == 1 and r2["new"] == 0
    assert not any("/estudiosintablero" in c[1] for c in red.calls[antes:])


def test_sin_red_no_busca_tableros(client, auth):
    r = client.post("/extension/captures/bulk", headers=auth, json={"items": [linkedin(9, "Backend Engineer", "Acme Corp")]})
    assert r.status_code == 201 and r.json()["saved"] == 1


def test_lote_limitado(client, auth):
    items = [linkedin(i, f"Puesto {i}", "Empresa") for i in range(61)]
    assert client.post("/extension/captures/bulk", headers=auth, json={"items": items}).status_code == 422
