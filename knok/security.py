"""Contraseñas (scrypt), tokens de acceso y cifrado de secretos guardados (Fernet)."""
import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken

from knok.settings import get_settings

_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}
TOKEN_PREFIX = "knk_"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        alg, salt_b64, dk_b64 = stored.split("$")
    except ValueError:
        return False
    if alg != "scrypt":
        return False
    dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), **_SCRYPT)
    return hmac.compare_digest(dk, base64.b64decode(dk_b64))


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _fernet() -> Fernet:
    clave = hashlib.sha256(("knok-fernet:" + get_settings().secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(clave))


def encrypt(texto: str) -> str:
    return _fernet().encrypt(texto.encode()).decode() if texto else ""


def decrypt(cifrado: str) -> str:
    if not cifrado:
        return ""
    try:
        return _fernet().decrypt(cifrado.encode()).decode()
    except InvalidToken:
        return ""


def random_id(n: int = 16) -> str:
    return secrets.token_urlsafe(n)[:n * 2].replace("-", "x").replace("_", "y").lower()
