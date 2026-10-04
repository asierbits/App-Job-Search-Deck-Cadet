"""Idiomas: qué idioma usar con cada empresa según su país, y textos de sistema por idioma.

Para añadir un idioma: añádelo a SUPPORTED, crea las plantillas `templates/<idioma>/` del pack y
añade sus palabras en `knok/core/mail/classify.py` y en `knok/core/filling/patterns.yaml`.
"""
SUPPORTED = ("es", "en", "fr", "de", "pt", "it", "nl")
FALLBACK = "en"

COUNTRY_LANGUAGE = {
    # español
    **dict.fromkeys(["es", "mx", "ar", "co", "cl", "pe", "ve", "ec", "gt", "cu", "bo", "do", "hn", "py", "sv",
                     "ni", "cr", "pa", "uy", "pr", "gq"], "es"),
    # inglés
    **dict.fromkeys(["gb", "ie", "us", "ca", "au", "nz", "za", "mt", "sg", "in"], "en"),
    # resto
    **dict.fromkeys(["fr", "lu", "mc"], "fr"),
    "be": "fr",
    **dict.fromkeys(["de", "at", "li"], "de"),
    "ch": "de",
    **dict.fromkeys(["pt", "br", "ao", "mz"], "pt"),
    **dict.fromkeys(["it", "sm", "va"], "it"),
    "nl": "nl",
}


def language_for_country(country: str, available: list[str] | tuple[str, ...]) -> str:
    """Idioma del país si el pack tiene plantillas en ese idioma; si no, inglés (o el primero disponible)."""
    lang = COUNTRY_LANGUAGE.get((country or "").lower(), FALLBACK)
    if lang in available:
        return lang
    return FALLBACK if FALLBACK in available else (available[0] if available else FALLBACK)


MESSAGES = {
    "es": {
        "status.prepared": "Preparada", "status.confirmed": "Confirmada", "status.sent": "Enviada",
        "status.replied": "Respondida", "status.interview": "Entrevista", "status.discarded": "Descartada",
        "status.error": "Error",
        "route.ats_extension": "Formulario de la empresa (extensión)", "route.portal_api": "Portal con API",
        "route.portal_copilot": "Copiloto en el portal", "route.email": "Correo directo",
        "route.manual": "A mano",
    },
    "en": {
        "status.prepared": "Prepared", "status.confirmed": "Confirmed", "status.sent": "Sent",
        "status.replied": "Replied", "status.interview": "Interview", "status.discarded": "Discarded",
        "status.error": "Error",
        "route.ats_extension": "Company form (extension)", "route.portal_api": "Portal API",
        "route.portal_copilot": "Portal copilot", "route.email": "Direct email", "route.manual": "Manual",
    },
}


def t(key: str, lang: str = "es") -> str:
    return MESSAGES.get(lang, MESSAGES["en"]).get(key) or MESSAGES["en"].get(key, key)
