"""Adzuna API (plan gratuito, ~1.000 llamadas/mes para TODA la aplicación).

  GET https://api.adzuna.com/v1/api/jobs/{country}/search/{page}?app_id=…&app_key=…&what=…&where=…

Condiciones: hay que mostrar la atribución ("Jobs by Adzuna") y enlazar con su redirect_url.
Por eso la oferta guarda redirect_url como url y la vía queda "manual" salvo que la limpieza encuentre
la misma oferta en el ATS de la empresa (entonces se usa la original).
"""
from knok.core.http import Http, get_json
from knok.core.sources.base import RawJob, parse_dt
from knok.core.text import html_to_text

API = "https://api.adzuna.com/v1/api/jobs"
COUNTRIES = {"gb", "us", "at", "au", "be", "br", "ca", "ch", "de", "es", "fr", "in", "it", "mx", "nl", "nz",
             "pl", "sg", "za"}
ATTRIBUTION = "Jobs by Adzuna"


def parse_results(data: dict, country: str) -> list[RawJob]:
    out = []
    for r in data.get("results", []):
        area = (r.get("location") or {}).get("area") or []
        ciudad = area[-1] if len(area) >= 3 else (area[1] if len(area) == 2 else "")
        sal = ""
        if r.get("salary_min"):
            sal = f"{int(r['salary_min'])}" + (f"-{int(r['salary_max'])}" if r.get("salary_max") else "")
        out.append(RawJob(
            source="adzuna", source_job_id=str(r["id"]), title=html_to_text(r.get("title") or ""),
            company_name=(r.get("company") or {}).get("display_name") or "", city=ciudad, country=country,
            description=html_to_text(r.get("description") or ""), url=r.get("redirect_url") or "",
            apply_url=r.get("redirect_url") or "", posted_at=parse_dt(r.get("created")), salary=sal,
            raw={"category": (r.get("category") or {}).get("label"), "contract_time": r.get("contract_time"),
                 "location": (r.get("location") or {}).get("display_name")},
        ))
    return out


def search(http: Http, app_id: str, app_key: str, country: str, what: str, where: str = "", page: int = 1,
           per_page: int = 50, max_days_old: int = 30) -> list[RawJob]:
    if country not in COUNTRIES:
        return []
    params = {"app_id": app_id, "app_key": app_key, "what": what, "results_per_page": per_page,
              "max_days_old": max_days_old, "content-type": "application/json"}
    if where:
        params["where"] = where
    data = get_json(http, f"{API}/{country}/search/{page}", params=params)
    return parse_results(data, country)
