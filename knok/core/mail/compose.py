"""Composición de correos y cartas con plantillas y variables.

Variables disponibles (en español, como en las plantillas, y con alias en inglés):
  {nombre} {nombre_pila} {apellidos} {email} {telefono} {linkedin} {web}
  {empresa} {puesto} {ciudad} {pais} {sector} {asunto}
  + los campos propios del pack ({titulacion}, {universidad}, {area}…), con su versión por idioma
    si existe (titulacion_en se usa en los correos en inglés).
"""
from dataclasses import dataclass

from knok.core.text import fill_template, missing_variables, tidy_body

ALIASES = {"name": "nombre", "first_name": "nombre_pila", "last_name": "apellidos", "phone": "telefono",
           "company": "empresa", "position": "puesto", "job_title": "puesto", "city": "ciudad",
           "country": "pais", "website": "web", "subject": "asunto"}


@dataclass
class Rendered:
    subject: str
    body: str
    missing: list[str]
    language: str


def template_values(profile: dict, lang: str, pack_field_keys: list[str], company: dict | None = None,
                    job: dict | None = None, extra: dict | None = None) -> dict:
    company, job = company or {}, job or {}
    links = profile.get("links") or {}
    pack_data = profile.get("pack_data") or {}
    nombre = " ".join(x for x in (profile.get("first_name"), profile.get("last_name")) if x).strip()
    v = {
        "nombre": nombre,
        "nombre_pila": profile.get("first_name") or "",
        "apellidos": profile.get("last_name") or "",
        "email": profile.get("email") or "",
        "telefono": profile.get("phone") or "",
        "linkedin": links.get("linkedin") or "",
        "web": links.get("website") or links.get("github") or "",
        "empresa": company.get("name") or job.get("company_name") or "",
        "puesto": job.get("title") or "",
        "ciudad": job.get("city") or company.get("city") or profile.get("city") or "",
        "pais": job.get("country") or company.get("country") or "",
        "sector": company.get("sector") or "",
    }
    for key in pack_field_keys:
        v[key] = pack_data.get(f"{key}_{lang}") or pack_data.get(key) or ""
    v.update({k: x for k, x in (extra or {}).items() if x is not None})
    for alias, original in ALIASES.items():
        v.setdefault(alias, v.get(original, ""))
    return v


def render(subject_tpl: str, body_tpl: str, values: dict, language: str) -> Rendered:
    faltan = sorted(set(missing_variables(subject_tpl, values)) | set(missing_variables(body_tpl, values)))
    # Una variable vacía no debe dejar "{telefono}" en el correo: se sustituye por ''
    vacias = {k: "" for k in faltan}
    vals = {**values, **vacias}
    return Rendered(subject=fill_template(subject_tpl, vals).strip(),
                    body=tidy_body(fill_template(body_tpl, vals)), missing=faltan, language=language)


# Variables cuya ausencia no impide enviar (se quitan con la línea vacía)
OPTIONAL_VARIABLES = {"telefono", "linkedin", "web", "ciudad", "pais", "sector", "phone", "website", "city",
                      "country"}


def blocking_missing(missing: list[str]) -> list[str]:
    return [m for m in missing if m not in OPTIONAL_VARIABLES]
