"""Nichos del usuario: crear, editar, borrar y comprobar que un pack se puede usar."""
import re
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from knok.db.models import Niche, Profile
from knok.packs import custom
from knok.packs.loader import all_packs
from knok.packs.sectors import BY_ID


def pack_allowed(db: Session, slug: str | None, user_id: int) -> bool:
    """Los packs de knok son de todos; un nicho propio, solo de quien lo creó."""
    if not slug:
        return False
    if slug in all_packs():
        return True
    return db.scalar(select(Niche.id).where(Niche.slug == slug, Niche.user_id == user_id)) is not None


def _slug(nombre: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", custom._variante(nombre)).strip("-")[:30] or "nicho"
    return f"{custom.PREFIX}{base}-{secrets.token_hex(3)}"


def out(n: Niche) -> dict:
    spec = custom.NicheSpec.model_validate(n.spec)
    pack = custom.lookup(n.slug) or custom.remember(n.slug, spec)
    return {"slug": n.slug, "name": n.name, "spec": spec.model_dump(),
            "sector_labels": [BY_ID[s].es for s in spec.sectors],
            "summary": {"osm_tags": sum(len(v) for v in pack.sources.osm.tags.values()),
                        "job_titles": len(spec.job_titles), "mentions": len(spec.mention_terms),
                        "directories": len(spec.directories)},
            "updated_at": n.updated_at.isoformat() if n.updated_at else None}


def list_for(db: Session, user_id: int) -> list[Niche]:
    return list(db.scalars(select(Niche).where(Niche.user_id == user_id).order_by(Niche.id)))


def create(db: Session, profile: Profile, spec: custom.NicheSpec, activate: bool = True) -> Niche:
    n = Niche(user_id=profile.user_id, slug=_slug(spec.name), name=spec.name, spec=spec.model_dump())
    db.add(n)
    db.flush()
    custom.remember(n.slug, spec)
    if activate:
        profile.pack = n.slug
    return n


def update(db: Session, n: Niche, spec: custom.NicheSpec) -> Niche:
    n.name, n.spec = spec.name, spec.model_dump()
    db.flush()
    custom.remember(n.slug, spec)
    return n


def delete(db: Session, n: Niche) -> None:
    for p in db.scalars(select(Profile).where(Profile.pack == n.slug)):
        p.pack = "general"
    custom.forget(n.slug)
    db.delete(n)
