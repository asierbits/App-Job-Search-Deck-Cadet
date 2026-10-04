"""Reconocer qué pregunta es cada campo de un formulario, sin IA: patrones por idioma + pistas técnicas.

Orden de evidencia:
  1. Pista técnica fuerte: atributo autocomplete (given-name, email…) o nombre del campo (first_name, urls[LinkedIn]…).
  2. Patrones de la etiqueta: globales (patterns.yaml) + del pack + aprendidos (aprobados por el admin).
     Gana el patrón más específico (más palabras); en empate, el de más peso.
Devuelve la clave canónica y una confianza: high | medium | low.
"""
import pathlib
import re
from dataclasses import dataclass
from functools import lru_cache

import yaml

from knok.core.text import norm
from knok.packs.schema import Pack

PATTERNS_FILE = pathlib.Path(__file__).with_name("patterns.yaml")

AUTOCOMPLETE = {
    "given-name": "first_name", "family-name": "last_name", "name": "full_name", "email": "email", "tel": "phone",
    "tel-national": "phone", "address-level2": "city", "country": "country", "country-name": "country",
    "organization": "current_company", "organization-title": "current_title", "url": "website", "bday": "date_of_birth",
    "street-address": "location", "postal-code": "location", "sex": "eeo_gender",
}

NAME_HINTS = [
    (r"^(first[_-]?name|firstname|fname|given[_-]?name|vorname|nombre)$", "first_name"),
    (r"^(last[_-]?name|lastname|lname|family[_-]?name|surname|nachname|apellidos?)$", "last_name"),
    (r"^(full[_-]?name|name|candidate[_-]?name)$", "full_name"),
    (r"^(e-?mail|email[_-]?address|candidate[_-]?email)$", "email"),
    (r"^(phone|phone[_-]?number|tel|telephone|mobile)$", "phone"),
    (r"^(resume|cv|resume[_-]?file|resume[_-]?upload|attachments?\[resume\])$", "resume"),
    (r"^(cover[_-]?letter|coverletter|comments)$", "cover_letter"),
    (r"^(cover[_-]?letter[_-]?file|cover_letter_upload)$", "cover_letter_file"),
    (r"^urls\[linkedin\]$|^linkedin(_url|_profile)?$", "linkedin"),
    (r"^urls\[github\]$|^github(_url)?$", "github"),
    (r"^urls\[(portfolio|other|website)\]$|^(website|portfolio)(_url)?$", "website"),
    (r"^(location|current[_-]?location)$", "location"),
    (r"^org$|^current[_-]?company$", "current_company"),
]


@dataclass
class Match:
    key: str | None
    confidence: str          # high | medium | low
    evidence: str = ""


@dataclass(frozen=True)
class Pattern:
    key: str
    text: str                # normalizado
    words: int
    weight: int = 10


@lru_cache
def global_patterns() -> tuple[Pattern, ...]:
    data = yaml.safe_load(PATTERNS_FILE.read_text(encoding="utf-8")) or {}
    out = []
    for key, por_idioma in data.items():
        for lista in (por_idioma or {}).values():
            for p in lista or []:
                n = norm(str(p))
                out.append(Pattern(key, n, len(n.split())))
    return tuple(out)


def pack_patterns(pack: Pack | None) -> list[Pattern]:
    out = []
    for k in (pack.answer_keys if pack else []):
        for lista in k.patterns.values():
            for p in lista:
                n = norm(p)
                out.append(Pattern(k.key, n, len(n.split()), weight=12))  # el nicho gana empates
    return out


@lru_cache(maxsize=8192)
def _rx(texto: str) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9])" + re.escape(texto) + r"(?![a-z0-9])")


def match_field(label: str, name: str = "", autocomplete: str = "", patterns: list[Pattern] | None = None) -> Match:
    ac = (autocomplete or "").strip().lower().split()[-1:] if autocomplete else []
    if ac and ac[0] in AUTOCOMPLETE:
        return Match(AUTOCOMPLETE[ac[0]], "high", f"autocomplete={ac[0]}")
    nombre = (name or "").strip().lower()
    for rx, key in NAME_HINTS:
        if nombre and re.search(rx, nombre):
            return Match(key, "high", f"name={nombre}")

    etiqueta = norm(label).replace("*", " ").strip()
    if not etiqueta:
        return Match(None, "low", "sin etiqueta")
    candidatos: list[tuple[int, int, int, str, str]] = []
    for p in list(global_patterns()) + list(patterns or []):
        if p.text and _rx(p.text).search(etiqueta):
            exacto = int(etiqueta == p.text)
            candidatos.append((exacto, p.words, p.weight, p.key, p.text))
    if not candidatos:
        return Match(None, "low", "pregunta desconocida")
    candidatos.sort(reverse=True)
    mejor = candidatos[0]
    claves = {c[3] for c in candidatos}
    if mejor[0] or len(claves) == 1:
        conf = "high"
    elif len(candidatos) > 1 and candidatos[1][:3] == mejor[:3] and candidatos[1][3] != mejor[3]:
        conf = "low"      # empate entre dos claves distintas: que lo revise el usuario
    else:
        conf = "medium"
    return Match(mejor[3], conf, f"«{mejor[4]}»")
