"""Rastreo de la web de una empresa (portado y generalizado de legacy/core/webemail.py).

Visita la portada y hasta MAX_PAGES páginas del mismo dominio, priorizando las de empleo (las del pack
primero), contacto y aviso legal, respetando robots.txt. Saca:
  - buzones GENÉRICOS del propio dominio (los personales se descartan aquí mismo),
  - la página de empleo y los enlaces a ATS (que alimentan el catálogo de slugs),
  - menciones y señales que define el pack, y avisos (p. ej. cobros a candidatos),
  - el nombre de la empresa según su web.
Si la web bloquea a los programas (401/403/429), se respeta y se marca: nunca se finge ser un navegador.
"""
import html
import re
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass, field

from knok.core.domains import domain_of, host
from knok.core.emails.generic import is_generic
from knok.core.emails.score import MailboxRules, score
from knok.core.http import Http
from knok.core.sources.ats.detect import detect
from knok.core.text import visible_text
from knok.packs.schema import Pack

MAX_PAGES = 8
MAX_SECONDS = 45

RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}")
RE_LINK = re.compile(r"""<a\b[^>]*?href\s*=\s*["']([^"'#]+)["'][^>]*>(.*?)</a>""", re.I | re.S)
RE_CFEMAIL = re.compile(r"""data-cfemail\s*=\s*["']([0-9a-fA-F]+)["']""")
RE_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
RE_SITENAME = re.compile(r"""<meta[^>]+property=["']og:site_name["'][^>]+content=["']([^"']+)["']""", re.I)

CAREER_KEYWORDS = ["career", "careers", "karriere", "jobs", "job", "empleo", "trabaja", "trabajar", "join",
                   "vacanc", "recruit", "stellen", "emploi", "carriere", "lavora", "werken-bij", "vacatures"]
CONTACT_KEYWORDS = ["impressum", "imprint", "contact", "kontakt", "contacto", "contatto", "contato", "kontakt-oss",
                    "aviso-legal", "legal", "mentions-legales", "about", "nosotros", "quienes-somos", "ueber-uns",
                    "uber-uns", "om-oss"]
NOT_CAREERS = ("/blog", "/news", "/noticias", "/press", "/prensa", "/actualidad", "/aktuelles", "/nyheter",
               "/actualites")
JOB_PORTALS = ["crewportal", "crew-portal", "workday", "successfactors", "teamtailor", "recruitee", "greenhouse.io",
               "lever.co", "ashbyhq", "smartrecruiters", "personio", "jobs.", "careers.", "join.com", "applytojob",
               "bamboohr", "taleo", "icims", "softgarden", "jobylon", "workable"]
NOT_HTML = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif", ".pdf", ".zip", ".mp4", ".doc", ".docx",
            ".xls", ".xlsx", ".ppt", ".pptx", ".ics")


@dataclass
class CrawlRules:
    page_keywords: list[str]
    careers_cutoff: int                   # las palabras antes de este índice son de empleo
    mailbox: MailboxRules
    mentions: list[tuple[str, list[str]]] = field(default_factory=list)
    signals: list[tuple[str, re.Pattern]] = field(default_factory=list)
    warnings: dict[str, re.Pattern] = field(default_factory=dict)
    warnings_on_careers_only: set[str] = field(default_factory=set)

    @classmethod
    def for_pack(cls, pack: Pack | None) -> "CrawlRules":
        c = pack.crawl if pack else None
        empleo = list(dict.fromkeys((c.page_keywords if c else []) + CAREER_KEYWORDS))
        return cls(
            page_keywords=empleo + CONTACT_KEYWORDS, careers_cutoff=len(empleo),
            mailbox=MailboxRules.for_pack(pack),
            mentions=[(m.label, m.variants) for m in (c.mentions if c else [])],
            signals=[(s.label, re.compile(r"\b(?:" + "|".join(s.terms) + r")\b")) for s in (c.career_signals if c else [])],
            warnings={k: re.compile("|".join(v), re.I) for k, v in (c.warnings if c else {}).items() if v},
            warnings_on_careers_only=set(c.warnings_on_careers_only if c else []),
        )


def _cloudflare(hexa: str) -> str:
    clave = int(hexa[:2], 16)
    return "".join(chr(int(hexa[i:i + 2], 16) ^ clave) for i in range(2, len(hexa), 2))


def extract_emails(texto: str) -> set[str]:
    """Emails de una página, incluidos los ofuscados ('info [at] empresa [dot] de') y los de Cloudflare."""
    texto = html.unescape(texto)
    extra = []
    for h in RE_CFEMAIL.findall(texto):
        try:
            extra.append(_cloudflare(h))
        except ValueError:
            pass
    texto = re.sub(r"\s*[\[\(\{]\s*(?:at|arroba|ät)\s*[\]\)\}]\s*", "@", texto, flags=re.I)
    texto = re.sub(r"\s*[\[\(\{]\s*(?:dot|punto|punkt|point)\s*[\]\)\}]\s*", ".", texto, flags=re.I)
    out = set()
    for e in RE_EMAIL.findall(texto) + extra:
        e = e.strip(".").lower()
        if e.endswith(NOT_HTML) or "example." in e.split("@")[-1][:8]:
            continue
        out.add(e)
    return out


def site_name(texto: str) -> str:
    m = RE_SITENAME.search(texto) or RE_TITLE.search(texto)
    if not m:
        return ""
    titulo = re.sub(r"\s+", " ", html.unescape(m.group(1))).strip(" |–—-:·")
    partes = [p.strip() for p in re.split(r"\s[|–—\-:·]\s", titulo) if 2 < len(p.strip()) < 60]
    comunes = ("home", "inicio", "startseite", "accueil", "welcome", "bienvenid", "forside", "etusivu")
    partes = [p for p in partes if not p.lower().startswith(comunes)]
    return min(partes, key=len) if partes else ""


def _priority(url: str, texto_enlace: str, rules: CrawlRules) -> int | None:
    ruta = urllib.parse.urlsplit(url).path.lower()
    texto = re.sub(r"<[^>]+>", " ", texto_enlace).lower()
    for i, p in enumerate(rules.page_keywords):
        if p in ruta or p in texto:
            return i
    return None


def _links(texto: str, base: str, dom: str, rules: CrawlRules):
    internos, portales, ats = [], [], set()
    for href, txt in RE_LINK.findall(texto):
        href = html.unescape(href).strip()
        if href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        url = urllib.parse.urljoin(base, href).split("#")[0]
        if not url.startswith("http") or url.lower().split("?")[0].endswith(NOT_HTML):
            continue
        ref = detect(url)
        if ref and ref.info.kind == "ats" and ref.slug:
            ats.add((ref.platform, ref.slug))
        d = domain_of(url)
        prio = _priority(url, txt, rules)
        if d == dom:
            if prio is not None:
                internos.append((prio, url))
        elif prio is not None and prio < rules.careers_cutoff and any(p in url.lower() for p in JOB_PORTALS):
            portales.append((prio, url))
    ordenar = lambda lista: list(dict.fromkeys(u for _, u in sorted(lista)))
    return ordenar(internos), ordenar(portales), ats


def _robots(http: Http, inicio: str) -> urllib.robotparser.RobotFileParser:
    rp = urllib.robotparser.RobotFileParser()
    try:
        r = http.request("GET", urllib.parse.urljoin(inicio, "/robots.txt"), max_bytes=300_000, timeout=10,
                         insecure_fallback=True)
        rp.parse(r.text.splitlines() if r.ok else [])
    except Exception:
        rp.parse([])
    return rp


def crawl(http: Http, web: str, rules: CrawlRules, user_agent: str = "knok-bot") -> dict:
    res = {"read": False, "blocked": False, "robots_blocked": False, "name": "", "emails": [], "best_email": "",
           "best_email_url": "", "careers_url": "", "ats": [], "mentions": [], "signals": [], "warnings": [],
           "pages": 0}
    if not web:
        return res
    if not re.match(r"https?://", web, re.I):
        web = "https://" + web
    dom = domain_of(web)
    if not dom:
        return res
    limite = time.monotonic() + MAX_SECONDS
    robots = _robots(http, web)
    if not robots.can_fetch(user_agent, web):
        res["robots_blocked"] = True
        return res
    pendientes, visitadas = [web], set()
    hallados: dict[str, tuple[int, str, bool]] = {}
    ats: set = set()
    careers_signal = False

    while pendientes and len(visitadas) < MAX_PAGES and time.monotonic() < limite:
        url = pendientes.pop(0)
        if url in visitadas or not robots.can_fetch(user_agent, url):
            continue
        visitadas.add(url)
        try:
            r = http.request("GET", url, timeout=15, max_bytes=1_500_000, insecure_fallback=True)
        except Exception:
            if not res["read"] and url.startswith("https://"):
                pendientes.insert(0, "http://" + url[8:])  # algunas webs pequeñas no tienen https
            continue
        if not r.ok:
            if not res["read"] and r.status in (401, 403, 429):
                res["blocked"] = True
                break
            continue
        if r.content_type and not r.content_type.startswith("text/html"):
            continue
        texto, final = r.text, r.url or url
        if not res["read"]:
            res["read"] = True
            dom = domain_of(final) or dom
            res["name"] = site_name(texto)
        res["pages"] += 1
        internos, portales, ats_pagina = _links(texto, final, dom, rules)
        ats |= ats_pagina
        nuevos = [u for u in internos if u not in visitadas and u not in pendientes]
        pendientes = sorted(pendientes + nuevos, key=lambda u: _priority(u, "", rules) if _priority(u, "", rules) is not None else 99)

        ruta = urllib.parse.urlsplit(final).path.lower()
        es_empleo = any(p in ruta for p in rules.page_keywords[:rules.careers_cutoff]) and \
            not any(n in ruta for n in NOT_CAREERS)
        visible = visible_text(texto)
        for etiqueta, variantes in rules.mentions:
            if etiqueta not in res["mentions"] and any(re.search(r"\b" + re.escape(v) + r"\b", visible) for v in variantes):
                res["mentions"].append(etiqueta)
        vistos = {a["type"] for a in res["warnings"]}
        for tipo, patron in rules.warnings.items():
            if tipo in vistos or (tipo in rules.warnings_on_careers_only and not es_empleo):
                continue
            m = patron.search(visible)
            if m:
                ini, fin = max(0, m.start() - 90), min(len(visible), m.end() + 90)
                res["warnings"].append({"type": tipo, "text": visible[ini:fin].strip(), "url": final})
        if es_empleo:
            senal = [et for et, rx in rules.signals if rx.search(visible)]
            for s in senal:
                if s not in res["signals"]:
                    res["signals"].append(s)
            # La página de empleo preferida es la que tiene señales del nicho
            if not res["careers_url"] or (senal and not careers_signal):
                res["careers_url"], careers_signal = final, bool(senal)
        if portales and not res["careers_url"]:
            res["careers_url"] = portales[0]

        for e in extract_emails(texto):
            if not is_generic(e, rules.mailbox.extra_roles):
                continue   # personal o descartado: nunca se guarda
            puntos = score(e, dom, rules.mailbox, es_empleo)
            if puntos is None:
                continue
            if e not in hallados or hallados[e][0] < puntos:
                hallados[e] = (puntos, final, es_empleo)
        # Ya hay un buzón preferido del propio dominio en una página de empleo: se para, salvo que el pack
        # defina avisos de seguridad (entonces se revisan todas las páginas permitidas)
        if not rules.warnings and any(p >= 24 for p, _, _ in hallados.values()):
            break

    orden = sorted(hallados.items(), key=lambda kv: (-kv[1][0], kv[0]))
    res["emails"] = [{"email": e, "url": u, "on_careers_page": c, "score": p} for e, (p, u, c) in orden]
    if orden:
        res["best_email"], res["best_email_url"] = orden[0][0], orden[0][1][1]
    res["ats"] = [{"platform": p, "slug": s} for p, s in sorted(ats)]
    res["host"] = host(web)
    return res

