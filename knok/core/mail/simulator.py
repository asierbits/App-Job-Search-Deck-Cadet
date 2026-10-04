"""Respuestas simuladas (modo Simulación): textos neutros por idioma; nada sale ni llega de verdad."""
import random

KINDS = [("interview", 0.25), ("info", 0.30), ("rejection", 0.35), ("auto", 0.10)]

TEXTS = {
    "es": {
        "interview": [("Re: {asunto}", "Hola {nombre}:\n\nGracias por escribirnos. Nos gustaría conocerte. "
                       "¿Tendrías disponibilidad para una videollamada esta semana?\n\nUn saludo,\n{empresa}")],
        "info": [("Re: {asunto}", "Hola {nombre}:\n\nGracias por tu interés. Para valorar tu candidatura te pedimos "
                  "que completes el formulario de nuestro portal y nos envíes más información.\n\nSaludos,\n{empresa}")],
        "rejection": [("Re: {asunto}", "Hola {nombre}:\n\nMuchas gracias por contactar con {empresa}. Lamentablemente, "
                       "en este momento no disponemos de vacantes para tu perfil.\n\nTe deseamos mucha suerte.")],
        "auto": [("Respuesta automática: {asunto}", "Gracias por tu mensaje. Esta es una respuesta automática: lo "
                  "revisaremos lo antes posible.\n\n{empresa}")],
    },
    "en": {
        "interview": [("Re: {asunto}", "Hi {nombre},\n\nThanks for reaching out. We would like to schedule a short "
                       "video call with you. What is your availability next week?\n\nBest regards,\n{empresa}")],
        "info": [("Re: {asunto}", "Hi {nombre},\n\nThanks for your message. Please complete the application form on our "
                  "portal so we can consider your profile.\n\nKind regards,\n{empresa}")],
        "rejection": [("Re: {asunto}", "Dear {nombre},\n\nThank you for your interest in {empresa}. Unfortunately, "
                       "we have no open positions for your profile at the moment.\n\nBest of luck!")],
        "auto": [("Automatic reply: {asunto}", "Thank you for your message. This is an automatic reply to confirm "
                  "that we have received your email.\n\n{empresa}")],
    },
}


def pick_kind(rng: random.Random, reply_probability: float = 0.6) -> str | None:
    if rng.random() > reply_probability:
        return None
    return rng.choices([k for k, _ in KINDS], weights=[w for _, w in KINDS])[0]


def compose(kind: str, lang: str, values: dict, rng: random.Random) -> tuple[str, str]:
    textos = TEXTS.get(lang) or TEXTS["en"]
    asunto, cuerpo = rng.choice(textos[kind])
    return asunto.format(**values), cuerpo.format(**values)
