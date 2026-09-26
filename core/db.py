"""Base de datos SQLite. Cada modo (simulacion / prueba / real) tiene su propio fichero,
así los datos de prueba nunca se mezclan con los envíos reales."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from . import config

ESQUEMA = """
CREATE TABLE IF NOT EXISTS empresas (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'empresa',      -- empresa | agencia
    sector TEXT DEFAULT '',
    ciudad TEXT DEFAULT '',
    email TEXT DEFAULT '',
    web TEXT DEFAULT '',
    telefono TEXT DEFAULT '',
    fuente TEXT DEFAULT '',
    ref_externa TEXT DEFAULT '',
    estado TEXT NOT NULL DEFAULT 'nueva',      -- nueva | sin_email | enviado | respondida | descartada | error
    notas TEXT DEFAULT '',
    creado TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_empresas_ref ON empresas(ref_externa) WHERE ref_externa <> '';
CREATE INDEX IF NOT EXISTS ix_empresas_email ON empresas(email);

CREATE TABLE IF NOT EXISTS correos (
    id INTEGER PRIMARY KEY,
    empresa_id INTEGER NOT NULL REFERENCES empresas(id),
    destinatario TEXT NOT NULL,                -- a quién se envió realmente
    asunto TEXT NOT NULL,
    cuerpo TEXT NOT NULL,
    message_id TEXT NOT NULL,
    modo TEXT NOT NULL,
    estado TEXT NOT NULL,                      -- enviado | error
    error TEXT DEFAULT '',
    enviado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_correos_msgid ON correos(message_id);

CREATE TABLE IF NOT EXISTS respuestas (
    id INTEGER PRIMARY KEY,
    empresa_id INTEGER REFERENCES empresas(id),
    correo_id INTEGER REFERENCES correos(id),
    remitente TEXT NOT NULL,
    asunto TEXT NOT NULL,
    cuerpo TEXT NOT NULL,
    categoria TEXT NOT NULL,                   -- entrevista | info | rechazo | automatica | otra
    recibido_en TEXT NOT NULL,
    leida INTEGER NOT NULL DEFAULT 0,
    simulada INTEGER NOT NULL DEFAULT 0,
    uid_imap TEXT DEFAULT ''
);

-- Respuestas simuladas pendientes de "llegar" (solo modo simulación)
CREATE TABLE IF NOT EXISTS respuestas_programadas (
    id INTEGER PRIMARY KEY,
    empresa_id INTEGER NOT NULL,
    correo_id INTEGER NOT NULL,
    tipo TEXT NOT NULL,
    llega_en TEXT NOT NULL
);

-- UIDs de IMAP ya revisados, para no volver a descargarlos
CREATE TABLE IF NOT EXISTS imap_vistos (uid TEXT PRIMARY KEY);

CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    nivel TEXT NOT NULL,                       -- info | ok | aviso | error
    mensaje TEXT NOT NULL
);
"""


def ahora():
    return datetime.now().isoformat(timespec="seconds")


def ruta_db(modo):
    carpeta = config.ruta("datos")
    os.makedirs(carpeta, exist_ok=True)
    return os.path.join(carpeta, f"{modo}.db")


@contextmanager
def conectar(modo=None):
    """Abre, hace commit (o rollback si falla) y cierra siempre."""
    modo = modo or config.cargar()["modo"]
    con = sqlite3.connect(ruta_db(modo), timeout=15)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(ESQUEMA)
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def filas(cur):
    return [dict(r) for r in cur.fetchall()]


def evento(mensaje, nivel="info", modo=None):
    with conectar(modo) as con:
        con.execute("INSERT INTO eventos(ts, nivel, mensaje) VALUES (?,?,?)", (ahora(), nivel, mensaje))
    print(f"[{nivel}] {mensaje}")


def borrar(modo):
    p = ruta_db(modo)
    for sufijo in ("", "-wal", "-shm"):
        if os.path.exists(p + sufijo):
            os.remove(p + sufijo)
