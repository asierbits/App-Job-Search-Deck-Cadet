"""Respuestas simuladas para probar el panel sin enviar nada de verdad."""
import random
from datetime import datetime, timedelta

from . import db

TIPOS = [("entrevista", 0.25), ("info", 0.30), ("rechazo", 0.35), ("automatica", 0.10)]

TEXTOS = {
    "entrevista": [
        ("Re: {asunto}",
         "Hola {nombre}:\n\nGracias por escribirnos. Tenemos previsto embarcar alumnos de puente en los "
         "próximos meses y nos gustaría conocerte. ¿Tendrías disponibilidad para una videollamada de 30 "
         "minutos esta semana?\n\nUn saludo,\nDepartamento de Flota\n{empresa}"),
        ("Re: {asunto}",
         "Buenos días {nombre},\n\nHemos revisado tu CV. Podrías embarcar el mes que viene en uno de "
         "nuestros buques; antes queremos hacerte una breve entrevista. Indícanos qué día te viene mejor."
         "\n\nSaludos,\nPersonal de Flota\n{empresa}"),
    ],
    "info": [
        ("Re: {asunto}",
         "Hola {nombre}:\n\nGracias por tu interés. Para valorar tu candidatura necesitamos copia de tu "
         "libreta marítima, el certificado médico en vigor y tus certificados STCW. ¿Nos los puedes "
         "enviar?\n\nUn saludo,\n{empresa}"),
        ("Re: {asunto}",
         "Hola:\n\nGracias por el CV. Los alumnos se gestionan a través de nuestro portal de tripulación: "
         "te pedimos que completes allí el formulario para que tu candidatura quede registrada."
         "\n\nSaludos,\n{empresa}"),
    ],
    "rechazo": [
        ("Re: {asunto}",
         "Hola {nombre}:\n\nMuchas gracias por contactar con {empresa}. Lamentablemente, en este momento no "
         "disponemos de plazas de alumno en nuestra flota. Guardaremos tu CV para futuras oportunidades."
         "\n\nTe deseamos mucha suerte."),
        ("Re: {asunto}",
         "Estimado/a {nombre}:\n\nAgradecemos tu interés, pero ahora mismo tenemos cubiertas todas las "
         "plazas de alumnos de puente y en este momento no podemos ofrecerte embarque.\n\nUn saludo,\n{empresa}"),
    ],
    "automatica": [
        ("Respuesta automática: {asunto}",
         "Gracias por tu mensaje. Esta es una respuesta automática: hemos recibido tu correo y lo "
         "revisaremos lo antes posible.\n\n{empresa}"),
    ],
}


TEXTOS_EN = {
    "entrevista": [
        ("Re: {asunto}",
         "Hi {nombre},\n\nThanks for reaching out. We are planning to take on new deck cadets and would "
         "like to schedule a short video call with you. What is your availability next week?"
         "\n\nBest regards,\nCrewing Department\n{empresa}"),
    ],
    "info": [
        ("Re: {asunto}",
         "Hi {nombre},\n\nThanks for your message. Cadet applications at {empresa} are handled through our "
         "crew portal, so please complete the application form there and upload your STCW certificates."
         "\n\nKind regards,\nCrewing\n{empresa}"),
    ],
    "rechazo": [
        ("Re: {asunto}",
         "Dear {nombre},\n\nThank you for your interest in {empresa}. Unfortunately, all our cadet positions "
         "are filled at the moment. We will keep your CV on file.\n\nBest of luck!"),
    ],
    "automatica": [
        ("Automatic reply: {asunto}",
         "Thank you for your message. This is an automatic reply to confirm that we have received your "
         "email.\n\n{empresa}"),
    ],
}


def programar(cfg, empresa, correo_id):
    """Decide al azar si la empresa 'contestará' y cuándo."""
    s = cfg["simulacion"]
    if random.random() > float(s["prob_respuesta"]):
        return
    tipo = random.choices([t for t, _ in TIPOS], weights=[p for _, p in TIPOS])[0]
    retraso = random.uniform(float(s["retraso_min_seg"]), float(s["retraso_max_seg"]))
    llega = (datetime.now() + timedelta(seconds=retraso)).isoformat(timespec="seconds")
    with db.conectar("simulacion") as con:
        con.execute("INSERT INTO respuestas_programadas(empresa_id, correo_id, tipo, llega_en) VALUES (?,?,?,?)",
                    (empresa["id"], correo_id, tipo, llega))


def entregar_pendientes(cfg):
    """Mueve a la bandeja las respuestas simuladas cuya hora ya ha llegado. Devuelve cuántas."""
    from .correo import clasificar  # import aquí para evitar import circular

    with db.conectar("simulacion") as con:
        pendientes = db.filas(con.execute(
            """SELECT p.*, e.nombre AS empresa, e.email, e.pais, c.asunto
               FROM respuestas_programadas p
               JOIN empresas e ON e.id = p.empresa_id
               JOIN correos c ON c.id = p.correo_id
               WHERE p.llega_en <= ?""", (db.ahora(),)))
        entregadas = []
        for p in pendientes:
            # Reclamar la fila primero: si otro proceso ya la entregó, no duplicar
            if con.execute("DELETE FROM respuestas_programadas WHERE id = ?", (p["id"],)).rowcount != 1:
                continue
            entregadas.append(p)
            textos = TEXTOS if (p["pais"] or "es") == "es" else TEXTOS_EN
            plantilla_asunto, plantilla_cuerpo = random.choice(textos[p["tipo"]])
            valores = {"nombre": cfg["perfil"]["nombre"], "empresa": p["empresa"], "asunto": p["asunto"]}
            asunto = plantilla_asunto.format(**valores)
            cuerpo = plantilla_cuerpo.format(**valores)
            con.execute(
                """INSERT INTO respuestas(empresa_id, correo_id, remitente, asunto, cuerpo, categoria,
                                          recibido_en, simulada)
                   VALUES (?,?,?,?,?,?,?,1)""",
                (p["empresa_id"], p["correo_id"], f"{p['empresa']} <{p['email']}>", asunto, cuerpo,
                 clasificar(asunto, cuerpo), db.ahora()))
            con.execute("UPDATE empresas SET estado = 'respondida' WHERE id = ?", (p["empresa_id"],))
    for p in entregadas:
        db.evento(f"Respuesta (simulada) de {p['empresa']}", "ok", "simulacion")
    return len(entregadas)
