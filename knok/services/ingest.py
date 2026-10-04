"""Ingesta en la base común: empresas (por dominio), buzones genéricos, ofertas, catálogo de ATS y duplicados.

Reglas:
  - Una empresa se identifica por su dominio registrable; si no se conoce, por nombre normalizado + país.
  - Solo se guardan buzones GENÉRICOS y del propio dominio de la empresa.
  - Cada oferta calcula su huella (empresa + puesto + ciudad); entre las que comparten huella se marca
    como original la de la empresa (ATS) y las demás apuntan a ella (canonical_job_id).
  - Un enlace de solicitud que apunta a un ATS con API pública añade ese tablero al catálogo.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from knok.core.cleaning.dedupe import Candidate, pick_original
from knok.core.cleaning.normalize import company_key_name, fingerprint, title_key
from knok.core.domains import FREE_PROVIDERS, domain_of, is_company_site, pretty_name
from knok.core.emails.generic import is_generic
from knok.core.sources.ats.detect import PLATFORMS, detect
from knok.core.sources.base import RawCompany, RawJob
from knok.db.models import AtsBoard, Company, CompanyEmail, Job, utcnow


def pack_roles(pack_slug: str) -> frozenset[str]:
    """Buzones de rol propios del nicho (los que defina cada pack) que también cuentan como genéricos."""
    from knok.packs.loader import all_packs
    p = all_packs().get(pack_slug)
    return frozenset(p.crawl.extra_generic + p.crawl.mailbox_priority) if p else frozenset()


def _add_unique(lista: list | None, valor: str) -> list:
    lista = list(lista or [])
    if valor and valor not in lista:
        lista.append(valor)
    return lista


def find_company(db: Session, domain: str = "", name: str = "", country: str = "") -> Company | None:
    if domain:
        c = db.scalar(select(Company).where(Company.domain == domain))
        if c:
            return c
    if name:
        q = select(Company).where(Company.name_norm == company_key_name(name))
        if country:
            q = q.where(Company.country.in_((country, "")))
        return db.scalars(q.limit(1)).first()
    return None


def upsert_company(db: Session, raw: RawCompany, pack: str = "") -> Company:
    web = raw.website if raw.website and is_company_site(raw.website) else ""
    dom = raw.domain or domain_of(web)
    if not dom and raw.email:
        d = domain_of(raw.email)
        dom = d if d and d not in FREE_PROVIDERS else ""
    nombre = (raw.name or "").strip() or pretty_name(dom)
    c = find_company(db, dom, nombre, raw.country)
    if c is None:
        c = Company(name=nombre[:300], name_norm=company_key_name(nombre), domain=dom or None,
                    country=raw.country or "", city=raw.city or "", sector=raw.sector or "", kind=raw.kind,
                    website=web or (f"https://{dom}/" if dom else ""), careers_url=raw.careers_url or "",
                    phone=raw.phone or "", wikidata_id=raw.wikidata_id or "", osm_ref=raw.osm_ref or "",
                    packs=[pack] if pack else [], sources=[raw.source] if raw.source else [], flags={})
        db.add(c)
        db.flush()
    else:
        if not c.domain and dom and not db.scalar(select(Company.id).where(Company.domain == dom)):
            c.domain = dom
        # completar lo que falte; el nombre "bonito" sacado del dominio se sustituye por uno real
        if raw.name and c.name == pretty_name(c.domain or "") and raw.name != pretty_name(dom):
            c.name, c.name_norm = raw.name[:300], company_key_name(raw.name)
        for campo in ("country", "city", "sector", "phone", "wikidata_id", "osm_ref", "careers_url"):
            v = getattr(raw, campo, "")
            if v and not getattr(c, campo):
                setattr(c, campo, v)
        if web and not c.website:
            c.website = web
        if raw.kind != "company" and c.kind == "company":
            c.kind = raw.kind
        c.packs = _add_unique(c.packs, pack)
        c.sources = _add_unique(c.sources, raw.source)
    if raw.email:
        add_company_email(db, c, raw.email, raw.email_source_url, raw.source, extra_roles=pack_roles(pack))
    return c


def add_company_email(db: Session, c: Company, email: str, found_on_url: str = "", source: str = "",
                      on_careers_page: bool = False, extra_roles: frozenset[str] = frozenset()) -> CompanyEmail | None:
    """Guarda un buzón solo si es genérico y del dominio de la empresa. Devuelve None si se descarta."""
    email = (email or "").strip().lower()
    if not email or not is_generic(email, extra_roles):
        return None
    d = domain_of(email)
    if c.domain and d != c.domain and d.split(".")[0] != c.domain.split(".")[0]:
        return None   # buzón de otra empresa (la agencia que hizo la web, un proveedor…)
    if d in FREE_PROVIDERS:
        return None   # info@gmail.com no identifica a la empresa con seguridad
    ce = db.scalar(select(CompanyEmail).where(CompanyEmail.email == email))
    if ce is None:
        ce = CompanyEmail(company_id=c.id, email=email, local_part=email.split("@")[0], found_on_url=found_on_url or "",
                          source=source, on_careers_page=on_careers_page)
        db.add(ce)
        db.flush()
    else:
        ce.last_seen_at = utcnow()
        ce.on_careers_page = ce.on_careers_page or on_careers_page
    return ce


def register_board(db: Session, ats: str, slug: str, company: Company | None, discovered_from: str) -> AtsBoard | None:
    if not slug or ats not in PLATFORMS or not PLATFORMS[ats].public_api:
        return None
    b = db.scalar(select(AtsBoard).where(AtsBoard.ats == ats, AtsBoard.slug == slug))
    if b is None:
        b = AtsBoard(ats=ats, slug=slug, company_id=company.id if company else None, discovered_from=discovered_from)
        db.add(b)
        db.flush()
    elif company and not b.company_id:
        b.company_id = company.id
    return b


def upsert_job(db: Session, raw: RawJob, pack: str = "") -> Job:
    ref = detect(raw.apply_url or raw.url)
    # Empresa: por la fuente ATS (tablero ya catalogado), por dominio o por nombre
    company = None
    if raw.ats and raw.ats_slug:
        b = db.scalar(select(AtsBoard).where(AtsBoard.ats == raw.ats, AtsBoard.slug == raw.ats_slug))
        if b and b.company_id:
            company = db.get(Company, b.company_id)
    dom = raw.company_domain or domain_of(raw.company_website)
    if company is None and (dom or raw.company_name):
        company = upsert_company(db, RawCompany(name=raw.company_name, source=raw.source, domain=dom,
                                                website=raw.company_website, country=raw.country), pack)
    elif company is not None:
        company.packs = _add_unique(company.packs, pack)
    if raw.apply_email and company is not None:
        add_company_email(db, company, raw.apply_email, raw.url, raw.source, on_careers_page=True,
                          extra_roles=pack_roles(pack))

    if raw.source != "sample":  # los datos de ejemplo no ensucian el catálogo real
        if raw.ats and raw.ats_slug:
            register_board(db, raw.ats, raw.ats_slug, company, raw.source)
        elif ref and ref.slug:
            register_board(db, ref.platform, ref.slug, company, raw.source)

    j = db.scalar(select(Job).where(Job.source == raw.source, Job.source_job_id == raw.source_job_id))
    # La huella usa la empresa ya identificada (id), así coinciden copias de fuentes distintas
    fp = fingerprint(f"c{company.id}" if company else "", raw.company_name, raw.title, raw.city, raw.remote)
    valores = dict(
        company_id=company.id if company else None, company_name=(raw.company_name or (company.name if company else ""))[:300],
        title=raw.title[:400], title_norm=title_key(raw.title)[:400], city=raw.city[:160], country=raw.country or "",
        remote=raw.remote, language=raw.language, description=raw.description, url=raw.url, apply_url=raw.apply_url,
        apply_platform=ref.platform if ref else ("email" if raw.apply_email else ""),
        apply_email=raw.apply_email if raw.apply_email and is_generic(raw.apply_email, pack_roles(pack)) else "",
        easy_apply=raw.easy_apply, salary=raw.salary[:120], fingerprint=fp, raw=raw.raw,
        posted_at=raw.posted_at,
    )
    if raw.questions:
        valores["questions"] = raw.questions
    anterior_fp = None
    if j is None:
        j = Job(source=raw.source, source_job_id=raw.source_job_id, **valores)
        db.add(j)
    else:
        anterior_fp = j.fingerprint
        for k, v in valores.items():
            if v not in (None, "") or k in ("remote", "easy_apply"):
                setattr(j, k, v)
        j.last_seen_at, j.closed_at = utcnow(), None
    db.flush()
    recompute_canonical(db, fp)
    if anterior_fp and anterior_fp != fp:
        recompute_canonical(db, anterior_fp)
    return j


def recompute_canonical(db: Session, fp: str) -> None:
    grupo = list(db.scalars(select(Job).where(Job.fingerprint == fp, Job.closed_at.is_(None))))
    if not grupo:
        return
    original = pick_original([Candidate(j.id, j.source, j.apply_url, len(j.description or ""), j.first_seen_at)
                              for j in grupo])
    for j in grupo:
        j.canonical_job_id = None if j.id == original.id else original.id
    db.flush()


def close_missing(db: Session, source: str, prefix: str, seen_ids: set[str]) -> int:
    """Ofertas de un tablero que ya no aparecen → cerradas (no se borran: pueden tener candidaturas)."""
    n = 0
    for j in db.scalars(select(Job).where(Job.source == source, Job.source_job_id.like(f"{prefix}%"),
                                          Job.closed_at.is_(None))):
        if j.source_job_id not in seen_ids:
            j.closed_at = utcnow()
            n += 1
            if j.fingerprint:
                db.flush()
                recompute_canonical(db, j.fingerprint)
    return n
