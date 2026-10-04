"""Normalización de texto común a todo el motor."""
import html
import re
import unicodedata

_ESPACIOS = re.compile(r"\s+")


def strip_accents(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")


def norm(texto: str) -> str:
    """Minúsculas, sin tildes, sin signos raros y con espacios simples. Para comparar textos."""
    t = strip_accents(texto).lower()
    t = re.sub(r"[^a-z0-9@+#./ -]+", " ", t)
    return _ESPACIOS.sub(" ", t).strip()


def html_to_text(fragmento: str) -> str:
    """Texto legible de un fragmento HTML (descripciones de ofertas)."""
    if not fragmento:
        return ""
    t = html.unescape(fragmento)
    if "&lt;" in t:  # algunas APIs (Greenhouse) escapan el HTML dos veces
        t = html.unescape(t)
    t = re.sub(r"<(script|style|noscript|svg)\b.*?</\1>", " ", t, flags=re.I | re.S)
    t = re.sub(r"<\s*(br|/p|/div|/li|/h\d|/tr)\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"<li[^>]*>", "\n• ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    lineas = [_ESPACIOS.sub(" ", l).strip() for l in t.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip()


def visible_text(pagina: str) -> str:
    """Lo que ve una persona en una página (sin scripts, estilos ni etiquetas), normalizado sin tildes."""
    t = re.sub(r"<(script|style|noscript|svg)\b.*?</\1>", " ", pagina, flags=re.I | re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    return _ESPACIOS.sub(" ", strip_accents(t).lower())


def fill_template(texto: str, valores: dict) -> str:
    """Sustituye {variables}. Una variable desconocida se deja tal cual en vez de romper."""
    return re.sub(r"\{(\w+)\}", lambda m: str(valores[m.group(1)]) if m.group(1) in valores and
                  valores[m.group(1)] is not None else m.group(0), texto or "")


def missing_variables(texto: str, valores: dict) -> list[str]:
    return sorted({v for v in re.findall(r"\{(\w+)\}", texto or "") if not str(valores.get(v) or "").strip()})


def tidy_body(texto: str) -> str:
    """Quita huecos que dejan las variables vacías (teléfono, LinkedIn…)."""
    lineas = [l.rstrip() for l in (texto or "").splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip() + "\n"
