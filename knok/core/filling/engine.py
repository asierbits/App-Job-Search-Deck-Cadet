"""Motor de relleno SIN IA.

Para cada campo del formulario:
  1. ¿El usuario ya contestó exactamente esta pregunta antes? → su respuesta (origen "custom").
  2. Si no, se reconoce la clave canónica (matcher) y se busca el valor:
       perfil → banco de respuestas → documentos → plantilla (carta) → deducción simple y explicada.
  3. Desplegables y radios: la respuesta se convierte en una de sus opciones; si no encaja, se marca.
  4. Preguntas desconocidas, consentimientos y datos sensibles sin respuesta guardada: VACÍOS y
     marcados "requiere revisión". Nunca se inventa nada.
El resultado dice, campo a campo, qué se dedujo, de dónde, con qué confianza y qué falta.
"""
from dataclasses import asdict, dataclass, field
from typing import Any

from knok.core.filling.fields import BY_KEY, is_sensitive
from knok.core.filling.matcher import Pattern, match_field
from knok.core.filling.options import as_bool, pick_option
from knok.core.geo import countries_in_text, country_from_text
from knok.core.text import norm

EU = {"at", "be", "bg", "hr", "cy", "cz", "dk", "ee", "fi", "fr", "de", "gr", "hu", "ie", "it", "lv", "lt", "lu",
      "mt", "nl", "pl", "pt", "ro", "sk", "si", "es", "se"}
EEA = EU | {"is", "li", "no"}
COUNTRY_DISPLAY = {
    "es": ("Spain", "España"), "pt": ("Portugal", "Portugal"), "fr": ("France", "Francia"), "de": ("Germany", "Alemania"),
    "it": ("Italy", "Italia"), "nl": ("Netherlands", "Países Bajos"), "be": ("Belgium", "Bélgica"),
    "gb": ("United Kingdom", "Reino Unido"), "ie": ("Ireland", "Irlanda"), "us": ("United States", "Estados Unidos"),
    "mx": ("Mexico", "México"), "ar": ("Argentina", "Argentina"), "co": ("Colombia", "Colombia"),
    "cl": ("Chile", "Chile"), "pe": ("Peru", "Perú"), "dk": ("Denmark", "Dinamarca"), "se": ("Sweden", "Suecia"),
    "no": ("Norway", "Noruega"), "fi": ("Finland", "Finlandia"), "gr": ("Greece", "Grecia"), "ch": ("Switzerland", "Suiza"),
    "at": ("Austria", "Austria"), "pl": ("Poland", "Polonia"), "cy": ("Cyprus", "Chipre"), "mt": ("Malta", "Malta"),
}
LANG_NAMES = {"es": ("Spanish", "Español"), "en": ("English", "Inglés"), "fr": ("French", "Francés"),
              "de": ("German", "Alemán"), "it": ("Italian", "Italiano"), "pt": ("Portuguese", "Portugués"),
              "nl": ("Dutch", "Neerlandés"), "ca": ("Catalan", "Catalán"), "eu": ("Basque", "Euskera"),
              "gl": ("Galician", "Gallego"), "zh": ("Chinese", "Chino"), "ar": ("Arabic", "Árabe")}


@dataclass
class FormField:
    id: str
    label: str
    type: str = "text"            # text | textarea | email | tel | url | number | date | select | multiselect | radio | checkbox | file
    required: bool = False
    options: list[dict] = field(default_factory=list)
    name: str = ""
    autocomplete: str = ""
    placeholder: str = ""
    description: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "FormField":
        return cls(id=str(d.get("id") or d.get("name") or ""), label=d.get("label") or "", type=d.get("type") or "text",
                   required=bool(d.get("required")), options=list(d.get("options") or []), name=d.get("name") or "",
                   autocomplete=d.get("autocomplete") or "", placeholder=d.get("placeholder") or "",
                   description=d.get("description") or "")


@dataclass
class FillContext:
    profile: dict
    language: str = "en"
    answers: dict[str, dict[str, Any]] = field(default_factory=dict)   # clave → {idioma | "*": valor}
    custom: dict[str, Any] = field(default_factory=dict)               # etiqueta normalizada → valor
    documents: dict[str, list[dict]] = field(default_factory=dict)     # tipo → [{id, filename, language, is_default}]
    cover_letter: str = ""
    job_country: str = ""
    patterns: list[Pattern] = field(default_factory=list)


@dataclass
class FilledField:
    id: str
    label: str
    type: str
    required: bool
    key: str | None
    value: Any
    display: str
    origin: str                   # profile | answer | custom | document | template | deduced | none
    confidence: str               # high | medium | low
    needs_review: bool
    reason: str
    options: list[dict] = field(default_factory=list)


def country_name(iso: str, lang: str) -> str:
    en, es = COUNTRY_DISPLAY.get(iso, (iso.upper(), iso.upper()))
    return es if lang == "es" else en


def _answer(ctx: FillContext, key: str):
    a = ctx.answers.get(key) or {}
    for k in (ctx.language, "*", ""):
        if k in a and a[k] not in (None, ""):
            return a[k]
    return None


def _document(ctx: FillContext, kind: str) -> dict | None:
    docs = ctx.documents.get(kind) or []
    for pref in (ctx.language, ""):
        for d in sorted(docs, key=lambda d: not d.get("is_default")):
            if d.get("language", "") == pref:
                return d
    return docs[0] if docs else None


def _countries(valor) -> set[str]:
    if isinstance(valor, str):
        valor = [v for v in valor.replace(";", ",").split(",")]
    out = set()
    for v in valor or []:
        v = str(v).strip().lower()
        if v in ("eu", "ue"):
            out |= EU
        elif v in ("eea", "eee"):
            out |= EEA
        elif v:
            out.add(country_from_text(v) or v[:2])
    return out


def _target_country(label: str, ctx: FillContext) -> str:
    """El país por el que pregunta ('…to work in Germany?'); si no nombra ninguno, el de la oferta."""
    nombrados = countries_in_text(label)
    return nombrados[0] if nombrados else ctx.job_country


def resolve(key: str, f: FormField, ctx: FillContext) -> tuple[Any, str, str]:
    """(valor, origen, motivo). Valor None = no se sabe."""
    p, links = ctx.profile, ctx.profile.get("links") or {}
    fd = BY_KEY.get(key)
    if key == "first_name":
        return p.get("first_name") or None, "profile", "nombre del perfil"
    if key == "last_name":
        return p.get("last_name") or None, "profile", "apellidos del perfil"
    if key == "full_name":
        n = " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x)
        return n or None, "profile", "nombre completo del perfil"
    if key in ("email", "phone", "city"):
        return p.get(key) or None, "profile", f"{key} del perfil"
    if key == "country":
        c = p.get("country") or ""
        return (country_name(c, ctx.language) if c else None), "profile", "país del perfil"
    if key == "location":
        partes = [p.get("city") or "", country_name(p["country"], ctx.language) if p.get("country") else ""]
        v = ", ".join(x for x in partes if x)
        return v or None, "profile", "ciudad y país del perfil"
    if key in ("linkedin", "github", "website"):
        v = links.get(key) or (links.get("portfolio") if key == "website" else None)
        return v or None, "profile", f"enlace {key} del perfil"
    if key == "resume":
        d = _document(ctx, "cv")
        return ({"document_id": d["id"], "filename": d["filename"]} if d else None), "document", "CV por defecto"
    if key == "cover_letter_file":
        d = _document(ctx, "cover_letter")
        return ({"document_id": d["id"], "filename": d["filename"]} if d else None), "document", "carta guardada"
    if key == "cover_letter":
        return ctx.cover_letter or None, "template", "carta generada con tu plantilla"
    if key == "consent":
        return None, "none", "los consentimientos los marcas tú"

    v = _answer(ctx, key)
    if v is not None:
        if key == "work_authorization" and not isinstance(v, bool):
            destino = _target_country(f.label, ctx)
            if not destino:
                return None, "answer", "no sé de qué país pregunta"
            return destino in _countries(v), "answer", f"permiso de trabajo en {destino.upper()} según tu banco"
        return v, "answer", "banco de respuestas"
    if fd and fd.sensitive:
        return None, "none", "dato sensible: solo se rellena si lo guardas en tu banco"
    if key == "needs_sponsorship":
        aut = _answer(ctx, "work_authorization")
        destino = _target_country(f.label, ctx)
        if aut is not None and destino and not isinstance(aut, bool):
            return destino not in _countries(aut), "deduced", "deducido de tu permiso de trabajo"
    if key == "languages_summary" and p.get("languages"):
        idx = 1 if ctx.language == "es" else 0
        txt = ", ".join(f"{LANG_NAMES.get(l['code'], (l['code'], l['code']))[idx]}"
                        + (f" ({l['level']})" if l.get("level") else "") for l in p["languages"])
        return txt, "deduced", "idiomas del perfil"
    if key == "degree" and (p.get("pack_data") or {}).get("titulacion"):
        pd = p["pack_data"]
        return pd.get(f"titulacion_{ctx.language}") or pd["titulacion"], "profile", "titulación del perfil"
    if key == "university" and (p.get("pack_data") or {}).get("universidad"):
        return p["pack_data"]["universidad"], "profile", "universidad del perfil"
    return None, "none", "no está en tu banco de respuestas"


def _display(valor, f: FormField) -> str:
    if isinstance(valor, dict) and "filename" in valor:
        return valor["filename"]
    if f.options:
        for o in f.options:
            if str(o.get("value", o.get("label"))) == str(valor):
                return o.get("label") or str(valor)
    if isinstance(valor, bool):
        return "Sí" if valor else "No"
    return "" if valor is None else str(valor)


def fill(fields: list[FormField], ctx: FillContext) -> dict:
    matches = [match_field(f.label, f.name, f.autocomplete, ctx.patterns) for f in fields]
    claves = {m.key for m in matches}
    # "Nombre" junto a "Apellidos" en el mismo formulario es el nombre de pila
    if "last_name" in claves and "first_name" not in claves:
        for m in matches:
            if m.key == "full_name":
                m.key, m.evidence = "first_name", m.evidence + " (hay campo de apellidos)"

    out: list[FilledField] = []
    for f, m in zip(fields, matches):
        if f.type == "hidden":
            continue
        ln = norm(f.label)
        if ln and ln in ctx.custom:
            valor, origen, motivo, conf, key = ctx.custom[ln], "custom", "ya contestaste esta pregunta", "high", m.key
        elif m.key in ("resume", "cover_letter_file") and f.type != "file":
            # "pega aquí tu CV": alternativa al archivo, que es lo que se rellena
            key, valor, origen, conf, motivo = m.key, None, "none", m.confidence, "alternativa al archivo adjunto"
        elif m.key:
            key, conf = m.key, m.confidence
            valor, origen, motivo = resolve(key, f, ctx)
            motivo = f"{motivo} · reconocida por {m.evidence}"
        else:
            key, valor, origen, conf, motivo = None, None, "none", "low", "pregunta desconocida: contéstala y se recordará"

        alternativa = motivo == "alternativa al archivo adjunto"
        revisar = (valor in (None, "") and not alternativa) or conf == "low" or key == "consent" or is_sensitive(key or "")
        if valor not in (None, "") and f.type in ("select", "radio", "multiselect") and f.options:
            elegido, por = pick_option(valor, f.options, key or "")
            if elegido is None:
                motivo += f" · tu respuesta «{valor}» no coincide con ninguna opción"
                valor, revisar = None, True
            else:
                valor, motivo = elegido, motivo + f" · opción por {por}"
        elif f.type == "checkbox" and valor not in (None, ""):
            b = as_bool(valor)
            valor = b if b is not None else valor
        elif f.type == "number" and isinstance(valor, str):
            nums = [c for c in valor if c.isdigit() or c in ".,"]
            valor = "".join(nums).replace(",", ".") or valor
        elif f.type == "file" and not isinstance(valor, dict):
            valor, revisar = None, True
            motivo = "falta el documento: súbelo en Documentos"
        out.append(FilledField(id=f.id, label=f.label, type=f.type, required=f.required, key=key, value=valor,
                               display=_display(valor, f), origin=origen if valor not in (None, "") else "none",
                               confidence=conf, needs_review=revisar, reason=motivo, options=f.options))
    faltan = [x.id for x in out if x.required and x.value in (None, "")]
    return {
        "fields": [asdict(x) for x in out],
        "missing": faltan,
        "unknown": [x.label for x in out if x.key is None and x.origin != "custom"],
        "stats": {"total": len(out), "filled": sum(x.value not in (None, "") for x in out),
                  "needs_review": sum(x.needs_review for x in out), "missing_required": len(faltan)},
    }
