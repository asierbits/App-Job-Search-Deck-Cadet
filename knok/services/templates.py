"""Plantillas efectivas: las del usuario si las tiene; si no, las del pack."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from knok.core.mail.compose import Rendered, render, template_values
from knok.db.models import Profile, Template
from knok.packs.loader import pack_or_default
from knok.packs.schema import Pack, TemplateText

KINDS = ("email", "cover_letter", "followup")
AUDIENCES = ("company", "agency", "job")


def effective_template(db: Session, user_id: int, pack: Pack, kind: str, audience: str,
                       lang: str) -> tuple[TemplateText | None, str]:
    for aud in dict.fromkeys((audience, "company")):
        t = db.scalar(select(Template).where(Template.user_id == user_id, Template.kind == kind,
                                             Template.audience == aud, Template.language == lang))
        if t is not None:
            return TemplateText(subject=t.subject, body=t.body), "user"
    tpl = pack.template(kind, audience, lang)
    return tpl, "pack" if tpl else "none"


def profile_dict(p: Profile) -> dict:
    return {"first_name": p.first_name, "last_name": p.last_name, "email": p.email, "phone": p.phone,
            "city": p.city, "country": p.country, "links": p.links or {}, "pack_data": p.pack_data or {},
            "languages": p.languages or []}


def render_for(db: Session, profile: Profile, kind: str, audience: str, lang: str, company: dict | None = None,
               job: dict | None = None, extra: dict | None = None) -> Rendered | None:
    pack = pack_or_default(profile.pack)
    tpl, _ = effective_template(db, profile.user_id, pack, kind, audience, lang)
    if tpl is None:
        return None
    vals = template_values(profile_dict(profile), lang, [f.key for f in pack.profile_fields], company, job, extra)
    return render(tpl.subject, tpl.body, vals, lang)
