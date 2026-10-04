"""Wikidata: empresas/instituciones con web oficial, por categoría y país (portado de legacy/core/maritimo.py).

Las categorías (patrones SPARQL sobre ?item) y los países los define el pack.
"""
import json
import re
import time

from knok.core.domains import domain_of, is_company_site, pretty_name
from knok.core.http import Http
from knok.core.sources.base import RawCompany
from knok.packs.schema import WikidataCfg

ENDPOINT = "https://query.wikidata.org/sparql"

# ISO 3166-1 alfa-2 → identificador de Wikidata
COUNTRY_QID = {
    "es": "Q29", "pt": "Q45", "fr": "Q142", "it": "Q38", "de": "Q183", "nl": "Q55", "be": "Q31", "lu": "Q32",
    "ie": "Q27", "gb": "Q145", "dk": "Q35", "se": "Q34", "no": "Q20", "fi": "Q33", "is": "Q189", "pl": "Q36",
    "ee": "Q191", "lv": "Q211", "lt": "Q37", "gr": "Q41", "cy": "Q229", "mt": "Q233", "hr": "Q224",
    "si": "Q215", "ro": "Q218", "bg": "Q219", "ch": "Q39", "mc": "Q235", "at": "Q40", "cz": "Q213",
    "sk": "Q214", "hu": "Q28", "us": "Q30", "ca": "Q16", "mx": "Q96", "ar": "Q414", "co": "Q739", "cl": "Q298",
    "pe": "Q419", "br": "Q155", "au": "Q408", "nz": "Q664", "in": "Q668", "sg": "Q334", "jp": "Q17",
}


def build_query(where: str, countries: list[str]) -> str:
    qids = " ".join("wd:" + COUNTRY_QID[c] for c in countries if c in COUNTRY_QID)
    return f"""SELECT ?item ?itemLabel ?web ?pais WHERE {{
      VALUES ?pais {{ {qids} }}
      {where}
      ?item wdt:P17 ?pais ; wdt:P856 ?web .
      FILTER NOT EXISTS {{ ?item wdt:P576 ?disuelta }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "es,en". }}
    }}"""


def parse_bindings(filas: list[dict], categoria: str) -> list[RawCompany]:
    iso = {q: c for c, q in COUNTRY_QID.items()}
    out = {}
    for f in filas:
        web = f["web"]["value"]
        if not is_company_site(web):
            continue
        dom = domain_of(web)
        if not dom or dom in out:
            continue
        nombre = f["itemLabel"]["value"]
        if re.fullmatch(r"Q\d+", nombre):
            nombre = pretty_name(dom)
        out[dom] = RawCompany(name=nombre, source="wikidata", website=web, domain=dom, sector=categoria,
                              country=iso.get(f["pais"]["value"].rsplit("/", 1)[-1], ""),
                              wikidata_id=f["item"]["value"].rsplit("/", 1)[-1])
    return list(out.values())


def search(http: Http, cfg: WikidataCfg, countries: list[str] | None = None, avisar=lambda *a: None) -> list[RawCompany]:
    paises = [c for c in (countries or cfg.countries) if c in COUNTRY_QID]
    if not cfg.queries or not paises:
        return []
    res: dict[str, RawCompany] = {}
    for q in cfg.queries:
        filas = None
        for intento in range(3):
            r = http.request("POST", ENDPOINT, data={"query": build_query(q.where, paises)},
                             headers={"Accept": "application/sparql-results+json"}, timeout=90)
            if r.ok:
                filas = json.loads(r.content)["results"]["bindings"]
                break
            if r.status not in (429, 500, 502, 503, 504) or intento == 2:
                avisar("warning", f"Wikidata ({q.label}): no disponible ahora ({r.status}).")
                break
            time.sleep(min(int(r.headers.get("retry-after") or 15), 60))
        for c in parse_bindings(filas or [], q.label):
            res.setdefault(c.domain, c)
        time.sleep(2)  # amabilidad con el servicio público
    return list(res.values())
