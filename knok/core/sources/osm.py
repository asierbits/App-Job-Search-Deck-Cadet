"""OpenStreetMap: empresas alrededor de una ciudad (portado de legacy/core/busqueda.py).

Geocodificación con Nominatim y consulta con Overpass, ambos gratis y sin clave. Sus normas de uso piden
como mucho 1 petición/segundo y cachear: el servicio de prospección cachea por (ciudad, radio, etiquetas).
Las etiquetas (office=*, amenity=*) las define cada pack.
"""
import re
import time
import urllib.parse

from knok.core.http import Http, HttpError, get_json
from knok.core.sources.base import RawCompany
from knok.packs.schema import OsmCfg

OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter"]
NOMINATIM = "https://nominatim.openstreetmap.org/search"


def geocode(http: Http, ciudad: str) -> tuple[float, float, str, str]:
    res = get_json(http, NOMINATIM, params={"q": ciudad, "format": "json", "limit": 1, "addressdetails": 1,
                                            "accept-language": "es,en"}, timeout=30)
    if not res:
        raise ValueError(f"no encuentro '{ciudad}' en el mapa")
    lugar = res[0]
    return (float(lugar["lat"]), float(lugar["lon"]), (lugar.get("address") or {}).get("country_code", ""),
            lugar.get("display_name", ciudad).split(",")[0])


def build_query(lat: float, lon: float, radio_m: int, cfg: OsmCfg) -> str:
    zona = f"(around:{radio_m},{lat},{lon})"
    partes = []
    for clave, valores in cfg.tags.items():
        filtro = f'["{clave}"~"^({"|".join(map(re.escape, valores))})$"]["name"]'
        for contacto in ('["email"]', '["contact:email"]', '["website"]', '["contact:website"]'):
            partes.append(f"nwr{zona}{filtro}{contacto};")
    return "[out:json][timeout:100];\n(\n" + "\n".join(partes) + "\n);\nout tags center 2000;"


def _overpass(http: Http, consulta: str) -> dict:
    ultimo = None
    for intento, servidor in enumerate(OVERPASS * 2):
        try:
            r = http.request("POST", servidor, data={"data": consulta}, timeout=120)
            if r.ok:
                return r.json()
            ultimo = HttpError(r.status, servidor)
            if r.status not in (429, 502, 503, 504):
                raise ultimo
        except HttpError:
            raise
        except Exception as ex:
            ultimo = ex
        if intento >= len(OVERPASS) - 1:
            time.sleep(5)
    raise RuntimeError(f"OpenStreetMap saturado, inténtalo en unos minutos ({ultimo})")


def _email(valor: str) -> str:
    m = re.search(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", valor or "")
    return m.group(0).lower() if m else ""


def parse_elements(data: dict, cfg: OsmCfg, ciudad: str, pais: str) -> list[RawCompany]:
    agencias = {t.split("=", 1)[1] for t in cfg.agency_tags if "=" in t}
    out = []
    for el in data.get("elements", []):
        t = el.get("tags", {})
        tipo_osm = next((t.get(k) for k in cfg.tags if t.get(k)), "")
        web = t.get("website") or t.get("contact:website") or ""
        out.append(RawCompany(
            name=(t.get("name") or "").strip(), source="openstreetmap", website=web,
            email=_email(t.get("email") or t.get("contact:email")), city=t.get("addr:city") or ciudad,
            country=(t.get("addr:country") or pais or "").lower()[:2],
            sector=cfg.sector_labels.get(tipo_osm, tipo_osm), kind="agency" if tipo_osm in agencias else "company",
            phone=t.get("phone") or t.get("contact:phone") or "", osm_ref=f"{el['type']}/{el['id']}",
        ))
    return [c for c in out if c.name and (c.email or c.website)]


def search_city(http: Http, ciudad: str, radio_km: float, cfg: OsmCfg) -> list[RawCompany]:
    if not cfg.tags:
        return []
    lat, lon, pais, nombre = geocode(http, ciudad)
    time.sleep(1.1)  # normas de uso de OSM: como mucho 1 petición por segundo
    data = _overpass(http, build_query(lat, lon, int(radio_km * 1000), cfg))
    return parse_elements(data, cfg, nombre, pais)


def city_key(ciudad: str, radio_km: float, cfg: OsmCfg) -> str:
    return urllib.parse.quote(f"{ciudad.lower().strip()}|{radio_km}|{sorted(cfg.tags.items())}")
