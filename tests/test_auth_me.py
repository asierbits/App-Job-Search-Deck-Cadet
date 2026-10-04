from tests.conftest import register


def test_registro_login_y_logout(client):
    h = register(client)
    assert client.get("/me", headers=h).status_code == 200
    r = client.post("/auth/login", json={"email": "ANA@example.com", "password": "contraseña-segura"})
    assert r.status_code == 200
    assert client.post("/auth/logout", headers=h).status_code == 204
    assert client.get("/me", headers=h).status_code == 401


def test_email_duplicado_y_credenciales_malas(client):
    register(client)
    r = client.post("/auth/register", json={"email": "ana@example.com", "password": "otra-contraseña"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "email_taken"
    r = client.post("/auth/login", json={"email": "ana@example.com", "password": "mala-mala"})
    assert r.status_code == 401


def test_sin_token(client):
    r = client.get("/me")
    assert r.status_code == 401 and r.json()["detail"]["code"] == "unauthenticated"


def test_token_para_la_extension(client, auth):
    r = client.post("/auth/tokens", json={"name": "extensión"}, headers=auth)
    assert r.status_code == 201
    ext = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.get("/me", headers=ext).status_code == 200
    tokens = client.get("/auth/tokens", headers=auth).json()
    assert len(tokens) == 2 and sum(t["current"] for t in tokens) == 1
    assert client.delete(f"/auth/tokens/{r.json()['token_id']}", headers=auth).status_code == 204
    assert client.get("/me", headers=ext).status_code == 401


def test_perfil_y_ajustes(client, auth):
    r = client.patch("/me/profile", headers=auth, json={
        "first_name": "Ana", "last_name": "Pérez", "country": "ES", "mode": "test",
        "pack_data": {"titulacion": "Grado en Náutica", "titulacion_en": "BSc Nautical Science"},
        "languages": [{"code": "en", "level": "C1"}]})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["country"] == "es" and p["mode"] == "test" and p["pack_data"]["titulacion_en"]
    me = client.get("/me", headers=auth).json()
    codigos = {x["code"] for x in me["sending_problems"]}
    assert {"gmail_not_connected", "missing_cv"} <= codigos
    assert me["reply_forwarding_address"].startswith("u-")


def test_limite_diario_no_supera_el_de_gmail(client, auth):
    r = client.patch("/me/profile", headers=auth, json={"daily_limit": 900})
    assert r.status_code == 422


def test_pack_desconocido(client, auth):
    assert client.patch("/me/profile", headers=auth, json={"pack": "astronautas"}).status_code == 422


def test_documentos(client, auth):
    r = client.post("/me/documents", headers=auth, files={"file": ("mi cv.pdf", b"%PDF-1.4 cv", "application/pdf")},
                    data={"kind": "cv", "language": "es"})
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["is_default"] is True and doc["filename"] == "mi cv.pdf"
    r2 = client.post("/me/documents", headers=auth, files={"file": ("cv2.pdf", b"%PDF-1.4 otro", "application/pdf")},
                     data={"kind": "cv", "language": "es", "is_default": "true"})
    docs = {d["id"]: d for d in client.get("/me/documents", headers=auth).json()}
    assert docs[r2.json()["id"]]["is_default"] and not docs[doc["id"]]["is_default"]
    f = client.get(f"/me/documents/{doc['id']}/file", headers=auth)
    assert f.content == b"%PDF-1.4 cv"
    mal = client.post("/me/documents", headers=auth, files={"file": ("virus.exe", b"MZ", "application/x")})
    assert mal.status_code == 422
    assert client.delete(f"/me/documents/{doc['id']}", headers=auth).status_code == 204


def test_documentos_de_otro_usuario_no_se_ven(client, auth):
    r = client.post("/me/documents", headers=auth, files={"file": ("cv.pdf", b"x", "application/pdf")})
    otro = register(client, email="luis@example.com")
    assert client.get(f"/me/documents/{r.json()['id']}/file", headers=otro).status_code == 404


def test_banco_de_respuestas(client, auth):
    claves = {a["key"]: a for a in client.get("/me/answers", headers=auth).json()}
    assert "stcw_certificates" in claves and claves["eeo_gender"]["sensitive"]
    assert client.put("/me/answers/years_experience", headers=auth, json={"value": 2}).status_code == 200
    assert client.put("/me/answers/salary_expectation", headers=auth,
                      json={"value": "30.000 €", "language": "es"}).status_code == 200
    assert client.put("/me/answers/inventada", headers=auth, json={"value": 1}).status_code == 422
    claves = {a["key"]: a for a in client.get("/me/answers", headers=auth).json()}
    assert claves["years_experience"]["values"] == {"*": 2}
    assert claves["salary_expectation"]["values"] == {"es": "30.000 €"}
    r = client.put("/me/custom-answers", headers=auth, json={"label": "¿Por qué quieres trabajar aquí?", "value": "…"})
    r2 = client.put("/me/custom-answers", headers=auth, json={"label": "¿POR QUÉ quieres trabajar aquí?", "value": "b"})
    assert r.json()["id"] == r2.json()["id"]


def test_plantillas_y_vista_previa(client, auth):
    client.patch("/me/profile", headers=auth, json={"first_name": "Ana", "last_name": "Pérez",
                                                    "pack_data": {"titulacion": "Grado en Náutica"}})
    t = client.get("/me/templates", headers=auth).json()
    assert "titulacion" in t["variables"]
    email_es = next(x for x in t["templates"] if x["kind"] == "email" and x["audience"] == "company"
                    and x["language"] == "es")
    assert email_es["source"] == "pack"
    pv = client.post("/me/templates/preview", headers=auth,
                     json={"language": "es", "company_name": "Naviera Ejemplo"}).json()
    assert "Naviera Ejemplo" in pv["body"] and "Ana Pérez" in pv["body"]
    assert "universidad" in pv["blocking"] and "telefono" not in pv["blocking"]
    assert "{telefono}" not in pv["body"]
    r = client.put("/me/templates/email/company/es", headers=auth, json={"subject": "Hola {empresa}", "body": "Cuerpo {nombre}"})
    assert r.status_code == 200
    pv = client.post("/me/templates/preview", headers=auth, json={"language": "es", "company_name": "X"}).json()
    assert pv["subject"] == "Hola X"
    assert client.delete("/me/templates/email/company/es", headers=auth).status_code == 204


def test_exportar_y_borrar_cuenta(client, auth):
    client.post("/me/documents", headers=auth, files={"file": ("cv.pdf", b"x", "application/pdf")})
    exp = client.get("/me/export", headers=auth)
    assert exp.status_code == 200 and "password_hash" not in exp.text and exp.json()["documents"]
    assert client.post("/me/delete", headers=auth, json={"password": "mala"}).status_code == 401
    assert client.post("/me/delete", headers=auth, json={"password": "contraseña-segura"}).status_code == 204
    r = client.post("/auth/login", json={"email": "ana@example.com", "password": "contraseña-segura"})
    assert r.status_code == 401


def test_packs_publicos(client):
    r = client.get("/packs")
    assert {p["slug"] for p in r.json()} >= {"marina_mercante", "doctorados_investigacion"}
    d = client.get("/packs/marina_mercante").json()
    assert any(f["key"] == "titulacion" for f in d["profile_fields"])
    assert client.get("/packs/nada").status_code == 404
