"""Rastreo de webs, directorios, OSM y Wikidata, con webs y respuestas de ejemplo (sin red)."""
import zlib

from sqlalchemy import select

from knok.core.crawl.website import CrawlRules, crawl, extract_emails
from knok.core.http import FakeHttp
from knok.core.sources import directories, osm, wikidata
from knok.db.models import AtsBoard, Company, CompanyEmail, Crawl
from knok.packs.loader import get_pack
from tests.conftest import fixture_text

WEB = "https://naviera-ejemplo.com"


def web_ejemplo() -> FakeHttp:
    f = lambda n: fixture_text(f"websites/naviera/{n}")
    return FakeHttp({
        f"{WEB}/robots.txt": (200, f("robots.txt"), "text/plain"),
        f"{WEB}/careers": f("careers.html"),
        f"{WEB}/contacto": f("contacto.html"),
        f"{WEB}/aviso-legal": "<html><body>Aviso legal</body></html>",
        f"{WEB}/privado": "<html>info-secreto@naviera-ejemplo.com</html>",
        WEB: f("index.html"),
    })


def test_rastreo_completo_con_reglas_del_pack():
    http = web_ejemplo()
    r = crawl(http, WEB, CrawlRules.for_pack(get_pack("marina_mercante")))
    assert r["read"] and r["name"] == "Naviera Ejemplo"
    emails = [e["email"] for e in r["emails"]]
    assert r["best_email"] == "crewing@naviera-ejemplo.com"       # Cloudflare + página de empleo + prioridad del pack
    assert "info@naviera-ejemplo.com" in emails                   # ofuscado [at] [dot]
    assert "juan.perez@naviera-ejemplo.com" not in emails         # personal: nunca
    assert "hola@agenciaweb.com" not in emails                    # de otra empresa
    assert emails.index("sales@naviera-ejemplo.com") > emails.index("info@naviera-ejemplo.com")
    assert r["careers_url"] == f"{WEB}/careers"
    assert {"platform": "greenhouse", "slug": "navieraejemplo"} in r["ats"]
    assert "deck cadet" in r["mentions"] and "empleo embarcado / offshore" in r["signals"]
    assert any(w["type"] == "ucrania" for w in r["warnings"])
    # robots.txt respetado: /privado/ nunca se visita
    assert not any("/privado" in u for _, u, _ in http.calls)


def test_reglas_generales_sin_pack():
    r = crawl(web_ejemplo(), WEB, CrawlRules.for_pack(get_pack("general")))
    assert r["mentions"] == [] and r["warnings"] == []
    assert r["best_email"] in ("rrhh@naviera-ejemplo.com", "info@naviera-ejemplo.com")


def test_web_que_bloquea_programas():
    http = FakeHttp({f"{WEB}/robots.txt": (404, "", "text/plain"), WEB: (403, "Forbidden", "text/html")})
    r = crawl(http, WEB, CrawlRules.for_pack(None))
    assert r["blocked"] and not r["read"] and r["emails"] == []


def test_robots_prohibe_todo():
    http = FakeHttp({f"{WEB}/robots.txt": (200, "User-agent: *\nDisallow: /\n", "text/plain"), WEB: "<html></html>"})
    r = crawl(http, WEB, CrawlRules.for_pack(None), user_agent="knok-bot")
    assert r["robots_blocked"] and len(http.calls) == 1


def test_extraer_emails_ofuscados():
    assert extract_emails("rrhh(arroba)empresa.es y jobs [at] empresa [dot] de") >= {"rrhh@empresa.es", "jobs@empresa.de"}
    assert "x@example.com" not in extract_emails("x@example.com logo@2x.png")


def test_servicio_de_rastreo_con_cache(db):
    from knok.core.sources.base import RawCompany
    from knok.services import ingest
    from knok.services.crawling import crawl_companies
    pack = get_pack("marina_mercante")
    c = ingest.upsert_company(db, RawCompany(name="Naviera Ejemplo", source="t", website=WEB), pack.slug)
    http = web_ejemplo()
    st = crawl_companies(db, [c], pack, http)
    assert st["crawled"] == 1 and st["new_emails"] >= 2 and st["ats"] == 1
    assert c.careers_url.endswith("/careers") and c.flags["marina_mercante"]["mentions"]
    assert db.scalar(select(AtsBoard).where(AtsBoard.slug == "navieraejemplo")).company_id == c.id
    guardados = set(db.scalars(select(CompanyEmail.email)))
    assert "juan.perez@naviera-ejemplo.com" not in guardados and "crewing@naviera-ejemplo.com" in guardados
    llamadas = len(http.calls)
    st2 = crawl_companies(db, [c], pack, http)
    assert st2["reused"] == 1 and len(http.calls) == llamadas    # caché de 30 días: no se vuelve a visitar
    assert db.get(Crawl, ("naviera-ejemplo.com", "marina_mercante")).status == "ok"


def test_directorio_html_paginado():
    p1 = ('<html><a href="https://www.naviera-uno.es">Naviera Uno</a> <a href="https://www.facebook.com/x">fb</a>'
          '<a href="https://asociacion.org/socios?page=2">2</a> info@naviera-uno.es</html>')
    p2 = '<html><a href="https://naviera-dos.de/">Website</a> <a href="https://asociacion.org/">Inicio</a></html>'
    http = FakeHttp({"https://asociacion.org/robots.txt": (404, "", "text/plain"),
                     "https://asociacion.org/socios?page=2": p2, "https://asociacion.org/socios": p1})
    res = directories.read_directory(http, "https://asociacion.org/socios", "es", allowed_countries=["es", "de"])
    por_dom = {c.domain: c for c in res}
    assert set(por_dom) == {"naviera-uno.es", "naviera-dos.de"}
    assert por_dom["naviera-uno.es"].email == "info@naviera-uno.es" and por_dom["naviera-dos.de"].country == "de"
    assert por_dom["naviera-dos.de"].name == "Naviera Dos"


def test_directorio_pdf_con_bloques_comprimidos():
    contenido = zlib.compress(b"/URI (https://www.naviera-tres.es/) /URI (mailto:flota@naviera-tres.es) crew@naviera-cuatro.es")
    pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nstream\n" + contenido + b"\nendstream\nendobj\n"
    res = directories.parse_pdf(pdf, [])
    assert res["naviera-tres.es"]["email"] == "flota@naviera-tres.es"
    assert "naviera-cuatro.es" in res


def test_osm_parse_y_consulta():
    cfg = get_pack("general").sources.osm
    q = osm.build_query(43.26, -2.93, 10000, cfg)
    assert '["office"~"^(company|it|' in q and "around:10000,43.26,-2.93" in q
    data = {"elements": [
        {"type": "node", "id": 1, "tags": {"name": "ETT Ejemplo", "office": "employment_agency", "email": "info@ett.es"}},
        {"type": "way", "id": 2, "tags": {"name": "Consultora", "office": "consulting", "website": "https://consultora.es"}},
        {"type": "node", "id": 3, "tags": {"name": "Sin contacto", "office": "it"}},
    ]}
    res = osm.parse_elements(data, cfg, "Bilbao", "es")
    assert [c.name for c in res] == ["ETT Ejemplo", "Consultora"]
    assert res[0].kind == "agency" and res[1].sector == "Consultoría" and res[0].osm_ref == "node/1"


def test_wikidata_parse():
    filas = [{"item": {"value": "http://www.wikidata.org/entity/Q1"}, "itemLabel": {"value": "Naviera Uno"},
              "web": {"value": "https://www.naviera-uno.es"}, "pais": {"value": "http://www.wikidata.org/entity/Q29"}},
             {"item": {"value": "http://www.wikidata.org/entity/Q2"}, "itemLabel": {"value": "Q2"},
              "web": {"value": "https://naviera-dos.de"}, "pais": {"value": "http://www.wikidata.org/entity/Q183"}},
             {"item": {"value": "http://www.wikidata.org/entity/Q3"}, "itemLabel": {"value": "X"},
              "web": {"value": "https://www.facebook.com/x"}, "pais": {"value": "http://www.wikidata.org/entity/Q29"}}]
    res = wikidata.parse_bindings(filas, "Naviera")
    assert [(c.name, c.country, c.domain) for c in res] == [("Naviera Uno", "es", "naviera-uno.es"),
                                                            ("Naviera Dos", "de", "naviera-dos.de")]
    assert "wd:Q29" in wikidata.build_query("?item wdt:P31 wd:Q1 .", ["es", "zz"])


def test_exclusion_de_entidades_que_no_son_del_nicho():
    from knok.services.prospecting import is_excluded
    p = get_pack("marina_mercante")
    assert is_excluded(p, "Asociación de Navieros Españoles") and is_excluded(p, "Astilleros del Norte")
    assert not is_excluded(p, "Naviera Armas")
