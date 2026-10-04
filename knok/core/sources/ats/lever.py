"""Lever Postings API (pública, sin clave).

  GET https://api.lever.co/v0/postings/{slug}?mode=json
  (Las empresas en la región UE usan api.eu.lever.co; se prueba si la global devuelve 404.)
"""
from knok.core.geo import parse_location
from knok.core.http import Http, HttpError, get_json
from knok.core.sources.base import RawJob, parse_dt
from knok.core.text import html_to_text

APIS = ("https://api.lever.co/v0/postings", "https://api.eu.lever.co/v0/postings")


def parse_jobs(data: list, slug: str, company_name: str = "") -> list[RawJob]:
    out = []
    for p in data or []:
        cat = p.get("categories") or {}
        loc = cat.get("location") or ", ".join(cat.get("allLocations") or [])
        ciudad, pais, remoto = parse_location(loc)
        pais = pais or (p.get("country") or "").lower()
        remoto = remoto or (p.get("workplaceType") == "remote")
        texto = p.get("descriptionPlain") or html_to_text(p.get("description") or "")
        for lista in p.get("lists") or []:
            texto += "\n\n" + (lista.get("text") or "") + "\n" + html_to_text(lista.get("content") or "")
        texto += "\n\n" + (p.get("additionalPlain") or html_to_text(p.get("additional") or ""))
        out.append(RawJob(
            source="lever", source_job_id=f"{slug}:{p['id']}", title=(p.get("text") or "").strip(),
            company_name=company_name, city=ciudad, country=pais, remote=remoto, description=texto.strip(),
            url=p.get("hostedUrl") or "", apply_url=p.get("applyUrl") or p.get("hostedUrl") or "",
            posted_at=parse_dt(p.get("createdAt")), ats="lever", ats_slug=slug,
            raw={"id": p["id"], "team": cat.get("team"), "commitment": cat.get("commitment")},
        ))
    return out


def fetch_board(http: Http, slug: str) -> tuple[str, list[RawJob]]:
    ultimo = None
    for api in APIS:
        try:
            data = get_json(http, f"{api}/{slug}", params={"mode": "json"})
            return "", parse_jobs(data, slug)
        except HttpError as ex:
            ultimo = ex
            if ex.status != 404:
                raise
    raise ultimo
