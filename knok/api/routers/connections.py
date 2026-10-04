"""Conectar cuentas externas por OAuth: Gmail (solo envío) e InfoJobs (candidatura por API).

Flujo desde tu web:
  1. GET /connections/google/start?return_to=https://tuweb/ajustes   (con el token del usuario) → {url}
  2. Tu web redirige el navegador a esa url (Google pide permiso).
  3. Google vuelve a /connections/google/callback; la API guarda los tokens cifrados y redirige a
     return_to?connected=google (o ?error=…).
"""
import urllib.parse
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from knok.api.deps import ApiError, current_user, get_db
from knok.core.http import default_http
from knok.core.mail import gmail
from knok.core.sources import infojobs
from knok.db.models import OAuthAccount, OAuthState, User, utcnow
from knok.security import decrypt, encrypt, random_id
from knok.services.events import log_event
from knok.settings import get_settings

router = APIRouter(prefix="/connections", tags=["me"])
STATE_TTL = timedelta(minutes=15)


def _callback(provider: str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/connections/{provider}/callback"


def _safe_return(return_to: str) -> str:
    """Solo se vuelve a orígenes permitidos (tu web), nunca a una URL arbitraria."""
    s = get_settings()
    permitidos = [o.rstrip("/") for o in s.cors_origins + [s.web_base_url]]
    if return_to and any(return_to.startswith(o + "/") or return_to == o for o in permitidos):
        return return_to
    return s.web_base_url


def _back(return_to: str, **params) -> RedirectResponse:
    sep = "&" if "?" in return_to else "?"
    return RedirectResponse(return_to + sep + urllib.parse.urlencode(params), status_code=302)


def _new_state(db: Session, user: User, provider: str, return_to: str) -> str:
    db.execute(delete(OAuthState).where(OAuthState.created_at < utcnow() - STATE_TTL))
    st = random_id(24)
    db.add(OAuthState(state=st, user_id=user.id, provider=provider, return_to=_safe_return(return_to)))
    return st


def _take_state(db: Session, state: str, provider: str) -> OAuthState | None:
    st = db.get(OAuthState, state or "")
    if st is None or st.provider != provider:
        return None
    db.delete(st)
    return st if st.created_at >= utcnow() - STATE_TTL else None


def _save_account(db: Session, user_id: int, provider: str, email: str, access: str, refresh: str, expires, scopes: str):
    acc = db.scalar(select(OAuthAccount).where(OAuthAccount.user_id == user_id, OAuthAccount.provider == provider))
    if acc is None:
        acc = OAuthAccount(user_id=user_id, provider=provider)
        db.add(acc)
    acc.account_email, acc.scopes, acc.expires_at = email, scopes, expires
    acc.access_token_enc = encrypt(access)
    if refresh:  # Google solo lo manda la primera vez (o con prompt=consent)
        acc.refresh_token_enc = encrypt(refresh)


# ------------------------------------------------------------------------------------- Google

@router.get("/google/start", summary="Empezar a conectar Gmail (devuelve la URL de Google)")
def google_start(return_to: str = Query("", description="URL de tu web a la que volver"),
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = get_settings()
    if not s.google_client_id:
        raise ApiError(503, "not_configured", "Falta configurar KNOK_GOOGLE_CLIENT_ID / KNOK_GOOGLE_CLIENT_SECRET")
    st = _new_state(db, user, "google", return_to)
    return {"url": gmail.authorization_url(s.google_client_id, _callback("google"), st, login_hint=user.email)}


@router.get("/google/callback", include_in_schema=False)
def google_callback(state: str = "", code: str = "", error: str = "", db: Session = Depends(get_db)):
    st = _take_state(db, state, "google")
    if st is None:
        return _back(get_settings().web_base_url, error="invalid_state")
    if error or not code:
        return _back(st.return_to, error=error or "no_code")
    s = get_settings()
    try:
        t = gmail.exchange_code(default_http(), s.google_client_id, s.google_client_secret, code, _callback("google"))
    except gmail.GmailError as ex:
        return _back(st.return_to, error="token_exchange", detail=str(ex)[:120])
    if "gmail.send" not in t["scope"]:
        return _back(st.return_to, error="missing_scope")
    _save_account(db, st.user_id, "google", t["email"], t["access_token"], t["refresh_token"], t["expires_at"], t["scope"])
    log_event(db, st.user_id, f"Gmail conectado ({t['email']}).", "ok")
    return _back(st.return_to, connected="google")


@router.delete("/google", status_code=204, summary="Desconectar Gmail (revoca el permiso en Google)")
def google_disconnect(user: User = Depends(current_user), db: Session = Depends(get_db)):
    acc = db.scalar(select(OAuthAccount).where(OAuthAccount.user_id == user.id, OAuthAccount.provider == "google"))
    if acc:
        gmail.revoke(default_http(), decrypt(acc.refresh_token_enc) or decrypt(acc.access_token_enc))
        db.delete(acc)


# ------------------------------------------------------------------------------------- InfoJobs

@router.get("/infojobs/start", summary="Empezar a conectar InfoJobs (devuelve la URL de InfoJobs)")
def infojobs_start(return_to: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = get_settings()
    if not s.infojobs_client_id:
        raise ApiError(503, "not_configured", "Falta configurar KNOK_INFOJOBS_CLIENT_ID / KNOK_INFOJOBS_CLIENT_SECRET")
    st = _new_state(db, user, "infojobs", return_to)
    q = {"scope": infojobs.SCOPES, "client_id": s.infojobs_client_id, "redirect_uri": _callback("infojobs"),
         "response_type": "code", "state": st}
    return {"url": infojobs.AUTHORIZE + "?" + urllib.parse.urlencode(q)}


@router.get("/infojobs/callback", include_in_schema=False)
def infojobs_callback(state: str = "", code: str = "", error: str = "", db: Session = Depends(get_db)):
    st = _take_state(db, state, "infojobs")
    if st is None:
        return _back(get_settings().web_base_url, error="invalid_state")
    if error or not code:
        return _back(st.return_to, error=error or "no_code")
    s = get_settings()
    r = default_http().request("POST", infojobs.TOKEN, params={
        "grant_type": "authorization_code", "client_id": s.infojobs_client_id, "client_secret": s.infojobs_client_secret,
        "code": code, "redirect_uri": _callback("infojobs")})
    if not r.ok:
        return _back(st.return_to, error="token_exchange")
    t = r.json()
    _save_account(db, st.user_id, "infojobs", "", t.get("access_token", ""), t.get("refresh_token", ""),
                  utcnow() + timedelta(seconds=int(t.get("expires_in", 3600))), infojobs.SCOPES)
    log_event(db, st.user_id, "InfoJobs conectado.", "ok")
    return _back(st.return_to, connected="infojobs")


@router.delete("/infojobs", status_code=204, summary="Desconectar InfoJobs")
def infojobs_disconnect(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(delete(OAuthAccount).where(OAuthAccount.user_id == user.id, OAuthAccount.provider == "infojobs"))
