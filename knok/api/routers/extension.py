"""Endpoints para la extensión de Chrome (modo copiloto).

La extensión NO decide nada: lee el formulario de la página, pide aquí el plan de relleno (el mismo motor
que usa la API) y escribe los valores. Nunca pulsa "Enviar": cuando el usuario envía, avisa con
/extension/submitted. Solo actúa cuando el usuario pulsa un botón.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from knok.api.deps import ApiError, current_profile, get_db, not_found
from knok.core.domains import domain_of
from knok.core.sources.ats.detect import PLATFORMS, detect
from knok.core.sources.base import RawJob
from knok.core.text import html_to_text
from knok.db import models as m
from knok.services import applications as svc
from knok.services import ingest
from knok.services.filling import fill_form
from knok.services.templates import render_for

router = APIRouter(prefix="/extension", tags=["extension"])

LINKEDIN_WARNING = {
    "es": "LinkedIn prohíbe en sus condiciones automatizar la cuenta, aunque tú pulses cada paso. Úsalo de una en una "
          "y con pausas; existe riesgo de restricción de tu cuenta.",
    "en": "LinkedIn's terms forbid automating your account, even when you click each step. Use it one application "
          "at a time with pauses; your account could be restricted.",
}
LIMITS = {"batch_size": 40, "pause_between_jobs_seconds": [8, 20], "linkedin_one_by_one": True,
          "max_open_tabs": 10}


class FormFieldIn(BaseModel):
    id: str
    label: str = ""
    type: str = "text"
    required: bool = False
    options: list[dict] = []
    name: str = ""
    autocomplete: str = ""
    placeholder: str = ""


class FillPlanIn(BaseModel):
    url: str
    application_id: int | None = None
    platform: str = ""
    fields: list[FormFieldIn] = Field(default=[], max_length=300)


class SubmittedIn(BaseModel):
    application_id: int
    url: str = ""


class CaptureIn(BaseModel):
    url: str = Field(description="Página de la oferta que el usuario está viendo")
    title: str = Field(min_length=2, max_length=400)
    company: str = Field(default="", max_length=300)
    location: str = Field(default="", max_length=200)
    apply_url: str = Field(default="", description="Enlace de solicitud externo, si lo hay (ATS de la empresa)")
    company_website: str = ""
    easy_apply: bool = False
    description: str = Field(default="", max_length=60000, description="Se guarda SOLO en tu candidatura, no en la base común")


@router.get("/config", summary="Configuración de la extensión: plataformas, límites y avisos")
def config(profile: m.Profile = Depends(current_profile)):
    return {"platforms": {p.name: {"extension": p.extension, "kind": p.kind, "autofill_allowed": p.autofill_allowed}
                          for p in PLATFORMS.values()},
            "limits": LIMITS, "linkedin_warning": LINKEDIN_WARNING, "mode": profile.mode, "pack": profile.pack}


@router.get("/queue", summary="Candidaturas que la extensión debe preparar (formulario de la empresa o portal)")
def queue(batch_id: int | None = None, profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    q = select(m.Application).where(m.Application.user_id == profile.user_id, m.Application.mode == profile.mode,
                                    m.Application.route.in_(("ats_extension", "portal_copilot")),
                                    m.Application.status.in_(("prepared", "confirmed")))
    if batch_id:
        q = q.where(m.Application.batch_id == batch_id)
    out = []
    for a in db.scalars(q.order_by(m.Application.id).limit(LIMITS["batch_size"])):
        out.append({"id": a.id, "status": a.status, "route": a.route, "platform": a.platform, "apply_url": a.apply_url,
                    "title": a.job.title if a.job else "", "company": a.job.company_name if a.job else "",
                    "warnings": a.warnings or []})
    return out


def _find_application(db: Session, profile: m.Profile, url: str) -> m.Application | None:
    ref = detect(url)
    candidatos = select(m.Application).join(m.Job, m.Job.id == m.Application.job_id).where(
        m.Application.user_id == profile.user_id, m.Application.mode == profile.mode,
        m.Application.status.in_(svc.OPEN))
    base = url.split("?")[0].rstrip("/")
    for a in db.scalars(candidatos.where(or_(m.Job.apply_url.like(base + "%"), m.Job.url.like(base + "%")))):
        return a
    if ref and ref.job_id:
        for a in db.scalars(candidatos.where(or_(m.Job.apply_url.like(f"%{ref.job_id}%"), m.Job.url.like(f"%{ref.job_id}%")))):
            return a
    return None


@router.post("/fill-plan", summary="Plan de relleno para el formulario que la extensión ve en la página")
def fill_plan(data: FillPlanIn, profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    app = None
    if data.application_id:
        app = db.get(m.Application, data.application_id)
        if app is None or app.user_id != profile.user_id:
            raise not_found("Candidatura")
    else:
        app = _find_application(db, profile, data.url)
    lang = app.language if app else profile.user.locale or "en"
    empresa = {"name": app.company.name} if app and app.company else {}
    puesto = {"title": app.job.title, "country": app.job.country} if app and app.job else None
    carta = render_for(db, profile, "cover_letter", "company", lang, empresa, puesto)
    ref = detect(data.url)
    res = fill_form(db, profile, [f.model_dump() for f in data.fields], lang,
                    puesto["country"] if puesto else "", carta.body if carta else "",
                    data.platform or (ref.platform if ref else ""))
    for f in res["fields"]:
        if isinstance(f["value"], dict) and "document_id" in f["value"]:
            f["value"]["download_url"] = f"/me/documents/{f['value']['document_id']}/file"
    if app is not None and app.status in svc.OPEN:
        app.fields = res["fields"]   # lo que hay en la página real queda visible en la revisión de la API
    plataforma = data.platform or (ref.platform if ref else "")
    return {"application_id": app.id if app else None, "language": lang, **res,
            "cover_letter": carta.body if carta else "",
            "warnings": (app.warnings if app else []) + ([{"type": "linkedin_risk", "text": LINKEDIN_WARNING.get(lang, LINKEDIN_WARNING["en"])}]
                                                         if plataforma == "linkedin" else []),
            "never_submit": True}


@router.post("/submitted", summary="El usuario pulsó Enviar en la página: marcar como enviada")
def submitted(data: SubmittedIn, profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    app = db.get(m.Application, data.application_id)
    if app is None or app.user_id != profile.user_id:
        raise not_found("Candidatura")
    if app.status == "sent":
        return svc.review_item(db, app)
    try:
        return svc.review_item(db, svc.mark_sent(db, profile, app, how="extensión"))
    except svc.ApplicationError as ex:
        raise ApiError(409, ex.code, str(ex))


@router.post("/captures", status_code=201, summary="Guardar en knok la oferta que estás viendo (LinkedIn, Indeed, Google…)")
def capture(data: CaptureIn, profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    """A la base común solo van hechos mínimos (empresa, puesto, ubicación, enlace de solicitud). La descripción
    del portal se queda en TU candidatura, nunca en la base común."""
    from knok.core.geo import parse_location
    ref_pagina = detect(data.url)
    ciudad, pais, remoto = parse_location(data.location)
    plataforma = ref_pagina.platform if ref_pagina else domain_of(data.url)
    origen_id = f"{plataforma}:{ref_pagina.job_id}" if ref_pagina and ref_pagina.job_id else data.url.split("?")[0][:200]
    job = ingest.upsert_job(db, RawJob(
        source="capture", source_job_id=origen_id, title=data.title.strip(), company_name=data.company.strip(),
        company_website=data.company_website, city=ciudad, country=pais, remote=remoto, url=data.url,
        apply_url=data.apply_url or data.url, easy_apply=data.easy_apply, raw={"platform": plataforma}), profile.pack)
    # Si es copia de una oferta original (la del ATS de la empresa), se aplica a la original
    original = db.get(m.Job, job.canonical_job_id) if job.canonical_job_id else None
    destino = original or job
    app = svc.new_application(db, profile, destino, destino.company)
    if data.description and app.status in svc.OPEN and not app.notes:
        app.notes = html_to_text(data.description)[:20000]
    return {"application": svc.review_item(db, app), "job_id": job.id,
            "original_job_id": original.id if original else None}
