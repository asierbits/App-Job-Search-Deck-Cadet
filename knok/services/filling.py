"""Relleno con datos del usuario y aprendizaje:
  - las preguntas que el motor no reconoce se guardan en `unknown_questions` (para ampliar el diccionario);
  - lo que el usuario contesta en la revisión se recuerda en su banco (custom_answers);
  - el admin puede asignar una pregunta nueva a una clave → patrón aprendido para todos.
"""
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from knok.core.filling.engine import FillContext, FormField, fill
from knok.core.filling.matcher import Pattern, pack_patterns
from knok.core.text import norm
from knok.db.models import Answer, CustomAnswer, Document, Profile, QuestionPattern, UnknownQuestion, utcnow
from knok.packs.loader import pack_or_default
from knok.services.templates import profile_dict


def learned_patterns(db: Session, pack_slug: str) -> list[Pattern]:
    q = select(QuestionPattern).where(or_(QuestionPattern.pack == "", QuestionPattern.pack == pack_slug))
    return [Pattern(p.key, norm(p.pattern), len(norm(p.pattern).split()), p.weight) for p in db.scalars(q)]


def build_context(db: Session, profile: Profile, language: str, job_country: str = "", cover_letter: str = "") -> FillContext:
    pack = pack_or_default(profile.pack)
    respuestas: dict[str, dict] = {}
    for a in db.scalars(select(Answer).where(Answer.user_id == profile.user_id)):
        respuestas.setdefault(a.key, {})[a.language or "*"] = a.value
    custom = {c.label_norm: c.value for c in db.scalars(select(CustomAnswer).where(CustomAnswer.user_id == profile.user_id))}
    docs: dict[str, list] = {}
    for d in db.scalars(select(Document).where(Document.user_id == profile.user_id)):
        docs.setdefault(d.kind, []).append({"id": d.id, "filename": d.filename, "language": d.language,
                                            "is_default": d.is_default})
    return FillContext(profile=profile_dict(profile), language=language, answers=respuestas, custom=custom,
                       documents=docs, cover_letter=cover_letter, job_country=job_country,
                       patterns=pack_patterns(pack) + learned_patterns(db, pack.slug))


def fill_form(db: Session, profile: Profile, fields: list[dict], language: str, job_country: str = "",
              cover_letter: str = "", platform: str = "") -> dict:
    ctx = build_context(db, profile, language, job_country, cover_letter)
    res = fill([FormField.from_dict(f) for f in fields], ctx)
    record_unknown(db, profile.pack, language, platform,
                   [f for f in res["fields"] if f["key"] is None and f["origin"] != "custom"])
    return res


def record_unknown(db: Session, pack: str, language: str, platform: str, campos: list[dict]) -> None:
    for c in campos:
        ln = norm(c["label"])[:400]
        if len(ln) < 3:
            continue
        u = db.scalar(select(UnknownQuestion).where(UnknownQuestion.label_norm == ln, UnknownQuestion.pack == pack))
        if u is None:
            db.add(UnknownQuestion(label=c["label"][:2000], label_norm=ln, pack=pack, language=language,
                                   field_type=c.get("type", "text"), options=c.get("options") or [],
                                   platforms=[platform] if platform else []))
            db.flush()
        else:
            u.times_seen += 1
            u.last_seen_at = utcnow()
            if platform and platform not in (u.platforms or []):
                u.platforms = list(u.platforms or []) + [platform]


def remember_answer(db: Session, user_id: int, label: str, value) -> None:
    ln = norm(label)[:400]
    if not ln or value in (None, ""):
        return
    c = db.scalar(select(CustomAnswer).where(CustomAnswer.user_id == user_id, CustomAnswer.label_norm == ln))
    if c is None:
        db.add(CustomAnswer(user_id=user_id, label=label[:1000], label_norm=ln, value=value))
    else:
        c.value = value
