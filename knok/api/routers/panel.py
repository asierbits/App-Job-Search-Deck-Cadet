"""Endpoints de conveniencia para el panel (la interfaz web incluida y tu web si los quiere usar).

Juntan en una sola llamada lo que el panel enseña: estado general, la tabla de empresas y ofertas
(resultados de la búsqueda + candidaturas ya hechas) y el envío de lo que el usuario marca.
Nada se envía sin POST /panel/send con la lista explícita de lo seleccionado.
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from knok.api.deps import ApiError, current_profile, current_user, get_db, not_found
from knok.api.routers.me import _profile_out
from knok.core.emails.score import MailboxRules, best
from knok.db import models as m
from knok.packs.loader import all_packs, pack_or_default
from knok.services import applications as svc
from knok.packs import custom
from knok.services import inbox, niches, tracking
from knok.services.events import log_event
from knok.services.mailer import APP_PASSWORD
from knok.services.readiness import google_account, sending_problems
from knok.settings import get_settings

router = APIRouter(prefix="/panel", tags=["panel"])

BOARD_MAX = 1000


def _search_out(s: m.Search | None) -> dict | None:
    if s is None:
        return None
    return {"id": s.id, "status": s.status, "params": s.params, "stats": s.stats, "error": s.error,
            "created_at": s.created_at.isoformat(), "finished_at": s.finished_at.isoformat() if s.finished_at else None}


def _latest_search(db: Session, user_id: int) -> m.Search | None:
    return db.scalars(select(m.Search).where(m.Search.user_id == user_id).order_by(m.Search.id.desc()).limit(1)).first()


def _app_label(a: m.Application | None) -> dict:
    if a is None:
        return {"company": "", "title": ""}
    empresa = a.company.name if a.company else (a.job.company_name if a.job else "")
    return {"company": empresa, "title": a.job.title if a.job else ""}


def _reply_out(db: Session, r: m.Reply) -> dict:
    a = db.get(m.Application, r.application_id) if r.application_id else None
    return {"id": r.id, "application_id": r.application_id, "source": r.source, "from": r.from_addr,
            "subject": r.subject, "body": r.body, "category": r.category, "read": r.read,
            "received_at": r.received_at.isoformat(), **_app_label(a)}


@router.get("/state", summary="Todo lo que el panel enseña de un vistazo")
def state(user: m.User = Depends(current_user), profile: m.Profile = Depends(current_profile),
          db: Session = Depends(get_db)):
    s = get_settings()
    pack = pack_or_default(profile.pack)
    g = google_account(db, user.id)
    respuestas = db.scalars(select(m.Reply).where(m.Reply.user_id == user.id, m.Reply.mode == profile.mode)
                            .order_by(m.Reply.received_at.desc()).limit(100))
    eventos = db.scalars(select(m.Event).where(m.Event.user_id == user.id).order_by(m.Event.id.desc()).limit(40))
    return {
        "user": {"id": user.id, "email": user.email},
        "profile": _profile_out(profile),
        "pack": {"slug": pack.slug, "name": pack.name("es"), "description": pack.description.get("es", ""),
                 "languages": pack.languages, "default_countries": pack.sources.default_countries,
                 "custom": pack.slug.startswith(custom.PREFIX),
                 "company_sources": {"osm": bool(pack.sources.osm.tags), "wikidata": bool(pack.sources.wikidata.queries),
                                     "directories": len(pack.sources.directories)},
                 "profile_fields": [f.model_dump() for f in pack.profile_fields]},
        "packs": [{"slug": p.slug, "name": p.name("es"), "custom": False,
                   "description": p.description.get("es", "")} for p in all_packs().values()]
                 + [{"slug": n.slug, "name": n.name, "custom": True, "description": (n.spec or {}).get("description", "")}
                    for n in niches.list_for(db, user.id)],
        "connections": {"google": {"connected": g is not None, "email": g.account_email if g else "",
                                   "method": ("app_password" if g.scopes == APP_PASSWORD else "oauth") if g else "",
                                   "oauth_configured": bool(s.google_client_id),
                                   "app_password_allowed": s.local_single_user,
                                   "inbox_checked_at": inbox.last_check(g)}},
        "sending_problems": sending_problems(db, profile),
        "offline": s.offline_sources,
        "sources_ready": {"adzuna": bool(s.adzuna_app_id and s.adzuna_app_key),
                          "infojobs": bool(s.infojobs_client_id and s.infojobs_client_secret)},
        "search": _search_out(_latest_search(db, user.id)),
        "summary": tracking.summary(db, profile),
        "replies": [_reply_out(db, r) for r in respuestas],
        "events": [{"id": e.id, "ts": e.ts.isoformat(), "level": e.level, "message": e.message} for e in eventos],
    }


def _row_from(c: m.Company | None, j: m.Job | None, emails: list[str], pack_slug: str) -> dict:
    flags = (c.flags or {}) if c else {}
    f = flags.get(pack_slug, {})
    return {
        "kind": "job" if j else "company",
        "name": (c.name if c else "") or (j.company_name if j else ""),
        "title": j.title if j else "",
        "sector": c.sector if c else "",
        "company_kind": c.kind if c else "",
        "country": (j.country if j else "") or (c.country if c else ""),
        "city": (j.city if j else "") or (c.city if c else ""),
        "website": c.website if c else "",
        "careers_url": c.careers_url if c else "",
        "job_url": j.url if j else "",
        "source": j.source if j else ",".join(c.sources or []) if c else "",
        "email": emails[0] if emails else "",
        "mentions": f.get("mentions", []),
        "signals": f.get("signals", []),
        "warnings": f.get("warnings", []),
        "blocked": bool(flags.get("blocked")),
        "crawled": bool(f.get("crawled_at")),
    }


def _board_search(db: Session, user_id: int) -> m.Search | None:
    """La última búsqueda con resultados (si la nueva aún no tiene ninguno, o se detuvo antes de empezar,
    la tabla sigue enseñando los de la anterior)."""
    recientes = list(db.scalars(select(m.Search).where(m.Search.user_id == user_id)
                                .order_by(m.Search.id.desc()).limit(20)))
    con = next((s for s in recientes if db.scalar(select(m.SearchResult.id)
                                                  .where(m.SearchResult.search_id == s.id).limit(1))), None)
    return con or (recientes[0] if recientes else None)


def _key(job_id: int | None, company_id: int | None) -> str:
    """Clave estable de una fila: la misma antes y después de preparar la candidatura."""
    return f"j{job_id}" if job_id else f"c{company_id}"


@router.get("/board", summary="Tabla de empresas y ofertas: resultados de la búsqueda + candidaturas")
def board(search_id: int | None = None, user: m.User = Depends(current_user),
          profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    pack = pack_or_default(profile.pack)
    if search_id:
        search = db.get(m.Search, search_id)
        if search is None or search.user_id != user.id:
            raise not_found("Búsqueda")
    else:
        search = _board_search(db, user.id)
    resultados = list(db.scalars(select(m.SearchResult).where(m.SearchResult.search_id == search.id)
                                 .order_by(m.SearchResult.score.desc(), m.SearchResult.id).limit(BOARD_MAX))) \
        if search else []
    apps = list(db.scalars(select(m.Application).where(m.Application.user_id == user.id,
                                                       m.Application.mode == profile.mode)
                           .order_by(m.Application.last_status_at.desc()).limit(BOARD_MAX)))

    # Buzones de todas las empresas de una vez (no una consulta por fila)
    ids_empresa = {r.company_id for r in resultados if r.company_id} | {a.company_id for a in apps if a.company_id}
    por_empresa: dict[int, list[tuple[str, bool]]] = {}
    for cid, email, carreras in db.execute(select(m.CompanyEmail.company_id, m.CompanyEmail.email,
                                                  m.CompanyEmail.on_careers_page)
                                           .where(m.CompanyEmail.company_id.in_(ids_empresa))) if ids_empresa else []:
        por_empresa.setdefault(cid, []).append((email, carreras))
    reglas = MailboxRules.for_pack(pack)
    empresas = {c.id: c for c in db.scalars(select(m.Company).where(m.Company.id.in_(ids_empresa)))} \
        if ids_empresa else {}
    ids_oferta = {r.job_id for r in resultados if r.job_id} | {a.job_id for a in apps if a.job_id}
    ofertas = {j.id: j for j in db.scalars(select(m.Job).where(m.Job.id.in_(ids_oferta)))} if ids_oferta else {}

    def correos(c: m.Company | None) -> list[str]:
        return best(por_empresa.get(c.id, []), c.domain or "", reglas) if c else []

    ultimas: dict[int, str] = {}
    if apps:
        for aid, cat in db.execute(select(m.Reply.application_id, m.Reply.category)
                                   .where(m.Reply.application_id.in_([a.id for a in apps]))
                                   .order_by(m.Reply.received_at)):
            ultimas[aid] = cat

    filas, vistas = [], {}
    for a in apps:
        c, j = empresas.get(a.company_id), ofertas.get(a.job_id)
        fila = {**_row_from(c, j, correos(c), pack.slug), "key": _key(a.job_id, a.company_id), "application_id": a.id,
                "result_id": None, "route": a.route, "platform": a.platform, "score": None,
                "reasons": [a.route_reason] if a.route_reason else [], "status": a.status,
                "email": a.contact_email or (correos(c)[:1] or [""])[0], "apply_url": a.apply_url,
                "sent_at": a.sent_at.isoformat() if a.sent_at else None, "reply": ultimas.get(a.id),
                "follow_up_due": bool(a.status == "sent" and a.follow_up_at and a.follow_up_at <= m.utcnow())}
        filas.append(fila)
        vistas[(a.job_id, a.company_id if a.job_id is None else None)] = fila
    for r in resultados:
        clave = (r.job_id, r.company_id if r.job_id is None else None)
        if clave in vistas:          # ya tiene candidatura: se enseña esa, con la puntuación de la búsqueda
            vistas[clave]["score"] = r.score
            vistas[clave]["result_id"] = r.id
            vistas[clave]["reasons"] = r.reasons
            continue
        c, j = empresas.get(r.company_id), ofertas.get(r.job_id)
        filas.append({**_row_from(c, j, correos(c), pack.slug), "key": _key(r.job_id, r.company_id), "application_id": None,
                      "result_id": r.id, "route": r.route, "platform": r.platform, "score": r.score,
                      "reasons": r.reasons, "status": "new", "apply_url": (j.apply_url or j.url) if j else
                      (c.careers_url if c else ""), "sent_at": None, "reply": None, "follow_up_due": False})
    return {"search": _search_out(search), "mode": profile.mode, "items": filas}


class PickIn(BaseModel):
    result_ids: list[int] = Field(default=[], max_length=500)
    application_ids: list[int] = Field(default=[], max_length=500)


def _apps_for(db: Session, profile: m.Profile, data: PickIn) -> list[m.Application]:
    apps: list[m.Application] = []
    for aid in dict.fromkeys(data.application_ids):
        a = db.get(m.Application, aid)
        if a is None or a.user_id != profile.user_id:
            raise not_found("Candidatura")
        apps.append(a)
    for rid in dict.fromkeys(data.result_ids):
        r = db.get(m.SearchResult, rid)
        s = db.get(m.Search, r.search_id) if r else None
        if r is None or s is None or s.user_id != profile.user_id:
            raise not_found("Resultado")
        job = db.get(m.Job, r.job_id) if r.job_id else None
        company = db.get(m.Company, r.company_id) if r.company_id else (job.company if job else None)
        a = svc.new_application(db, profile, job, company)
        if a not in apps:
            apps.append(a)
    return apps


@router.post("/prepare", summary="Preparar (sin enviar) lo marcado y devolverlo para revisar")
def prepare(data: PickIn, profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    return {"items": [svc.review_item(db, a) for a in _apps_for(db, profile, data)]}


@router.post("/send", summary="EL CLIC: preparar y enviar lo que has marcado en la tabla")
def send(data: PickIn, profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    if not data.result_ids and not data.application_ids:
        raise ApiError(422, "nothing_selected", "No has marcado nada")
    apps = _apps_for(db, profile, data)
    db.flush()
    resultados = svc.send_selected(db, profile, apps)
    por_id = {a.id: a for a in apps}
    for r in resultados:
        r.update(_app_label(por_id.get(r["id"])))
    enviadas = sum(1 for r in resultados if r["outcome"] in ("email_queued", "submitted", "submitted_simulated"))
    log_event(db, profile.user_id, f"Has confirmado {len(apps)} candidaturas: {enviadas} en cola o enviadas.", "ok")
    return {"results": resultados}


@router.post("/discard", summary="Descartar lo marcado (no vuelve a salir en las búsquedas)")
def discard(data: PickIn, profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    n = 0
    for a in _apps_for(db, profile, data):
        if a.status in svc.OPEN:
            a.status, a.follow_up_at, a.last_status_at = "discarded", None, m.utcnow()
            n += 1
    return {"discarded": n}


@router.get("/replies", summary="Respuestas con la empresa y el puesto")
def replies(limit: int = Query(200, le=1000), profile: m.Profile = Depends(current_profile),
            db: Session = Depends(get_db)):
    return [_reply_out(db, r) for r in db.scalars(select(m.Reply).where(
        m.Reply.user_id == profile.user_id, m.Reply.mode == profile.mode)
        .order_by(m.Reply.received_at.desc()).limit(limit))]


@router.post("/check-inbox", summary="Revisar ahora el Gmail en busca de respuestas (contraseña de aplicación)")
def check_inbox(profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    from knok.core.mail.apppassword import MailboxError
    g = google_account(db, profile.user_id)
    if g is None or g.scopes != APP_PASSWORD:
        raise ApiError(409, "no_mailbox", "Para leer las respuestas conecta Gmail con contraseña de aplicación "
                                          "(o anótalas a mano / reenvíalas a knok)")
    try:
        nuevas = inbox.check_user(db, profile, g)
    except MailboxError as ex:
        raise ApiError(502, "mailbox_error", str(ex))
    return {"new": nuevas, "checked_at": inbox.last_check(g)}
