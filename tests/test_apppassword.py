"""Gmail con contraseña de aplicación (panel local): conectar, enviar por SMTP y leer respuestas por IMAP."""
from email.message import EmailMessage

import pytest

from knok.core.mail import apppassword
from knok.settings import get_settings
from tests.test_review import preparar


@pytest.fixture
def local(client, monkeypatch):
    monkeypatch.setenv("KNOK_LOCAL_SINGLE_USER", "true")
    get_settings.cache_clear()
    h = {"Authorization": f"Bearer {client.get('/auth/local').json()['token']}"}
    llamadas = {"login": [], "send": [], "buzon": []}
    monkeypatch.setattr(apppassword, "check_login", lambda u, p: llamadas["login"].append((u, p)))
    monkeypatch.setattr(apppassword, "send", lambda u, p, raw, to: llamadas["send"].append((u, raw, to)))

    def leer(u, p, desde, interesa, limit=300):
        return [raw for raw in llamadas["buzon"] if interesa(raw.split(b"\n\n", 1)[0])]
    monkeypatch.setattr(apppassword, "fetch_since", leer)
    return h, llamadas


def test_solo_en_el_panel_local(client, auth):
    r = client.post("/connections/google/app-password", headers=auth,
                    json={"email": "ana@gmail.com", "password": "abcd efgh ijkl mnop"})
    assert r.status_code == 404


def test_conectar_enviar_y_leer_respuestas(client, local):
    h, llamadas = local
    r = client.post("/connections/google/app-password", headers=h,
                    json={"email": "Ana@gmail.com", "password": "abcd efgh ijkl mnop"})
    assert r.status_code == 200 and llamadas["login"] == [("ana@gmail.com", "abcdefghijklmnop")]
    g = client.get("/panel/state", headers=h).json()["connections"]["google"]
    assert g["connected"] and g["method"] == "app_password" and g["email"] == "ana@gmail.com"

    preparar(client, h, mode="test", email="ana@gmail.com")
    fila = next(f for f in client.get("/panel/board", headers=h).json()["items"]
                if f["route"] == "email" and f["status"] == "prepared")
    res = client.post("/panel/send", headers=h, json={"application_ids": [fila["application_id"]]}).json()["results"]
    assert res[0]["outcome"] == "email_queued"
    (cuenta, raw, destino), = llamadas["send"]
    assert cuenta == "ana@gmail.com" and destino == ["ana@gmail.com"]   # modo prueba: te llega a ti
    assert b"[PRUEBA" in raw

    # Nuestro propio correo (llega a la bandeja en modo prueba) no cuenta como respuesta
    llamadas["buzon"].append(raw)
    msg_id = next(l for l in raw.decode().splitlines() if l.lower().startswith("message-id:")).split(":", 1)[1].strip()
    respuesta = EmailMessage()
    respuesta["From"], respuesta["To"] = "Ana <ana@gmail.com>", "ana@gmail.com"
    respuesta["Subject"], respuesta["In-Reply-To"] = "Re: candidatura", msg_id
    respuesta["Message-ID"] = "<resp-1@gmail.com>"
    respuesta.set_content("Hola, nos gustaría hacerte una entrevista el lunes.")
    llamadas["buzon"].append(respuesta.as_bytes())

    r = client.post("/panel/check-inbox", headers=h).json()
    assert r["new"] == 1 and r["checked_at"]
    assert client.post("/panel/check-inbox", headers=h).json()["new"] == 0    # no se duplica
    st = client.get("/panel/state", headers=h).json()
    assert st["replies"][0]["category"] == "interview" and st["replies"][0]["company"]
    fila = next(f for f in client.get("/panel/board", headers=h).json()["items"] if f["key"] == fila["key"])
    assert fila["status"] == "interview" and fila["reply"] == "interview"


def test_revisar_sin_buzon(client, local):
    h, _ = local
    assert client.post("/panel/check-inbox", headers=h).status_code == 409
