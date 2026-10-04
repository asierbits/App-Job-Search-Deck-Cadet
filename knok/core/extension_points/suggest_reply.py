"""Punto de extensión OPCIONAL: sugerir una respuesta a un correo recibido.

knok no usa IA: este punto existe, pero está DESACTIVADO (KNOK_SUGGEST_REPLY_PROVIDER vacío).
Si algún día se quiere activar, se implementa un `ReplySuggester` y se registra con `register()`.
Aun activado, una sugerencia es solo un borrador: enviarla requiere el clic del usuario, como todo.
"""
from typing import Protocol

from knok.settings import get_settings


class ReplySuggester(Protocol):
    name: str

    def suggest(self, *, reply_subject: str, reply_body: str, application: dict, profile: dict,
                language: str) -> str: ...


_REGISTRY: dict[str, ReplySuggester] = {}


def register(suggester: ReplySuggester) -> None:
    _REGISTRY[suggester.name] = suggester


def active() -> ReplySuggester | None:
    nombre = get_settings().suggest_reply_provider
    return _REGISTRY.get(nombre) if nombre else None
