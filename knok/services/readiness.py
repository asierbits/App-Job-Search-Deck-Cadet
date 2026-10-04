"""¿Puede este usuario enviar en su modo actual? Lista de problemas legibles (vacía = todo listo)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from knok.db.models import Document, OAuthAccount, Profile

MODES = ("simulation", "test", "live")


def google_account(db: Session, user_id: int) -> OAuthAccount | None:
    return db.scalar(select(OAuthAccount).where(OAuthAccount.user_id == user_id, OAuthAccount.provider == "google"))


def sending_problems(db: Session, profile: Profile) -> list[dict]:
    p = []
    if not (profile.first_name or "").strip():
        p.append({"code": "missing_name", "message": "Falta tu nombre en el perfil."})
    if profile.mode in ("test", "live") and google_account(db, profile.user_id) is None:
        p.append({"code": "gmail_not_connected", "message": "Conecta tu Gmail para enviar en modo prueba o real."})
    if profile.mode == "test" and not (profile.email or "").strip():
        p.append({"code": "missing_email", "message": "Falta tu email (en modo prueba los correos te llegan a ti)."})
    tiene_cv = db.scalar(select(Document.id).where(Document.user_id == profile.user_id, Document.kind == "cv").limit(1))
    if not tiene_cv:
        p.append({"code": "missing_cv", "message": "Sube tu CV en Documentos."})
    return p
