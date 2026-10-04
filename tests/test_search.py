"""Búsqueda completa en modo sin red (datos de ejemplo del pack) + ingesta con APIs simuladas."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from knok.core.http import FakeHttp
from knok.core.matching import score_job
from knok.db.models import AtsBoard, Company, CompanyEmail, Job, SourceRun
from knok.packs.loader import get_pack
from knok.services import ingest, sources
from tests.conftest import fixture_json


def test_busqueda_con_datos_de_ejemplo(client, auth):
    r = client.post("/searches", headers=auth, json={"countries": ["es", "de", "gr", "dk", "fr"]})
    assert r.status_code == 202, r.text
    s = client.get(f"/searches/{r.json()['id']}", headers=auth).json()
    assert s["status"] == "done", s
    res = client.get(f"/searches/{s['id']}/results?limit=100", headers=auth).json()
    titulos = {(i["job"] or {}).get("title"): i for i in res["items"] if i["job"]}
    assert "Accountant (m/f/d)" not in titulos                         # no es del nicho
    gh = titulos["Deck Cadet – 2026 Intake"]
    assert gh["route"] == "ats_extension" and gh["platform"] == "greenhouse"
    # la copia de Adzuna de la misma oferta no aparece: manda la original del ATS
    assert sum(1 for i in res["items"] if i["job"] and "2026 Intake" in i["job"]["title"]) == 1
    assert titulos["Trainee Officer (Deck) – Fleet Programme"]["route"] == "ats_extension"
    assert titulos["Deck Cadet"]["route"] in ("portal_copilot", "manual")
    assert titulos["Deck Cadet (alumno de puente)"]["route"] == "email"
    assert titulos["Deck cadet"]["route"] == "manual"   # solo había un correo personal: nunca se usa
    routes = s["stats"]["routes"]
    assert routes.get("ats_extension", 0) >= 3


def test_filtro_por_pais(client, auth):
    r = client.post("/searches", headers=auth, json={"countries": ["de"], "include_companies": False})
    res = client.get(f"/searches/{r.json()['id']}/results", headers=auth).json()
    assert res["items"] and all(i["job"]["country"] == "de" or i["job"]["remote"] for i in res["items"])


def test_palabras_clave_del_usuario(client, auth):
    r = client.post("/searches", headers=auth, json={"countries": ["es", "gr"], "keywords": ["LNG"],
                                                     "include_companies": False})
    res = client.get(f"/searches/{r.json()['id']}/results", headers=auth).json()
    assert [i["job"]["title"] for i in res["items"]] == ["Cadet Officer – LNG Fleet"]


def test_busquedas_de_otro_usuario(client, auth):
    from tests.conftest import register
    r = client.post("/searches", headers=auth, json={})
    otro = register(client, email="otro@example.com")
    assert client.get(f"/searches/{r.json()['id']}", headers=otro).status_code == 404


def test_detalle_de_oferta_con_duplicados(client, auth):
    r = client.post("/searches", headers=auth, json={"countries": ["es"]})
    res = client.get(f"/searches/{r.json()['id']}/results", headers=auth).json()
    gh = next(i for i in res["items"] if i["job"] and i["job"]["title"] == "Deck Cadet – 2026 Intake")
    d = client.get(f"/jobs/{gh['job']['id']}", headers=auth).json()
    assert len(d["duplicates"]) == 1 and d["questions"]


def test_ingesta_ats_con_api_simulada(db):
    http = FakeHttp({
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs": fixture_json("ats/greenhouse_jobs.json"),
        "https://boards-api.greenhouse.io/v1/boards/acme": fixture_json("ats/greenhouse_board.json"),
    })
    ingest.register_board(db, "greenhouse", "acme", None, "manual")
    ingest.register_board(db, "lever", "noexiste", None, "manual")
    stats = sources.ingest_ats(db, http, get_pack("general"))
    assert stats["jobs"] == 2 and stats["invalid"] == 1
    b = db.scalar(select(AtsBoard).where(AtsBoard.slug == "acme"))
    assert b.status == "active" and b.company_id
    assert db.get(Company, b.company_id).name == "Acme Corp"
    # Segunda lectura sin una de las ofertas → se cierra (no se borra)
    data = fixture_json("ats/greenhouse_jobs.json")
    data["jobs"] = data["jobs"][:1]
    http.add("https://boards-api.greenhouse.io/v1/boards/acme/jobs", 200, data)
    b.last_checked_at = None
    db.flush()
    sources.ingest_ats(db, http, get_pack("general"))
    cerradas = db.scalars(select(Job).where(Job.closed_at.is_not(None))).all()
    assert len(cerradas) == 1


def test_adzuna_respeta_cache_y_cuota(db, monkeypatch):
    monkeypatch.setenv("KNOK_ADZUNA_APP_ID", "id")
    monkeypatch.setenv("KNOK_ADZUNA_APP_KEY", "key")
    monkeypatch.setenv("KNOK_ADZUNA_MONTHLY_QUOTA", "2")
    from knok.settings import get_settings
    get_settings.cache_clear()
    http = FakeHttp({"https://api.adzuna.com/v1/api/jobs/es/search/1": fixture_json("adzuna/search.json")})
    pack = get_pack("general")
    st = sources.ingest_adzuna(db, http, pack, ["es"], ["python"])
    assert st["calls"] == 1 and st["jobs"] == 2
    st2 = sources.ingest_adzuna(db, http, pack, ["es"], ["python"])
    assert st2["calls"] == 0 and st2["cached"] == 1          # misma consulta: caché compartida
    sources.ingest_adzuna(db, http, pack, ["es"], ["go", "rust", "java"])
    assert sources.calls_this_month(db, "adzuna") == 2       # cuota de 2 llamadas/mes respetada
    assert len(http.calls) == 2


def test_adzuna_sin_credenciales_no_llama(db):
    http = FakeHttp()
    st = sources.ingest_adzuna(db, http, get_pack("general"), ["es"], ["python"])
    assert "skipped" in st and not http.calls


def test_dedupe_entre_fuentes_en_bd(db):
    from knok.core.sources.base import RawJob
    a = ingest.upsert_job(db, RawJob(source="adzuna", source_job_id="1", title="Backend Engineer", company_name="Acme Corp",
                                     city="Madrid", country="es", apply_url="https://www.adzuna.es/land/ad/1"))
    b = ingest.upsert_job(db, RawJob(source="greenhouse", source_job_id="acme:9", title="Backend Engineer (m/f/d)",
                                     company_name="ACME Corp S.L.", city="Madrid, Spain", country="es",
                                     apply_url="https://boards.greenhouse.io/acme/jobs/9", ats="greenhouse", ats_slug="acme"))
    db.refresh(a)
    assert a.canonical_job_id == b.id and b.canonical_job_id is None
    assert a.company_id == b.company_id


def test_solo_buzones_genericos_en_la_base_comun(db):
    from knok.core.sources.base import RawCompany
    c = ingest.upsert_company(db, RawCompany(name="Acme", source="t", website="https://acme.com", email="ana.lopez@acme.com"))
    ingest.add_company_email(db, c, "rrhh@acme.com")
    ingest.add_company_email(db, c, "jobs@otra.com")
    ingest.add_company_email(db, c, "info@gmail.com")
    assert [e.email for e in db.scalars(select(CompanyEmail))] == ["rrhh@acme.com"]


def test_puntuacion_explicable():
    m = score_job(title="Deck Cadet", description="sea service on our vessels", country="es", city="Bilbao",
                  remote=False, posted_at=datetime.now(timezone.utc) - timedelta(days=2),
                  match=get_pack("marina_mercante").match, keywords=[], countries=["es"], cities=["Bilbao"])
    assert m.matched and m.score > 50 and any("nicho" in r for r in m.reasons)
    no = score_job(title="Police cadet", description="police cadet program", country="es", city="", remote=False,
                   posted_at=None, match=get_pack("marina_mercante").match, keywords=[], countries=["es"], cities=[])
    assert not no.matched
