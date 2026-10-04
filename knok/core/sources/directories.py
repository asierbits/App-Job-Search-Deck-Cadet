"""Directorios de asociaciones (listas de socios en HTML o PDF), con paginación.

Portado de legacy/core/maritimo.py. Las URL de los directorios, las entidades a excluir y los países
admitidos los define cada pack.
"""
import html
import re
import time
import urllib.parse
import urllib.robotparser
import zlib

from knok.core.crawl.website import RE_LINK, extract_emails
from knok.core.domains import country_of_domain, domain_of, is_company_site, pretty_name
from knok.core.emails.score import MailboxRules, score
from knok.core.http import Http
from knok.core.sources.base import RawCompany

RE_PAGE_NUM = re.compile(r"([?&][\w-]*page[\w-]*=|/page/|/seite/|/pagina/)(\d+)", re.I)
_NEXT = ("›", "»", ">", "next", "siguiente", "weiter", "nächste", "suivant", "neste", "volgende")


def _clean_name(texto: str, dom: str) -> str:
    t = re.sub(r"<[^>]+>", " ", html.unescape(texto))
    t = re.sub(r"\b(website|webside|web|www|homepage|hjemmeside|webseite|site|visit|besøk|besuchen|read more|mehr|"
               r"voir|ver más|link)\b", " ", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" -–|:·")
    if len(t) < 3 or ("." in t and " " not in t) or t.lower().startswith("http"):
        return pretty_name(dom)
    return t[:120]


def parse_html(url: str, texto: str, excluded_domains: list[str]) -> dict[str, dict]:
    propio = domain_of(url)
    cands: dict[str, dict] = {}
    for href, txt in RE_LINK.findall(texto):
        href = html.unescape(href).strip()
        if not href.startswith("http") or not is_company_site(href):
            continue
        dom = domain_of(href)
        if not dom or dom == propio or any(x in dom for x in excluded_domains):
            continue
        cands.setdefault(dom, {"name": _clean_name(txt, dom), "website": href, "email": ""})
    for e in extract_emails(texto):
        base = e.split("@")[1].split(".")[0]
        for dom, c in cands.items():
            if dom.split(".")[0] == base and not c["email"]:
                c["email"] = e
    return cands


def parse_pdf(datos: bytes, excluded_domains: list[str]) -> dict[str, dict]:
    """Webs (enlaces /URI) y emails de un PDF, sin librerías: también dentro de bloques comprimidos."""
    bloques = [datos]
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", datos, re.S):
        try:
            bloques.append(zlib.decompress(m.group(1)))
        except Exception:
            pass
    todo = b"\n".join(bloques).decode("latin-1")
    webs = [u for u in re.findall(r"/URI\s*\((https?://[^)]+)\)", todo) if is_company_site(u)]
    emails = extract_emails(" ".join(re.findall(r"/URI\s*\(mailto:([^)]+)\)", todo)) + " " + todo)
    cands: dict[str, dict] = {}
    for w in webs:
        dom = domain_of(w)
        if dom and not any(x in dom for x in excluded_domains):
            raiz = urllib.parse.urlunsplit(urllib.parse.urlsplit(w)[:2] + ("/", "", ""))
            cands.setdefault(dom, {"name": pretty_name(dom), "website": raiz, "email": ""})
    reglas = MailboxRules()
    for e in sorted(emails):
        dom_e = domain_of(e)
        if not dom_e or any(x in dom_e for x in excluded_domains):
            continue
        base = dom_e.split(".")[0]
        destino = next((c for d, c in cands.items() if d.split(".")[0] == base), None)
        if destino is None:
            destino = cands.setdefault(dom_e, {"name": pretty_name(dom_e), "website": f"https://{dom_e}/", "email": ""})
        d_web = domain_of(destino["website"])
        if not destino["email"] or (score(e, d_web, reglas) or 0) > (score(destino["email"], d_web, reglas) or 0):
            destino["email"] = e
    return cands


def next_page(texto: str, url: str) -> str | None:
    host = domain_of(url)
    m = RE_PAGE_NUM.search(url)
    actual = int(m.group(2)) if m else 1
    for href, _ in RE_LINK.findall(texto):
        h = urllib.parse.urljoin(url, html.unescape(href))
        m = RE_PAGE_NUM.search(h)
        if m and domain_of(h) == host and int(m.group(2)) == actual + 1:
            return h
    for href, txt in RE_LINK.findall(texto):
        t = re.sub(r"<[^>]+>", "", txt).strip().lower()
        if t in _NEXT:
            sig = urllib.parse.urljoin(url, html.unescape(href))
            if domain_of(sig) == host and sig != url:
                return sig
    return None


def read_directory(http: Http, url: str, default_country: str = "", excluded_domains: list[str] | None = None,
                   allowed_countries: list[str] | None = None, user_agent: str = "knok-bot",
                   max_pages: int = 30) -> list[RawCompany]:
    excluidos = excluded_domains or []
    partes = urllib.parse.urlsplit(url)
    robots = urllib.robotparser.RobotFileParser()
    try:
        r = http.request("GET", f"{partes.scheme}://{partes.netloc}/robots.txt", timeout=20)
        robots.parse(r.text.splitlines() if r.ok else [])
    except Exception:
        robots.parse([])
    if not robots.can_fetch(user_agent, url):
        raise PermissionError(f"{partes.netloc}: su robots.txt no permite leer esa página")

    cands: dict[str, dict] = {}
    visitadas, actual = set(), url
    while actual and actual not in visitadas and len(visitadas) < max_pages:
        visitadas.add(actual)
        r = http.request("GET", actual, timeout=60, max_bytes=8_000_000, insecure_fallback=True)
        if not r.ok:
            break
        if r.content_type == "application/pdf" or r.content[:5] == b"%PDF-":
            for k, v in parse_pdf(r.content, excluidos).items():
                cands.setdefault(k, v)
            break
        for k, v in parse_html(r.url or actual, r.text, excluidos).items():
            cands.setdefault(k, v)
        actual = next_page(r.text, r.url or actual)
        if actual:
            time.sleep(1)

    propia = domain_of(url).split(".")[0]
    fuente = partes.netloc.removeprefix("www.")
    out = []
    for dom, c in cands.items():
        if dom.split(".")[0] == propia:
            continue   # la propia asociación
        pais = country_of_domain(dom, default_country)
        if allowed_countries and pais and pais not in allowed_countries:
            continue
        out.append(RawCompany(name=c["name"], source=fuente, domain=dom, website=c["website"], email=c["email"],
                              country=pais))
    return out
