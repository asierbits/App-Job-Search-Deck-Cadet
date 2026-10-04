"""Lo que produce cualquier fuente: ofertas (RawJob) y empresas sin oferta (RawCompany)."""
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class RawJob:
    source: str                       # greenhouse | lever | ashby | adzuna | infojobs | capture | sample
    source_job_id: str
    title: str
    company_name: str = ""
    company_domain: str = ""
    company_website: str = ""
    city: str = ""
    country: str = ""
    remote: bool = False
    description: str = ""             # texto plano
    url: str = ""                     # página de la oferta
    apply_url: str = ""
    apply_email: str = ""
    easy_apply: bool = False
    posted_at: datetime | None = None
    salary: str = ""
    language: str = ""
    questions: list = field(default_factory=list)   # [{id,label,type,required,options:[{label,value}]}]
    ats: str = ""                     # si la fuente es un ATS: cuál y su slug
    ats_slug: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class RawCompany:
    name: str
    source: str
    domain: str = ""
    website: str = ""
    email: str = ""
    email_source_url: str = ""
    country: str = ""
    city: str = ""
    sector: str = ""
    kind: str = "company"             # company | agency | institution
    phone: str = ""
    wikidata_id: str = ""
    osm_ref: str = ""
    careers_url: str = ""


def parse_dt(valor) -> datetime | None:
    """ISO 8601, epoch en ms o en s → datetime con zona UTC."""
    if valor in (None, ""):
        return None
    try:
        if isinstance(valor, (int, float)):
            seg = valor / 1000 if valor > 10_000_000_000 else valor
            return datetime.fromtimestamp(seg, tz=timezone.utc)
        v = str(valor).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None
