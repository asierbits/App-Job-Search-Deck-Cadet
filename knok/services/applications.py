"""Candidaturas: tandas (~40), preparación, revisión, confirmación y envío.

Flujo:
  1. create_batch: de los mejores resultados de una búsqueda crea candidaturas "prepared" y las rellena.
  2. El usuario revisa (GET /batches/{id}) y corrige (PATCH /applications/{id}).
  3. send_selected: UN clic con la lista de las que quiere → se confirman y:
       email           se encolan (Simulación / Prueba / Real, con límites y pausas)
       portal_api      se envían por la API oficial (InfoJobs)
       ats_extension   quedan listas para la extensión, que rellena el formulario; el usuario pulsa Enviar
       portal_copilot  ídem, una a una dentro del portal
       manual          se abre el enlace; el usuario la marca como enviada
Nada sale sin ese clic.
"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from knok.core.http import default_http
from knok.core.i18n import language_for_country
from knok.core.routing.router import RouteInput, decide
from knok.core.sources import infojobs
from knok.core.sources.ats import greenhouse
from knok.core.sources.ats.detect import detect
from knok.db.models import (Application, Batch, Company, Job, OAuthAccount, Profile, SearchResult, utcnow)
from knok.packs.loader import pack_or_default
from knok.security import decrypt
from knok.services import mailer
from knok.services.companies import best_emails
from knok.services.events import log_event
from knok.services.filling import fill_form, remember_answer
from knok.services.templates import render_for
from knok.settings import get_settings

PREPARABLE = ("ats_extension", "portal_api", "portal_copilot", "email")
BATCH_SIZE = 40
OPEN = ("prepared", "confirmed", "error")


class ApplicationError(ValueError):
    def __init__(self, code: str, message: str, problems: list | None = None):
        super().__init__(message)
        self.code, self.problems = code, problems or []


# ------------------------------------------------------------------------------------- crear y preparar

def find_existing(db: Session, profile: Profile, job_id: int | None, company_id: int | None) -> Application | None:
    q = select(Application).where(Application.user_id == profile.user_id, Application.mode == profile.mode)
    q = q.where(Application.job_id == job_id) if job_id else q.where(Application.job_id.is_(None),
                                                                     Application.company_id == company_id)
    return db.scalar(q)


def new_application(db: Session, profile: Profile, job: Job | None, company: Company | None,
                    batch: Batch | None = None) -> Application:
    existente = find_existing(db, profile, job.id if job else None, company.id if company else None)
    if existente:
        return existente
    pack = pack_or_default(profile.pack)
    ij = db.scalar(select(OAuthAccount.id).where(OAuthAccount.user_id == profile.user_id,
                                                 OAuthAccount.provider == "infojobs")) is not None
    d = decide(RouteInput(has_job=job is not None, source=job.source if job else "", apply_url=job.apply_url if job else "",
                          url=job.url if job else "", easy_apply=job.easy_apply if job else False,
                          apply_email=job.apply_email if job else "", company_emails=best_emails(db, company, pack),
                          careers_url=company.careers_url if company else "", infojobs_connected=ij,
                          extra_roles=frozenset(pack.crawl.extra_generic + pack.crawl.mailbox_priority)))
    app = Application(user_id=profile.user_id, mode=profile.mode, batch_id=batch.id if batch else None,
                      job_id=job.id if job else None, company_id=company.id if company else None, route=d.route,
                      platform=d.platform, route_reason=d.reason, contact_email=d.contact_email,
                      apply_url=d.apply_url or (job.apply_url if job else "") or (company.careers_url if company else ""),
                      warnings=[{"type": w} for w in d.warnings], status="prepared")
    db.add(app)
    db.flush()
    prepare(db, app, profile)
    return app


def reroute(db: Session, app: Application, profile: Profile, job: Job) -> Application:
    """Pasar una candidatura a otra oferta (la original en el formulario de la empresa) y volver a prepararla."""
    pack = pack_or_default(profile.pack)
    d = decide(RouteInput(has_job=True, source=job.source, apply_url=job.apply_url, url=job.url,
                          easy_apply=job.easy_apply, apply_email=job.apply_email,
                          company_emails=best_emails(db, job.company, pack),
                          extra_roles=frozenset(pack.crawl.extra_generic + pack.crawl.mailbox_priority)))
    app.job_id, app.company_id = job.id, job.company_id
    app.route, app.platform, app.route_reason = d.route, d.platform, d.reason
    app.apply_url = d.apply_url or job.apply_url
    app.contact_email = d.contact_email
    app.status = "prepared"
    db.flush()
    db.refresh(app)
    prepare(db, app, profile)
    return app


def _language(app: Application, profile: Profile) -> str:
    pack = pack_or_default(profile.pack)
    if app.job and app.job.language in pack.languages:
        return app.job.language
    pais = (app.job.country if app.job else "") or (app.company.country if app.company else "")
    return language_for_country(pais, pack.languages)


def _company_dict(app: Application) -> dict:
    c = app.company
    if c:
        return {"name": c.name, "city": c.city, "country": c.country, "sector": c.sector}
    return {"name": app.job.company_name if app.job else ""}


def _job_dict(app: Application) -> dict | None:
    j = app.job
    return {"title": j.title, "city": j.city, "country": j.country, "company_name": j.company_name} if j else None


def _questions(db: Session, app: Application) -> list[dict]:
    """Preguntas conocidas del formulario: las que ya trae la oferta o las de la API pública de Greenhouse."""
    j = app.job
    if j is None:
        return []
    if j.questions:
        return j.questions
    ref = detect(j.apply_url or j.url)
    if ref and ref.platform == "greenhouse" and ref.job_id and not get_settings().offline_sources:
        try:
            j.questions = greenhouse.fetch_questions(default_http(), ref.slug, ref.job_id)
        except Exception:
            j.questions = []
    return j.questions or []


def prepare(db: Session, app: Application, profile: Profile) -> None:
    pack = pack_or_default(profile.pack)
    lang = _language(app, profile)
    app.language = lang
    warnings = [w for w in (app.warnings or []) if w.get("type") in ("linkedin_risk", "infojobs_not_connected")]
    if app.company and (app.company.flags or {}).get(pack.slug, {}).get("warnings"):
        for w in app.company.flags[pack.slug]["warnings"]:
            warnings.append({"type": "company_" + w["type"], "text": w.get("text", ""), "url": w.get("url", "")})
    if app.job and app.job.closed_at:
        warnings.append({"type": "job_closed"})

    empresa, puesto = _company_dict(app), _job_dict(app)
    if app.route == "email":
        audiencia = "job" if puesto else ("agency" if app.company and app.company.kind == "agency" else "company")
        r = render_for(db, profile, "email", audiencia, lang, empresa, puesto)
        if r:
            app.subject, app.body = r.subject, r.body
            from knok.core.mail.compose import blocking_missing
            faltan = blocking_missing(r.missing)
            if faltan:
                warnings.append({"type": "missing_variables", "vars": faltan})
        app.document_ids = mailer.default_attachments(db, profile.user_id, lang)
        app.fields = []
    else:
        carta = render_for(db, profile, "cover_letter", "company", lang, empresa, puesto)
        res = fill_form(db, profile, _questions(db, app), lang, puesto["country"] if puesto else "",
                        carta.body if carta else "", app.platform)
        app.fields = res["fields"]
        app.body = carta.body if carta else ""
    app.warnings = warnings


def create_batch(db: Session, profile: Profile, search_id: int | None = None, result_ids: list[int] | None = None,
                 size: int = BATCH_SIZE, routes: list[str] | None = None, include_manual: bool = False) -> Batch:
    rutas = set(routes or PREPARABLE) | ({"manual"} if include_manual else set())
    q = select(SearchResult)
    if result_ids:
        q = q.where(SearchResult.id.in_(result_ids))
    elif search_id:
        q = q.where(SearchResult.search_id == search_id)
    else:
        raise ApplicationError("bad_request", "Indica search_id o result_ids")
    batch = Batch(user_id=profile.user_id, search_id=search_id, mode=profile.mode, status="review")
    db.add(batch)
    db.flush()
    n = 0
    for r in db.scalars(q.order_by(SearchResult.score.desc(), SearchResult.id)):
        if n >= size:
            break
        if r.route not in rutas:
            continue
        job = db.get(Job, r.job_id) if r.job_id else None
        company = db.get(Company, r.company_id) if r.company_id else (job.company if job else None)
        existente = find_existing(db, profile, job.id if job else None, company.id if company else None)
        if existente is not None:
            if existente.status in OPEN:   # preparada antes y sin enviar: entra en esta tanda
                existente.batch_id = batch.id
                n += 1
            continue
        new_application(db, profile, job, company, batch)
        n += 1
    log_event(db, profile.user_id, f"Tanda preparada con {n} candidaturas para revisar.", "ok", batch_id=batch.id)
    return batch


# ------------------------------------------------------------------------------------- revisión

def blocking_problems(app: Application) -> list[dict]:
    p = []
    if app.status not in OPEN:
        p.append({"code": "not_open", "message": f"La candidatura ya está en estado '{app.status}'."})
    if app.route == "email":
        if not app.contact_email:
            p.append({"code": "no_contact", "message": "No hay buzón genérico al que escribir."})
        if not app.subject.strip() or not app.body.strip():
            p.append({"code": "empty_email", "message": "El correo está vacío."})
        for w in app.warnings or []:
            if w.get("type") == "missing_variables":
                p.append({"code": "missing_variables",
                          "message": "Faltan datos del perfil en el correo: " + ", ".join(w["vars"])})
    if app.route == "portal_api":
        faltan = [f["label"] for f in app.fields or [] if f.get("required") and f.get("value") in (None, "")]
        if faltan:
            p.append({"code": "missing_fields", "message": "Faltan respuestas obligatorias: " + "; ".join(faltan)})
    if app.route == "manual":
        p.append({"code": "manual", "message": "Esta candidatura se hace a mano: abre el enlace y márcala como enviada."})
    return p


def review_item(db: Session, app: Application) -> dict:
    j, c = app.job, app.company
    campos = app.fields or []
    return {
        "id": app.id, "status": app.status, "mode": app.mode, "route": app.route, "platform": app.platform,
        "route_reason": app.route_reason, "language": app.language, "apply_url": app.apply_url,
        "job": {"id": j.id, "title": j.title, "company_name": j.company_name, "city": j.city, "country": j.country,
                "url": j.url, "description": (j.description or "")[:4000], "source": j.source} if j else None,
        "company": {"id": c.id, "name": c.name, "domain": c.domain, "website": c.website, "careers_url": c.careers_url,
                    "country": c.country} if c else None,
        "email": {"to": app.contact_email, "subject": app.subject, "body": app.body,
                  "attachments": app.document_ids} if app.route == "email" else None,
        "cover_letter": app.body if app.route != "email" else None,
        "fields": campos,
        "deduced": [f["id"] for f in campos if f.get("value") not in (None, "") and not f.get("needs_review")],
        "needs_review": [f["id"] for f in campos if f.get("needs_review")],
        "missing": [f["id"] for f in campos if f.get("required") and f.get("value") in (None, "")],
        "warnings": app.warnings or [],
        "blocking": blocking_problems(app) if app.status in OPEN else [],
        "notes": app.notes,
        "sent_at": app.sent_at.isoformat() if app.sent_at else None,
    }


def update(db: Session, app: Application, profile: Profile, patch: dict) -> Application:
    if set(patch) <= {"notes"}:          # las notas se pueden escribir en cualquier momento
        app.notes = patch.get("notes") or ""
        return app
    if app.status not in OPEN:
        raise ApplicationError("not_open", f"No se puede editar una candidatura en estado '{app.status}'")
    if "contact_email" in patch:
        from knok.core.emails.generic import is_generic
        pack = pack_or_default(profile.pack)
        e = (patch["contact_email"] or "").strip().lower()
        if e and not is_generic(e, frozenset(pack.crawl.extra_generic + pack.crawl.mailbox_priority)):
            raise ApplicationError("personal_email", "Solo se escribe a buzones genéricos de empresa (info@, rrhh@…)")
        app.contact_email = e
    for k in ("subject", "body", "notes"):
        if k in patch and patch[k] is not None:
            setattr(app, k, patch[k])
    if "subject" in patch or "body" in patch:
        # El usuario ha revisado el texto: el aviso de variables vacías ya no bloquea
        app.warnings = [w for w in app.warnings or [] if w.get("type") != "missing_variables"]
    if "document_ids" in patch and patch["document_ids"] is not None:
        from knok.db.models import Document
        propios = set(db.scalars(select(Document.id).where(Document.user_id == app.user_id,
                                                           Document.id.in_(patch["document_ids"]))))
        app.document_ids = [d for d in patch["document_ids"] if d in propios]
    if patch.get("fields"):
        por_id = {f["id"]: dict(f) for f in app.fields or []}
        for cambio in patch["fields"]:
            f = por_id.get(str(cambio.get("id")))
            if f is None:
                continue
            f["value"] = cambio.get("value")
            f["display"] = str(cambio.get("value") or "")
            f["origin"], f["confidence"], f["needs_review"] = "user", "high", False
            if cambio.get("remember", True) and f.get("key") is None and f["type"] not in ("file",):
                remember_answer(db, app.user_id, f["label"], cambio.get("value"))
        app.fields = list(por_id.values())
    app.updated_at = utcnow()
    return app


# ------------------------------------------------------------------------------------- el clic: enviar las seleccionadas

def send_selected(db: Session, profile: Profile, apps: list[Application]) -> list[dict]:
    resultados, para_correo = [], []
    for app in apps:
        problemas = [p for p in blocking_problems(app) if p["code"] != "manual"]
        if problemas:
            resultados.append({"id": app.id, "outcome": "blocked", "problems": problemas})
            continue
        app.status, app.confirmed_at, app.last_status_at = "confirmed", utcnow(), utcnow()
        if app.route == "email":
            para_correo.append(app)
        elif app.route == "portal_api":
            resultados.append(_submit_infojobs(db, profile, app))
        elif app.route in ("ats_extension", "portal_copilot"):
            resultados.append({"id": app.id, "outcome": "ready_for_extension", "apply_url": app.apply_url})
        else:
            resultados.append({"id": app.id, "outcome": "open_link", "apply_url": app.apply_url})
    if para_correo:
        try:
            emails = mailer.queue_application_emails(db, profile, para_correo)
            por_app = {e.application_id: e for e in emails}
            for app in para_correo:
                e = por_app.get(app.id)
                resultados.append({"id": app.id, "outcome": "email_queued" if e else "blocked",
                                   "email_id": e.id if e else None,
                                   "status": e.status if e else None})
        except mailer.SendingBlocked as ex:
            for app in para_correo:
                app.status = "prepared"
                resultados.append({"id": app.id, "outcome": "blocked", "problems": ex.problems})
    return resultados


def _submit_infojobs(db: Session, profile: Profile, app: Application) -> dict:
    if profile.mode == "test":
        app.status = "prepared"
        return {"id": app.id, "outcome": "blocked", "problems": [{"code": "no_test_mode",
                "message": "InfoJobs no tiene modo prueba: usa Simulación para probar o Real para enviar."}]}
    if profile.mode == "simulation":
        app.status, app.sent_at = "sent", utcnow()
        app.follow_up_at = app.sent_at + timedelta(days=profile.followup_days)
        log_event(db, profile.user_id, f"Candidatura (simulada) por InfoJobs: {app.job.title if app.job else ''}", "ok")
        return {"id": app.id, "outcome": "submitted_simulated"}
    s = get_settings()
    acc = db.scalar(select(OAuthAccount).where(OAuthAccount.user_id == profile.user_id, OAuthAccount.provider == "infojobs"))
    if acc is None:
        app.status = "prepared"
        return {"id": app.id, "outcome": "blocked", "problems": [{"code": "infojobs_not_connected",
                                                                  "message": "Conecta tu cuenta de InfoJobs."}]}
    token, http = decrypt(acc.access_token_enc), default_http()
    try:
        cvs = infojobs.list_curricula(http, s.infojobs_client_id, s.infojobs_client_secret, token)
        if not cvs:
            raise ApplicationError("no_curriculum", "No tienes ningún CV en InfoJobs")
        cuerpo = infojobs.build_application(cvs[0].get("code", ""), app.fields or [], app.body)
        infojobs.apply(http, s.infojobs_client_id, s.infojobs_client_secret, token, app.job.source_job_id, cuerpo)
    except Exception as ex:
        app.status = "error"
        app.notes = (app.notes + "\n" if app.notes else "") + f"InfoJobs: {ex}"
        return {"id": app.id, "outcome": "error", "problems": [{"code": "infojobs_error", "message": str(ex)}]}
    app.status, app.sent_at = "sent", utcnow()
    app.follow_up_at = app.sent_at + timedelta(days=profile.followup_days)
    log_event(db, profile.user_id, f"Candidatura enviada por InfoJobs: {app.job.title}", "ok", application_id=app.id)
    return {"id": app.id, "outcome": "submitted"}


def mark_sent(db: Session, profile: Profile, app: Application, how: str = "manual") -> Application:
    if app.status not in OPEN:
        raise ApplicationError("not_open", f"La candidatura ya está en estado '{app.status}'")
    ahora = utcnow()
    app.status, app.sent_at, app.last_status_at = "sent", ahora, ahora
    app.confirmed_at = app.confirmed_at or ahora
    app.follow_up_at = ahora + timedelta(days=profile.followup_days)
    log_event(db, profile.user_id, f"Candidatura marcada como enviada ({how}): "
              f"{(app.job.title if app.job else '') or (app.company.name if app.company else '')}", "ok",
              application_id=app.id)
    return app

