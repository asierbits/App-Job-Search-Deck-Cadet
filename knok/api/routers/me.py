"""El usuario: perfil, ajustes, documentos, banco de respuestas, plantillas, exportación y borrado."""
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from knok import storage
from knok.api.deps import ApiError, current_profile, current_user, get_db, not_found
from knok.core.filling.fields import is_sensitive
from knok.core.mail.compose import blocking_missing, render, template_values
from knok.core.text import norm
from knok.db import models as m
from knok.packs.loader import answer_keys_for, pack_or_default
from knok.services.niches import pack_allowed
from knok.security import verify_password
from knok.services.readiness import MODES, google_account, sending_problems
from knok.services.templates import AUDIENCES, KINDS, effective_template, profile_dict
from knok.settings import get_settings

router = APIRouter(prefix="/me", tags=["me"])


# ------------------------------------------------------------------------------------- perfil

class Language(BaseModel):
    code: str = Field(pattern=r"^[a-z]{2}$")
    level: str = Field(default="", description="A1…C2, native")


class ProfileOut(BaseModel):
    pack: str
    mode: Literal["simulation", "test", "live"]
    first_name: str
    last_name: str
    email: str
    phone: str
    city: str
    country: str
    links: dict[str, str]
    languages: list[Language]
    pack_data: dict[str, Any]
    daily_limit: int
    pause_seconds: int
    followup_days: int


class ProfilePatch(BaseModel):
    pack: str | None = None
    mode: Literal["simulation", "test", "live"] | None = None
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    city: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, pattern=r"^([a-zA-Z]{2})?$")
    links: dict[str, str] | None = None
    languages: list[Language] | None = None
    pack_data: dict[str, Any] | None = None
    daily_limit: int | None = Field(default=None, ge=1)
    pause_seconds: int | None = Field(default=None, ge=5, le=3600)
    followup_days: int | None = Field(default=None, ge=1, le=90)


def _profile_out(p: m.Profile) -> ProfileOut:
    return ProfileOut(pack=p.pack, mode=p.mode, first_name=p.first_name, last_name=p.last_name, email=p.email,
                      phone=p.phone, city=p.city, country=p.country, links=p.links or {},
                      languages=p.languages or [], pack_data=p.pack_data or {}, daily_limit=p.daily_limit,
                      pause_seconds=p.pause_seconds, followup_days=p.followup_days)


@router.get("", summary="Usuario, perfil, cuentas conectadas y si está listo para enviar")
def me(user: m.User = Depends(current_user), profile: m.Profile = Depends(current_profile),
       db: Session = Depends(get_db)):
    g = google_account(db, user.id)
    ij = db.scalar(select(m.OAuthAccount).where(m.OAuthAccount.user_id == user.id,
                                                m.OAuthAccount.provider == "infojobs"))
    s = get_settings()
    return {
        "user": {"id": user.id, "email": user.email, "locale": user.locale, "is_admin": user.is_admin},
        "profile": _profile_out(profile),
        "connections": {
            "google": {"connected": g is not None, "email": g.account_email if g else ""},
            "infojobs": {"connected": ij is not None},
        },
        "reply_forwarding_address": f"u-{profile.inbound_token}@{s.inbound_domain}" if profile.inbound_token else "",
        "sending_problems": sending_problems(db, profile),
    }


@router.patch("/profile", response_model=ProfileOut, summary="Actualizar perfil y ajustes")
def update_profile(data: ProfilePatch, profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    cambios = data.model_dump(exclude_unset=True)
    if "pack" in cambios and not pack_allowed(db, cambios["pack"], profile.user_id):
        raise ApiError(422, "unknown_pack", f"Pack desconocido: {cambios['pack']}")
    tope = get_settings().gmail_daily_cap
    if cambios.get("daily_limit") and cambios["daily_limit"] > tope:
        raise ApiError(422, "daily_limit_too_high", f"El límite diario no puede pasar de {tope} (tope de Gmail)")
    if "country" in cambios:
        cambios["country"] = (cambios["country"] or "").lower()
    if "languages" in cambios:
        cambios["languages"] = [l.model_dump() if hasattr(l, "model_dump") else l for l in data.languages or []]
    if "pack_data" in cambios:
        cambios["pack_data"] = {**(profile.pack_data or {}), **cambios["pack_data"]}
    for k, v in cambios.items():
        setattr(profile, k, v)
    return _profile_out(profile)


@router.get("/export", summary="Exportar todos mis datos (RGPD)")
def export(user: m.User = Depends(current_user), profile: m.Profile = Depends(current_profile),
           db: Session = Depends(get_db)):
    def rows(model, *where):
        out = []
        for r in db.scalars(select(model).where(*where)):
            d = {c.name: getattr(r, c.name) for c in model.__table__.columns}
            d.pop("password_hash", None)
            d.pop("access_token_enc", None)
            d.pop("refresh_token_enc", None)
            d.pop("token_hash", None)
            out.append({k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in d.items()})
        return out
    uid = user.id
    data = {
        "user": {"id": uid, "email": user.email, "locale": user.locale, "created_at": user.created_at.isoformat()},
        "profile": _profile_out(profile).model_dump(),
        "documents": rows(m.Document, m.Document.user_id == uid),
        "answers": rows(m.Answer, m.Answer.user_id == uid),
        "custom_answers": rows(m.CustomAnswer, m.CustomAnswer.user_id == uid),
        "templates": rows(m.Template, m.Template.user_id == uid),
        "searches": rows(m.Search, m.Search.user_id == uid),
        "applications": rows(m.Application, m.Application.user_id == uid),
        "emails": rows(m.Email, m.Email.user_id == uid),
        "replies": rows(m.Reply, m.Reply.user_id == uid),
        "connections": rows(m.OAuthAccount, m.OAuthAccount.user_id == uid),
    }
    import json
    return Response(json.dumps(data, ensure_ascii=False, indent=2, default=str), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="knok-mis-datos.json"'})


class DeleteIn(BaseModel):
    password: str


@router.post("/delete", status_code=204, summary="Borrar mi cuenta y todos mis datos (irreversible)")
def delete_account(data: DeleteIn, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(data.password, user.password_hash):
        raise ApiError(401, "bad_credentials", "Contraseña incorrecta")
    storage.delete_prefix(f"users/{user.id}")
    # Orden explícito: SQLite en tests no aplica ON DELETE CASCADE sin PRAGMA
    for model in (m.Reply, m.SimulatedReply, m.Email, m.Application, m.Batch, m.SearchResult, m.Search,
                  m.Document, m.Answer, m.CustomAnswer, m.Template, m.OAuthAccount, m.OAuthState,
                  m.ApiToken, m.Event, m.Task, m.Profile):
        if model is m.SimulatedReply:
            ids = select(m.Email.id).where(m.Email.user_id == user.id)
            db.execute(delete(model).where(model.email_id.in_(ids)))
        elif model is m.SearchResult:
            ids = select(m.Search.id).where(m.Search.user_id == user.id)
            db.execute(delete(model).where(model.search_id.in_(ids)))
        else:
            db.execute(delete(model).where(model.user_id == user.id))
    db.delete(user)


# ------------------------------------------------------------------------------------- documentos

class DocumentOut(BaseModel):
    id: int
    kind: str
    language: str
    label: str
    filename: str
    mime: str
    size: int
    is_default: bool
    created_at: str


def _doc_out(d: m.Document) -> DocumentOut:
    return DocumentOut(id=d.id, kind=d.kind, language=d.language, label=d.label, filename=d.filename, mime=d.mime,
                       size=d.size, is_default=d.is_default, created_at=d.created_at.isoformat())


DocKind = Literal["cv", "cover_letter", "certificate", "other"]


@router.get("/documents", response_model=list[DocumentOut], summary="Mis documentos (CVs, cartas…)")
def list_documents(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return [_doc_out(d) for d in db.scalars(select(m.Document).where(m.Document.user_id == user.id)
                                             .order_by(m.Document.kind, m.Document.language, m.Document.id))]


@router.post("/documents", response_model=DocumentOut, status_code=201, summary="Subir un documento")
async def upload_document(file: UploadFile = File(...), kind: DocKind = Form("cv"),
                          language: str = Form("", pattern=r"^([a-z]{2})?$"), label: str = Form(""),
                          is_default: bool = Form(False), user: m.User = Depends(current_user),
                          db: Session = Depends(get_db)):
    datos = await file.read()
    nombre = storage.safe_filename(file.filename or "documento")
    if not nombre.lower().endswith(storage.ALLOWED_EXT):
        raise ApiError(422, "bad_extension", f"Tipo de archivo no admitido. Usa: {', '.join(storage.ALLOWED_EXT)}")
    if len(datos) > storage.MAX_FILE:
        raise ApiError(413, "too_large", "El archivo pesa más de 10 MB")
    ocupado = sum(d.size for d in db.scalars(select(m.Document).where(m.Document.user_id == user.id)))
    if ocupado + len(datos) > storage.MAX_PER_USER:
        raise ApiError(413, "quota", "Has llegado al límite de 50 MB de documentos")
    key = storage.save(f"users/{user.id}/documents", nombre, datos)
    hay_otro = db.scalar(select(m.Document.id).where(m.Document.user_id == user.id, m.Document.kind == kind,
                                                     m.Document.language == language).limit(1))
    d = m.Document(user_id=user.id, kind=kind, language=language, label=label or nombre, filename=nombre,
                   storage_key=key, mime=storage.guess_mime(nombre), size=len(datos),
                   is_default=is_default or not hay_otro)
    db.add(d)
    db.flush()
    if d.is_default:
        _unico_por_defecto(db, d)
    return _doc_out(d)


def _unico_por_defecto(db: Session, d: m.Document) -> None:
    for o in db.scalars(select(m.Document).where(m.Document.user_id == d.user_id, m.Document.kind == d.kind,
                                                 m.Document.language == d.language, m.Document.id != d.id)):
        o.is_default = False


class DocumentPatch(BaseModel):
    label: str | None = None
    language: str | None = Field(default=None, pattern=r"^([a-z]{2})?$")
    is_default: bool | None = None


def _own_doc(db: Session, user_id: int, doc_id: int) -> m.Document:
    d = db.get(m.Document, doc_id)
    if d is None or d.user_id != user_id:
        raise not_found("Documento")
    return d


@router.patch("/documents/{doc_id}", response_model=DocumentOut, summary="Editar un documento")
def update_document(doc_id: int, data: DocumentPatch, user: m.User = Depends(current_user),
                    db: Session = Depends(get_db)):
    d = _own_doc(db, user.id, doc_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(d, k, v)
    if d.is_default:
        _unico_por_defecto(db, d)
    return _doc_out(d)


@router.get("/documents/{doc_id}/file", summary="Descargar un documento")
def download_document(doc_id: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    d = _own_doc(db, user.id, doc_id)
    return Response(storage.read(d.storage_key), media_type=d.mime,
                    headers={"Content-Disposition": f'attachment; filename="{d.filename}"'})


@router.delete("/documents/{doc_id}", status_code=204, summary="Borrar un documento")
def delete_document(doc_id: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    d = _own_doc(db, user.id, doc_id)
    storage.delete(d.storage_key)
    db.delete(d)


# ------------------------------------------------------------------------------------- banco de respuestas

class AnswerIn(BaseModel):
    value: Any
    language: str = Field(default="", pattern=r"^([a-z]{2})?$", description="'' = vale para todos los idiomas")


@router.get("/answers", summary="Banco de respuestas: claves disponibles (globales + del pack) y mis valores")
def list_answers(user: m.User = Depends(current_user), profile: m.Profile = Depends(current_profile),
                 db: Session = Depends(get_db)):
    pack = pack_or_default(profile.pack)
    mias: dict[str, dict] = {}
    for a in db.scalars(select(m.Answer).where(m.Answer.user_id == user.id)):
        mias.setdefault(a.key, {})[a.language or "*"] = a.value
    return [{"key": k.key, "label": k.label, "type": k.type, "options": k.options, "sensitive": is_sensitive(k.key),
             "values": mias.get(k.key, {})} for k in answer_keys_for(pack)]


@router.put("/answers/{key}", summary="Guardar una respuesta del banco")
def put_answer(key: str, data: AnswerIn, user: m.User = Depends(current_user),
               profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    claves = {k.key for k in answer_keys_for(pack_or_default(profile.pack))}
    if key not in claves:
        raise ApiError(422, "unknown_key", f"Clave desconocida: {key}. Para preguntas libres usa /me/custom-answers")
    a = db.scalar(select(m.Answer).where(m.Answer.user_id == user.id, m.Answer.key == key,
                                         m.Answer.language == data.language))
    if a is None:
        a = m.Answer(user_id=user.id, key=key, language=data.language)
        db.add(a)
    a.value = data.value
    return {"key": key, "language": data.language, "value": a.value}


@router.delete("/answers/{key}", status_code=204, summary="Borrar una respuesta del banco")
def delete_answer(key: str, language: str = "", user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(delete(m.Answer).where(m.Answer.user_id == user.id, m.Answer.key == key, m.Answer.language == language))


class CustomAnswerIn(BaseModel):
    label: str = Field(min_length=2, max_length=1000, description="La pregunta tal como aparece")
    value: Any


@router.get("/custom-answers", summary="Respuestas a preguntas libres (sin clave canónica)")
def list_custom(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": c.id, "label": c.label, "value": c.value}
            for c in db.scalars(select(m.CustomAnswer).where(m.CustomAnswer.user_id == user.id)
                                .order_by(m.CustomAnswer.id))]


@router.put("/custom-answers", summary="Guardar (o actualizar) la respuesta a una pregunta libre")
def put_custom(data: CustomAnswerIn, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    ln = norm(data.label)[:400]
    c = db.scalar(select(m.CustomAnswer).where(m.CustomAnswer.user_id == user.id, m.CustomAnswer.label_norm == ln))
    if c is None:
        c = m.CustomAnswer(user_id=user.id, label=data.label, label_norm=ln)
        db.add(c)
    c.value = data.value
    db.flush()
    return {"id": c.id, "label": c.label, "value": c.value}


@router.delete("/custom-answers/{cid}", status_code=204, summary="Borrar una respuesta libre")
def delete_custom(cid: int, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(delete(m.CustomAnswer).where(m.CustomAnswer.user_id == user.id, m.CustomAnswer.id == cid))


# ------------------------------------------------------------------------------------- plantillas

Kind = Literal["email", "cover_letter", "followup"]
Audience = Literal["company", "agency", "job"]


class TemplateIn(BaseModel):
    subject: str = Field(default="", max_length=300)
    body: str = Field(min_length=1, max_length=20000)


class PreviewIn(BaseModel):
    kind: Kind = "email"
    audience: Audience = "company"
    language: str = Field(default="es", pattern=r"^[a-z]{2}$")
    subject: str | None = Field(default=None, description="Texto a probar; si falta, la plantilla guardada")
    body: str | None = None
    company_name: str = "Empresa de Ejemplo"
    job_title: str = ""
    city: str = ""


@router.get("/templates", summary="Plantillas efectivas (mías o del pack) para cada tipo, audiencia e idioma")
def list_templates(user: m.User = Depends(current_user), profile: m.Profile = Depends(current_profile),
                   db: Session = Depends(get_db)):
    pack = pack_or_default(profile.pack)
    out = []
    for kind in KINDS:
        for aud in AUDIENCES:
            for lang in pack.languages:
                tpl, source = effective_template(db, user.id, pack, kind, aud, lang)
                if tpl:
                    out.append({"kind": kind, "audience": aud, "language": lang, "subject": tpl.subject,
                                "body": tpl.body, "source": source})
    return {"variables": ["nombre", "nombre_pila", "apellidos", "email", "telefono", "linkedin", "web", "empresa",
                          "puesto", "ciudad", "pais", "sector", "asunto"] + [f.key for f in pack.profile_fields],
            "templates": out}


@router.put("/templates/{kind}/{audience}/{language}", summary="Guardar mi versión de una plantilla")
def put_template(kind: Kind, audience: Audience, language: str, data: TemplateIn,
                 user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    t = db.scalar(select(m.Template).where(m.Template.user_id == user.id, m.Template.kind == kind,
                                           m.Template.audience == audience, m.Template.language == language))
    if t is None:
        t = m.Template(user_id=user.id, kind=kind, audience=audience, language=language)
        db.add(t)
    t.subject, t.body = data.subject, data.body
    return {"kind": kind, "audience": audience, "language": language, "subject": t.subject, "body": t.body,
            "source": "user"}


@router.delete("/templates/{kind}/{audience}/{language}", status_code=204,
               summary="Volver a la plantilla del pack")
def reset_template(kind: Kind, audience: Audience, language: str, user: m.User = Depends(current_user),
                   db: Session = Depends(get_db)):
    db.execute(delete(m.Template).where(m.Template.user_id == user.id, m.Template.kind == kind,
                                        m.Template.audience == audience, m.Template.language == language))


@router.post("/templates/preview", summary="Vista previa con mis datos (marca las variables vacías)")
def preview_template(data: PreviewIn, user: m.User = Depends(current_user),
                     profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    pack = pack_or_default(profile.pack)
    tpl, _ = effective_template(db, user.id, pack, data.kind, data.audience, data.language)
    subject = data.subject if data.subject is not None else (tpl.subject if tpl else "")
    body = data.body if data.body is not None else (tpl.body if tpl else "")
    vals = template_values(profile_dict(profile), data.language, [f.key for f in pack.profile_fields],
                           company={"name": data.company_name, "city": data.city},
                           job={"title": data.job_title} if data.job_title else None,
                           extra={"asunto": "(asunto original)"})
    r = render(subject, body, vals, data.language)
    return {"subject": r.subject, "body": r.body, "missing": r.missing, "blocking": blocking_missing(r.missing)}
