"""Nichos: los de knok (packs) y los que crea cada usuario para buscar en cualquier sector."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from knok.api.deps import ApiError, current_profile, current_user, get_db, not_found
from knok.db import models as m
from knok.packs.custom import NicheSpec
from knok.packs.sectors import catalog
from knok.services import niches as svc

router = APIRouter(tags=["packs"])


class NicheIn(NicheSpec):
    activate: bool = True


class ActivateIn(BaseModel):
    slug: str


@router.get("/niches/sectors", summary="Sectores para crear un nicho (qué empresas se buscan en OpenStreetMap)")
def sectors():
    return catalog()


@router.get("/me/niches", summary="Mis nichos")
def my_niches(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return [svc.out(n) for n in svc.list_for(db, user.id)]


def _own(db: Session, user_id: int, slug: str) -> m.Niche:
    n = db.scalar(select(m.Niche).where(m.Niche.slug == slug, m.Niche.user_id == user_id))
    if n is None:
        raise not_found("Nicho")
    return n


def _check(data: NicheSpec) -> None:
    if not data.sectors and not data.job_titles and not data.directories and not data.osm_extra:
        raise ApiError(422, "empty_niche", "Elige al menos un sector o escribe algún puesto que buscas")


@router.post("/me/niches", status_code=201, summary="Crear un nicho propio (y usarlo)")
def create_niche(data: NicheIn, profile: m.Profile = Depends(current_profile), db: Session = Depends(get_db)):
    _check(data)
    if len(svc.list_for(db, profile.user_id)) >= 30:
        raise ApiError(422, "too_many", "Tienes demasiados nichos: borra alguno")
    n = svc.create(db, profile, NicheSpec.model_validate(data.model_dump(exclude={"activate"})), data.activate)
    return svc.out(n)


@router.put("/me/niches/{slug}", summary="Editar un nicho propio")
def update_niche(slug: str, data: NicheSpec, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    _check(data)
    return svc.out(svc.update(db, _own(db, user.id, slug), data))


@router.delete("/me/niches/{slug}", status_code=204, summary="Borrar un nicho propio")
def delete_niche(slug: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    svc.delete(db, _own(db, user.id, slug))
