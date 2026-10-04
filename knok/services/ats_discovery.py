"""Localizar el formulario de empleo propio de una empresa (Greenhouse, Lever, Ashby) a partir de su nombre.

Sirve para las ofertas guardadas desde un portal (p. ej. LinkedIn): si la empresa publica sus ofertas en uno
de esos ATS, knok lee su tablero por la API pública del ATS, encuentra la misma oferta y la candidatura pasa
a hacerse en el formulario de la empresa (que la extensión rellena en el piloto automático), fuera del portal.

Solo APIs públicas de los ATS, sin buscador y sin tocar el portal. Cada empresa cuesta como mucho
2 nombres × 3 ATS = 6 consultas, y un tablero que no existe se recuerda para no volver a preguntar.
"""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from knok.core.cleaning.normalize import title_key
from knok.core.http import Http, HttpError
from knok.core.sources.ats import FETCHERS
from knok.core.text import norm
from knok.db.models import Application, AtsBoard, Company, Job, Profile
from knok.services import ingest
from knok.services.events import log_event
from knok.services.sources import refresh_board
from knok.worker.queue import task

ATS_ORDER = ("greenhouse", "lever", "ashby")
MAX_COMPANIES = 10
_SUFIJOS = re.compile(
    r"\b(s ?l ?u?|s ?a ?u?|s ?l ?l|sociedad limitada|gmbh|ag|inc|llc|ltd|limited|plc|b ?v|n ?v|sas|sarl|spa|srl|oy|ab|"
    r"as|group|grupo|holding|spain|espana|iberia|europe|international|technologies|technology|labs)\b")


def _limpio(nombre: str) -> list[str]:
    t = re.sub(r"[^a-z0-9 ]+", " ", norm(nombre or ""))
    t = _SUFIJOS.sub(" ", t)
    return t.split()


def slug_candidates(nombre: str) -> list[str]:
    """«Acme Robotics, S.L.» → ['acmerobotics', 'acme-robotics']: así suelen llamarse los tableros."""
    palabras = _limpio(nombre)
    if not palabras:
        return []
    out = ["".join(palabras), "-".join(palabras)]
    return [s for s in dict.fromkeys(out) if len(s) >= 3][:2]


def same_company(nombre_tablero: str, nombre_empresa: str) -> bool | None:
    """True/False si el ATS dice cómo se llama la empresa; None si no lo dice (Lever)."""
    if not nombre_tablero:
        return None
    a, b = " ".join(_limpio(nombre_tablero)), " ".join(_limpio(nombre_empresa))
    return bool(a and b and (a in b or b in a))


def discover_board(db: Session, http: Http, company: Company, pack: str = "") -> AtsBoard | None:
    activo = db.scalar(select(AtsBoard).where(AtsBoard.company_id == company.id, AtsBoard.status == "active"))
    if activo:
        return activo
    candidatos = slug_candidates(company.name)
    for slug in candidatos:
        for ats in ATS_ORDER:
            b = db.scalar(select(AtsBoard).where(AtsBoard.ats == ats, AtsBoard.slug == slug))
            if b is not None and b.status == "invalid":
                continue
            if b is not None and b.status == "active" and b.company_id not in (None, company.id):
                continue      # ese tablero ya es de otra empresa
            try:
                nombre, jobs = FETCHERS[ats](http, slug)
            except HttpError as ex:
                if ex.status == 404:
                    if b is None:
                        b = ingest.register_board(db, ats, slug, None, "lookup")
                    if b is not None:
                        b.status = "invalid"
                continue
            except Exception:
                continue
            if not jobs:
                continue
            coincide = same_company(nombre, company.name)
            # Sin nombre que comparar, solo vale el nombre completo de la empresa (no una parte)
            if coincide is False or (coincide is None and slug != candidatos[0]):
                continue
            b = b or ingest.register_board(db, ats, slug, company, "lookup")
            if b is None:
                continue
            b.company_id = company.id
            db.flush()
            refresh_board(db, http, b, pack)
            return b
    return None


def _parecido(a: str, b: str) -> bool:
    ka, kb = title_key(a), title_key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    sa, sb = set(ka.split()), set(kb.split())
    return len(sa & sb) / len(sa | sb) >= 0.7


def reroute_captures(db: Session, profile: Profile, board: AtsBoard) -> list[Application]:
    """Candidaturas guardadas desde un portal que existen en el tablero de la empresa → al formulario de la empresa."""
    from knok.services import applications as svc
    ofertas = list(db.scalars(select(Job).where(Job.source == board.ats, Job.source_job_id.like(f"{board.slug}:%"),
                                                Job.closed_at.is_(None))))
    movidas = []
    apps = db.scalars(select(Application).join(Job, Job.id == Application.job_id).where(
        Application.user_id == profile.user_id, Application.mode == profile.mode, Application.status.in_(svc.OPEN),
        Job.source == "capture", Job.company_id == board.company_id))
    for app in apps:
        destino = next((j for j in ofertas if _parecido(j.title, app.job.title)), None)
        if destino is None or svc.find_existing(db, profile, destino.id, destino.company_id):
            continue
        svc.reroute(db, app, profile, destino)
        movidas.append(app)
    return movidas


@task("discover_ats")
def discover_ats_task(db: Session, payload: dict) -> dict:
    from knok.core.http import default_http
    from knok.settings import get_settings
    if get_settings().offline_sources:
        return {"skipped": "offline"}
    profile = db.get(Profile, payload["user_id"])
    if profile is None:
        return {"missing": True}
    return discover_for_user(db, default_http(), profile, payload.get("company_ids") or [])


def discover_for_user(db: Session, http: Http, profile: Profile, company_ids: list[int]) -> dict:
    out = {"looked": 0, "found": 0, "moved": 0}
    for cid in list(dict.fromkeys(company_ids))[:MAX_COMPANIES]:
        c = db.get(Company, cid)
        if c is None or not c.name:
            continue
        out["looked"] += 1
        b = discover_board(db, http, c, profile.pack)
        if b is None:
            continue
        out["found"] += 1
        movidas = reroute_captures(db, profile, b)
        out["moved"] += len(movidas)
        if movidas:
            log_event(db, profile.user_id, f"{c.name}: tiene sus ofertas en {b.ats.capitalize()}. "
                      f"{len(movidas)} {'candidatura pasa' if len(movidas) == 1 else 'candidaturas pasan'} "
                      "al formulario de la empresa (piloto automático).", "ok")
    return out
