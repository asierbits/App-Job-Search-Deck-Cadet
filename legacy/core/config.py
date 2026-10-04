"""Carga y guarda la configuración (config.json) y los secretos (secretos.json)."""
import copy
import json
import os
import threading

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_CONFIG = os.path.join(RAIZ, "config.json")
RUTA_SECRETOS = os.path.join(RAIZ, "secretos.json")

MODOS = ("simulacion", "prueba", "real")

from .maritimo import DIRECTORIOS as DIRECTORIOS_MARITIMOS  # noqa: E402

POR_DEFECTO = {
    # simulacion: no sale nada de tu PC | prueba: envíos reales pero a tu propio correo | real: envía a las empresas
    "modo": "simulacion",
    "perfil": {
        "nombre": "Tu Nombre",
        "email": "tu.correo@gmail.com",
        "telefono": "",
        "titulacion": "Grado en Náutica y Transporte Marítimo",
        "titulacion_en": "BSc in Nautical Science and Maritime Transport",  # para los correos en inglés
        "universidad": "Universidad de ...",
        "linkedin": "",
        "cv": "datos/cv.pdf",
    },
    "busqueda": {
        # maritimo: navieras europeas (Wikidata + directorios de asociaciones de navieros)
        # osm: OpenStreetMap alrededor de ciudades | ejemplo: empresas ficticias (@example.com)
        "fuente": "maritimo",
        "usar_wikidata": True,
        "directorios": list(DIRECTORIOS_MARITIMOS),  # "url" o "url | país" (web o PDF)
        "ciudades": ["Bilbao"],          # solo para OpenStreetMap (cualquier país)
        "radio_km": 10,
        "tipos": ["empresa", "agencia"],
        "palabras_clave": "",
        "max_resultados": 60,            # por ciudad (OpenStreetMap)
        "buscar_email_web": True,        # rastrear a fondo la web de cada empresa
        "max_webs_por_ejecucion": 1000,
    },
    "envio": {
        "asunto": "Solicitud de embarque como alumno de puente - {nombre}",
        "plantilla": (
            "Estimado equipo de {empresa}:\n\n"
            "Mi nombre es {nombre} y he finalizado el {titulacion} en la {universidad}. Me pongo en "
            "contacto con ustedes porque busco embarque como alumno de puente para realizar el periodo "
            "de prácticas a bordo necesario para obtener mi título profesional.\n\n"
            "Me encantaría poder hacerlo en su flota. Tengo disponibilidad inmediata para embarcar y les "
            "adjunto mi currículum con mi formación y certificados.\n\n"
            "Quedo a su disposición para ampliar cualquier información o para una entrevista.\n\n"
            "Muchas gracias por su atención.\n\n"
            "Un saludo,\n{nombre}\n{telefono}\n{linkedin}"
        ),
        "plantilla_agencia": (
            "Estimado equipo de {empresa}:\n\n"
            "Mi nombre es {nombre} y he finalizado el {titulacion} en la {universidad}. Busco embarque "
            "como alumno de puente para completar el periodo de prácticas a bordo necesario para mi "
            "título profesional, y me gustaría que tuvieran en cuenta mi perfil para cualquiera de las "
            "navieras con las que trabajan.\n\n"
            "Tengo disponibilidad inmediata para embarcar. Les adjunto mi currículum.\n\n"
            "Muchas gracias.\n\n"
            "Un saludo,\n{nombre}\n{telefono}\n{linkedin}"
        ),
        # Versiones en inglés: se usan con empresas de fuera de España
        "asunto_en": "Deck Cadet application - {nombre}",
        "plantilla_en": (
            "Dear {empresa} team,\n\n"
            "My name is {nombre} and I have recently completed my {titulacion} at {universidad}. "
            "I am writing to apply for a Deck Cadet position, as I am looking for a vessel on which to "
            "complete the onboard sea service required for my Officer of the Watch certificate.\n\n"
            "I would be very keen to join your fleet. I am available to embark immediately, and I have "
            "attached my CV with my training and certificates.\n\n"
            "Please let me know if you need any further information or would like to arrange an interview.\n\n"
            "Thank you for your time and consideration.\n\n"
            "Kind regards,\n{nombre}\n{telefono}\n{linkedin}"
        ),
        "plantilla_agencia_en": (
            "Dear {empresa} team,\n\n"
            "My name is {nombre} and I have recently completed my {titulacion} at {universidad}. "
            "I am looking for a Deck Cadet position to complete the onboard sea service required for my "
            "Officer of the Watch certificate, and I would be grateful if you could consider my profile "
            "for any of the shipping companies you work with.\n\n"
            "I am available to embark immediately. Please find my CV attached.\n\n"
            "Thank you very much.\n\n"
            "Kind regards,\n{nombre}\n{telefono}\n{linkedin}"
        ),
        "adjuntar_cv": True,
        "max_por_ejecucion": 10,
        "limite_diario": 20,
        "pausa_segundos": 45,
    },
    "servidor_correo": {
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 465,
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "usuario": "",
        "intervalo_comprobacion_seg": 60,
    },
    "simulacion": {
        "prob_respuesta": 0.6,
        "retraso_min_seg": 8,
        "retraso_max_seg": 45,
    },
}

# Textos por defecto de versiones anteriores (prácticas genéricas). Si la configuración guardada
# conserva uno de estos sin tocar, se sustituye por el nuevo por defecto (embarque de alumno de puente).
ANTIGUOS = {
    "envio.asunto": "Solicitud de prácticas - {nombre}",
    "envio.plantilla": (
            "Hola, equipo de {empresa}:\n\n"
            "Mi nombre es {nombre} y acabo de terminar el {titulacion} en la {universidad}. "
            "Estoy buscando mi primera experiencia profesional como alumno en prácticas y me encantaría "
            "poder aprender y aportar en {empresa}.\n\n"
            "Os adjunto mi currículum. Tengo disponibilidad inmediata y estaría encantado de "
            "concertar una breve llamada o entrevista cuando os venga bien.\n\n"
            "Muchas gracias por vuestro tiempo.\n\n"
            "Un saludo,\n{nombre}\n{telefono}\n{linkedin}"
        ),
    "envio.plantilla_agencia": (
            "Hola, equipo de {empresa}:\n\n"
            "Mi nombre es {nombre} y acabo de terminar el {titulacion} en la {universidad}. "
            "Estoy buscando mi primera oportunidad de prácticas y me gustaría que tuvierais en cuenta "
            "mi perfil para los procesos que gestionéis en {ciudad} o en remoto.\n\n"
            "Os adjunto mi currículum. Tengo disponibilidad inmediata.\n\n"
            "Muchas gracias.\n\n"
            "Un saludo,\n{nombre}\n{telefono}\n{linkedin}"
        ),
    "envio.asunto_en": "Internship application - {nombre}",
    "envio.plantilla_en": (
            "Dear {empresa} team,\n\n"
            "My name is {nombre} and I have just completed my {titulacion} at {universidad}. "
            "I am looking for my first professional experience as an intern, and I would love the "
            "opportunity to learn and contribute at {empresa} in {ciudad}.\n\n"
            "Please find my CV attached. I am available to start immediately and would be happy to "
            "arrange a short call or interview at your convenience.\n\n"
            "Thank you for your time.\n\n"
            "Kind regards,\n{nombre}\n{telefono}\n{linkedin}"
        ),
    "envio.plantilla_agencia_en": (
            "Dear {empresa} team,\n\n"
            "My name is {nombre} and I have just completed my {titulacion} at {universidad}. "
            "I am looking for my first internship and would be grateful if you could consider my "
            "profile for any suitable opportunities in {ciudad} or remotely.\n\n"
            "Please find my CV attached. I am available to start immediately.\n\n"
            "Thank you very much.\n\n"
            "Kind regards,\n{nombre}\n{telefono}\n{linkedin}"
        ),
    "perfil.titulacion": "Grado en ...",
}

_lock = threading.Lock()


def _fusionar(base, extra):
    """Mezcla recursiva: las claves nuevas del por-defecto aparecen aunque config.json sea antiguo."""
    res = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(res.get(k), dict):
            res[k] = _fusionar(res[k], v)
        else:
            res[k] = v
    return res


def cargar():
    with _lock:
        datos = {}
        if os.path.exists(RUTA_CONFIG):
            with open(RUTA_CONFIG, encoding="utf-8") as f:
                datos = json.load(f)
        cfg = _fusionar(POR_DEFECTO, datos)
        if cfg["modo"] not in MODOS:
            cfg["modo"] = "simulacion"
        # Textos por defecto antiguos que nunca se editaron → los nuevos (embarque de alumno de puente)
        for ruta, antiguo in ANTIGUOS.items():
            seccion, clave = ruta.split(".")
            if cfg[seccion].get(clave) == antiguo:
                cfg[seccion][clave] = POR_DEFECTO[seccion][clave]
        # Versiones antiguas tenían una sola "ciudad"
        b = cfg["busqueda"]
        antigua = b.pop("ciudad", None)
        if antigua and "ciudades" not in datos.get("busqueda", {}):
            b["ciudades"] = [antigua]
        b["ciudades"] = [c.strip() for c in b["ciudades"] if c.strip()] or ["Bilbao"]
        return cfg


def guardar(nueva):
    cfg = _fusionar(POR_DEFECTO, nueva)
    if cfg["modo"] not in MODOS:
        raise ValueError("Modo no válido")
    with _lock:
        with open(RUTA_CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    return cfg


def contrasena_correo():
    """La contraseña vive solo en secretos.json (ignorado por git) y el panel nunca la recibe de vuelta."""
    if os.environ.get("BUSCATRABAJO_PASS"):
        return os.environ["BUSCATRABAJO_PASS"]
    if os.path.exists(RUTA_SECRETOS):
        with open(RUTA_SECRETOS, encoding="utf-8") as f:
            return json.load(f).get("smtp_password", "")
    return ""


def guardar_contrasena(contrasena):
    with _lock:
        with open(RUTA_SECRETOS, "w", encoding="utf-8") as f:
            json.dump({"smtp_password": contrasena}, f, indent=2)


def cuenta():
    """Estado de la cuenta de correo conectada (sin exponer la contraseña)."""
    usuario = cargar()["servidor_correo"]["usuario"]
    return {"usuario": usuario, "conectada": bool(usuario and contrasena_correo())}


def ruta(rel):
    return rel if os.path.isabs(rel) else os.path.join(RAIZ, rel)
