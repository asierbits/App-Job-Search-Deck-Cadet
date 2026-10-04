def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_openapi_disponible(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert r.json()["info"]["title"] == "knok API"


def test_banco_de_pruebas(client):
    r = client.get("/playground")
    assert r.status_code == 200 and "Enviar seleccionadas" in r.text
