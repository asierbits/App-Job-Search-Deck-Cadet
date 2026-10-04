"""Dependencias comunes de la API: sesión de BD, usuario autenticado, errores."""
from collections.abc import Iterator
from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from knok.db import session as dbs
from knok.db.models import ApiToken, Profile, User, utcnow
from knok.security import hash_token


class ApiError(HTTPException):
    """Error con código estable (para que tu web lo traduzca) y mensaje legible."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(status_code=status, detail={"code": code, "message": message})


def not_found(what: str = "Recurso") -> ApiError:
    return ApiError(404, "not_found", f"{what} no encontrado")


def get_db() -> Iterator[Session]:
    s = dbs.new_session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


_bearer = HTTPBearer(auto_error=False, description="Token de acceso `knk_…` (POST /auth/login o /auth/register)")


def current_user(request: Request, cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
                 db: Session = Depends(get_db)) -> User:
    if cred is None or not cred.credentials:
        raise ApiError(401, "unauthenticated", "Falta el token de acceso (Authorization: Bearer …)")
    tok = db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(cred.credentials)))
    ahora = utcnow()
    if tok is None or (tok.expires_at and tok.expires_at < ahora):
        raise ApiError(401, "invalid_token", "Token no válido o caducado")
    if tok.last_used_at is None or ahora - tok.last_used_at > timedelta(minutes=5):
        tok.last_used_at = ahora
    user = db.get(User, tok.user_id)
    request.state.token_id = tok.id
    return user


def current_profile(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Profile:
    p = db.get(Profile, user.id)
    if p is None:
        p = Profile(user_id=user.id, email=user.email)
        db.add(p)
        db.flush()
    return p


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise ApiError(403, "forbidden", "Solo para administradores")
    return user

