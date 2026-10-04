"""Carga y valida los packs de nicho de knok/packs/<slug>/.

Las plantillas de `_base/` sirven a todos los packs; las del pack las sustituyen si existen.
"""
import pathlib
import re
from functools import lru_cache

import yaml

from knok.packs.schema import AnswerKey, Pack, TemplateText

PACKS_DIR = pathlib.Path(__file__).parent
_NOMBRE_PLANTILLA = re.compile(r"^(email|cover_letter|followup)_([a-z_]+)\.txt$")


class PackError(ValueError):
    pass


def parse_template(texto: str) -> TemplateText:
    """Primera línea opcional 'Subject: …', una línea en blanco y el cuerpo."""
    lineas = texto.replace("\r\n", "\n").split("\n")
    asunto = ""
    if lineas and lineas[0].lower().startswith("subject:"):
        asunto = lineas[0].split(":", 1)[1].strip()
        lineas = lineas[1:]
        while lineas and not lineas[0].strip():
            lineas.pop(0)
    return TemplateText(subject=asunto, body="\n".join(lineas).rstrip() + "\n")


def _plantillas(carpeta: pathlib.Path) -> dict[str, TemplateText]:
    res = {}
    base = carpeta / "templates"
    if not base.is_dir():
        return res
    for lang_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        for f in sorted(lang_dir.glob("*.txt")):
            m = _NOMBRE_PLANTILLA.match(f.name)
            if not m:
                raise PackError(f"Nombre de plantilla no válido: {f}")
            res[f"{m.group(1)}.{m.group(2)}.{lang_dir.name}"] = parse_template(f.read_text(encoding="utf-8"))
    return res


def load_pack(carpeta: pathlib.Path) -> Pack:
    datos = yaml.safe_load((carpeta / "pack.yaml").read_text(encoding="utf-8")) or {}
    preguntas = carpeta / "questions.yaml"
    if preguntas.exists():
        extra = yaml.safe_load(preguntas.read_text(encoding="utf-8")) or []
        datos.setdefault("answer_keys", [])
        datos["answer_keys"] += extra
    plantillas = _plantillas(PACKS_DIR / "_base")
    plantillas.update(_plantillas(carpeta))
    datos["templates"] = plantillas
    pack = Pack.model_validate(datos)
    if pack.slug != carpeta.name:
        raise PackError(f"El slug '{pack.slug}' no coincide con la carpeta '{carpeta.name}'")
    for k in pack.answer_keys:
        if not re.fullmatch(r"[a-z][a-z0-9_.]*", k.key):
            raise PackError(f"{pack.slug}: clave de respuesta no válida '{k.key}'")
    for lang in pack.languages:
        if pack.template("email", "company", lang) is None:
            raise PackError(f"{pack.slug}: falta la plantilla de correo para '{lang}'")
    return pack


@lru_cache
def all_packs() -> dict[str, Pack]:
    packs = {}
    for carpeta in sorted(PACKS_DIR.iterdir()):
        if carpeta.is_dir() and (carpeta / "pack.yaml").exists():
            p = load_pack(carpeta)
            packs[p.slug] = p
    return packs


@lru_cache
def base_templates() -> dict[str, TemplateText]:
    """Plantillas genéricas (las usan los nichos que crea el usuario)."""
    return _plantillas(PACKS_DIR / "_base")


def find_pack(slug: str | None) -> Pack | None:
    """Un pack de knok/packs/ o un nicho creado por un usuario (slug 'n-…'); None si no existe."""
    if not slug:
        return None
    packs = all_packs()
    if slug in packs:
        return packs[slug]
    from knok.packs import custom
    return custom.lookup(slug)


def pack_exists(slug: str | None) -> bool:
    return find_pack(slug) is not None


def get_pack(slug: str) -> Pack:
    p = find_pack(slug)
    if p is None:
        raise PackError(f"Pack desconocido: '{slug}'. Disponibles: {', '.join(all_packs())}")
    return p


def default_pack() -> Pack:
    """Pack genérico (sin nicho) para perfiles que aún no han elegido uno."""
    return get_pack("general")


def pack_or_default(slug: str | None) -> Pack:
    return find_pack(slug) or default_pack()


def answer_keys_for(pack: Pack) -> list[AnswerKey]:
    from knok.core.filling.fields import GLOBAL_ANSWER_KEYS
    vistos = {k.key for k in pack.answer_keys}
    return [k for k in GLOBAL_ANSWER_KEYS if k.key not in vistos] + list(pack.answer_keys)
