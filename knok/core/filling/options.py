"""Convertir una respuesta del banco en una de las opciones de un desplegable o botón de radio."""
import re

from knok.core.geo import COUNTRY_NAMES, country_from_text
from knok.core.text import norm

YES = {"yes", "y", "si", "sí", "ja", "oui", "sim", "true", "1", "i am", "i do", "i have", "yes i am", "yes, i am"}
NO = {"no", "n", "nein", "non", "nao", "não", "false", "0", "i am not", "i do not", "no, i am not"}
DECLINE = ["decline", "prefer not", "prefiero no", "no deseo", "i don't wish", "i do not wish", "not to answer",
           "no contestar", "keine angabe", "je ne souhaite pas"]


def as_bool(valor) -> bool | None:
    if isinstance(valor, bool):
        return valor
    if valor is None:
        return None
    n = norm(str(valor))
    if n in {norm(x) for x in YES}:
        return True
    if n in {norm(x) for x in NO}:
        return False
    return None


def _option_bool(label: str) -> bool | None:
    n = norm(label)
    if any(n.startswith(norm(y)) for y in ("yes", "si", "ja", "oui", "sim")) and not n.startswith("no"):
        return True
    if n.startswith(("no", "nein", "non", "nao")):
        return False
    return None


def _numbers(texto: str) -> list[float]:
    return [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", texto)]


def _range(label: str) -> tuple[float, float] | None:
    """'1-3 años' → (1,3); 'Más de 5' / '5+' → (5, ∞); 'Menos de 1' → (0,1)."""
    n = norm(label)
    nums = _numbers(n)
    if not nums:
        return None
    if re.search(r"(mas de|more than|over|above|plus de|mehr als|\+)", n) or n.rstrip().endswith("+"):
        return (nums[0] + (0 if "+" in n else 0.0001), float("inf"))
    if re.search(r"(menos de|less than|under|below|moins de|weniger als)", n):
        return (0.0, nums[0] - 0.0001)
    if len(nums) >= 2:
        return (nums[0], nums[1])
    return (nums[0], nums[0])


def pick_option(valor, options: list[dict], key: str = "") -> tuple[str | None, str]:
    """Devuelve (value de la opción, motivo). None si no hay una coincidencia clara."""
    if not options or valor in (None, ""):
        return None, "sin valor"
    etiquetas = [(o.get("label") or "", str(o.get("value", o.get("label", "")))) for o in options]

    b = as_bool(valor) if not isinstance(valor, (int, float)) or isinstance(valor, bool) else None
    if b is not None:
        for lab, val in etiquetas:
            if _option_bool(lab) is b:
                return val, "sí/no"
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        for lab, val in etiquetas:
            r = _range(lab)
            if r and r[0] <= float(valor) <= r[1]:
                return val, f"rango «{lab}»"
    texto = norm(str(valor))
    for lab, val in etiquetas:
        if norm(lab) == texto or norm(val) == texto:
            return val, "coincidencia exacta"
    if key in ("country", "nationality") and texto:
        iso = country_from_text(texto) or (texto if texto in COUNTRY_NAMES else "")
        for lab, val in etiquetas:
            if iso and (country_from_text(lab) == iso or norm(val) == iso):
                return val, "país"
    contiene = [(lab, val) for lab, val in etiquetas if texto and len(texto) >= 3 and (texto in norm(lab) or norm(lab) in texto)]
    if len(contiene) == 1:
        return contiene[0][1], "coincidencia parcial"
    return None, "ninguna opción encaja"


def decline_option(options: list[dict]) -> str | None:
    """La opción 'prefiero no contestar', si existe (para preguntas sensibles que el usuario quiere omitir)."""
    for o in options:
        if any(d in norm(o.get("label") or "") for d in map(norm, DECLINE)):
            return str(o.get("value", o.get("label")))
    return None
