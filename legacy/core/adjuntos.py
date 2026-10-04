"""Archivos que se adjuntan a los correos (CV, certificados…), uno o varios por idioma.

Se suben desde el panel (Configuración → Archivos adjuntos) y se guardan en datos/adjuntos/es y
datos/adjuntos/en. A cada empresa se le adjuntan los del idioma de su correo.
"""
import mimetypes
import os
import re

from . import config

IDIOMAS = ("es", "en")
MAX_BYTES = 15 * 1024 * 1024        # por archivo
MAX_TOTAL = 20 * 1024 * 1024        # por idioma (Gmail no admite más de 25 MB por correo)
EXTENSIONES = (".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".jpg", ".jpeg", ".png")


def carpeta(idioma):
    if idioma not in IDIOMAS:
        raise ValueError("Idioma no válido")
    ruta = config.ruta(os.path.join("datos", "adjuntos", idioma))
    os.makedirs(ruta, exist_ok=True)
    return ruta


def nombre_seguro(nombre):
    """Solo el nombre del archivo, sin rutas ni caracteres raros."""
    nombre = os.path.basename((nombre or "").replace("\\", "/"))
    nombre = re.sub(r"[^\w.\- ()áéíóúñÁÉÍÓÚÑüÜ]", "_", nombre).strip(" .")
    if not nombre:
        raise ValueError("Nombre de archivo no válido")
    base, ext = os.path.splitext(nombre)
    return base[:100] + ext.lower()


def listar(idioma):
    c = carpeta(idioma)
    return [{"nombre": n, "tamano": os.path.getsize(os.path.join(c, n))}
            for n in sorted(os.listdir(c)) if os.path.isfile(os.path.join(c, n))]


def todos():
    return {i: listar(i) for i in IDIOMAS}


def guardar(idioma, nombre, datos):
    nombre = nombre_seguro(nombre)
    if not nombre.lower().endswith(EXTENSIONES):
        raise ValueError(f"Tipo de archivo no admitido. Usa: {', '.join(EXTENSIONES)}")
    if len(datos) > MAX_BYTES:
        raise ValueError("El archivo pesa más de 15 MB")
    ocupado = sum(a["tamano"] for a in listar(idioma) if a["nombre"] != nombre)
    if ocupado + len(datos) > MAX_TOTAL:
        raise ValueError("Entre todos los archivos de este idioma pasarían de 20 MB (Gmail admite 25 MB por correo)")
    with open(os.path.join(carpeta(idioma), nombre), "wb") as f:
        f.write(datos)
    return nombre


def borrar(idioma, nombre):
    ruta = os.path.join(carpeta(idioma), nombre_seguro(nombre))
    if os.path.isfile(ruta):
        os.remove(ruta)


def ruta_archivo(idioma, nombre):
    ruta = os.path.join(carpeta(idioma), nombre_seguro(nombre))
    if not os.path.isfile(ruta):
        raise LookupError("Archivo no encontrado")
    return ruta


def para_correo(cfg, idioma):
    """Rutas de los archivos a adjuntar a un correo en ese idioma.
    Si no has subido ninguno para ese idioma, se usa el CV antiguo (perfil.cv) si existe."""
    if not cfg["envio"]["adjuntar_cv"]:
        return []
    c = carpeta(idioma)
    rutas = [os.path.join(c, a["nombre"]) for a in listar(idioma)]
    if not rutas:
        antiguo = config.ruta(cfg["perfil"].get("cv") or "")
        if cfg["perfil"].get("cv") and os.path.isfile(antiguo):
            rutas = [antiguo]
    return rutas


def tipo(ruta):
    return mimetypes.guess_type(ruta)[0] or "application/octet-stream"
