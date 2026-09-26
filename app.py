"""Busca Prácticas — panel local.

Uso:  python app.py      y abre http://127.0.0.1:8765
"""
import json
import mimetypes
import os
import re
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from core import config, correo, db
from core.motor import Motor, enviados_hoy

PUERTO = int(os.environ.get("PUERTO", 8765))
ESTATICOS = os.path.join(config.RAIZ, "static")
motor = Motor()


# ---------------------------------------------------------------- lógica de la API

def api_estado(_):
    cfg = config.cargar()
    modo = cfg["modo"]
    with db.conectar(modo) as con:
        uno = lambda sql, *a: con.execute(sql, a).fetchone()[0]
        categorias = {r[0]: r[1] for r in con.execute(
            "SELECT categoria, count(DISTINCT empresa_id) FROM respuestas GROUP BY categoria")}
        kpis = {
            "empresas": uno("SELECT count(*) FROM empresas"),
            "con_email": uno("SELECT count(*) FROM empresas WHERE email <> ''"),
            "agencias": uno("SELECT count(*) FROM empresas WHERE tipo='agencia'"),
            "enviados": uno("SELECT count(DISTINCT empresa_id) FROM correos WHERE estado='enviado'"),
            "respondidas": uno("SELECT count(DISTINCT empresa_id) FROM respuestas"),
            "no_leidas": uno("SELECT count(*) FROM respuestas WHERE leida=0"),
            "pendientes_envio": uno("SELECT count(*) FROM empresas WHERE estado='nueva' AND email <> ''"),
            "errores": uno("SELECT count(*) FROM empresas WHERE estado='error'"),
            "categorias": categorias,
        }
    return {
        "modo": modo,
        "motor": motor.estado,
        "kpis": kpis,
        "problemas": correo.problemas_envio(cfg),
        "enviados_hoy": enviados_hoy(modo),
        "limite_diario": cfg["envio"]["limite_diario"],
    }


def api_empresas(_):
    with db.conectar() as con:
        return db.filas(con.execute("""
            SELECT e.*,
                   (SELECT max(enviado_en) FROM correos c WHERE c.empresa_id = e.id) AS ultimo_envio,
                   (SELECT count(*) FROM respuestas r WHERE r.empresa_id = e.id) AS n_respuestas,
                   (SELECT categoria FROM respuestas r WHERE r.empresa_id = e.id
                     ORDER BY recibido_en DESC LIMIT 1) AS ultima_categoria
            FROM empresas e ORDER BY e.id DESC"""))


def api_empresa(_, id_):
    with db.conectar() as con:
        e = con.execute("SELECT * FROM empresas WHERE id=?", (id_,)).fetchone()
        if not e:
            raise LookupError("Empresa no encontrada")
        return {
            "empresa": dict(e),
            "correos": db.filas(con.execute("SELECT * FROM correos WHERE empresa_id=? ORDER BY enviado_en", (id_,))),
            "respuestas": db.filas(con.execute(
                "SELECT * FROM respuestas WHERE empresa_id=? ORDER BY recibido_en", (id_,))),
        }


def api_crear_empresa(d):
    nombre = (d.get("nombre") or "").strip()
    if not nombre:
        raise ValueError("El nombre es obligatorio")
    email = (d.get("email") or "").strip()
    with db.conectar() as con:
        cur = con.execute(
            """INSERT INTO empresas(nombre, tipo, sector, ciudad, email, web, fuente, estado, creado)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (nombre, d.get("tipo") or "empresa", d.get("sector", ""), d.get("ciudad", ""), email,
             d.get("web", ""), "manual", "nueva" if email else "sin_email", db.ahora()))
        return {"id": cur.lastrowid}


def api_editar_empresa(d, id_):
    with db.conectar() as con:
        e = con.execute("SELECT * FROM empresas WHERE id=?", (id_,)).fetchone()
        if not e:
            raise LookupError("Empresa no encontrada")
        email = d.get("email", e["email"]).strip()
        estado = d.get("estado", e["estado"])
        if estado not in ("nueva", "sin_email", "enviado", "respondida", "descartada", "error"):
            raise ValueError("Estado no válido")
        if estado in ("sin_email", "nueva"):
            estado = "nueva" if email else "sin_email"
        con.execute("UPDATE empresas SET email=?, estado=?, notas=? WHERE id=?",
                    (email, estado, d.get("notas", e["notas"]), id_))
    return {"ok": True}


def api_respuestas(_):
    with db.conectar() as con:
        return db.filas(con.execute("""
            SELECT r.*, e.nombre AS empresa, e.tipo AS empresa_tipo
            FROM respuestas r LEFT JOIN empresas e ON e.id = r.empresa_id
            ORDER BY r.recibido_en DESC, r.id DESC"""))


def api_marcar_leida(d, id_):
    with db.conectar() as con:
        con.execute("UPDATE respuestas SET leida=? WHERE id=?", (1 if d.get("leida", True) else 0, id_))
    return {"ok": True}


def api_cambiar_categoria(d, id_):
    if d.get("categoria") not in ("entrevista", "info", "rechazo", "automatica", "otra"):
        raise ValueError("Categoría no válida")
    with db.conectar() as con:
        con.execute("UPDATE respuestas SET categoria=? WHERE id=?", (d["categoria"], id_))
    return {"ok": True}


def api_eventos(q):
    desde = int(q.get("desde", ["0"])[0])
    with db.conectar() as con:
        return db.filas(con.execute(
            "SELECT * FROM (SELECT * FROM eventos WHERE id > ? ORDER BY id DESC LIMIT 200) ORDER BY id",
            (desde,)))


def api_guardar_config(d):
    actual = config.cargar()
    if motor.estado["ejecutando"] and d.get("modo", actual["modo"]) != actual["modo"]:
        raise ValueError("No puedes cambiar de modo mientras el proceso está en marcha")
    cfg = config.guardar(d)
    if cfg["modo"] != actual["modo"]:
        db.evento(f"Cambiado a modo '{cfg['modo']}'.", "aviso", cfg["modo"])
    return cfg


def api_vista_previa(d):
    cfg = config.cargar()
    if d.get("config"):
        cfg = config._fusionar(cfg, d["config"])
    ejemplo = {"nombre": "Empresa Ejemplo S.L." if d.get("tipo") != "agencia" else "Agencia Ejemplo",
               "tipo": d.get("tipo", "empresa"), "ciudad": cfg["busqueda"]["ciudad"], "sector": "Informática"}
    asunto, cuerpo = correo.componer(cfg, ejemplo)
    return {"asunto": asunto, "cuerpo": cuerpo}


def api_iniciar(_):
    if not motor.iniciar():
        raise ValueError("Ya hay un proceso en marcha")
    return {"ok": True}


def api_detener(_):
    motor.detener()
    return {"ok": True}


def api_comprobar(_):
    return {"nuevas": motor.comprobar_respuestas(forzar=True)}


def api_borrar_datos(d):
    modo = config.cargar()["modo"]
    if motor.estado["ejecutando"]:
        raise ValueError("Detén el proceso antes de borrar los datos")
    if modo == "real" and d.get("confirmacion") != "BORRAR":
        raise ValueError("Para borrar los datos reales escribe BORRAR")
    db.borrar(modo)
    db.evento("Datos de este modo borrados.", "aviso", modo)
    return {"ok": True}


RUTAS = [
    ("GET", r"/api/estado", api_estado),
    ("GET", r"/api/empresas", api_empresas),
    ("GET", r"/api/empresas/(\d+)", api_empresa),
    ("POST", r"/api/empresas", api_crear_empresa),
    ("POST", r"/api/empresas/(\d+)", api_editar_empresa),
    ("GET", r"/api/respuestas", api_respuestas),
    ("POST", r"/api/respuestas/(\d+)/leida", api_marcar_leida),
    ("POST", r"/api/respuestas/(\d+)/categoria", api_cambiar_categoria),
    ("GET", r"/api/eventos", api_eventos),
    ("GET", r"/api/config", lambda _: config.cargar()),
    ("POST", r"/api/config", api_guardar_config),
    ("POST", r"/api/vista-previa", api_vista_previa),
    ("POST", r"/api/iniciar", api_iniciar),
    ("POST", r"/api/detener", api_detener),
    ("POST", r"/api/comprobar", api_comprobar),
    ("POST", r"/api/borrar-datos", api_borrar_datos),
]


# ---------------------------------------------------------------- servidor HTTP

class Manejador(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # silencio: el registro útil está en el panel

    def _json(self, codigo, datos):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _api(self, metodo):
        url = urlparse(self.path)
        for m, patron, fn in RUTAS:
            coincide = re.fullmatch(patron, url.path)
            if m != metodo or not coincide:
                continue
            try:
                if metodo == "GET":
                    arg = parse_qs(url.query)
                else:
                    largo = int(self.headers.get("Content-Length") or 0)
                    arg = json.loads(self.rfile.read(largo) or b"{}")
                self._json(200, fn(arg, *(int(g) for g in coincide.groups())))
            except LookupError as ex:
                self._json(404, {"error": str(ex)})
            except ValueError as ex:
                self._json(400, {"error": str(ex)})
            except Exception as ex:
                self._json(500, {"error": f"{type(ex).__name__}: {ex}"})
            return
        self._json(404, {"error": "Ruta no encontrada"})

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._api("GET")
        ruta = urlparse(self.path).path
        ruta = "index.html" if ruta in ("", "/") else ruta.lstrip("/")
        fichero = os.path.normpath(os.path.join(ESTATICOS, ruta))
        if not fichero.startswith(ESTATICOS) or not os.path.isfile(fichero):
            self.send_error(404)
            return
        with open(fichero, "rb") as f:
            datos = f.read()
        tipo = mimetypes.guess_type(fichero)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo.endswith("javascript"):
            tipo += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(datos)

    def do_POST(self):
        if not self.path.startswith("/api/"):
            self.send_error(404)
            return
        # Solo aceptar peticiones desde el propio panel (evita que otra web abierta dispare envíos)
        origen = self.headers.get("Origin")
        if origen and urlparse(origen).hostname not in ("127.0.0.1", "localhost"):
            self._json(403, {"error": "Origen no permitido"})
            return
        self._api("POST")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not os.path.exists(config.RUTA_CONFIG):
        config.guardar(config.POR_DEFECTO)
    motor.vigilar()
    servidor = ThreadingHTTPServer(("127.0.0.1", PUERTO), Manejador)
    url = f"http://127.0.0.1:{PUERTO}"
    print(f"Panel en {url}  (Ctrl+C para salir)")
    if "--sin-navegador" not in sys.argv:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nHasta luego.")


if __name__ == "__main__":
    main()
