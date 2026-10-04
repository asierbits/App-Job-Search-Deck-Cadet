"""Envío de correos: modos Simulación / Prueba / Real, límites, pausas, Gmail OAuth (simulado) y respuestas."""
import email
import email.policy
from datetime import timedelta

import pytest
from sqlalchemy import select

from knok import storage
from knok.core.http import FakeHttp, set_default_http
from knok.core.mail import gmail
from knok.core.mail.classify import classify
from knok.db.models import Application, Company, Email, OAuthAccount, Profile, Reply, SimulatedReply, Task, User, utcnow
from knok.security import encrypt, hash_password
from knok.services import mailer


@pytest.fixture
def usuario(db):
    u = User(email="ana@example.com", password_hash=hash_password("x" * 8))
    db.add(u)
    db.flush()
    p = Profile(user_id=u.id, pack="marina_mercante", first_name="Ana", last_name="Pérez", email="ana@gmail.com",
                mode="simulation", daily_limit=2, pause_seconds=45)
    db.add(p)
    db.flush()
    return p


def candidatura(db, profile, contacto="crewing@naviera.example.com", status="confirmed"):
    c = Company(name="Naviera Ejemplo", name_norm="naviera ejemplo", domain=contacto.split("@")[1])
    db.add(c)
    db.flush()
    a = Application(user_id=profile.user_id, mode=profile.mode, company_id=c.id, route="email", status=status,
                    language="es", contact_email=contacto, subject="Solicitud - Ana", body="Hola\n")
    db.add(a)
    db.flush()
    return a


@pytest.fixture
def gmail_falso(monkeypatch):
    monkeypatch.setenv("KNOK_GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("KNOK_GOOGLE_CLIENT_SECRET", "secret")
    from knok.settings import get_settings
    get_settings.cache_clear()
    http = FakeHttp({gmail.TOKEN_URL: {"access_token": "nuevo", "expires_in": 3600},
                     gmail.SEND_URL: {"id": "g1", "threadId": "t1"}})
    set_default_http(http)
    yield http
    set_default_http(None)


def conectar_gmail(db, profile, email_cuenta="ana@gmail.com"):
    db.add(OAuthAccount(user_id=profile.user_id, provider="google", account_email=email_cuenta, scopes="gmail.send",
                        access_token_enc=encrypt("viejo"), refresh_token_enc=encrypt("refresh"),
                        expires_at=utcnow() - timedelta(minutes=5)))
    db.flush()


def test_nada_se_encola_sin_confirmar(db, usuario):
    a = candidatura(db, usuario, status="prepared")
    assert mailer.queue_application_emails(db, usuario, [a]) == []


def test_simulacion_guarda_eml_y_llega_respuesta(db, usuario, tmp_path):
    a = candidatura(db, usuario)
    [e] = mailer.queue_application_emails(db, usuario, [a])
    db.refresh(e)
    assert e.status == "sent" and a.status == "sent" and a.follow_up_at is not None
    eml = list((tmp_path / "storage" / "users" / str(usuario.user_id) / "outbox").glob("*.eml"))
    assert len(eml) == 1
    msg = email.message_from_bytes(eml[0].read_bytes())
    assert msg["To"] == "crewing@naviera.example.com" and msg["Message-ID"] == e.message_id
    # La respuesta simulada llega cuando toca (forzamos el reloj)
    if db.scalar(select(SimulatedReply)):
        n = mailer.deliver_due_simulated(db, now=utcnow() + timedelta(minutes=5))
        assert n == 1
        r = db.scalar(select(Reply))
        assert r.source == "simulated" and r.category in ("interview", "info", "rejection", "auto")
        assert a.status in ("interview", "replied", "discarded")


def test_prueba_envia_solo_al_propio_usuario(db, usuario, gmail_falso):
    usuario.mode = "test"
    conectar_gmail(db, usuario)
    from knok.db.models import Document
    db.add(Document(user_id=usuario.user_id, kind="cv", filename="cv.pdf", mime="application/pdf", size=3,
                    storage_key=storage.save("users/1/documents", "cv.pdf", b"%PDF")))
    a = candidatura(db, usuario)
    [e] = mailer.queue_application_emails(db, usuario, [a])
    db.refresh(e)
    assert e.status == "sent" and e.gmail_id == "g1" and e.to_addr == "ana@gmail.com"
    envio = next(c for c in gmail_falso.calls if c[1].startswith(gmail.SEND_URL))
    raw = email.message_from_bytes(envio[2], policy=email.policy.default)
    assert raw["To"] == "ana@gmail.com" and raw["Subject"].startswith("[PRUEBA → crewing@naviera.example.com]")
    assert any(p.get_filename() == "cv.pdf" for p in raw.iter_attachments())
    acc = db.scalar(select(OAuthAccount))
    assert acc.expires_at is not None  # el token caducado se refrescó


def test_real_respeta_el_limite_diario(db, usuario, gmail_falso):
    usuario.mode = "live"
    conectar_gmail(db, usuario)
    from knok.db.models import Document
    db.add(Document(user_id=usuario.user_id, kind="cv", filename="cv.pdf", mime="application/pdf", size=1,
                    storage_key=storage.save("u", "cv.pdf", b"x")))
    apps = [candidatura(db, usuario, f"jobs@empresa{i}.example.com") for i in range(3)]
    emails = mailer.queue_application_emails(db, usuario, apps)
    estados = sorted(db.get(Email, e.id).status for e in emails)
    assert estados == ["queued", "sent", "sent"]           # límite diario = 2
    aplazada = db.scalar(select(Task).where(Task.name == "send_email", Task.status == "queued"))
    assert aplazada.run_after > utcnow() + timedelta(hours=1)  # mañana, no se pierde


def test_real_sin_gmail_no_encola(db, usuario):
    usuario.mode = "live"
    a = candidatura(db, usuario)
    with pytest.raises(mailer.SendingBlocked) as ex:
        mailer.queue_application_emails(db, usuario, [a])
    assert {p["code"] for p in ex.value.problems} >= {"gmail_not_connected", "missing_cv"}


def test_gmail_revocado_marca_error_y_pide_reconectar(db, usuario, gmail_falso):
    usuario.mode = "live"
    conectar_gmail(db, usuario)
    gmail_falso.add(gmail.SEND_URL, 401, {"error": "invalid"})
    from knok.db.models import Document
    db.add(Document(user_id=usuario.user_id, kind="cv", filename="cv.pdf", mime="application/pdf", size=1,
                    storage_key=storage.save("u", "cv.pdf", b"x")))
    a = candidatura(db, usuario)
    [e] = mailer.queue_application_emails(db, usuario, [a])
    db.refresh(e)
    assert e.status == "error" and "conectar" in e.error and a.status == "confirmed"


@pytest.mark.parametrize("asunto,cuerpo,cat", [
    ("Re: candidatura", "Nos gustaría hacerte una entrevista el martes", "interview"),
    ("Re: application", "Unfortunately we have no vacancies", "rejection"),
    ("Out of office", "I am out of office until Monday", "auto"),
    ("Re: solicitud", "Por favor, completa el formulario de nuestro portal", "info"),
    ("Hola", "Gracias", "other"),
])
def test_clasificacion(asunto, cuerpo, cat):
    assert classify(asunto, cuerpo) == cat


def test_clasificacion_con_frases_del_pack():
    from knok.packs.loader import get_pack
    extra = get_pack("marina_mercante").reply_keywords
    assert classify("Re: x", "Please send your seaman's book", extra) == "info"


# ------------------------------------------------------------------------------------- OAuth Google

def test_conectar_gmail_flujo_completo(client, auth, monkeypatch):
    assert client.get("/connections/google/start", headers=auth).status_code == 503
    monkeypatch.setenv("KNOK_GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("KNOK_GOOGLE_CLIENT_SECRET", "secret")
    from knok.settings import get_settings
    get_settings.cache_clear()
    r = client.get("/connections/google/start?return_to=http://localhost:3000/ajustes", headers=auth).json()
    assert "gmail.send" in r["url"] and "access_type=offline" in r["url"]
    import urllib.parse
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(r["url"]).query)["state"][0]
    http = FakeHttp({gmail.TOKEN_URL: {"access_token": "at", "refresh_token": "rt", "expires_in": 3600,
                                       "scope": "openid email https://www.googleapis.com/auth/gmail.send"},
                     gmail.USERINFO_URL: {"email": "ana@gmail.com"}})
    set_default_http(http)
    try:
        cb = client.get(f"/connections/google/callback?state={state}&code=abc", follow_redirects=False)
        assert cb.status_code == 302 and cb.headers["location"] == "http://localhost:3000/ajustes?connected=google"
        me = client.get("/me", headers=auth).json()
        assert me["connections"]["google"] == {"connected": True, "email": "ana@gmail.com"}
        # el mismo state no sirve dos veces
        cb2 = client.get(f"/connections/google/callback?state={state}&code=abc", follow_redirects=False)
        assert "error=invalid_state" in cb2.headers["location"]
        assert client.delete("/connections/google", headers=auth).status_code == 204
        assert client.get("/me", headers=auth).json()["connections"]["google"]["connected"] is False
    finally:
        set_default_http(None)


def test_return_to_no_permite_redirecciones_abiertas(client, auth, monkeypatch):
    monkeypatch.setenv("KNOK_GOOGLE_CLIENT_ID", "cid")
    from knok.settings import get_settings
    get_settings.cache_clear()
    r = client.get("/connections/google/start?return_to=https://malo.com/robar", headers=auth).json()
    import urllib.parse
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(r["url"]).query)["state"][0]
    cb = client.get(f"/connections/google/callback?state={state}&error=access_denied", follow_redirects=False)
    assert cb.headers["location"].startswith("http://localhost:3000")
