"""Busca Prácticas — panel local.

Uso:  python app.py      y abre http://127.0.0.1:8765
"""
import json
import mimetypes
import os
import re
import sys
import webbrowser
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from core import config, correo, db
from core.motor import Motor, buscar_email_empresa, enviados_hoy

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
            "seleccionadas": uno("SELECT count(*) FROM empresas WHERE seleccionada=1 AND estado='nueva' AND email<>''"),
            "rastreadas": uno("SELECT count(*) FROM empresas WHERE email_buscado<>''"),
            "con_avisos": uno("SELECT count(*) FROM empresas WHERE avisos NOT IN ('', '[]')"),
            "empleo_mar": uno("SELECT count(*) FROM empresas WHERE menciones LIKE '%empleo embarcado / offshore%'"),
            "cadetes": uno("SELECT count(*) FROM empresas WHERE cadetes=1"),
            "portales": uno("SELECT count(*) FROM empresas WHERE email='' AND web_empleo<>''"),
            "por_rastrear": uno("SELECT count(*) FROM empresas WHERE estado IN ('sin_email','nueva') "
                                "AND web<>'' AND email_buscado=''"),
            "categorias": categorias,
        }
        # Actividad de los últimos 14 días (envíos y respuestas por día)
        desde = (date.today() - timedelta(days=13)).isoformat()
        enviados_dia = dict(con.execute(
            "SELECT substr(enviado_en,1,10) d, count(*) FROM correos WHERE estado='enviado' AND enviado_en >= ? "
            "GROUP BY d", (desde,)).fetchall())
        respuestas_dia = dict(con.execute(
            "SELECT substr(recibido_en,1,10) d, count(*) FROM respuestas WHERE recibido_en >= ? GROUP BY d",
            (desde,)).fetchall())
    dias = [(date.today() - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
    return {
        "modo": modo,
        "nombre": cfg["perfil"]["nombre"],
        "ciudades": cfg["busqueda"]["ciudades"],
        "fuente": cfg["busqueda"]["fuente"],
        "max_por_ejecucion": cfg["envio"]["max_por_ejecucion"],
        "cuenta": config.cuenta(),
        "motor": motor.estado,
        "revision": motor.revision(cfg),
        "fuentes_leidas": db.leer_meta("fuentes_leidas", modo),
        "kpis": kpis,
        "diario": [{"dia": d, "enviados": enviados_dia.get(d, 0), "respuestas": respuestas_dia.get(d, 0)}
                   for d in dias],
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
            FROM empresas e
            ORDER BY (e.estado IN ('respondida', 'enviado')) DESC, e.cadetes DESC, (e.pais = 'es') DESC,
                     (e.email <> '') DESC, e.id DESC"""))


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
            """INSERT INTO empresas(nombre, tipo, sector, ciudad, pais, email, web, fuente, estado, creado)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (nombre, d.get("tipo") or "empresa", d.get("sector", ""), d.get("ciudad", ""),
             (d.get("pais") or "es").lower()[:2], email, d.get("web", ""), "manual",
             "nueva" if email else "sin_email", db.ahora()))
        return {"id": cur.lastrowid}


def api_buscar_email(_, id_):
    """Busca el email de una empresa en su web (a petición, desde la tabla)."""
    with db.conectar() as con:
        e = con.execute("SELECT * FROM empresas WHERE id=?", (id_,)).fetchone()
    if not e:
        raise LookupError("Empresa no encontrada")
    if not e["web"]:
        raise ValueError("Esta empresa no tiene web")
    email = buscar_email_empresa(dict(e))
    if not email:
        db.evento(f"No se encontró ningún email en la web de {e['nombre']}.", "aviso")
    return {"email": email}


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
        con.execute("UPDATE empresas SET email=?, estado=?, notas=?, "
                    "seleccionada = CASE WHEN ? = 'nueva' AND ? <> '' THEN seleccionada ELSE 0 END WHERE id=?",
                    (email, estado, d.get("notas", e["notas"]), estado, email, id_))
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
    # La cuenta solo cambia desde «Conectar Gmail», nunca al guardar el formulario
    d.setdefault("servidor_correo", {})["usuario"] = actual["servidor_correo"]["usuario"]
    cfg = config.guardar(d)
    if cfg["modo"] != actual["modo"]:
        db.evento(f"Cambiado a modo '{cfg['modo']}'.", "aviso", cfg["modo"])
    return cfg


def api_conectar_cuenta(d):
    usuario = (d.get("usuario") or "").strip().lower()
    contrasena = re.sub(r"\s+", "", d.get("contrasena") or "")  # Google la muestra en grupos de 4 con espacios
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", usuario):
        raise ValueError("Escribe una dirección de correo válida")
    if not contrasena:
        raise ValueError("Falta la contraseña de aplicación")
    cfg = config.cargar()
    correo.probar_conexion(cfg, usuario, contrasena)
    config.guardar_contrasena(contrasena)
    cfg["servidor_correo"]["usuario"] = usuario
    if cfg["perfil"]["email"] in ("", config.POR_DEFECTO["perfil"]["email"]):
        cfg["perfil"]["email"] = usuario
    config.guardar(cfg)
    db.evento(f"Cuenta de correo conectada: {usuario}", "ok")
    return config.cuenta()


def api_desconectar_cuenta(_):
    config.guardar_contrasena("")
    db.evento("Cuenta de correo desconectada.", "aviso")
    return config.cuenta()


def api_iniciar(d):
    """Paso 1: buscar navieras nuevas y rastrear las webs pendientes (no envía nada).
    Con {"forzar": true} se releen las fuentes aunque se hayan leído hoy."""
    if not motor.buscar(forzar=bool((d or {}).get("forzar"))):
        raise ValueError("Ya hay un proceso en marcha")
    return {"ok": True}


def api_rastrear_pendientes(_):
    if not motor.rastrear_pendientes():
        raise ValueError("Ya hay un proceso en marcha")
    return {"ok": True}


def api_enviar(_):
    """Paso 2: enviar el correo a las navieras seleccionadas."""
    if not motor.enviar():
        raise ValueError("Ya hay un proceso en marcha")
    return {"ok": True}


def api_seleccion(d):
    """Marca o desmarca navieras para enviarles el correo. Solo se pueden marcar las que tienen email
    y a las que aún no se ha escrito."""
    ids = [int(i) for i in d.get("ids", [])][:5000]
    valor = 1 if d.get("seleccionada", True) else 0
    if not ids:
        return {"cambiadas": 0}
    marcas = ",".join("?" * len(ids))
    condicion = "AND estado = 'nueva' AND email <> ''" if valor else ""
    with db.conectar() as con:
        n = con.execute(f"UPDATE empresas SET seleccionada = ? WHERE id IN ({marcas}) {condicion}",
                        [valor, *ids]).rowcount
    return {"cambiadas": n}


def api_correo_empresa(_, id_):
    """El correo exacto que recibiría esta empresa (asunto, texto, idioma y a quién llegaría)."""
    cfg = config.cargar()
    with db.conectar() as con:
        e = con.execute("SELECT * FROM empresas WHERE id=?", (id_,)).fetchone()
    if not e:
        raise LookupError("Empresa no encontrada")
    e = dict(e)
    asunto, cuerpo = correo.componer(cfg, e)
    destinatario = cfg["perfil"]["email"] if cfg["modo"] == "prueba" else e["email"]
    return {"asunto": asunto, "cuerpo": cuerpo, "idioma": correo.idioma(e), "destinatario": destinatario,
            "modo": cfg["modo"], "adjunto": os.path.basename(cfg["perfil"]["cv"]) if cfg["envio"]["adjuntar_cv"] else ""}


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
    ("POST", r"/api/empresas/(\d+)/buscar-email", api_buscar_email),
    ("POST", r"/api/empresas/(\d+)", api_editar_empresa),
    ("GET", r"/api/respuestas", api_respuestas),
    ("POST", r"/api/respuestas/(\d+)/leida", api_marcar_leida),
    ("POST", r"/api/respuestas/(\d+)/categoria", api_cambiar_categoria),
    ("GET", r"/api/eventos", api_eventos),
    ("GET", r"/api/config", lambda _: config.cargar()),
    ("POST", r"/api/config", api_guardar_config),
    ("GET", r"/api/config/defecto", lambda _: config.POR_DEFECTO),
    ("POST", r"/api/cuenta", api_conectar_cuenta),
    ("POST", r"/api/cuenta/desconectar", api_desconectar_cuenta),
    ("POST", r"/api/iniciar", api_iniciar),
    ("POST", r"/api/rastrear-pendientes", api_rastrear_pendientes),
    ("POST", r"/api/enviar", api_enviar),
    ("POST", r"/api/seleccion", api_seleccion),
    ("GET", r"/api/empresas/(\d+)/correo", api_correo_empresa),
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
    url = f"http://127.0.0.1:{PUERTO}"
    # En Windows, reutilizar la dirección permitiría abrir DOS paneles en el mismo puerto: los dos
    # enviarían correos y entregarían respuestas a la vez. Así, el segundo falla y abre el primero.
    ThreadingHTTPServer.allow_reuse_address = False
    try:
        servidor = ThreadingHTTPServer(("127.0.0.1", PUERTO), Manejador)
    except OSError:
        print(f"El panel ya está abierto en {url}. Lo abro en el navegador.")
        if "--sin-navegador" not in sys.argv:
            webbrowser.open(url)
        return
    motor.vigilar()
    print(f"Panel en {url}  (Ctrl+C para salir)")
    if "--sin-navegador" not in sys.argv:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nHasta luego.")


if __name__ == "__main__":
    main()
