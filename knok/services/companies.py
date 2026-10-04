"""Consultas sobre empresas de la base común."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from knok.core.emails.score import MailboxRules, best
from knok.db.models import Company, CompanyEmail
from knok.packs.schema import Pack


def best_emails(db: Session, company: Company | None, pack: Pack | None) -> list[str]:
    if company is None:
        return []
    filas = db.execute(select(CompanyEmail.email, CompanyEmail.on_careers_page)
                       .where(CompanyEmail.company_id == company.id)).all()
    return best([(e, c) for e, c in filas], company.domain or "", MailboxRules.for_pack(pack))


def company_summary(c: Company | None) -> dict | None:
    if c is None:
        return None
    return {"id": c.id, "name": c.name, "domain": c.domain, "country": c.country, "city": c.city, "sector": c.sector,
            "kind": c.kind, "website": c.website, "careers_url": c.careers_url, "flags": c.flags or {}}
