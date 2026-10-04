"""InfoJobs API oficial (España).

Búsqueda con las credenciales de la aplicación (Basic client_id:client_secret).
Preguntas y candidatura con el OAuth del candidato ("Basic …,Bearer …").

Las versiones de cada endpoint son las de la documentación de InfoJobs; si cambian, se tocan aquí.
La candidatura por API requiere que InfoJobs conceda a la aplicación los permisos de candidato.
"""
import base64

from knok.core.http import Http, HttpError
from knok.core.sources.base import RawJob, parse_dt
from knok.core.text import html_to_text

BASE = "https://api.infojobs.net/api"
SEARCH = f"{BASE}/9/offer"
DETAIL = f"{BASE}/7/offer/{{id}}"
QUESTIONS = f"{BASE}/1/offer/{{id}}/question"
APPLY = f"{BASE}/4/offer/{{id}}/application"
CURRICULA = f"{BASE}/2/curriculum"
AUTHORIZE = "https://www.infojobs.net/api/oauth/user-authorize/index.xhtml"
TOKEN = "https://www.infojobs.net/oauth/authorize"
SCOPES = "MY_APPLICATIONS,CANDIDATE_PROFILE_WITH_EMAIL,CANDIDATE_READ_CURRICULUM_SKILLS,CV"


def app_auth(client_id: str, client_secret: str, user_token: str = "") -> dict:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    return {"Authorization": f"Basic {basic}" + (f",Bearer {user_token}" if user_token else "")}


def parse_offers(data: dict) -> list[RawJob]:
    out = []
    for o in data.get("offers", []):
        autor = o.get("author") or {}
        tele = ((o.get("teleworking") or {}).get("value") or "").lower()
        out.append(RawJob(
            source="infojobs", source_job_id=str(o["id"]), title=(o.get("title") or "").strip(),
            company_name=autor.get("name") or "", city=o.get("city") or (o.get("province") or {}).get("value") or "",
            country="es", remote="remoto" in tele or "teletrabajo" in tele,
            description=html_to_text(o.get("requirementMin") or ""), url=o.get("link") or "",
            apply_url=o.get("link") or "", posted_at=parse_dt(o.get("published")),
            salary=o.get("salaryDescription") or "", language="es",
            raw={"id": o["id"], "author_id": autor.get("id"), "category": (o.get("category") or {}).get("value")},
        ))
    return out


def search(http: Http, client_id: str, client_secret: str, q: str, province: str = "", page: int = 1,
           max_results: int = 50) -> list[RawJob]:
    params = {"q": q, "page": page, "maxResults": max_results, "order": "updated-desc"}
    if province:
        params["province"] = province
    r = http.request("GET", SEARCH, params=params, headers={**app_auth(client_id, client_secret),
                                                           "Accept": "application/json"})
    if not r.ok:
        raise HttpError(r.status, SEARCH)
    return parse_offers(r.json())


def parse_questions(data: dict) -> list[dict]:
    campos = []
    for k in data.get("killerQuestions") or []:
        campos.append({"id": f"killer:{k['id']}", "label": k.get("question") or "", "type": "select",
                       "required": True,
                       "options": [{"label": a.get("answer"), "value": str(a.get("id"))} for a in k.get("answers") or []]})
    for o in data.get("openQuestions") or []:
        campos.append({"id": f"open:{o['id']}", "label": o.get("question") or "", "type": "textarea",
                       "required": True, "options": []})
    return campos


def fetch_questions(http: Http, client_id: str, client_secret: str, user_token: str, offer_id: str) -> list[dict]:
    url = QUESTIONS.format(id=offer_id)
    r = http.request("GET", url, headers={**app_auth(client_id, client_secret, user_token), "Accept": "application/json"})
    if not r.ok:
        raise HttpError(r.status, url)
    return parse_questions(r.json())


def build_application(curriculum_code: str, fields: list[dict], cover_letter: str = "") -> dict:
    """Cuerpo de la candidatura a partir de los campos revisados (id 'killer:…' / 'open:…')."""
    killer, abiertas = [], []
    for f in fields:
        fid = str(f.get("id") or "")
        if fid.startswith("killer:") and f.get("value") not in (None, ""):
            killer.append({"id": int(fid.split(":", 1)[1]), "answerId": int(f["value"])})
        elif fid.startswith("open:") and f.get("value"):
            abiertas.append({"id": int(fid.split(":", 1)[1]), "answer": str(f["value"])})
    cuerpo = {"curriculumCode": curriculum_code, "killerQuestions": killer, "openQuestions": abiertas}
    if cover_letter:
        cuerpo["coverLetter"] = {"text": cover_letter}
    return cuerpo


def list_curricula(http: Http, client_id: str, client_secret: str, user_token: str) -> list[dict]:
    r = http.request("GET", CURRICULA, headers={**app_auth(client_id, client_secret, user_token), "Accept": "application/json"})
    if not r.ok:
        raise HttpError(r.status, CURRICULA)
    return r.json() if isinstance(r.json(), list) else []


def apply(http: Http, client_id: str, client_secret: str, user_token: str, offer_id: str, body: dict) -> dict:
    url = APPLY.format(id=offer_id)
    r = http.request("POST", url, json_body=body,
                     headers={**app_auth(client_id, client_secret, user_token), "Accept": "application/json"})
    if not r.ok:
        raise HttpError(r.status, url, f"InfoJobs rechazó la candidatura ({r.status}): {r.text[:300]}")
    return r.json() if r.content else {}
