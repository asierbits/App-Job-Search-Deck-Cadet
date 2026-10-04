"""Correo entrante reenviado a knok (opción B de detección de respuestas, sin leer Gmail).

El usuario crea en Gmail un filtro (knok genera el XML para importarlo) que reenvía a
u-<token>@<dominio de knok> los correos de las empresas a las que ha escrito. Un receptor (p. ej.
Cloudflare Email Routing + Worker, gratis) entrega el correo en bruto a POST /inbound/email.
"""
import re
from dataclasses import dataclass, field
from email import message_from_bytes, policy
from email.utils import getaddresses, parseaddr
from xml.sax.saxutils import quoteattr

TOKEN_RE = re.compile(r"\bu-([a-z0-9]{8,40})@", re.I)
QUOTE_RE = re.compile(r"^\s*(El|On|Le|Am|Il)\s.+(escribió|wrote|a écrit|schrieb|ha scritto)\s*:?\s*$", re.I)
FORWARD_RE = re.compile(r"^-{2,}\s*(Forwarded message|Mensaje reenviado|Message transféré|Weitergeleitete Nachricht)", re.I)


@dataclass
class Inbound:
    tokens: list[str]
    from_addr: str
    from_name: str
    subject: str
    body: str
    message_id: str
    references: list[str] = field(default_factory=list)
    auto_submitted: bool = False
    original_from: str = ""            # remitente original si el correo vino reenviado "a mano"
    gmail_confirmation: str = ""       # código de confirmación del reenvío de Gmail


def _body(msg) -> str:
    parte = msg.get_body(preferencelist=("plain", "html"))
    if parte is None:
        return ""
    contenido = parte.get_content()
    if parte.get_content_type() == "text/html":
        contenido = re.sub(r"<(br|/p|/div)\s*/?>", "\n", contenido, flags=re.I)
        contenido = re.sub(r"<[^>]+>", "", contenido)
    return contenido


def strip_quoted(texto: str) -> str:
    """Quita el texto citado (el correo original) para quedarse con la respuesta."""
    out = []
    for linea in texto.splitlines():
        if QUOTE_RE.match(linea) or linea.startswith(">"):
            break
        out.append(linea)
    return "\n".join(out).strip()


def parse(raw: bytes, envelope_to: str = "") -> Inbound:
    msg = message_from_bytes(raw, policy=policy.default)
    destinos = " ".join([envelope_to] + [str(msg.get(h, "")) for h in ("Delivered-To", "X-Original-To", "X-Forwarded-To",
                                                                        "To", "Cc")])
    tokens = list(dict.fromkeys(t.lower() for t in TOKEN_RE.findall(destinos)))
    nombre, remitente = parseaddr(str(msg.get("From", "")))
    refs = re.findall(r"<[^>]+>", f"{msg.get('In-Reply-To', '')} {msg.get('References', '')}")
    cuerpo = _body(msg)
    original = ""
    if FORWARD_RE.search(cuerpo):   # reenviado a mano: el remitente real está en el bloque citado
        m = re.search(r"^(?:From|De|Von|Da):\s*(.+)$", cuerpo, re.M)
        if m:
            original = (getaddresses([m.group(1)])[0][1] or "").lower()
    asunto = str(msg.get("Subject", ""))
    codigo = ""
    if remitente.lower().startswith("forwarding-noreply@google.com"):
        m = re.search(r"\b(\d{6,12})\b", asunto + " " + cuerpo)
        codigo = m.group(1) if m else ""
    auto = str(msg.get("Auto-Submitted", "no")).lower() not in ("", "no") or bool(msg.get("X-Autoreply"))
    return Inbound(tokens=tokens, from_addr=remitente.lower(), from_name=nombre, subject=asunto,
                   body=strip_quoted(cuerpo) if not original else cuerpo.strip(),
                   message_id=str(msg.get("Message-ID", "")).strip(), references=refs, auto_submitted=auto,
                   original_from=original, gmail_confirmation=codigo)


def gmail_filter_xml(domains: list[str], forward_to: str, max_query: int = 1200) -> str:
    """Filtros de Gmail importables (Ajustes → Filtros → Importar). Se trocean: Gmail limita la longitud."""
    grupos, actual = [], []
    for d in sorted(set(domains)):
        prueba = actual + [d]
        if actual and len(" OR ".join("@" + x for x in prueba)) + 2 > max_query:
            grupos.append(actual)
            actual = [d]
        else:
            actual = prueba
    if actual:
        grupos.append(actual)
    entradas = []
    for g in grupos:
        consulta = "(" + " OR ".join("@" + x for x in g) + ")"
        entradas.append(
            "  <entry>\n    <category term='filter'></category>\n    <title>knok: respuestas de empresas</title>\n"
            "    <content></content>\n"
            f"    <apps:property name='from' value={quoteattr(consulta)}/>\n"
            f"    <apps:property name='forwardTo' value={quoteattr(forward_to)}/>\n"
            "    <apps:property name='sizeOperator' value='s_sl'/>\n    <apps:property name='sizeUnit' value='s_smb'/>\n"
            "  </entry>")
    return ("<?xml version='1.0' encoding='UTF-8'?>\n"
            "<feed xmlns='http://www.w3.org/2005/Atom' xmlns:apps='http://schemas.google.com/apps/2006'>\n"
            "  <title>Mail Filters</title>\n" + "\n".join(entradas) + "\n</feed>\n")
