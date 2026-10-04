"""Packs de nicho (lectura pública: tu web los usa para el selector de nicho y los formularios)."""
from fastapi import APIRouter

from knok.api.deps import ApiError
from knok.core.filling.fields import is_sensitive
from knok.packs.loader import PackError, all_packs, answer_keys_for, get_pack

router = APIRouter(prefix="/packs", tags=["packs"])


@router.get("", summary="Packs disponibles")
def list_packs():
    return [{"slug": p.slug, "version": p.version, "names": p.names, "description": p.description,
             "languages": p.languages} for p in all_packs().values()]


@router.get("/{slug}", summary="Detalle de un pack: campos del perfil, banco de respuestas y fuentes")
def pack_detail(slug: str):
    try:
        p = get_pack(slug)
    except PackError as ex:
        raise ApiError(404, "not_found", str(ex))
    return {
        "slug": p.slug, "version": p.version, "names": p.names, "description": p.description,
        "languages": p.languages,
        "profile_fields": [f.model_dump() for f in p.profile_fields],
        "answer_keys": [{"key": k.key, "label": k.label, "type": k.type, "options": k.options,
                         "sensitive": is_sensitive(k.key)} for k in answer_keys_for(p)],
        "sources": {
            "default_countries": p.sources.default_countries,
            "wikidata": bool(p.sources.wikidata.queries),
            "directories": [d.url for d in p.sources.directories],
            "osm": bool(p.sources.osm.tags),
            "adzuna": p.sources.adzuna.what,
            "infojobs": p.sources.infojobs.q,
        },
        "templates": sorted(p.templates),
    }
