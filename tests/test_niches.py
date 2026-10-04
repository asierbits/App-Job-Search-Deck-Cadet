"""Nichos propios: cualquier sector, creado desde el panel, y una búsqueda real con él."""
from knok.core.sources import osm
from knok.packs.loader import find_pack
from tests.conftest import register
from tests.test_live_search import worker_real  # noqa: F401  (fixture con red simulada)

NICHO = {"name": "Consultoría junior", "description": "Primer empleo en consultoras",
         "sectors": ["consultoria", "no-existe"], "job_titles": "consultor junior, analista junior",
         "mention_terms": ["trabaja con nosotros", "Prácticas"], "mailboxes": ["rrhh@", "empleo"],
         "default_countries": ["ES", "pt"], "exclude_terms": ["senior"]}


def test_catalogo_de_sectores(client):
    s = {x["id"]: x for x in client.get("/niches/sectors").json()}
    assert s["hoteles"]["osm"]["tourism"] and s["empleo"]["agency"] and len(s) >= 25


def test_crear_usar_editar_y_borrar(client, auth):
    n = client.post("/me/niches", headers=auth, json=NICHO).json()
    assert n["slug"].startswith("n-consultoria-junior-") and n["spec"]["sectors"] == ["consultoria"]
    assert n["spec"]["job_titles"] == ["consultor junior", "analista junior"]
    assert n["spec"]["mailboxes"] == ["rrhh", "empleo"] and n["spec"]["default_countries"] == ["es", "pt"]
    assert client.get("/me", headers=auth).json()["profile"]["pack"] == n["slug"]   # se usa al crearlo

    pack = find_pack(n["slug"])
    assert pack.sources.osm.tags == {"office": ["consulting"]}
    assert pack.crawl.mailbox_priority[:2] == ["rrhh", "empleo"]
    assert [m.variants for m in pack.crawl.mentions] == [["trabaja con nosotros"], ["practicas"]]
    assert pack.match.negative == ["senior"] and pack.template("email", "company", "es")

    st = client.get("/panel/state", headers=auth).json()
    assert st["pack"]["custom"] and st["pack"]["name"] == "Consultoría junior"
    assert any(p["slug"] == n["slug"] and p["custom"] for p in st["packs"])
    assert client.get(f"/packs/{n['slug']}").json()["profile_fields"]

    r = client.put(f"/me/niches/{n['slug']}", headers=auth, json={**NICHO, "sectors": ["consultoria", "hoteles"]}).json()
    assert set(find_pack(n["slug"]).sources.osm.tags) == {"office", "tourism"} and len(r["sector_labels"]) == 2

    assert client.delete(f"/me/niches/{n['slug']}", headers=auth).status_code == 204
    assert client.get("/me", headers=auth).json()["profile"]["pack"] == "general"
    assert find_pack(n["slug"]) is None


def test_validacion_y_privacidad(client, auth):
    assert client.post("/me/niches", headers=auth, json={"name": "Vacío"}).status_code == 422
    n = client.post("/me/niches", headers=auth, json=NICHO).json()
    otro = register(client, email="otra@example.com")
    assert client.patch("/me/profile", headers=otro, json={"pack": n["slug"]}).status_code == 422
    assert client.post("/searches", headers=otro, json={"pack": n["slug"]}).status_code == 422
    assert client.put(f"/me/niches/{n['slug']}", headers=otro, json=NICHO).status_code == 404


def test_busqueda_real_con_un_nicho_propio(client, worker_real):  # noqa: F811
    from knok.worker import queue
    h = register(client, email="nicho@example.com", pack="general")
    n = client.post("/me/niches", headers=h, json=NICHO).json()
    s = client.post("/searches", headers=h, json={"cities": ["Bilbao"], "sources": ["companies"], "max_webs": 10}).json()
    assert s["params"]["pack"] == n["slug"] and s["params"]["countries"] == ["es", "pt"]
    assert queue.run_one() is True
    d = client.get(f"/searches/{s['id']}", headers=h).json()
    assert d["status"] == "done", d
    consulta = next(c for c in worker_real.calls if c[1].startswith(osm.OVERPASS[0]))
    assert "consulting" in str(consulta) and "engineer" not in str(consulta)   # solo el sector elegido
    filas = {f["name"]: f for f in client.get("/panel/board", headers=h).json()["items"]}
    alfa = filas["Consultora Alfa"]
    assert alfa["email"] == "rrhh@alfa-consultora.com" and "trabaja con nosotros" in alfa["mentions"]
    assert any("menciona" in r for r in alfa["reasons"])


def test_sin_ciudades_avisa(client, worker_real):  # noqa: F811
    from knok.worker import queue
    h = register(client, email="sinciudad@example.com", pack="general")
    client.post("/me/niches", headers=h, json=NICHO)
    client.post("/searches", headers=h, json={"sources": ["companies"]})
    queue.run_one()
    eventos = [e["message"] for e in client.get("/events", headers=h).json()]
    assert any("indica al menos una ciudad" in m for m in eventos)
