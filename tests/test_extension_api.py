"""Endpoints de la extensión: cola, plan de relleno, envío hecho por el usuario y capturas."""
from sqlalchemy import select

from knok.db.models import Job
from tests.test_review import preparar


def test_cola_plan_y_envio_por_el_usuario(client, auth):
    b = preparar(client, auth)
    cola = client.get(f"/extension/queue?batch_id={b['id']}", headers=auth).json()
    assert cola and all(c["route"] in ("ats_extension", "portal_copilot") for c in cola)
    gh = next(c for c in cola if c["title"] == "Deck Cadet – 2026 Intake")
    campos_pagina = [
        {"id": "knok-0", "label": "First Name", "type": "text", "required": True},
        {"id": "knok-1", "label": "Resume/CV", "type": "file", "required": True},
        {"id": "knok-2", "label": "Are you legally authorized to work in Spain?", "type": "select", "required": True,
         "options": [{"label": "Yes", "value": "1"}, {"label": "No", "value": "0"}]},
        {"id": "knok-3", "label": "I agree to the privacy policy", "type": "checkbox", "required": True},
    ]
    client.put("/me/answers/work_authorization", headers=auth, json={"value": ["EU"]})
    # Sin application_id: la API la encuentra por la URL de la página
    plan = client.post("/extension/fill-plan", headers=auth, json={"url": gh["apply_url"], "fields": campos_pagina}).json()
    assert plan["application_id"] == gh["id"] and plan["never_submit"] is True
    v = {f["id"]: f for f in plan["fields"]}
    assert v["knok-0"]["value"] == "Ana"
    assert v["knok-1"]["value"]["download_url"].endswith("/file")
    assert v["knok-2"]["value"] == "1"
    assert v["knok-3"]["value"] is None and v["knok-3"]["needs_review"]
    assert plan["missing"] == ["knok-3"]
    # La revisión por API ve lo mismo que hay en la página
    assert len(client.get(f"/applications/{gh['id']}", headers=auth).json()["fields"]) == 4
    # El usuario pulsa Enviar en la web → la extensión avisa
    r = client.post("/extension/submitted", headers=auth, json={"application_id": gh["id"]}).json()
    assert r["status"] == "sent"
    assert client.post("/extension/submitted", headers=auth, json={"application_id": gh["id"]}).json()["status"] == "sent"


def test_aviso_de_linkedin(client, auth):
    plan = client.post("/extension/fill-plan", headers=auth, json={"url": "https://www.linkedin.com/jobs/view/1/",
                                                                   "platform": "linkedin", "fields": []}).json()
    assert any(w["type"] == "linkedin_risk" for w in plan["warnings"])


def test_captura_guarda_hechos_minimos_en_la_base_comun(client, auth, db):
    r = client.post("/extension/captures", headers=auth, json={
        "url": "https://www.linkedin.com/jobs/view/3901234567/", "title": "Backend Engineer", "company": "Acme Corp",
        "location": "Madrid, Spain", "apply_url": "https://boards.greenhouse.io/acme/jobs/77",
        "description": "Texto completo copiado de LinkedIn"})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["application"]["route"] == "ats_extension"          # el enlace va al ATS de la empresa
    assert d["application"]["notes"] == "Texto completo copiado de LinkedIn"   # privado del usuario
    job = db.get(Job, d["job_id"])
    assert job.description == "" and job.source == "capture"      # la base común no guarda el texto del portal
    from knok.db.models import AtsBoard
    assert db.scalar(select(AtsBoard).where(AtsBoard.slug == "acme"))  # el catálogo de slugs crece


def test_captura_de_copia_usa_la_original(client, auth):
    s = client.post("/searches", headers=auth, json={"countries": ["es"]}).json()
    res = client.get(f"/searches/{s['id']}/results", headers=auth).json()
    original = next(i for i in res["items"] if i["job"] and i["job"]["title"] == "Deck Cadet – 2026 Intake")
    r = client.post("/extension/captures", headers=auth, json={
        "url": "https://www.linkedin.com/jobs/view/111/", "title": "Deck Cadet - 2026 Intake",
        "company": "Naviera Cantábrica de Ferris", "location": "Santander"}).json()
    assert r["original_job_id"] == original["job"]["id"]
    assert r["application"]["job"]["id"] == original["job"]["id"]


def test_web_cualquiera_usa_la_empresa_y_el_puesto_de_la_pagina(client, auth):
    """Sin candidatura en knok (p. ej. la página de prueba): la carta nombra la empresa y el puesto que dice la web."""
    client.patch("/me/profile", headers=auth, json={"first_name": "Ana", "last_name": "Pérez"})
    campos = [{"id": "knok-1", "label": "Nombre", "type": "text", "required": True},
              {"id": "knok-3", "label": "Apellidos", "type": "text", "required": True},
              {"id": "knok-2", "label": "Carta de presentación", "type": "textarea"}]
    plan = client.post("/extension/fill-plan", headers=auth, json={
        "url": "http://localhost:8000/ui/prueba-extension.html", "fields": campos,
        "company": "Empresa de Ejemplo S.L.", "title": "Auxiliar administrativo/a"}).json()
    assert plan["application_id"] is None and plan["never_submit"] is True
    assert "Empresa de Ejemplo S.L." in plan["cover_letter"] and "Auxiliar administrativo/a" in plan["cover_letter"]
    valores = {f["id"]: f["value"] for f in plan["fields"]}
    assert valores["knok-1"] == "Ana" and valores["knok-3"] == "Pérez"


def test_la_extension_se_conecta_sola_al_knok_local(client, monkeypatch):
    from knok.settings import get_settings
    monkeypatch.setenv("KNOK_LOCAL_SINGLE_USER", "true")
    get_settings.cache_clear()
    tok = client.get("/auth/local?client=extension").json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    nombres = [t["name"] for t in client.get("/auth/tokens", headers=h).json()]
    assert "extensión de Chrome" in nombres
    assert client.get("/extension/config", headers=h).status_code == 200
