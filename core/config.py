"""Carga y guarda la configuración (config.json) y los secretos (secretos.json)."""
import copy
import json
import os
import threading

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_CONFIG = os.path.join(RAIZ, "config.json")
RUTA_SECRETOS = os.path.join(RAIZ, "secretos.json")

MODOS = ("simulacion", "prueba", "real")

POR_DEFECTO = {
    # simulacion: no sale nada de tu PC | prueba: envíos reales pero a tu propio correo | real: envía a las empresas
    "modo": "simulacion",
    "perfil": {
        "nombre": "Tu Nombre",
        "email": "tu.correo@gmail.com",
        "telefono": "",
        "titulacion": "Grado en ...",
        "universidad": "Universidad de ...",
        "linkedin": "",
        "cv": "datos/cv.pdf",
    },
    "busqueda": {
        # ejemplo: empresas ficticias (@example.com) | osm: OpenStreetMap (datos reales)
        "fuente": "ejemplo",
        "ciudad": "Bilbao",
        "radio_km": 10,
        "tipos": ["empresa", "agencia"],
        "palabras_clave": "",
        "max_resultados": 60,
    },
    "envio": {
        "asunto": "Solicitud de prácticas - {nombre}",
        "plantilla": (
            "Hola, equipo de {empresa}:\n\n"
            "Mi nombre es {nombre} y acabo de terminar el {titulacion} en la {universidad}. "
            "Estoy buscando mi primera experiencia profesional como alumno en prácticas y me encantaría "
            "poder aprender y aportar en {empresa}.\n\n"
            "Os adjunto mi currículum. Tengo disponibilidad inmediata y estaría encantado de "
            "concertar una breve llamada o entrevista cuando os venga bien.\n\n"
            "Muchas gracias por vuestro tiempo.\n\n"
            "Un saludo,\n{nombre}\n{telefono}\n{linkedin}"
        ),
        "plantilla_agencia": (
            "Hola, equipo de {empresa}:\n\n"
            "Mi nombre es {nombre} y acabo de terminar el {titulacion} en la {universidad}. "
            "Estoy buscando mi primera oportunidad de prácticas y me gustaría que tuvierais en cuenta "
            "mi perfil para los procesos que gestionéis en {ciudad} o en remoto.\n\n"
            "Os adjunto mi currículum. Tengo disponibilidad inmediata.\n\n"
            "Muchas gracias.\n\n"
            "Un saludo,\n{nombre}\n{telefono}\n{linkedin}"
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
        "intervalo_comprobacion_seg": 180,
    },
    "simulacion": {
        "prob_respuesta": 0.6,
        "retraso_min_seg": 8,
        "retraso_max_seg": 45,
    },
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
    """La contraseña nunca va en config.json ni pasa por el panel."""
    if os.environ.get("BUSCATRABAJO_PASS"):
        return os.environ["BUSCATRABAJO_PASS"]
    if os.path.exists(RUTA_SECRETOS):
        with open(RUTA_SECRETOS, encoding="utf-8") as f:
            return json.load(f).get("smtp_password", "")
    return ""


def ruta(rel):
    return rel if os.path.isabs(rel) else os.path.join(RAIZ, rel)
