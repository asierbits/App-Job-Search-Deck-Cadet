"""Cuentas y tokens de acceso.

Tu web (Next.js) llama a /auth/register o /auth/login y guarda el token (cookie httpOnly en el
servidor de Next o almacenamiento del navegador). La extensión usa un token aparte, creado con
POST /auth/tokens, que el usuario puede revocar sin cerrar su sesión web.
"""
import ipaddress
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from knok.api.deps import ApiError, current_user, get_db, not_found
from knok.db.models import ApiToken, Profile, User, utcnow
from knok.security import hash_password, hash_token, new_token, random_id, verify_password
from knok.settings import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    locale: str = Field(default="es", pattern=r"^[a-z]{2}$")
    pack: str = ""


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    token: str = Field(description="Guárdalo: no se vuelve a mostrar")
    token_id: int
    expires_at: str | None
    user_id: int


class NewTokenIn(BaseModel):
    name: str = Field(default="extensión", max_length=80)
    days: int | None = Field(default=365, ge=1, le=3650, description="Caducidad; null = no caduca")


class TokenInfo(BaseModel):
    id: int
    name: str
    prefix: str
    created_at: str
    last_used_at: str | None
    expires_at: str | None
    current: bool


def issue_token(db: Session, user: User, name: str = "sesión", days: int | None = None) -> TokenOut:
    tok = new_token()
    dias = get_settings().token_ttl_days if days is None else days
    expira = utcnow() + timedelta(days=dias) if dias else None
    t = ApiToken(user_id=user.id, name=name, token_hash=hash_token(tok), prefix=tok[:10], expires_at=expira)
    db.add(t)
    db.flush()
    return TokenOut(token=tok, token_id=t.id, expires_at=expira.isoformat() if expira else None, user_id=user.id)


@router.post("/register", response_model=TokenOut, status_code=201, summary="Crear cuenta")
def register(data: RegisterIn, db: Session = Depends(get_db)):
    email = data.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise ApiError(409, "email_taken", "Ya existe una cuenta con ese email")
    from knok.packs.loader import all_packs
    if data.pack and data.pack not in all_packs():
        raise ApiError(422, "unknown_pack", f"Pack desconocido: {data.pack}")
    user = User(email=email, password_hash=hash_password(data.password), locale=data.locale,
                is_admin=email in [a.lower() for a in get_settings().admin_emails])
    db.add(user)
    db.flush()
    db.add(Profile(user_id=user.id, email=email, pack=data.pack or "general", inbound_token=random_id(12)))
    return issue_token(db, user)


@router.post("/login", response_model=TokenOut, summary="Iniciar sesión")
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    if user is None or not verify_password(data.password, user.password_hash):
        raise ApiError(401, "bad_credentials", "Email o contraseña incorrectos")
    return issue_token(db, user)


@router.post("/logout", status_code=204, summary="Cerrar sesión (revoca el token actual)")
def logout(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = db.get(ApiToken, request.state.token_id)
    if t:
        db.delete(t)


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=200)


@router.post("/password", status_code=204, summary="Cambiar contraseña (revoca las demás sesiones)")
def change_password(data: PasswordIn, request: Request, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(data.current_password, user.password_hash):
        raise ApiError(401, "bad_credentials", "La contraseña actual no es correcta")
    user.password_hash = hash_password(data.new_password)
    for t in db.scalars(select(ApiToken).where(ApiToken.user_id == user.id, ApiToken.id != request.state.token_id)):
        db.delete(t)


@router.get("/tokens", response_model=list[TokenInfo], summary="Tokens activos")
def list_tokens(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    toks = db.scalars(select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.id))
    return [TokenInfo(id=t.id, name=t.name, prefix=t.prefix, created_at=t.created_at.isoformat(),
                      last_used_at=t.last_used_at.isoformat() if t.last_used_at else None,
                      expires_at=t.expires_at.isoformat() if t.expires_at else None,
                      current=t.id == request.state.token_id) for t in toks]


@router.post("/tokens", response_model=TokenOut, status_code=201,
             summary="Crear un token aparte (p. ej. para la extensión de Chrome)")
def create_token(data: NewTokenIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return issue_token(db, user, name=data.name, days=data.days)


@router.delete("/tokens/{token_id}", status_code=204, summary="Revocar un token")
def revoke_token(token_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = db.get(ApiToken, token_id)
    if t is None or t.user_id != user.id:
        raise not_found("Token")
    db.delete(t)


LOCAL_EMAIL = "local@knok.local"
EXTENSION_TOKEN = "extensión de Chrome"
LOOPBACK = {"localhost", "testclient"}


def _from_this_machine(host: str) -> bool:
    """Este ordenador (o la red interna de Docker, que publica el puerto solo en 127.0.0.1)."""
    if host in LOOPBACK:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


@router.get("/local", response_model=TokenOut, summary="Sesión del panel local (un usuario en tu PC, sin login)")
def local_session(request: Request, client: str = "panel", db: Session = Depends(get_db)):
    """Solo con KNOK_LOCAL_SINGLE_USER=true y solo desde este mismo ordenador."""
    s = get_settings()
    if not s.local_single_user:
        raise ApiError(404, "not_found", "No disponible")
    if not _from_this_machine(request.client.host if request.client else ""):
        raise ApiError(403, "forbidden", "La sesión local solo funciona desde este ordenador")
    user = db.scalar(select(User).where(User.email == LOCAL_EMAIL))
    if user is None:
        from knok.packs.loader import all_packs
        user = User(email=LOCAL_EMAIL, password_hash=hash_password(random_id(24)), locale="es")
        db.add(user)
        db.flush()
        pack = s.local_default_pack if s.local_default_pack in all_packs() else "general"
        db.add(Profile(user_id=user.id, email="", pack=pack, inbound_token=random_id(12)))
    nombre = EXTENSION_TOKEN if client == "extension" else "panel local"
    return issue_token(db, user, name=nombre, days=3650)
