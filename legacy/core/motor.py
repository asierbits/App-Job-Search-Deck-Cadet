"""Procesos en segundo plano, en dos pasos que decides tú:

  1. buscar():  busca navieras y rastrea sus webs. NO envía nada. Se ve en directo qué web se está
                rastreando y qué se encuentra en cada una.
  2. enviar():  escribe solo a las empresas que hayas seleccionado en la pestaña Navieras.

Además, un hilo revisa las respuestas periódicamente.
"""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from . import busqueda, config, correo, db, maritimo, simulador, webemail

RASTREOS_A_LA_VEZ = 6
HORAS_ENTRE_LECTURAS = 24  # las fuentes de navieras se vuelven a leer como mucho una vez al día


def firma_busqueda(b):
    """Resumen de la configuración de búsqueda: si cambia (otra fuente, otros directorios…), se releen las fuentes."""
    claves = ("fuente", "usar_wikidata", "directorios", "ciudades", "radio_km", "tipos", "palabras_clave", "max_resultados")
    return json.dumps({k: b.get(k) for k in claves}, sort_keys=True, ensure_ascii=False)


class Motor:
    def __init__(self):
        self._lock = threading.Lock()
        self._detener = threading.Event()
        self._hilo = None
        self.estado = {"ejecutando": False, "tarea": None, "fase": "Parado", "hecho": 0, "total": 0, "en_curso": []}
        self._en_curso = {}  # id → nombre de las webs que se están rastreando ahora mismo
        self._ultima_imap = 0.0
        self._ultimo_error_imap = ""
        self.ultima_revision = None  # hora ISO de la última lectura de la bandeja

    # ------------------------------------------------------------ arranque de las tareas

    def _lanzar(self, tarea, destino):
        with self._lock:
            if self.estado["ejecutando"]:
                return False
            self._detener.clear()
            self._en_curso.clear()
            self.estado = {"ejecutando": True, "tarea": tarea, "fase": "Preparando", "hecho": 0, "total": 0,
                           "en_curso": []}
            self._hilo = threading.Thread(target=self._envolver, args=(destino,), daemon=True)
            self._hilo.start()
            return True

    def buscar(self, forzar=False):
        return self._lanzar("buscar", lambda cfg, modo: self._buscar(cfg, modo, forzar))

    def enviar(self):
        return self._lanzar("enviar", self._enviar)

    def rastrear_pendientes(self):
        """Solo el rastreo (sin volver a buscar): para seguir con las webs que quedaron pendientes."""
        return self._lanzar("buscar", lambda cfg, modo: self._rastrear_webs(cfg, modo))

    def detener(self):
        self._detener.set()

    def _fase(self, fase, hecho=0, total=0):
        self.estado.update({"fase": fase, "hecho": hecho, "total": total})

    def _envolver(self, destino):
        cfg = config.cargar()
        modo = cfg["modo"]
        try:
            destino(cfg, modo)
        except Exception as ex:
            db.evento(f"Error: {ex}", "error", modo)
        finally:
            self._en_curso.clear()
            self.estado.update({"ejecutando": False, "fase": "Parado", "en_curso": []})

    # ------------------------------------------------------------ paso 1: buscar y rastrear

    def _buscar(self, cfg, modo, forzar=False):
        b = cfg["busqueda"]
        # Las fuentes (Wikidata, directorios…) cambian poco: se leen como mucho una vez al día, salvo que
        # cambies la configuración de la búsqueda o lo fuerces. Lo ya guardado y analizado nunca se repite.
        firma = firma_busqueda(b)
        leidas = db.leer_meta("fuentes_leidas", modo)
        misma = db.leer_meta("fuentes_firma", modo) == firma
        if not forzar and misma and leidas and \
                datetime.now() - datetime.fromisoformat(leidas) < timedelta(hours=HORAS_ENTRE_LECTURAS):
            horas = (datetime.now() - datetime.fromisoformat(leidas)).total_seconds() / 3600
            hace = f"{int(horas * 60)} min" if horas < 1 else f"{horas:.0f} h"
            db.evento(f"Las fuentes se leyeron hace {hace}: no se vuelven a leer hasta dentro de "
                      f"{HORAS_ENTRE_LECTURAS} h. Se analizan solo las navieras pendientes.", "info", modo)
            self._rastrear_webs(cfg, modo)
            return
        self._fase("Buscando navieras")
        if b["fuente"] == "maritimo":
            n = len([d for d in b["directorios"] if d.strip()]) + (1 if b["usar_wikidata"] else 0)
            db.evento(f"Buscando navieras europeas en {n} fuente(s)…", "info", modo)
        elif b["fuente"] == "osm":
            db.evento(f"Buscando en OpenStreetMap en {len(b['ciudades'])} ciudad(es): "
                      f"{', '.join(b['ciudades'])}…", "info", modo)
        else:
            db.evento("Buscando en los datos de ejemplo…", "info", modo)
        resultados = busqueda.buscar(
            cfg,
            al_progresar=self._fase,
            al_avisar=lambda nivel, msg: db.evento(msg, nivel, modo),
            cancelado=self._detener.is_set)
        nuevas, repetidas = busqueda.guardar(resultados)
        if self._detener.is_set():
            db.evento("Detenido por el usuario.", "aviso", modo)
            return
        db.guardar_meta("fuentes_leidas", db.ahora(), modo)
        db.guardar_meta("fuentes_firma", firma, modo)
        if nuevas:
            db.evento(f"{nuevas} navieras nuevas" + (f" (las {repetidas} que ya tenías no se repiten)" if repetidas else "")
                      + ".", "ok", modo)
        else:
            db.evento(f"No hay navieras nuevas: las {repetidas} ya estaban guardadas y no se vuelven a analizar.",
                      "ok", modo)
        self._rastrear_webs(cfg, modo)

    def _rastrear_webs(self, cfg, modo):
        b = cfg["busqueda"]
        if b["buscar_email_web"]:
            if not self._buscar_emails_web(modo, int(b["max_webs_por_ejecucion"])):
                db.evento("Todas las navieras guardadas ya están analizadas: no hay nada nuevo que rastrear.", "ok", modo)
                return
        if self._detener.is_set():
            db.evento("Detenido por el usuario. Lo que falte se rastreará la próxima vez.", "aviso", modo)
        else:
            db.evento("Búsqueda terminada. Revisa las navieras y elige a cuáles escribir.", "ok", modo)

    def _buscar_emails_web(self, modo, maximo):
        """Rastrea a fondo la web de las empresas aún no revisadas (primero las españolas)."""
        with db.conectar(modo) as con:
            empresas = db.filas(con.execute(
                "SELECT * FROM empresas WHERE estado IN ('sin_email', 'nueva') AND web <> '' AND email_buscado = '' "
                "ORDER BY (pais = 'es') DESC, id LIMIT ?", (maximo,)))
            quedan = con.execute("SELECT count(*) FROM empresas WHERE estado IN ('sin_email', 'nueva') "
                                 "AND web <> '' AND email_buscado = ''").fetchone()[0] - len(empresas)
        if not empresas:
            return 0
        db.evento(f"Rastreando a fondo {len(empresas)} web(s) nuevas o pendientes" + (f" (quedan {quedan} para la próxima vez)" if quedan else "")
                  + "…", "info", modo)
        mejorados = cadetes = portales = hechas = reutilizadas = con_avisos = 0
        self._fase("Rastreando webs", 0, len(empresas))

        def uno(e):
            # Si se pulsa Detener, las que aún no han empezado se saltan (quedan para la próxima vez)
            if self._detener.is_set():
                return None
            with self._lock:
                self._en_curso[e["id"]] = e["nombre"]
                self.estado["en_curso"] = [{"id": i, "nombre": n} for i, n in self._en_curso.items()]
            try:
                return rastrear_empresa(e, modo)
            finally:
                with self._lock:
                    self._en_curso.pop(e["id"], None)
                    self.estado["en_curso"] = [{"id": i, "nombre": n} for i, n in self._en_curso.items()]

        # Cada web es de un servidor distinto: se rastrean varias a la vez sin cargar a ninguno
        with ThreadPoolExecutor(max_workers=RASTREOS_A_LA_VEZ) as grupo:
            for r in grupo.map(uno, empresas):
                hechas += 1
                self._fase("Rastreando webs", hechas, len(empresas))
                if r:
                    mejorados += bool(r.get("nuevo_email"))
                    cadetes += bool(r.get("cadetes"))
                    portales += bool(r.get("web_empleo"))
                    reutilizadas += bool(r.get("reutilizado"))
                    con_avisos += bool(r.get("avisos"))
        db.evento(f"Rastreo: {mejorados} emails nuevos o mejores, {cadetes} webs que hablan de cadetes, "
                  f"{portales} páginas de empleo/tripulación"
                  + (f", ⚠ {con_avisos} con avisos (cobro, Ucrania o Mar Negro) para revisar" if con_avisos else "")
                  + (f" ({reutilizadas} webs ya rastreadas antes, reutilizadas al instante)" if reutilizadas else "")
                  + ".", "ok", modo)
        return len(empresas)

    # ------------------------------------------------------------ paso 2: enviar a las seleccionadas

    def _enviar(self, cfg, modo):
        problemas = correo.problemas_envio(cfg)
        if problemas:
            for p in problemas:
                db.evento(p, "error", modo)
            db.evento("No se ha enviado nada: corrige la configuración.", "error", modo)
            return

        limite = int(cfg["envio"]["max_por_ejecucion"])
        if modo != "simulacion":
            restantes_hoy = int(cfg["envio"]["limite_diario"]) - enviados_hoy(modo)
            if restantes_hoy <= 0:
                db.evento("Límite diario de envíos alcanzado. Las seleccionadas se enviarán mañana.", "aviso", modo)
                return
            limite = min(limite, restantes_hoy)

        with db.conectar(modo) as con:
            pendientes = db.filas(con.execute(
                "SELECT * FROM empresas WHERE seleccionada = 1 AND estado = 'nueva' AND email <> '' "
                "ORDER BY cadetes DESC, (pais = 'es') DESC, id LIMIT ?", (limite,)))
            total_sel = con.execute("SELECT count(*) FROM empresas WHERE seleccionada = 1 AND estado = 'nueva' "
                                    "AND email <> ''").fetchone()[0]
        if not pendientes:
            db.evento("No hay navieras seleccionadas con email. Márcalas en la pestaña Navieras.", "aviso", modo)
            return
        if total_sel > len(pendientes):
            db.evento(f"Se enviarán {len(pendientes)} de {total_sel} seleccionadas (límite por envío o diario); "
                      "el resto quedan seleccionadas para la próxima vez.", "info", modo)

        pausa = 1.5 if modo == "simulacion" else float(cfg["envio"]["pausa_segundos"])
        for i, e in enumerate(pendientes):
            if self._detener.is_set():
                db.evento("Detenido por el usuario.", "aviso", modo)
                break
            self._fase("Enviando correos", i, len(pendientes))
            # Reservar la empresa: si ya no está pendiente (otro proceso, o la descartaste), saltarla
            with db.conectar(modo) as con:
                reservada = con.execute("UPDATE empresas SET estado='enviando', seleccionada=0 "
                                        "WHERE id=? AND estado='nueva'", (e["id"],)).rowcount == 1
            if not reservada:
                continue
            try:
                correo.enviar(cfg, e)
                etiqueta = {"simulacion": "simulado", "prueba": "a tu correo (prueba)", "real": "enviado"}[modo]
                db.evento(f"Correo a {e['nombre']} <{e['email']}> — {etiqueta}", "ok", modo)
            except correo.FaltanAdjuntos as ex:
                # No es culpa de la naviera: queda pendiente y seleccionada para cuando subas los archivos
                with db.conectar(modo) as con:
                    con.execute("UPDATE empresas SET estado='nueva', seleccionada=1 WHERE id=?", (e["id"],))
                db.evento(f"No enviado a {e['nombre']}: {ex}. Sigue seleccionada.", "aviso", modo)
            except Exception as ex:  # un fallo en una empresa no para el resto
                with db.conectar(modo) as con:
                    con.execute("UPDATE empresas SET estado='error', notas=? WHERE id=?", (str(ex), e["id"]))
                db.evento(f"Error enviando a {e['nombre']}: {ex}", "error", modo)
            self._fase("Enviando correos", i + 1, len(pendientes))
            if i < len(pendientes) - 1:
                self._detener.wait(pausa)
        db.evento("Envío terminado. Las respuestas irán apareciendo en el panel.", "ok", modo)

    # ------------------------------------------------------------ respuestas

    def comprobar_respuestas(self, forzar=False):
        cfg = config.cargar()
        if cfg["modo"] == "simulacion":
            return simulador.entregar_pendientes(cfg)
        if correo.problemas_envio(cfg):
            return 0
        if not forzar and not enviados_total(cfg["modo"]):
            return 0  # aún no se ha escrito a nadie: no gastar el intervalo
        intervalo = float(cfg["servidor_correo"]["intervalo_comprobacion_seg"])
        if not forzar and time.time() - self._ultima_imap < intervalo:
            return 0
        self._ultima_imap = time.time()
        try:
            n = correo.comprobar_imap(cfg)
            self._ultimo_error_imap = ""
            self.ultima_revision = db.ahora()
            if n:
                db.evento(f"{n} respuesta(s) nueva(s) en tu bandeja de entrada.", "ok")
            return n
        except Exception as ex:
            if str(ex) != self._ultimo_error_imap:  # no llenar el registro con el mismo error
                db.evento(f"No se pudo leer el correo (IMAP): {ex}", "error")
                self._ultimo_error_imap = str(ex)
            if forzar:
                raise
            return 0

    def vigilar(self):
        """Hilo que revisa respuestas cada pocos segundos (simulación) o cada intervalo (IMAP)."""
        def bucle():
            while True:
                try:
                    self.comprobar_respuestas()
                except Exception as ex:
                    print("vigilancia:", ex)
                time.sleep(3)
        threading.Thread(target=bucle, daemon=True).start()


    def revision(self, cfg):
        """Cuándo se leyó la bandeja por última vez y en cuántos segundos toca la siguiente."""
        if cfg["modo"] == "simulacion" or not self._ultima_imap:
            return {"ultima": self.ultima_revision, "proxima_seg": None}
        intervalo = float(cfg["servidor_correo"]["intervalo_comprobacion_seg"])
        return {"ultima": self.ultima_revision,
                "proxima_seg": max(0, round(self._ultima_imap + intervalo - time.time()))}


DIAS_VALIDEZ_RASTREO = 30  # pasado este tiempo, la web se vuelve a rastrear por si ha cambiado


def _rastreo_guardado(web):
    """Rastreo de esta web hecho en cualquier modo en los últimos días, o None."""
    dom = webemail.dominio(web if "://" in web else "https://" + web)
    limite = (datetime.now() - timedelta(days=DIAS_VALIDEZ_RASTREO)).isoformat(timespec="seconds")
    with db.conectar_rastreos() as con:
        # Los rastreos antiguos (sin términos de cadetes ni avisos) no sirven: se vuelven a hacer
        f = con.execute("SELECT * FROM rastreos WHERE dominio = ? AND fecha >= ? AND menciones IS NOT NULL",
                        (dom, limite)).fetchone()
    if not f:
        return None
    return {"email": f["email"], "email_fuente": f["email_fuente"], "web_empleo": f["web_empleo"],
            "cadetes": bool(f["cadetes"]), "nombre": f["nombre"] or "", "bloqueada": bool(f["bloqueada"]),
            "menciones": [m for m in f["menciones"].split("|") if m], "avisos": json.loads(f["avisos"] or "[]"),
            "reutilizado": True}


def _guardar_rastreo(web, r):
    dom = webemail.dominio(web if "://" in web else "https://" + web)
    with db.conectar_rastreos() as con:
        con.execute("INSERT OR REPLACE INTO rastreos(dominio, email, email_fuente, web_empleo, nombre, cadetes, "
                    "bloqueada, fecha, menciones, avisos) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (dom, r["email"], r["email_fuente"], r["web_empleo"], r["nombre"], int(r["cadetes"]),
                     int(r["bloqueada"]), db.ahora(), "|".join(r.get("menciones") or []),
                     json.dumps(r.get("avisos") or [], ensure_ascii=False)))


def rastrear_empresa(e, modo=None, reutilizar=True):
    """Rastrea la web de una empresa y guarda lo encontrado. Si ya se rastreó hace poco (en cualquier modo),
    se reutiliza sin volver a visitarla. Solo cambia el email si aún no se le ha escrito y el nuevo es
    mejor (p. ej. crewing@ frente a info@). Devuelve el resultado del rastreo."""
    r = _rastreo_guardado(e["web"]) if reutilizar else None
    if r is None:
        try:
            r = webemail.rastrear(e["web"])
            if r.get("leida") or r.get("bloqueada"):  # si la web no respondió, no se recuerda: se reintentará
                _guardar_rastreo(e["web"], r)
        except Exception:
            r = {"email": None, "email_fuente": None, "web_empleo": None, "cadetes": False, "nombre": "",
                 "bloqueada": False, "menciones": [], "avisos": []}
    avisos = list(r.get("avisos") or [])
    if (e.get("pais") == "ua" or webemail.dominio("https://" + e["web"].split("://")[-1]).endswith(".ua")) \
            and not any(a["tipo"] == "ucrania" for a in avisos):
        avisos.insert(0, {"tipo": "ucrania", "texto": "Empresa registrada en Ucrania (país o dominio .ua).", "url": e["web"]})
    nuevo = None
    if r["email"] and e["estado"] in ("nueva", "sin_email") and r["email"] != e["email"]:
        if not e["email"] or webemail.puntuacion(r["email"], e["web"]) > webemail.puntuacion(e["email"], e["web"]):
            nuevo = r["email"]
    nombre = e["nombre"]
    if r["nombre"] and nombre == maritimo.nombre_bonito(webemail.dominio(e["web"])):
        nombre = r["nombre"]  # el nombre salió del dominio: mejor el que da su propia web
    with db.conectar(modo) as con:
        con.execute(
            """UPDATE empresas SET email_buscado=?, nombre=?, cadetes=?, web_bloqueada=?, menciones=?, avisos=?,
                   web_empleo=CASE WHEN ? <> '' THEN ? ELSE web_empleo END,
                   email=COALESCE(?, email), email_fuente=CASE WHEN ? IS NOT NULL THEN ? ELSE email_fuente END,
                   estado=CASE WHEN ? IS NOT NULL AND estado='sin_email' THEN 'nueva' ELSE estado END
               WHERE id=?""",
            (db.ahora(), nombre, int(r["cadetes"]), int(r["bloqueada"]),
             "|".join(r.get("menciones") or []), json.dumps(avisos, ensure_ascii=False),
             r["web_empleo"] or "", r["web_empleo"] or "",
             nuevo, nuevo, r["email_fuente"], nuevo, e["id"]))
    if nuevo:
        db.evento(f"{nombre}: {'email mejor encontrado' if e['email'] else 'email encontrado'} en su web → {nuevo}", "ok", modo)
    r["nuevo_email"] = nuevo
    return r


def buscar_email_empresa(e, modo=None):
    """Rastrea una empresa a petición (botón «Rastrear de nuevo»): siempre visita la web otra vez.
    Devuelve el email con el que queda, o None."""
    r = rastrear_empresa(e, modo, reutilizar=False)
    return r["nuevo_email"] or e["email"] or None


def enviados_total(modo):
    with db.conectar(modo) as con:
        return con.execute("SELECT count(*) FROM correos WHERE estado='enviado'").fetchone()[0]


def enviados_hoy(modo):
    with db.conectar(modo) as con:
        return con.execute("SELECT count(*) FROM correos WHERE estado='enviado' AND enviado_en >= ?",
                           (date.today().isoformat(),)).fetchone()[0]
