"""Qué buzón es mejor para una candidatura (portado de legacy/core/webemail.py::_puntuar).

Orden: buzones preferidos del pack (definidos en el pack) > buzones de empleo/RR. HH. genéricos >
info@/contacto@ > buzones comerciales. Siempre del propio dominio de la empresa.
"""
from dataclasses import dataclass, field

from knok.core.domains import FREE_PROVIDERS, domain_of
from knok.packs.schema import Pack

DEFAULT_PRIORITY = ["jobs", "job", "careers", "career", "karriere", "bewerbung", "empleo", "rrhh", "hr",
                    "recruiting", "recruitment", "talent", "seleccion", "people", "personal", "practicas",
                    "internship", "trainee"]
DEFAULT_GENERIC = ["info", "contact", "contacto", "kontakt", "hello", "hola", "office", "mail", "hallo", "bonjour",
                   "post", "firmapost", "admin", "general", "reception"]
DEFAULT_COMMERCIAL = ["comercial", "sales", "ventas", "marketing", "export", "import", "customer", "cliente",
                      "atencion", "compras", "purchas", "press", "prensa", "booking", "reservas"]


@dataclass
class MailboxRules:
    priority: list[str] = field(default_factory=lambda: list(DEFAULT_PRIORITY))
    generic: list[str] = field(default_factory=lambda: list(DEFAULT_GENERIC))
    commercial: list[str] = field(default_factory=lambda: list(DEFAULT_COMMERCIAL))
    extra_roles: frozenset[str] = frozenset()

    @classmethod
    def for_pack(cls, pack: Pack | None) -> "MailboxRules":
        if pack is None:
            return cls()
        c = pack.crawl
        return cls(priority=list(dict.fromkeys(c.mailbox_priority + DEFAULT_PRIORITY)),
                   generic=list(DEFAULT_GENERIC),
                   commercial=list(dict.fromkeys(c.commercial + DEFAULT_COMMERCIAL)),
                   extra_roles=frozenset(c.extra_generic + c.mailbox_priority))


def score(email: str, company_domain: str, rules: MailboxRules, on_careers_page: bool = False) -> int | None:
    """Puntos del buzón (más = mejor). None = de otra empresa: no usar."""
    local, _, d = (email or "").lower().partition("@")
    dom = (company_domain or "").lower()
    d_reg = domain_of(email)
    propio = bool(dom) and (d_reg == dom or d.endswith("." + dom) or dom.endswith("." + d)
                            or d_reg.split(".")[0] == dom.split(".")[0])
    if not propio and d_reg not in FREE_PROVIDERS:
        return None
    puntos = 10 if propio else 3
    if d == dom or d.endswith("." + dom):
        puntos += 2
    if on_careers_page:
        puntos += 2
    for i, p in enumerate(rules.priority):
        if local == p or local.startswith(p) or ("." + p) in local or ("-" + p) in local:
            return puntos + 12 - min(i, 6)
    if any(c in local for c in rules.commercial):
        return puntos - 5
    if any(g == local or local.startswith(g) for g in rules.generic):
        return puntos + 3
    return puntos


def best(emails: list[tuple[str, bool]], company_domain: str, rules: MailboxRules) -> list[str]:
    """Ordena (email, encontrado_en_página_de_empleo) de mejor a peor, quitando los de otras empresas."""
    puntuados = [(score(e, company_domain, rules, careers), e) for e, careers in emails]
    return [e for s, e in sorted((x for x in puntuados if x[0] is not None), key=lambda x: (-x[0], x[1]))]
