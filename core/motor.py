"""Orquesta el proceso en segundo plano: buscar → guardar → enviar, y revisa respuestas periódicamente."""
import threading
import time
from datetime import date

from . import busqueda, config, correo, db, simulador


class Motor:
    def __init__(self):
        self._lock = threading.Lock()
        self._detener = threading.Event()
        self._hilo = None
        self.estado = {"ejecutando": False, "fase": "Parado", "hecho": 0, "total": 0}
        self._ultima_imap = 0.0
        self._ultimo_error_imap = ""

    # ------------------------------------------------------------ ciclo principal

    def iniciar(self):
        with self._lock:
            if self.estado["ejecutando"]:
                return False
            self._detener.clear()
            self.estado = {"ejecutando": True, "fase": "Preparando", "hecho": 0, "total": 0}
            self._hilo = threading.Thread(target=self._ejecutar, daemon=True)
            self._hilo.start()
            return True

    def detener(self):
        self._detener.set()

    def _fase(self, fase, hecho=0, total=0):
        self.estado.update({"fase": fase, "hecho": hecho, "total": total})

    def _ejecutar(self):
        cfg = config.cargar()
        modo = cfg["modo"]
        try:
            problemas = correo.problemas_envio(cfg)
            if problemas:
                for p in problemas:
                    db.evento(p, "error", modo)
                db.evento("No se ha iniciado: corrige la configuración.", "error", modo)
                return

            b = cfg["busqueda"]
            self._fase("Buscando empresas y agencias")
            db.evento(f"Buscando en '{b['fuente']}' alrededor de {b['ciudad']}…", "info", modo)
            resultados = busqueda.buscar(cfg)
            nuevas, repetidas = busqueda.guardar(resultados)
            con_email = sum(1 for r in resultados if r["email"])
            db.evento(f"Encontradas {len(resultados)} ({con_email} con email): {nuevas} nuevas, "
                      f"{repetidas} ya estaban.", "ok", modo)
            if self._detener.is_set():
                db.evento("Detenido por el usuario.", "aviso", modo)
                return

            limite = int(cfg["envio"]["max_por_ejecucion"])
            if modo != "simulacion":
                restantes_hoy = int(cfg["envio"]["limite_diario"]) - enviados_hoy(modo)
                if restantes_hoy <= 0:
                    db.evento("Límite diario de envíos alcanzado. Vuelve mañana.", "aviso", modo)
                    return
                limite = min(limite, restantes_hoy)

            with db.conectar(modo) as con:
                pendientes = db.filas(con.execute(
                    "SELECT * FROM empresas WHERE estado = 'nueva' AND email <> '' ORDER BY id LIMIT ?",
                    (limite,)))
            if not pendientes:
                db.evento("No hay empresas nuevas con email a las que escribir.", "aviso", modo)
                return

            pausa = 1.5 if modo == "simulacion" else float(cfg["envio"]["pausa_segundos"])
            for i, e in enumerate(pendientes):
                if self._detener.is_set():
                    db.evento("Detenido por el usuario.", "aviso", modo)
                    break
                self._fase("Enviando correos", i, len(pendientes))
                # Reservar la empresa: si ya no está pendiente (otro proceso, o la descartaste), saltarla
                with db.conectar(modo) as con:
                    reservada = con.execute("UPDATE empresas SET estado='enviando' WHERE id=? AND estado='nueva'",
                                            (e["id"],)).rowcount == 1
                if not reservada:
                    continue
                try:
                    correo.enviar(cfg, e)
                    etiqueta = {"simulacion": "simulado", "prueba": "a tu correo (prueba)", "real": "enviado"}[modo]
                    db.evento(f"Correo a {e['nombre']} <{e['email']}> — {etiqueta}", "ok", modo)
                except Exception as ex:  # un fallo en una empresa no para el resto
                    with db.conectar(modo) as con:
                        con.execute("UPDATE empresas SET estado='error', notas=? WHERE id=?", (str(ex), e["id"]))
                    db.evento(f"Error enviando a {e['nombre']}: {ex}", "error", modo)
                self._fase("Enviando correos", i + 1, len(pendientes))
                if i < len(pendientes) - 1:
                    self._detener.wait(pausa)
            db.evento("Proceso terminado. Las respuestas irán apareciendo en el panel.", "ok", modo)
        except Exception as ex:
            db.evento(f"Error: {ex}", "error", modo)
        finally:
            self.estado.update({"ejecutando": False, "fase": "Parado"})

    # ------------------------------------------------------------ respuestas

    def comprobar_respuestas(self, forzar=False):
        cfg = config.cargar()
        if cfg["modo"] == "simulacion":
            return simulador.entregar_pendientes(cfg)
        if correo.problemas_envio(cfg):
            return 0
        intervalo = float(cfg["servidor_correo"]["intervalo_comprobacion_seg"])
        if not forzar and time.time() - self._ultima_imap < intervalo:
            return 0
        self._ultima_imap = time.time()
        try:
            n = correo.comprobar_imap(cfg)
            self._ultimo_error_imap = ""
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


def enviados_hoy(modo):
    with db.conectar(modo) as con:
        return con.execute("SELECT count(*) FROM correos WHERE estado='enviado' AND enviado_en >= ?",
                           (date.today().isoformat(),)).fetchone()[0]
