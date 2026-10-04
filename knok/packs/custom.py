"""Nichos propios: el usuario describe su nicho en el panel y knok lo convierte en un pack.

Qué pide el panel (NicheSpec) y en qué se convierte:
  sectores            → etiquetas de OpenStreetMap (empresas alrededor de las ciudades) y buzones típicos
  puestos             → qué ofertas son del nicho (título y descripción) y qué se busca en Adzuna / InfoJobs
  términos            → qué se detecta en las webs de las empresas («prácticas», «junior»…) y da puntos
  buzones preferidos  → a qué buzón genérico escribir primero (empleo@, practicas@…)
  directorios         → listados de empresas (webs o PDF) de donde sacar webs y correos
Las plantillas de correo son las genéricas de knok/packs/_base (el usuario las edita en el panel).
"""
import re
import threading
import time

from pydantic import BaseModel, Field, field_validator

from knok.core.text import strip_accents
from knok.packs.schema import (CrawlCfg, DirectoryCfg, MatchCfg, Mention, OsmCfg, Pack, ProfileField, SourcesCfg,
                               AdzunaCfg, InfojobsCfg)
from knok.packs.sectors import BY_ID

PREFIX = "n-"
TTL = 30.0                                    # segundos que se recuerda un nicho leído de la base de datos
GENERIC_CAREER_PAGES = ["empleo", "trabaja", "trabaja-con-nosotros", "unete", "careers", "career", "jobs", "join-us",
                        "work-with-us", "karriere", "emploi", "lavora", "vacantes", "ofertas", "rrhh", "talento"]
GENERIC_MAILBOXES = ["empleo", "rrhh", "jobs", "careers", "seleccion", "talento", "hr", "recruiting", "cv"]


def _lista(v, maximo: int, largo: int = 80) -> list[str]:
    if isinstance(v, str):
        v = re.split(r"[,\n]", v)
    out = []
    for x in v or []:
        x = re.sub(r"\s+", " ", str(x)).strip()
        if x and len(x) <= largo and x.lower() not in {o.lower() for o in out}:
            out.append(x)
    return out[:maximo]


class NicheSpec(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=300)
    languages: list[str] = ["es", "en"]
    sectors: list[str] = Field(default=[], description="Ids del catálogo GET /niches/sectors")
    job_titles: list[str] = Field(default=[], description="Puestos u ofertas que buscas (cualquier idioma)")
    exclude_terms: list[str] = Field(default=[], description="Ofertas con estas palabras se descartan")
    mention_terms: list[str] = Field(default=[], description="Qué conviene que diga la web de la empresa")
    mailboxes: list[str] = Field(default=[], description="Buzones preferidos (parte antes de la @)")
    default_countries: list[str] = ["es"]
    directories: list[str] = Field(default=[], description="Listados de empresas: URL de una web o un PDF")
    osm_extra: list[str] = Field(default=[], description="Avanzado: etiquetas OSM 'clave=valor'")

    @field_validator("job_titles", "exclude_terms", "mention_terms", mode="before")
    @classmethod
    def _terminos(cls, v):
        return _lista(v, 40)

    @field_validator("mailboxes", mode="before")
    @classmethod
    def _buzones(cls, v):
        return [b.lower().split("@")[0] for b in _lista(v, 20, 40) if re.fullmatch(r"[a-z0-9._+-]+", b.lower().split("@")[0])]

    @field_validator("default_countries", mode="before")
    @classmethod
    def _paises(cls, v):
        return [p.lower() for p in _lista(v, 60, 2) if re.fullmatch(r"[a-zA-Z]{2}", p)]

    @field_validator("languages", mode="before")
    @classmethod
    def _idiomas(cls, v):
        return [i.lower() for i in _lista(v, 4, 2) if i.lower() in ("es", "en")] or ["es", "en"]

    @field_validator("directories", mode="before")
    @classmethod
    def _directorios(cls, v):
        return [u for u in _lista(v, 20, 500) if re.match(r"https?://[^\s/]+\.[^\s]+$", u)]

    @field_validator("osm_extra", mode="before")
    @classmethod
    def _osm(cls, v):
        return [t for t in _lista(v, 20) if re.fullmatch(r"[a-z_:]+=[a-z0-9_;:-]+", t)]

    @field_validator("sectors", mode="before")
    @classmethod
    def _sectores(cls, v):
        return [s for s in _lista(v, 30) if s in BY_ID]


def _variante(t: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(t).lower()).strip()


def build_pack(slug: str, spec: NicheSpec) -> Pack:
    from knok.packs.loader import base_templates
    tags: dict[str, list[str]] = {}
    etiquetas: dict[str, str] = {}
    agencias: list[str] = []
    buzones = list(spec.mailboxes)
    for sid in spec.sectors:
        s = BY_ID[sid]
        for k, vals in s.osm.items():
            tags.setdefault(k, [])
            tags[k] += [v for v in vals if v not in tags[k]]
            if s.agency:
                agencias += [f"{k}={v}" for v in vals]
        etiquetas.update(s.labels)
        buzones += [b for b in s.mailboxes if b not in buzones]
    for t in spec.osm_extra:
        k, v = t.split("=", 1)
        tags.setdefault(k, [])
        if v not in tags[k]:
            tags[k].append(v)
    for b in GENERIC_MAILBOXES:
        if b not in buzones:
            buzones.append(b)
    terminos = spec.mention_terms
    paginas = [re.sub(r"[^a-z0-9]+", "-", _variante(t)).strip("-") for t in terms_for_pages(terminos)]
    return Pack(
        slug=slug, names={"es": spec.name, "en": spec.name}, description={"es": spec.description, "en": spec.description},
        languages=spec.languages,
        profile_fields=[ProfileField(key="titulacion", label={"es": "Titulación / formación", "en": "Degree / training"},
                                     localized=True),
                        ProfileField(key="experiencia", label={"es": "Experiencia en una frase", "en": "Experience in one line"},
                                     localized=True)],
        sources=SourcesCfg(default_countries=spec.default_countries,
                           directories=[DirectoryCfg(url=u) for u in spec.directories],
                           osm=OsmCfg(tags=tags, agency_tags=agencias, sector_labels=etiquetas),
                           adzuna=AdzunaCfg(what=spec.job_titles[:5]), infojobs=InfojobsCfg(q=spec.job_titles[:5])),
        crawl=CrawlCfg(page_keywords=[p for p in paginas if p] + GENERIC_CAREER_PAGES,
                       mailbox_priority=buzones, extra_generic=buzones,
                       mentions=[Mention(label=t, variants=[_variante(t)]) for t in terminos]),
        match=MatchCfg(title_keywords={"*": spec.job_titles}, keywords={"*": spec.mention_terms},
                       negative=[_variante(t) for t in spec.exclude_terms]),
        templates=base_templates(),
    )


def terms_for_pages(terminos: list[str]) -> list[str]:
    """Términos cortos que pueden aparecer en la dirección de una página (/practicas, /junior…)."""
    return [t for t in terminos if len(t.split()) <= 2][:10]


# ------------------------------------------------------------------------------------- registro

_cache: dict[str, tuple[float, Pack | None]] = {}
_lock = threading.Lock()


def remember(slug: str, spec: dict | NicheSpec) -> Pack:
    pack = build_pack(slug, spec if isinstance(spec, NicheSpec) else NicheSpec.model_validate(spec))
    with _lock:
        _cache[slug] = (time.monotonic(), pack)
    return pack


def forget(slug: str) -> None:
    with _lock:
        _cache[slug] = (time.monotonic(), None)


def lookup(slug: str) -> Pack | None:
    """Pack de un nicho propio. Lo recuerda unos segundos (la API y el worker pueden ser procesos distintos)."""
    if not slug.startswith(PREFIX):
        return None
    with _lock:
        hit = _cache.get(slug)
    if hit and time.monotonic() - hit[0] < TTL:
        return hit[1]
    from sqlalchemy import select

    from knok.db import session as dbs
    from knok.db.models import Niche
    with dbs.engine().connect() as c:
        spec = c.execute(select(Niche.spec).where(Niche.slug == slug)).scalar()
    if spec is None:
        forget(slug)
        return hit[1] if hit else None
    return remember(slug, spec)
