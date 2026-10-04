"""Gmail con OAuth 2.0, solo para ENVIAR (scope gmail.send, "sensible": verificación gratuita).

No se pide ningún scope de lectura (gmail.readonly/metadata/modify/compose son "restringidos" y exigen
auditoría anual de pago). Las respuestas se detectan por marcado manual o reenvío (ver tracking).
"""
import base64
import urllib.parse
from datetime import datetime, timedelta, timezone

from knok.core.http import Http, HttpError

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SEND_URL = "https://gmail.googleapis.com/upload/gmail/v1/users/me/messages/send?uploadType=media"
SCOPES = ["openid", "email", "https://www.googleapis.com/auth/gmail.send"]
MAX_MESSAGE_BYTES = 35 * 1024 * 1024


class GmailError(Exception):
    def __init__(self, message: str, retryable: bool = False, reconnect: bool = False):
        super().__init__(message)
        self.retryable = retryable
        self.reconnect = reconnect


def authorization_url(client_id: str, redirect_uri: str, state: str, login_hint: str = "") -> str:
    q = {"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": " ".join(SCOPES),
         "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "state": state}
    if login_hint:
        q["login_hint"] = login_hint
    return AUTH_URL + "?" + urllib.parse.urlencode(q)


def _token_request(http: Http, data: dict) -> dict:
    r = http.request("POST", TOKEN_URL, data=data, headers={"Accept": "application/json"})
    if not r.ok:
        try:
            err = r.json().get("error", "")
        except Exception:
            err = r.text[:200]
        raise GmailError(f"Google rechazó el token ({r.status}: {err})", reconnect=err in ("invalid_grant", "unauthorized_client"))
    return r.json()


def exchange_code(http: Http, client_id: str, client_secret: str, code: str, redirect_uri: str) -> dict:
    t = _token_request(http, {"code": code, "client_id": client_id, "client_secret": client_secret,
                              "redirect_uri": redirect_uri, "grant_type": "authorization_code"})
    r = http.request("GET", USERINFO_URL, headers={"Authorization": f"Bearer {t['access_token']}"})
    email = r.json().get("email", "") if r.ok else ""
    return {"access_token": t["access_token"], "refresh_token": t.get("refresh_token", ""),
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=int(t.get("expires_in", 3600)) - 60),
            "scope": t.get("scope", ""), "email": email}


def refresh(http: Http, client_id: str, client_secret: str, refresh_token: str) -> dict:
    t = _token_request(http, {"refresh_token": refresh_token, "client_id": client_id, "client_secret": client_secret,
                              "grant_type": "refresh_token"})
    return {"access_token": t["access_token"],
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=int(t.get("expires_in", 3600)) - 60)}


def send(http: Http, access_token: str, raw: bytes) -> dict:
    if len(raw) > MAX_MESSAGE_BYTES:
        raise GmailError("El correo con adjuntos supera los 35 MB que admite Gmail")
    r = http.request("POST", SEND_URL, data=raw, timeout=60,
                     headers={"Authorization": f"Bearer {access_token}", "Content-Type": "message/rfc822"})
    if r.ok:
        return r.json()
    detalle = r.text[:300]
    if r.status == 401:
        raise GmailError("Gmail no aceptó el permiso: vuelve a conectar tu cuenta", reconnect=True)
    if r.status == 429 or "rateLimitExceeded" in detalle or "dailyLimitExceeded" in detalle:
        raise GmailError("Gmail ha limitado los envíos por hoy", retryable=True)
    if r.status >= 500:
        raise GmailError(f"Gmail no responde ({r.status})", retryable=True)
    raise GmailError(f"Gmail rechazó el correo ({r.status}): {detalle}")


def revoke(http: Http, token: str) -> None:
    try:
        http.request("POST", REVOKE_URL, data={"token": token})
    except HttpError:
        pass


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode()
