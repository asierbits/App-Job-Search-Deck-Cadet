"""Panel: sesión local, estado, tabla (resultados + candidaturas) y envío de lo marcado."""
from tests.conftest import register
from tests.test_review import preparar


def test_sesion_local_solo_si_esta_activada(client, monkeypatch):
    assert client.get("/auth/local").status_code == 404
    monkeypatch.setenv("KNOK_LOCAL_SINGLE_USER", "true")
    from knok.settings import get_settings
    get_settings.cache_clear()
    t1 = client.get("/auth/local").json()["token"]
    t2 = client.get("/auth/local").json()["token"]
    h1, h2 = ({"Authorization": f"Bearer {t}"} for t in (t1, t2))
    a, b = client.get("/me", headers=h1).json(), client.get("/me", headers=h2).json()
    assert a["user"]["id"] == b["user"]["id"] and a["profile"]["pack"] == "general"


def test_sesion_local_no_desde_fuera(db_engine, monkeypatch):
    from fastapi.testclient import TestClient
    from knok.api.main import create_app
    from knok.settings import get_settings
    monkeypatch.setenv("KNOK_LOCAL_SINGLE_USER", "true")
    get_settings.cache_clear()
    fuera = TestClient(create_app(), client=("8.8.8.8", 5000))
    assert fuera.get("/auth/local").status_code == 403


def test_estado_tabla_y_envio(client, auth):
    preparar(client, auth)   # perfil, CV, búsqueda (datos de ejemplo) y una tanda ya preparada
    st = client.get("/panel/state", headers=auth).json()
    assert st["search"]["status"] == "done" and st["pack"]["slug"] == "marina_mercante"
    assert st["connections"]["google"]["oauth_configured"] is False and st["profile"]["mode"] == "simulation"
    assert {"by_status", "daily"} <= set(st["summary"]) and st["events"]

    filas = client.get("/panel/board", headers=auth).json()["items"]
    assert filas and len({f["key"] for f in filas}) == len(filas)
    preparadas = [f for f in filas if f["status"] == "prepared"]
    nuevas = [f for f in filas if f["status"] == "new"]
    assert preparadas and all(f["application_id"] for f in preparadas)
    assert all(f["result_id"] and f["application_id"] is None for f in nuevas)
    # Una empresa con buzón genérico: el panel enseña a quién se escribiría
    correo = next(f for f in filas if f["route"] == "email" and f["kind"] == "company")
    assert "@" in correo["email"] and correo["name"]

    # Marcar una sin preparar y una preparada → un clic
    nueva_correo = next((f for f in nuevas if f["route"] == "email"), None)
    marcadas = {"application_ids": [correo["application_id"]] if correo["application_id"] else [],
                "result_ids": ([nueva_correo["result_id"]] if nueva_correo else [])
                + ([correo["result_id"]] if not correo["application_id"] else [])}
    res = client.post("/panel/send", headers=auth, json=marcadas).json()["results"]
    assert res and all(r["company"] for r in res)
    assert {r["outcome"] for r in res} <= {"email_queued", "blocked"}
    assert any(r["outcome"] == "email_queued" for r in res)

    despues = {f["key"]: f for f in client.get("/panel/board", headers=auth).json()["items"]}
    enviadas = [f for f in despues.values() if f["status"] in ("sent", "replied", "interview")]
    assert enviadas and all(f["sent_at"] for f in enviadas)
    # Nada más ha salido sin marcarlo
    assert len(enviadas) == sum(1 for r in res if r["outcome"] == "email_queued")


def test_preparar_y_descartar(client, auth):
    preparar(client, auth)
    filas = client.get("/panel/board", headers=auth).json()["items"]
    nueva = next(f for f in filas if f["status"] == "new")
    item = client.post("/panel/prepare", headers=auth, json={"result_ids": [nueva["result_id"]]}).json()["items"][0]
    assert item["status"] == "prepared"
    fila = next(f for f in client.get("/panel/board", headers=auth).json()["items"] if f["result_id"] == nueva["result_id"])
    assert fila["application_id"] == item["id"]          # la misma fila, ahora con su candidatura
    assert client.post("/panel/discard", headers=auth, json={"application_ids": [item["id"]]}).json()["discarded"] == 1


def test_no_se_toca_lo_de_otro(client, auth):
    preparar(client, auth)
    fila = client.get("/panel/board", headers=auth).json()["items"][0]
    otro = register(client, email="otro@example.com")
    campo = {"application_ids": [fila["application_id"]]} if fila["application_id"] else {"result_ids": [fila["result_id"]]}
    assert client.post("/panel/send", headers=otro, json=campo).status_code == 404
    assert client.post("/panel/send", headers=auth, json={}).status_code == 422


def test_la_tabla_no_se_vacia_si_la_nueva_busqueda_no_tiene_resultados(client, auth):
    preparar(client, auth)
    antes = client.get("/panel/board", headers=auth).json()
    from knok.db import session as dbs
    from knok.db.models import Search
    uid = client.get("/me", headers=auth).json()["user"]["id"]
    with dbs.session_scope() as s:   # una búsqueda detenida antes de empezar
        s.add(Search(user_id=uid, params={}, status="cancelled"))
    despues = client.get("/panel/board", headers=auth).json()
    assert despues["search"]["id"] == antes["search"]["id"] and len(despues["items"]) == len(antes["items"])
