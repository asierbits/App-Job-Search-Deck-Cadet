"""¿Es un buzón genérico de empresa (info@, rrhh@, jobs@…) o el de una persona?

Principio de knok: en la base común solo entran buzones GENÉRICOS. Se usa una lista blanca de roles:
si la parte local no es claramente un rol, se considera personal y se descarta. Mejor perder un
buzón dudoso que guardar el correo de una persona.
"""
import re
from functools import lru_cache

ROLE_WORDS = {
    # contacto general
    "info", "information", "informacion", "contact", "contacto", "contacta", "kontakt", "contatto", "contato",
    "hello", "hola", "hallo", "bonjour", "ciao", "hi", "office", "oficina", "buero", "buro", "mail", "email",
    "correo", "post", "firmapost", "postmaster", "admin", "administracion", "administration", "general",
    "reception", "recepcion", "empfang", "secretaria", "secretariat", "sekretariat", "enquiries", "enquiry",
    "inquiries", "inquiry", "consultas", "atencion", "service", "servicio", "team", "equipo", "company",
    "empresa", "central", "sede", "headoffice", "hq",
    # empleo / RR. HH.
    "jobs", "job", "careers", "career", "karriere", "carreras", "carrera", "empleo", "empleos", "trabajo",
    "trabaja", "trabajaconnosotros", "work", "workwithus", "joinus", "join", "hr", "rrhh", "rh", "humanresources",
    "recursoshumanos", "personal", "personalabteilung", "people", "talent", "talento", "recruiting", "recruitment",
    "recruit", "recrutement", "reclutamiento", "seleccion", "selection", "staffing", "hiring", "bewerbung",
    "bewerbungen", "candidaturas", "candidatura", "cv", "curriculum", "curriculums", "practicas", "internship",
    "internships", "intern", "trainee", "trainees", "graduates", "graduate", "apprentice", "ausbildung",
    "stage", "stages", "emploi", "lavoro", "lavora", "vagas", "werken", "jobb",
    # otros departamentos (válidos, aunque peores para una candidatura)
    "sales", "ventas", "comercial", "marketing", "press", "prensa", "media", "support", "soporte", "help",
    "ayuda", "operations", "operaciones", "accounts", "finance", "billing", "facturacion", "legal", "compliance",
    "booking", "bookings", "reservas", "orders", "pedidos", "export", "import", "purchasing", "compras",
    "logistics", "logistica", "customer", "clientes", "it", "tech", "dev", "research", "investigacion", "lab",
    # calificativos de departamento
    "acquisition", "department", "dept", "dpto", "departamento", "abteilung", "group", "global", "corporate",
    "spain", "espana", "europe", "emea", "iberia", "international", "intl", "es", "en", "uk",
}

DISCARD = {"noreply", "no-reply", "donotreply", "do-not-reply", "privacy", "datenschutz", "dpo", "gdpr", "rgpd",
           "abuse", "webmaster", "sentry", "example", "yourname", "tuemail", "tunombre", "name", "nombre",
           "newsletter", "unsubscribe", "bounce", "mailer-daemon", "notifications", "notification"}

_SEP = re.compile(r"[._+\-]+")


@lru_cache
def _places() -> frozenset[str]:
    """Ciudades y países conocidos: un buzón 'rrhh.madrid@' sigue siendo de rol."""
    from knok.core.geo import CITY_COUNTRY, _NAME_TO_ISO
    return frozenset({c.replace(" ", "") for c in CITY_COUNTRY} | {n.replace(" ", "") for n in _NAME_TO_ISO})


def local_part(email: str) -> str:
    return (email or "").split("@", 1)[0].lower()


def is_discarded(email: str) -> bool:
    lp = local_part(email)
    return lp in DISCARD or any(lp.startswith(d) for d in ("noreply", "no-reply", "donotreply", "mailer-daemon"))


def is_generic(email: str, extra_roles: set[str] | frozenset[str] = frozenset()) -> bool:
    """True si TODAS las partes del buzón son palabras de rol, códigos cortos o números.
    info@, rrhh.madrid@, jobs-es@, careers2@ → genéricos.  ana.lopez@, jsmith@, a.perez@ → personales."""
    lp = local_part(email)
    if not lp or "@" not in (email or "") or is_discarded(email):
        return False
    roles = ROLE_WORDS | {r.lower() for r in extra_roles}
    if lp in roles:
        return True
    partes = [p for p in _SEP.split(lp) if p]
    if not partes:
        return False
    tiene_rol = False
    for p in partes:
        if p in roles or re.sub(r"\d+$", "", p) in roles:
            tiene_rol = True
        elif re.fullmatch(r"\d+|[a-z]{2}", p) or p in _places():  # jobs.es, hr-uk, info2, rrhh.madrid
            continue
        else:
            return False
    return tiene_rol
