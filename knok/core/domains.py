"""Dominios: raíz registrable (empresa.co.uk), país por TLD, proveedores de correo gratuitos."""
import re
import urllib.parse
from functools import lru_cache

import tldextract

# Lista de sufijos incluida en el paquete: nunca se descarga en ejecución.
# Los dominios reservados (RFC 2606) cuentan como sufijo para que los datos de ejemplo
# (empresa-a.example.com, empresa-b.example.com) sean empresas distintas.
RESERVED_SUFFIXES = ("example.com", "example.org", "example.net")
_extract = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None, extra_suffixes=RESERVED_SUFFIXES)

FREE_PROVIDERS = {
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.es", "hotmail.fr", "outlook.com", "outlook.es",
    "live.com", "msn.com", "yahoo.com", "yahoo.es", "yahoo.fr", "yahoo.co.uk", "icloud.com", "me.com",
    "gmx.de", "gmx.net", "gmx.com", "web.de", "t-online.de", "orange.fr", "free.fr", "wanadoo.fr", "libero.it",
    "protonmail.com", "proton.me", "online.no", "aol.com", "mail.ru", "yandex.ru", "zoho.com",
}

# Webs que nunca son "la web de la empresa" (redes, acortadores, plataformas)
NOT_COMPANY_SITES = (
    "linkedin.", "twitter.", "facebook.", "instagram.", "youtube.", "google.", "x.com", "flickr.", "vimeo.",
    "wordpress.com", "wixsite.", "tiktok.", "pinterest.", "bit.ly", "goo.gl", "t.co", "wikipedia.",
    "wikimedia.", "indeed.", "glassdoor.", "infojobs.", "adzuna.", "greenhouse.io", "lever.co",
    "ashbyhq.com", "myworkdayjobs.com", "smartrecruiters.com", "recruitee.com", "teamtailor.com",
    "personio.", "workable.com",
)


def host(url: str) -> str:
    if not url:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I):
        url = "https://" + url
    h = (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".")
    return h[4:] if h.startswith("www.") else h


@lru_cache(maxsize=50_000)
def registrable(hostname: str) -> str:
    """careers.empresa.co.uk → empresa.co.uk. Devuelve '' si no es un dominio válido."""
    hostname = (hostname or "").lower().strip(".")
    if not hostname or re.fullmatch(r"[\d.]+", hostname):
        return ""
    r = _extract(hostname)
    if not r.domain or not r.suffix:
        return ""
    return f"{r.domain}.{r.suffix}"


def domain_of(url_or_email: str) -> str:
    """Dominio registrable de una URL o de un email."""
    v = (url_or_email or "").strip()
    if "@" in v and "://" not in v:
        return registrable(v.rsplit("@", 1)[1].lower())
    return registrable(host(v))


def country_of_domain(dom: str, default: str = "") -> str:
    tld = (dom or "").rsplit(".", 1)[-1].lower()
    tld = "gb" if tld == "uk" else tld
    if len(tld) == 2 and tld not in ("eu", "io", "co", "ai", "me", "tv", "fm", "ly", "to", "cc", "app"):
        return tld
    return default


def is_company_site(url: str) -> bool:
    h = host(url)
    return bool(h) and not any(s in h for s in NOT_COMPANY_SITES)


def pretty_name(dom: str) -> str:
    """Nombre legible a partir del dominio (último recurso)."""
    return re.sub(r"[-_]+", " ", (dom or "").split(".")[0]).title()
