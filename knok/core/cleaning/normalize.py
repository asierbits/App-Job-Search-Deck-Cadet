"""Normalización para comparar: empresa, puesto, ciudad y huella de una oferta."""
import hashlib
import re

from knok.core.geo import city_key
from knok.core.text import norm

_FORMAS_JURIDICAS = (
    "s.l.u", "s.l.l", "s.l", "slu", "sl", "s.a.u", "s.a", "sa", "s.c", "s.coop", "sociedad limitada",
    "sociedad anonima", "gmbh & co. kg", "gmbh & co kg", "gmbh", "ag", "kg", "ohg", "e.v", "ug",
    "ltd", "limited", "inc", "incorporated", "llc", "llp", "plc", "corp", "corporation", "co", "company",
    "b.v", "bv", "n.v", "nv", "sas", "s.a.s", "sarl", "s.a.r.l", "sasu", "eurl", "spa", "s.p.a", "srl", "s.r.l",
    "as", "a/s", "asa", "ab", "oy", "oyj", "aps", "sp. z o.o", "sp z o o", "lda", "unipessoal", "group", "grupo",
    "holding", "holdings",
)
_FJ_RE = re.compile(r"(?:[\s,]+(?:" + "|".join(re.escape(f) for f in sorted(_FORMAS_JURIDICAS, key=len, reverse=True))
                    + r")\.?)+$")

# Marcas de género/inclusividad y ruido en títulos de ofertas
_TITULO_RUIDO = [
    r"\((?:m|w|f|h|d|x|v|a|e)(?:\s*/\s*(?:m|w|f|h|d|x|v|a|e|div|i)){1,3}\)",   # (m/w/d) (h/m/x) (f/m/x)
    r"\b(?:m|w|f|h)\s*/\s*(?:m|w|f|h|d|x)(?:\s*/\s*[dx])?\b",
    r"\((?:all genders|alle geschlechter|tous genres|todos los generos|gn\*?)\)",
    r"\b(?:all genders)\b", r"\*in\b", r"\bgn\*",
    r"\b(?:remote|remoto|hybrid|hibrido|h[ií]brido|on-?site|teletrabajo|presencial)\b",
]
_TITULO_RE = re.compile("|".join(_TITULO_RUIDO), re.I)


def company_key_name(nombre: str) -> str:
    n = norm(nombre).replace(",", " ")
    n = _FJ_RE.sub("", " " + n).strip()
    return re.sub(r"[^a-z0-9 ]", "", n).strip()


def title_key(titulo: str) -> str:
    t = _TITULO_RE.sub(" ", titulo or "")
    t = norm(t)
    t = re.sub(r"[^a-z0-9+#]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def fingerprint(company_key: str, company_name: str, title: str, city: str, remote: bool = False) -> str:
    """Misma empresa + mismo puesto + misma ciudad = misma oferta (aunque venga de fuentes distintas).
    company_key: identificador estable de la empresa (id en la base común o dominio); si no hay, el nombre."""
    empresa = company_key or company_key_name(company_name)
    ciudad = city_key(city) or ("remote" if remote else "")
    base = f"{empresa}|{title_key(title)}|{ciudad}"
    return hashlib.sha1(base.encode()).hexdigest()[:32]
