"""¿A qué plataforma apunta una URL de solicitud? (ATS de empresa o portal de empleo)

Cada plataforma declara:
  kind              ats (formulario de la empresa) | portal (LinkedIn, Indeed, InfoJobs…)
  phase             fase del plan en la que se soporta
  extension         la extensión tiene adaptador para rellenar su formulario
  api_apply         se puede preparar la candidatura por API oficial
  autofill_allowed  False = sus condiciones prohíben automatizar (Indeed Apply): solo enlace manual
"""
import re
import urllib.parse
from dataclasses import dataclass


@dataclass(frozen=True)
class Platform:
    name: str
    kind: str
    phase: int
    extension: bool = False
    api_apply: bool = False
    autofill_allowed: bool = True
    public_api: bool = False      # tiene API pública de ofertas sin clave (para el catálogo de slugs)


PLATFORMS: dict[str, Platform] = {p.name: p for p in [
    Platform("greenhouse", "ats", 1, extension=True, public_api=True),
    Platform("lever", "ats", 1, extension=True, public_api=True),
    Platform("ashby", "ats", 1, extension=True, public_api=True),
    Platform("workday", "ats", 2),
    Platform("smartrecruiters", "ats", 2, extension=True, public_api=True),
    Platform("recruitee", "ats", 2, extension=True, public_api=True),
    Platform("teamtailor", "ats", 2, extension=True),
    Platform("personio", "ats", 2, extension=True),
    Platform("workable", "ats", 2, extension=True, public_api=True),
    Platform("linkedin", "portal", 8, extension=True),
    Platform("indeed", "portal", 2, autofill_allowed=False),
    Platform("infojobs", "portal", 3, api_apply=True),
    Platform("wellfound", "portal", 2, autofill_allowed=False),
    Platform("adzuna", "portal", 3, autofill_allowed=False),
]}


@dataclass(frozen=True)
class AtsRef:
    platform: str
    slug: str = ""
    job_id: str = ""

    @property
    def info(self) -> Platform:
        return PLATFORMS[self.platform]


_SEG = r"([^/?#]+)"
_PATTERNS: list[tuple[str, re.Pattern, tuple[int, int]]] = [
    # (plataforma, regex sobre host+ruta, (grupo del slug, grupo del id))
    ("greenhouse", re.compile(rf"^(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/{_SEG}(?:/jobs/(\d+))?"), (1, 2)),
    ("greenhouse", re.compile(rf"^boards-api\.greenhouse\.io/v1/boards/{_SEG}(?:/jobs/(\d+))?"), (1, 2)),
    ("lever", re.compile(rf"^jobs(?:\.eu)?\.lever\.co/{_SEG}(?:/([0-9a-f-]{{36}}))?"), (1, 2)),
    ("lever", re.compile(rf"^api(?:\.eu)?\.lever\.co/v0/postings/{_SEG}(?:/([0-9a-f-]{{36}}))?"), (1, 2)),
    ("ashby", re.compile(rf"^jobs\.ashbyhq\.com/{_SEG}(?:/([0-9a-f-]{{36}}))?"), (1, 2)),
    ("ashby", re.compile(rf"^api\.ashbyhq\.com/posting-api/job-board/{_SEG}"), (1, 0)),
    ("workday", re.compile(r"^([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/?#]+)(?:/job/[^?#]*_([A-Za-z0-9-]+))?"), (1, 3)),
    ("smartrecruiters", re.compile(rf"^(?:jobs|careers)\.smartrecruiters\.com/{_SEG}(?:/(\d+))?"), (1, 2)),
    ("recruitee", re.compile(r"^([a-z0-9-]+)\.recruitee\.com(?:/o/([^/?#]+))?"), (1, 2)),
    ("teamtailor", re.compile(r"^([a-z0-9-]+)\.teamtailor\.com(?:/jobs/(\d+))?"), (1, 2)),
    ("personio", re.compile(r"^([a-z0-9-]+)\.jobs\.personio\.(?:de|com)(?:/job/(\d+))?"), (1, 2)),
    ("workable", re.compile(rf"^apply\.workable\.com/{_SEG}(?:/j/([A-Z0-9]+))?"), (1, 2)),
    ("linkedin", re.compile(r"^(?:[a-z]{2}\.)?linkedin\.com/jobs/view/(?:[^/?#]*?-)?(\d+)"), (0, 1)),
    ("indeed", re.compile(r"^(?:[a-z]{2}\.)?indeed\.[a-z.]+/.*?(?:jk=|/viewjob/|vjk=)([0-9a-f]+)?"), (0, 1)),
    ("infojobs", re.compile(r"^infojobs\.net/.*?of-i([0-9a-f]+)"), (0, 1)),
    ("wellfound", re.compile(r"^wellfound\.com/(?:company/([^/?#]+)/)?jobs/(\d+)?"), (1, 2)),
    ("adzuna", re.compile(r"^(?:www\.)?adzuna\.[a-z.]+/(?:details|land/ad)/(\d+)"), (0, 1)),
]

# Plataformas cuyos slugs no distinguen mayúsculas (en el resto se conserva tal cual)
_SLUG_MINUSCULAS = {"greenhouse", "lever", "recruitee", "teamtailor", "personio", "workable", "wellfound"}
_NO_SON_SLUG = {"embed", "jobs", "api", "v1", "boards", "careers", "search", "o", "j", "job", "en", "es"}


def detect(url: str) -> AtsRef | None:
    if not url:
        return None
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    p = urllib.parse.urlsplit(url)
    host = (p.hostname or "").lower()
    if host.startswith("www.") and "adzuna" not in host:
        host = host[4:]
    destino = host + p.path

    # Greenhouse incrustado en la web de la empresa: ...?gh_jid=123 / embed/job_app?for=slug&token=123
    q = urllib.parse.parse_qs(p.query)
    if host.endswith("greenhouse.io") and "for" in q:
        return AtsRef("greenhouse", q["for"][0].lower(), (q.get("token") or [""])[0])
    for platform, rx, (g_slug, g_id) in _PATTERNS:
        m = rx.match(destino if platform not in ("indeed", "infojobs") else destino + "?" + p.query)
        if not m:
            continue
        slug = (m.group(g_slug) or "") if g_slug else ""
        job = (m.group(g_id) or "") if g_id else ""
        if platform == "indeed" and not job:
            job = (q.get("jk") or q.get("vjk") or [""])[0]
        if slug.lower() in _NO_SON_SLUG:
            slug = ""
        if PLATFORMS[platform].kind == "ats" and not slug:
            continue
        return AtsRef(platform, slug.lower() if platform in _SLUG_MINUSCULAS else slug, job)
    return None


def board_api_url(ref: AtsRef) -> str:
    """URL de la API pública de ofertas de un tablero (si la hay)."""
    return {
        "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{ref.slug}/jobs?content=true",
        "lever": f"https://api.lever.co/v0/postings/{ref.slug}?mode=json",
        "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{ref.slug}?includeCompensation=true",
    }.get(ref.platform, "")
