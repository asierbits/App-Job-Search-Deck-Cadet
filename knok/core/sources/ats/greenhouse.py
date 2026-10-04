"""Greenhouse Job Board API (pública, sin clave).

  GET https://boards-api.greenhouse.io/v1/boards/{slug}                     → nombre de la empresa
  GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true   → ofertas con descripción
  GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{id}?questions=true → preguntas del formulario
"""
from knok.core.geo import parse_location
from knok.core.http import Http, get_json
from knok.core.sources.base import RawJob, parse_dt
from knok.core.text import html_to_text

API = "https://boards-api.greenhouse.io/v1/boards"

_TIPOS = {"input_text": "text", "input_file": "file", "textarea": "textarea", "input_hidden": "hidden",
          "multi_value_single_select": "select", "multi_value_multi_select": "multiselect"}


def parse_jobs(data: dict, slug: str, company_name: str = "") -> list[RawJob]:
    out = []
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        ciudad, pais, remoto = parse_location(loc)
        for o in j.get("offices") or []:  # las oficinas suelen traer el país aunque la ubicación no
            if not pais:
                _, pais, _ = parse_location(o.get("location") or o.get("name") or "")
        out.append(RawJob(
            source="greenhouse", source_job_id=f"{slug}:{j['id']}", title=(j.get("title") or "").strip(),
            company_name=j.get("company_name") or company_name, city=ciudad, country=pais, remote=remoto,
            description=html_to_text(j.get("content") or ""), url=j.get("absolute_url") or "",
            apply_url=j.get("absolute_url") or f"https://boards.greenhouse.io/{slug}/jobs/{j['id']}",
            posted_at=parse_dt(j.get("first_published") or j.get("updated_at")),
            ats="greenhouse", ats_slug=slug,
            raw={"id": j["id"], "location": loc, "departments": [d.get("name") for d in j.get("departments") or []]},
        ))
    return out


def fetch_board(http: Http, slug: str) -> tuple[str, list[RawJob]]:
    """(nombre de la empresa, ofertas). Lanza HttpError(404) si el tablero no existe."""
    nombre = ""
    try:
        nombre = get_json(http, f"{API}/{slug}").get("name") or ""
    except Exception:
        pass
    data = get_json(http, f"{API}/{slug}/jobs", params={"content": "true"})
    return nombre, parse_jobs(data, slug, nombre)


def parse_questions(data: dict) -> list[dict]:
    """Preguntas de la oferta → esquema de formulario común."""
    campos = []
    for q in (data.get("questions") or []) + (data.get("location_questions") or []):
        for i, f in enumerate(q.get("fields") or []):
            tipo = _TIPOS.get(f.get("type"), "text")
            if tipo == "hidden":
                continue
            # Una pregunta con varios campos (CV como archivo O pegado): solo el primero es obligatorio
            campos.append({
                "id": f.get("name"), "label": q.get("label") or f.get("name"), "type": tipo,
                "required": bool(q.get("required")) and i == 0, "description": html_to_text(q.get("description") or ""),
                "options": [{"label": v.get("label"), "value": str(v.get("value"))} for v in f.get("values") or []],
            })
    return campos


def fetch_questions(http: Http, slug: str, job_id: str) -> list[dict]:
    data = get_json(http, f"{API}/{slug}/jobs/{job_id}", params={"questions": "true"})
    return parse_questions(data)
