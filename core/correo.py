"""Composición, envío (SMTP) y lectura de respuestas (IMAP)."""
import email
import imaplib
import mimetypes
import os
import re
import smtplib
import ssl
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

from . import config, db, simulador

# ---------------------------------------------------------------- composición

def _rellenar(texto, valores):
    # Sustitución tolerante: una {variable} desconocida se deja tal cual en vez de romper
    return re.sub(r"\{(\w+)\}", lambda m: str(valores.get(m.group(1), m.group(0))), texto)


def componer(cfg, empresa):
    envio = cfg["envio"]
    valores = dict(cfg["perfil"])
    valores.update({
        "empresa": empresa["nombre"],
        "ciudad": empresa.get("ciudad") or cfg["busqueda"]["ciudad"],
        "sector": empresa.get("sector", ""),
    })
    plantilla = envio["plantilla"]
    if empresa.get("tipo") == "agencia" and envio.get("plantilla_agencia", "").strip():
        plantilla = envio["plantilla_agencia"]
    cuerpo = _rellenar(plantilla, valores)
    cuerpo = re.sub(r"\n{3,}", "\n\n", cuerpo).rstrip() + "\n"   # sin huecos si falta teléfono/LinkedIn
    return _rellenar(envio["asunto"], valores), cuerpo


# ---------------------------------------------------------------- comprobaciones

def problemas_envio(cfg):
    """Lista de cosas que impiden enviar en el modo actual (vacía = todo OK)."""
    if cfg["modo"] == "simulacion":
        return []
    p = []
    sc = cfg["servidor_correo"]
    if not sc["usuario"]:
        p.append("Falta el usuario del correo (Configuración → Servidor de correo).")
    if not config.contrasena_correo():
        p.append("Falta la contraseña de aplicación en secretos.json.")
    if cfg["modo"] == "prueba" and not cfg["perfil"]["email"]:
        p.append("Falta tu email en el perfil (en modo prueba los correos te llegan a ti).")
    if cfg["envio"]["adjuntar_cv"] and not os.path.exists(config.ruta(cfg["perfil"]["cv"])):
        p.append(f"No encuentro el CV en '{cfg['perfil']['cv']}'. Ponlo ahí o desactiva 'Adjuntar CV'.")
    return p


# ---------------------------------------------------------------- envío

def enviar(cfg, empresa):
    """Envía (o simula) el correo a una empresa. Devuelve el id del correo guardado."""
    modo = cfg["modo"]
    asunto, cuerpo = componer(cfg, empresa)
    dominio = (cfg["servidor_correo"]["usuario"] or "buscatrabajo.local").split("@")[-1]
    message_id = make_msgid(domain=dominio)

    if modo == "simulacion":
        destinatario = empresa["email"]
        _guardar_eml(asunto, cuerpo, destinatario, message_id, cfg)
    else:
        if modo == "prueba":
            destinatario = cfg["perfil"]["email"]
            asunto_real = f"[PRUEBA → {empresa['email']}] {asunto}"
            cuerpo_real = (f"(Modo prueba: este correo iba para {empresa['nombre']} <{empresa['email']}>. "
                           f"Respóndelo haciéndote pasar por la empresa para probar el panel.)\n\n{cuerpo}")
        else:
            destinatario = empresa["email"]
            asunto_real, cuerpo_real = asunto, cuerpo
        _enviar_smtp(cfg, destinatario, asunto_real, cuerpo_real, message_id)

    with db.conectar() as con:
        cur = con.execute(
            """INSERT INTO correos(empresa_id, destinatario, asunto, cuerpo, message_id, modo, estado, enviado_en)
               VALUES (?,?,?,?,?,?,?,?)""",
            (empresa["id"], destinatario, asunto, cuerpo, message_id, modo, "enviado", db.ahora()))
        correo_id = cur.lastrowid
        con.execute("UPDATE empresas SET estado = 'enviado' WHERE id = ?", (empresa["id"],))

    if modo == "simulacion":
        simulador.programar(cfg, empresa, correo_id)
    return correo_id


def _mensaje(cfg, destinatario, asunto, cuerpo, message_id):
    perfil, sc = cfg["perfil"], cfg["servidor_correo"]
    msg = EmailMessage()
    msg["From"] = f"{perfil['nombre']} <{sc['usuario'] or perfil['email']}>"
    msg["To"] = destinatario
    msg["Subject"] = asunto
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = message_id
    msg.set_content(cuerpo)
    cv = config.ruta(perfil["cv"])
    if cfg["envio"]["adjuntar_cv"] and os.path.exists(cv):
        tipo, _ = mimetypes.guess_type(cv)
        principal, secundario = (tipo or "application/octet-stream").split("/")
        with open(cv, "rb") as f:
            msg.add_attachment(f.read(), maintype=principal, subtype=secundario,
                               filename=os.path.basename(cv))
    return msg


def _guardar_eml(asunto, cuerpo, destinatario, message_id, cfg):
    """En simulación el correo se guarda como .eml para que puedas abrirlo y revisarlo."""
    carpeta = config.ruta("datos/bandeja_salida_simulacion")
    os.makedirs(carpeta, exist_ok=True)
    msg = _mensaje(cfg, destinatario, asunto, cuerpo, message_id)
    nombre = re.sub(r"[^\w.-]", "_", destinatario) + f"_{datetime.now():%Y%m%d_%H%M%S}.eml"
    with open(os.path.join(carpeta, nombre), "wb") as f:
        f.write(msg.as_bytes())


def _enviar_smtp(cfg, destinatario, asunto, cuerpo, message_id):
    sc = cfg["servidor_correo"]
    msg = _mensaje(cfg, destinatario, asunto, cuerpo, message_id)
    ctx = ssl.create_default_context()
    puerto = int(sc["smtp_port"])
    if puerto == 465:
        with smtplib.SMTP_SSL(sc["smtp_host"], puerto, context=ctx, timeout=30) as s:
            s.login(sc["usuario"], config.contrasena_correo())
            s.send_message(msg)
    else:
        with smtplib.SMTP(sc["smtp_host"], puerto, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(sc["usuario"], config.contrasena_correo())
            s.send_message(msg)


# ---------------------------------------------------------------- clasificación

REGLAS = [
    ("automatica", ["respuesta automática", "respuesta automatica", "fuera de la oficina", "out of office",
                    "auto-reply", "autoreply", "no responda a este", "mensaje automático", "de vacaciones"]),
    ("rechazo", ["lamentablemente", "no disponemos", "no tenemos vacantes", "no hay vacantes",
                 "en este momento no", "no podemos ofrecer", "no estamos buscando", "otro candidato",
                 "no encaja", "no seguiremos", "desestimad"]),
    ("entrevista", ["entrevista", "reunión", "reunion", "videollamada", "llamada", "conocerte",
                    "conocerle", "disponibilidad para", "te citamos", "¿qué día", "que dia te viene"]),
    ("info", ["más información", "mas informacion", "convenio", "portal", "formulario", "inscríbete",
              "inscribete", "referencia", "expediente", "nos envíes", "nos envies", "podrías indicarnos",
              "podrias indicarnos", "adjunta", "completar"]),
]


def clasificar(asunto, cuerpo):
    texto = f"{asunto}\n{cuerpo}".lower()
    for categoria, palabras in REGLAS:
        if any(p in texto for p in palabras):
            return categoria
    return "otra"


# ---------------------------------------------------------------- IMAP

_MESES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_DOMINIOS_GENERICOS = {"gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "yahoo.es", "icloud.com",
                       "live.com", "hotmail.es", "outlook.es", "protonmail.com", "msn.com"}


def _texto(msg):
    parte = msg.get_body(preferencelist=("plain", "html"))
    if parte is None:
        return ""
    contenido = parte.get_content()
    if parte.get_content_type() == "text/html":
        contenido = re.sub(r"<(br|/p|/div)\s*/?>", "\n", contenido, flags=re.I)
        contenido = re.sub(r"<[^>]+>", "", contenido)
    # Quitar el texto citado (tu correo original) para que solo se vea la respuesta
    lineas = []
    for linea in contenido.splitlines():
        if re.match(r"^\s*(El|On)\s.+(escribió|wrote):\s*$", linea) or linea.startswith(">"):
            break
        lineas.append(linea)
    return "\n".join(lineas).strip()


def comprobar_imap(cfg):
    """Lee la bandeja de entrada y guarda las respuestas de empresas contactadas. Devuelve cuántas nuevas."""
    sc = cfg["servidor_correo"]
    with db.conectar() as con:
        primero = con.execute("SELECT min(enviado_en) FROM correos WHERE estado='enviado'").fetchone()[0]
        if not primero:
            return 0
        correos = {r["message_id"]: dict(r) for r in con.execute("SELECT * FROM correos")}
        empresas = db.filas(con.execute("SELECT * FROM empresas WHERE email <> ''"))
        vistos = {r[0] for r in con.execute("SELECT uid FROM imap_vistos")}

    por_email = {e["email"].lower(): e for e in empresas}
    por_dominio = {}
    for e in empresas:
        dom = e["email"].lower().split("@")[-1]
        if dom not in _DOMINIOS_GENERICOS:
            por_dominio[dom] = e

    fecha = datetime.fromisoformat(primero)
    desde = f"{fecha.day:02d}-{_MESES[fecha.month - 1]}-{fecha.year}"
    nuevas = 0

    m = imaplib.IMAP4_SSL(sc["imap_host"], int(sc["imap_port"]))
    try:
        m.login(sc["usuario"], config.contrasena_correo())
        m.select("INBOX", readonly=True)
        _, datos = m.uid("search", None, f"(SINCE {desde})")
        uids = [u.decode() for u in datos[0].split() if u.decode() not in vistos]
        for uid in uids:
            _, partes = m.uid("fetch", uid, "(BODY.PEEK[])")
            crudo = next((p[1] for p in partes if isinstance(p, tuple)), None)
            with db.conectar() as con:
                con.execute("INSERT OR IGNORE INTO imap_vistos(uid) VALUES (?)", (uid,))
            if not crudo:
                continue
            msg = email.message_from_bytes(crudo, policy=policy.default)
            if msg.get("Message-ID", "").strip() in correos:
                continue  # es una copia de nuestro propio envío (pasa en modo prueba)

            referencias = re.findall(r"<[^>]+>", f"{msg.get('In-Reply-To', '')} {msg.get('References', '')}")
            correo = next((correos[r] for r in referencias if r in correos), None)
            remitente = parseaddr(msg.get("From", ""))[1].lower()
            empresa_id = correo["empresa_id"] if correo else None
            if empresa_id is None:
                e = por_email.get(remitente) or por_dominio.get(remitente.split("@")[-1])
                if e is None:
                    continue  # correo que no tiene que ver con la búsqueda
                empresa_id = e["id"]

            asunto = str(msg.get("Subject", "(sin asunto)"))
            cuerpo = _texto(msg)
            with db.conectar() as con:
                con.execute(
                    """INSERT INTO respuestas(empresa_id, correo_id, remitente, asunto, cuerpo, categoria,
                                              recibido_en, simulada, uid_imap)
                       VALUES (?,?,?,?,?,?,?,0,?)""",
                    (empresa_id, correo["id"] if correo else None, str(msg.get("From", remitente)), asunto,
                     cuerpo, clasificar(asunto, cuerpo), db.ahora(), uid))
                con.execute("UPDATE empresas SET estado = 'respondida' WHERE id = ?", (empresa_id,))
            nuevas += 1
    finally:
        try:
            m.logout()
        except Exception:
            pass
    return nuevas
