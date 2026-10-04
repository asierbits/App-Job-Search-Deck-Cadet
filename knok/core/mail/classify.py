"""Clasificación de respuestas por palabras clave (portado de legacy/core/correo.py).

Categorías: interview | info | rejection | auto | other. El orden importa: gana la primera que encaje.
Cada pack puede añadir frases propias en `reply_keywords`.
"""
from knok.core.text import strip_accents

BASE_RULES: list[tuple[str, list[str]]] = [
    ("auto", ["respuesta automatica", "fuera de la oficina", "no responda a este", "mensaje automatico",
              "de vacaciones", "automatic reply", "auto-reply", "autoreply", "out of office", "do not reply",
              "automatische antwort", "abwesenheit", "reponse automatique", "absent du bureau",
              "hemos recibido tu candidatura", "we have received your application"]),
    ("rejection", ["lamentablemente", "no disponemos", "no tenemos vacantes", "no hay vacantes", "en este momento no",
                   "no podemos ofrecer", "no estamos buscando", "otro candidato", "otros candidatos", "no encaja",
                   "no seguiremos", "desestimad", "unfortunately", "regret to inform", "no open positions",
                   "not able to offer", "not hiring", "other candidates", "not moving forward",
                   "decided not to proceed", "leider", "absage", "malheureusement"]),
    ("interview", ["entrevista", "reunion", "videollamada", "llamada", "conocerte", "conocerle", "disponibilidad para",
                   "te citamos", "que dia te viene", "interview", "video call", "phone call", "a quick call", "a call",
                   "meet you", "your availability", "schedule a", "vorstellungsgesprach", "kennenlernen", "entretien",
                   "rencontrer"]),
    ("info", ["mas informacion", "convenio", "portal", "formulario", "inscribete", "referencia", "expediente",
              "nos envies", "podrias indicarnos", "adjunta", "completar", "application form", "more information",
              "please complete", "please apply", "could you send", "bewerbungsformular", "formular", "formulaire"]),
]

CATEGORIES = ("interview", "info", "rejection", "auto", "other")


def classify(subject: str, body: str, extra: dict[str, list[str]] | None = None) -> str:
    texto = strip_accents(f"{subject}\n{body}").lower()
    for categoria, palabras in BASE_RULES:
        todas = palabras + [strip_accents(p).lower() for p in (extra or {}).get(categoria, [])]
        if any(p in texto for p in todas):
            return categoria
    return "other"


def application_status_for(category: str) -> str:
    """Estado del seguimiento que implica una respuesta."""
    return {"interview": "interview", "rejection": "discarded"}.get(category, "replied")
