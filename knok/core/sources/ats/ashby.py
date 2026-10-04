"""Ashby Job Posting API (pública, sin clave).

  GET https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true
"""
from knok.core.geo import country_from_text, parse_location
from knok.core.http import Http, get_json
from knok.core.sources.base import RawJob, parse_dt
from knok.core.text import html_to_text

API = "https://api.ashbyhq.com/posting-api/job-board"


def parse_jobs(data: dict, slug: str, company_name: str = "") -> list[RawJob]:
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        ciudad, pais, remoto = parse_location(j.get("location") or "")
        direccion = ((j.get("address") or {}).get("postalAddress") or {})
        ciudad = ciudad or direccion.get("addressLocality") or ""
        pais = pais or country_from_text(direccion.get("addressCountry") or "")
        remoto = remoto or bool(j.get("isRemote")) or j.get("workplaceType") == "Remote"
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        out.append(RawJob(
            source="ashby", source_job_id=f"{slug}:{j['id']}", title=(j.get("title") or "").strip(),
            company_name=company_name, city=ciudad, country=pais, remote=remoto,
            description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml") or ""),
            url=j.get("jobUrl") or "", apply_url=j.get("applyUrl") or j.get("jobUrl") or "",
            posted_at=parse_dt(j.get("publishedAt")), salary=comp, ats="ashby", ats_slug=slug,
            raw={"id": j["id"], "department": j.get("department"), "employmentType": j.get("employmentType")},
        ))
    return out


def fetch_board(http: Http, slug: str) -> tuple[str, list[RawJob]]:
    data = get_json(http, f"{API}/{slug}", params={"includeCompensation": "true"})
    return "", parse_jobs(data, slug)
