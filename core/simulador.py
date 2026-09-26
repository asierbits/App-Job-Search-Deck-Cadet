"""Respuestas simuladas para probar el panel sin enviar nada de verdad."""
import random
from datetime import datetime, timedelta

from . import db

TIPOS = [("entrevista", 0.25), ("info", 0.30), ("rechazo", 0.35), ("automatica", 0.10)]

TEXTOS = {
    "entrevista": [
        ("Re: {asunto}",
         "Hola {nombre}:\n\nGracias por escribirnos. Nos ha gustado tu perfil y nos gustaría conocerte. "
         "¿Tendrías disponibilidad para una videollamada de 30 minutos esta semana o la próxima?\n\n"
         "Un saludo,\nEquipo de Personas\n{empresa}"),
        ("Re: {asunto}",
         "Buenos días {nombre},\n\nHemos revisado tu CV y queremos invitarte a una entrevista en nuestra "
         "oficina. Indícanos qué día te viene mejor.\n\nSaludos,\n{empresa}"),
    ],
    "info": [
        ("Re: {asunto}",
         "Hola {nombre}:\n\nGracias por tu interés. Para prácticas trabajamos mediante convenio con la "
         "universidad. ¿Podrías indicarnos si sigues matriculado o si tu universidad gestiona prácticas "
         "para titulados recientes?\n\nUn saludo,\n{empresa}"),
        ("Re: {asunto}",
         "Hola:\n\nGracias por el CV. Te pedimos que completes también el formulario de nuestro portal de "
         "empleo para que tu candidatura quede registrada.\n\nSaludos,\n{empresa}"),
    ],
    "rechazo": [
        ("Re: {asunto}",
         "Hola {nombre}:\n\nMuchas gracias por contactar con {empresa}. Lamentablemente, en este momento no "
         "disponemos de plazas de prácticas. Guardaremos tu CV para futuras oportunidades.\n\n"
         "Te deseamos mucha suerte."),
        ("Re: {asunto}",
         "Estimado/a {nombre}:\n\nAgradecemos tu interés, pero ahora mismo no estamos buscando perfiles en "
         "prácticas.\n\nUn saludo,\n{empresa}"),
    ],
    "automatica": [
        ("Respuesta automática: {asunto}",
         "Gracias por tu mensaje. Esta es una respuesta automática: hemos recibido tu correo y lo "
         "revisaremos lo antes posible.\n\n{empresa}"),
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
            """SELECT p.*, e.nombre AS empresa, e.email, c.asunto
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
            plantilla_asunto, plantilla_cuerpo = random.choice(TEXTOS[p["tipo"]])
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
