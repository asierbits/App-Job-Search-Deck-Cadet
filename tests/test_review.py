"""Flujo completo: búsqueda → tanda → revisión → corrección → UN clic → envío (en Simulación)."""
from sqlalchemy import select

from knok.db.models import CustomAnswer, UnknownQuestion
from tests.conftest import register


def preparar(client, h, **perfil):
    client.patch("/me/profile", headers=h, json={"first_name": "Ana", "last_name": "Pérez", "phone": "+34 600",
                                                 "country": "es", "pack_data": {"titulacion": "Grado en Náutica",
                                                                                "universidad": "Universidad de Cádiz"},
                                                 **perfil})
    client.post("/me/documents", headers=h, files={"file": ("cv.pdf", b"%PDF cv", "application/pdf")}, data={"kind": "cv"})
    client.put("/me/answers/sea_time_months", headers=h, json={"value": 4})
    s = client.post("/searches", headers=h, json={"countries": ["es", "de", "gr", "dk"]}).json()
    return client.post("/batches", headers=h, json={"search_id": s["id"], "size": 40}).json()


def test_tanda_revision_y_envio(client, auth):
    b = preparar(client, auth)
    assert b["status"] == "review" and len(b["items"]) >= 5
    por_titulo = {(i["job"] or {}).get("title") or i["company"]["name"]: i for i in b["items"]}
    assert "Alumno de puente – Ferry Algeciras-Ceuta" not in por_titulo or \
        por_titulo["Alumno de puente – Ferry Algeciras-Ceuta"]["route"] != "portal_api"
    gh = por_titulo["Deck Cadet – 2026 Intake"]
    assert gh["route"] == "ats_extension"
    campos = {f["id"]: f for f in gh["fields"]}
    assert campos["first_name"]["value"] == "Ana" and campos["resume"]["value"]["filename"] == "cv.pdf"
    assert campos["question_2"]["value"] == 4                          # meses de mar del banco (pack)
    assert "question_3" in gh["needs_review"] and gh["cover_letter"]
    # pregunta nueva registrada para ampliar el diccionario
    correo = next(i for i in b["items"] if i["route"] == "email" and i["job"] is None)
    assert correo["email"]["to"] and "Ana Pérez" in correo["email"]["body"] and correo["blocking"] == []
    assert correo["email"]["attachments"]

    # El usuario contesta la pregunta desconocida → se recuerda
    r = client.patch(f"/applications/{gh['id']}", headers=auth, json={"fields": [{"id": "question_3", "value": "El buque escuela"}]})
    assert r.status_code == 200 and "question_3" not in r.json()["needs_review"]

    # UN clic con las seleccionadas
    seleccion = [gh["id"], correo["id"]]
    res = client.post(f"/batches/{b['id']}/send", headers=auth, json={"application_ids": seleccion}).json()["results"]
    salidas = {x["id"]: x["outcome"] for x in res}
    assert salidas[gh["id"]] == "ready_for_extension" and salidas[correo["id"]] == "email_queued"
    assert client.get(f"/applications/{correo['id']}", headers=auth).json()["status"] in ("sent", "replied", "interview", "discarded")
    assert client.get(f"/applications/{gh['id']}", headers=auth).json()["status"] == "confirmed"
    # Las no seleccionadas siguen preparadas: nada se envía sin clic
    otras = [i for i in client.get(f"/batches/{b['id']}", headers=auth).json()["items"] if i["id"] not in seleccion]
    assert all(i["status"] == "prepared" for i in otras)
    # Enviar dos veces no duplica
    res2 = client.post(f"/batches/{b['id']}/send", headers=auth, json={"application_ids": [correo["id"]]}).json()["results"]
    assert res2[0]["outcome"] == "blocked"


def test_variables_vacias_bloquean_hasta_revisar(client, auth):
    b = preparar(client, auth, pack_data={"titulacion": "", "universidad": ""})
    correo = next(i for i in b["items"] if i["route"] == "email")
    assert any(p["code"] == "missing_variables" for p in correo["blocking"])
    res = client.post(f"/applications/{correo['id']}/send", headers=auth).json()["results"][0]
    assert res["outcome"] == "blocked"
    client.patch(f"/applications/{correo['id']}", headers=auth, json={"body": "Texto revisado por mí.\n"})
    assert client.post(f"/applications/{correo['id']}/send", headers=auth).json()["results"][0]["outcome"] == "email_queued"


def test_no_se_puede_poner_un_correo_personal(client, auth):
    b = preparar(client, auth)
    correo = next(i for i in b["items"] if i["route"] == "email")
    r = client.patch(f"/applications/{correo['id']}", headers=auth, json={"contact_email": "juan.perez@empresa.com"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "personal_email"


def test_respuestas_recordadas_y_preguntas_nuevas(client, auth, db):
    b = preparar(client, auth)
    gh = next(i for i in b["items"] if (i["job"] or {}).get("title") == "Deck Cadet – 2026 Intake")
    assert db.scalar(select(UnknownQuestion).where(UnknownQuestion.label == "What is your favourite ship and why?"))
    client.patch(f"/applications/{gh['id']}", headers=auth, json={"fields": [{"id": "question_3", "value": "El Elcano"}]})
    assert "El Elcano" in [c.value for c in db.scalars(select(CustomAnswer))]


def test_admin_asigna_pregunta_nueva(client, auth, db, monkeypatch):
    preparar(client, auth)
    monkeypatch.setenv("KNOK_ADMIN_EMAILS", "jefa@example.com")
    from knok.settings import get_settings
    get_settings.cache_clear()
    admin = register(client, email="jefa@example.com")
    assert client.get("/admin/unknown-questions", headers=auth).status_code == 403
    preguntas = client.get("/admin/unknown-questions", headers=admin).json()
    q = next(p for p in preguntas if p["label"] == "What is your favourite ship and why?")
    r = client.post(f"/admin/unknown-questions/{q['id']}/map", headers=admin, json={"key": "cover_letter"})
    assert r.status_code == 200
    from knok.services.filling import learned_patterns
    assert any(p.key == "cover_letter" for p in learned_patterns(db, "marina_mercante"))


def test_marcar_enviada_y_descartar(client, auth):
    b = preparar(client, auth)
    a, d = b["items"][0], b["items"][1]
    assert client.post(f"/applications/{a['id']}/mark-sent", headers=auth).json()["status"] == "sent"
    assert client.post(f"/applications/{a['id']}/mark-sent", headers=auth).status_code == 409
    assert client.post(f"/applications/{d['id']}/discard", headers=auth).json()["status"] == "discarded"


def test_tandas_de_otro_usuario(client, auth):
    b = preparar(client, auth)
    otro = register(client, email="otro@example.com")
    assert client.get(f"/batches/{b['id']}", headers=otro).status_code == 404
    assert client.post(f"/batches/{b['id']}/send", headers=otro, json={"application_ids": [b["items"][0]["id"]]}).status_code == 404
