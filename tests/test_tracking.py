"""Seguimiento: resumen, estados, respuestas (manual y reenviadas), recordatorios y CSV."""
from datetime import timedelta
from email.message import EmailMessage

from sqlalchemy import select

from knok.core.mail.inbound import gmail_filter_xml, parse
from knok.db.models import Application, Email, Event, Profile, Reply, utcnow
from tests.test_review import preparar


def enviar_correos(client, h, n=2):
    b = preparar(client, h)
    correos = [i for i in b["items"] if i["route"] == "email" and not i["blocking"]][:n]
    client.post(f"/batches/{b['id']}/send", headers=h, json={"application_ids": [c["id"] for c in correos]})
    return b, correos


def test_resumen_y_lista(client, auth):
    b, correos = enviar_correos(client, auth)
    s = client.get("/tracking/summary", headers=auth).json()
    assert s["mode"] == "simulation"
    enviadas = sum(s["by_status"].get(k, 0) for k in ("sent", "replied", "interview", "discarded"))
    assert enviadas == 2 and len(s["daily"]) == 14 and sum(d["sent"] for d in s["daily"]) == 2
    lista = client.get("/tracking?status=sent,replied,interview,discarded", headers=auth).json()
    assert lista["total"] == 2
    assert client.get("/tracking?q=contenedores", headers=auth).json()["total"] <= 1


def test_marcado_manual_de_respuesta(client, auth):
    _, correos = enviar_correos(client, auth, 1)
    aid = correos[0]["id"]
    r = client.post(f"/applications/{aid}/replies", headers=auth,
                    json={"body": "Nos gustaría hacerte una entrevista el jueves."}).json()
    assert r["reply"]["category"] == "interview" and r["application"]["status"] == "interview"
    assert r["application"]["follow_up_at"] is None
    rid = r["reply"]["id"]
    r2 = client.patch(f"/replies/{rid}", headers=auth, json={"category": "rejection"}).json()
    assert r2["category"] == "rejection"
    assert client.get(f"/applications/{aid}", headers=auth).json()["status"] == "discarded"
    assert client.post(f"/applications/{aid}/status", headers=auth, json={"status": "interview"}).json()["status"] == "interview"


def test_exportar_csv(client, auth):
    enviar_correos(client, auth)
    r = client.get("/tracking/export.csv", headers=auth)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lineas = r.text.lstrip("﻿").strip().splitlines()
    assert lineas[0].startswith("id,status,route") and len(lineas) >= 3


def test_seguimiento_en_el_mismo_hilo(client, auth, db):
    _, correos = enviar_correos(client, auth, 1)
    aid = correos[0]["id"]
    app = db.get(Application, aid)
    db.refresh(app)
    if app.status != "sent":   # la simulación pudo responder ya: se fuerza el caso sin respuesta
        app.status = "sent"
        db.commit()
    borrador = client.get(f"/applications/{aid}/followup", headers=auth).json()
    assert borrador["available"] and borrador["subject"].startswith("Re: ") and "seguimiento" in borrador["body"]
    r = client.post(f"/applications/{aid}/followup", headers=auth, json={"subject": borrador["subject"], "body": borrador["body"]})
    assert r.status_code == 200, r.text
    db.expire_all()
    seg = db.scalar(select(Email).where(Email.application_id == aid, Email.kind == "followup"))
    assert seg.status == "sent"
    otra = client.post(f"/applications/{aid}/followup", headers=auth, json={"subject": "x", "body": "y"})
    assert otra.status_code == 409   # un solo seguimiento por candidatura


def test_recordatorio_diario_de_seguimientos(client, auth, db):
    _, correos = enviar_correos(client, auth, 1)
    app = db.get(Application, correos[0]["id"])
    app.status, app.follow_up_at = "sent", utcnow() - timedelta(days=1)
    db.commit()
    from knok.services.tracking import mark_followups_due_task
    assert mark_followups_due_task(db, {})["users"] == 1
    assert mark_followups_due_task(db, {})["users"] == 0     # una vez al día
    assert db.scalar(select(Event).where(Event.message.like("Seguimiento pendiente%")))
    assert client.get("/tracking?due=true", headers=auth).json()["total"] == 1


def correo_entrante(to, frm, subject, body, in_reply_to=""):
    m = EmailMessage()
    m["To"], m["From"], m["Subject"] = to, frm, subject
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
    m.set_content(body)
    return m.as_bytes()


def test_respuesta_reenviada_por_filtro_de_gmail(client, auth, db, monkeypatch):
    monkeypatch.setenv("KNOK_INBOUND_SECRET", "s3cr3t")
    from knok.settings import get_settings
    get_settings.cache_clear()
    _, correos = enviar_correos(client, auth, 1)
    app = db.get(Application, correos[0]["id"])
    for r in db.scalars(select(Reply)):   # partimos sin respuestas simuladas
        db.delete(r)
    app.status = "sent"
    db.commit()
    direccion = client.get("/me/reply-forwarding", headers=auth).json()["address"]
    original = db.scalar(select(Email).where(Email.application_id == app.id))
    raw = correo_entrante(f"Ana <ana@gmail.com>, {direccion}", f"RRHH <{app.contact_email}>", "Re: candidatura",
                          "Lamentablemente no tenemos vacantes.\n\nEl lun, Ana escribió:\n> Hola", original.message_id)
    assert client.post("/inbound/email", content=raw, headers={"X-Knok-Inbound-Secret": "mal"}).status_code == 401
    r = client.post("/inbound/email", content=raw, headers={"X-Knok-Inbound-Secret": "s3cr3t"}).json()
    assert r["category"] == "rejection" and r["application_id"] == app.id
    rep = client.get("/replies?unread=true", headers=auth).json()[0]
    assert rep["source"] == "forward" and "Hola" not in rep["body"]       # sin el texto citado
    # Por dominio (sin cabeceras de respuesta)
    dom = app.contact_email.split("@")[1]
    r2 = client.post("/inbound/email", headers={"X-Knok-Inbound-Secret": "s3cr3t"},
                     content=correo_entrante(direccion, f"jefa@{dom}", "Entrevista", "¿Podemos hacer una videollamada?")).json()
    assert r2["category"] == "interview"
    # Destinatario desconocido o correo ajeno: se ignora
    r3 = client.post("/inbound/email", headers={"X-Knok-Inbound-Secret": "s3cr3t"},
                     content=correo_entrante("u-nadie123456@in.knok.app", "x@otra.com", "Hola", "spam")).json()
    assert "ignored" in r3


def test_codigo_de_confirmacion_del_reenvio(client, auth, db, monkeypatch):
    monkeypatch.setenv("KNOK_INBOUND_SECRET", "s3cr3t")
    from knok.settings import get_settings
    get_settings.cache_clear()
    direccion = client.get("/me/reply-forwarding", headers=auth).json()["address"]
    raw = correo_entrante(direccion, "Gmail Team <forwarding-noreply@google.com>",
                          "(#123456789) Gmail Forwarding Confirmation", "Confirmation code: 123456789")
    assert client.post("/inbound/email", content=raw, headers={"X-Knok-Inbound-Secret": "s3cr3t"}).json() == {"gmail_confirmation": True}
    ev = client.get("/events", headers=auth).json()
    assert any("123456789" in e["message"] for e in ev)


def test_filtros_de_gmail():
    xml = gmail_filter_xml([f"empresa{i}.com" for i in range(200)], "u-abc@in.knok.app", max_query=500)
    assert xml.count("<entry>") > 1 and "u-abc@in.knok.app" in xml and "@empresa0.com OR @empresa1.com" in xml
    import xml.etree.ElementTree as ET
    ET.fromstring(xml)   # XML válido


def test_filtros_por_api(client, auth):
    assert client.get("/me/reply-forwarding/filters.xml", headers=auth).status_code == 404
    enviar_correos(client, auth)
    r = client.get("/me/reply-forwarding/filters.xml", headers=auth)
    assert r.status_code == 200 and "forwardTo" in r.text


def test_parseo_de_reenvio_manual():
    cuerpo = ("---------- Forwarded message ---------\nFrom: RRHH Empresa <rrhh@empresa.com>\nDate: lun\nSubject: Re: x\n\n"
              "Queremos conocerte")
    i = parse(correo_entrante("u-abcdefgh12@in.knok.app", "ana@gmail.com", "Fwd: Re: x", cuerpo))
    assert i.original_from == "rrhh@empresa.com" and i.tokens == ["abcdefgh12"]
