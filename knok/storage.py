"""Almacenamiento de archivos (CVs, cartas, .eml de Simulación).

Por ahora en disco (KNOK_STORAGE_DIR). La interfaz es mínima a propósito para poder cambiar a un
almacenamiento S3‑compatible (Cloudflare R2, MinIO…) sin tocar el resto del código.
"""
import mimetypes
import pathlib
import re
import secrets

from knok.settings import get_settings

MAX_FILE = 10 * 1024 * 1024          # por archivo
MAX_PER_USER = 50 * 1024 * 1024
ALLOWED_EXT = (".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".jpg", ".jpeg", ".png")


class StorageError(ValueError):
    pass


def _root() -> pathlib.Path:
    p = pathlib.Path(get_settings().storage_dir).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_filename(nombre: str) -> str:
    nombre = pathlib.PurePosixPath((nombre or "").replace("\\", "/")).name
    nombre = re.sub(r"[^\w.\- ()]", "_", nombre, flags=re.UNICODE).strip(" .")
    if not nombre:
        raise StorageError("Nombre de archivo no válido")
    base, dot, ext = nombre.rpartition(".")
    return (base[:100] + dot + ext.lower()) if dot else nombre[:100]


def _path(key: str) -> pathlib.Path:
    p = (_root() / key).resolve()
    if _root() not in p.parents:
        raise StorageError("Ruta no válida")
    return p


def save(prefix: str, filename: str, data: bytes) -> str:
    key = f"{prefix}/{secrets.token_hex(8)}_{safe_filename(filename)}"
    p = _path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return key


def read(key: str) -> bytes:
    p = _path(key)
    if not p.is_file():
        raise StorageError("Archivo no encontrado")
    return p.read_bytes()


def delete(key: str) -> None:
    p = _path(key)
    if p.is_file():
        p.unlink()


def delete_prefix(prefix: str) -> None:
    import shutil
    p = _path(prefix)
    if p.is_dir():
        shutil.rmtree(p)


def guess_mime(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"
