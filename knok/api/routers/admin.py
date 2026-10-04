"""Administración del diccionario: preguntas nuevas → patrones para todos."""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from knok.api.deps import ApiError, get_db, not_found, require_admin
from knok.core.filling.fields import BY_KEY
from knok.core.text import norm
from knok.db import models as m
from knok.packs.loader import all_packs, answer_keys_for

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/unknown-questions", summary="Preguntas que el motor no reconoció (más vistas primero)")
def unknown(pack: str = "", only_unmapped: bool = True, limit: int = Query(100, le=500),
            _: m.User = Depends(require_admin), db: Session = Depends(get_db)):
    q = select(m.UnknownQuestion)
    if pack:
        q = q.where(m.UnknownQuestion.pack == pack)
    if only_unmapped:
        q = q.where(m.UnknownQuestion.mapped_key == "")
    return [{"id": u.id, "label": u.label, "pack": u.pack, "language": u.language, "type": u.field_type,
             "options": u.options, "platforms": u.platforms, "times_seen": u.times_seen, "mapped_key": u.mapped_key}
            for u in db.scalars(q.order_by(m.UnknownQuestion.times_seen.desc()).limit(limit))]


class MapIn(BaseModel):
    key: str
    pattern: str = Field(default="", description="Texto a reconocer; por defecto la pregunta entera")
    scope: str = Field(default="pack", pattern="^(pack|global)$")


@router.post("/unknown-questions/{qid}/map", summary="Asignar una pregunta nueva a una clave del banco")
def map_question(qid: int, data: MapIn, _: m.User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(m.UnknownQuestion, qid)
    if u is None:
        raise not_found("Pregunta")
    claves = set(BY_KEY)
    if u.pack in all_packs():
        claves |= {k.key for k in answer_keys_for(all_packs()[u.pack])}
    if data.key not in claves:
        raise ApiError(422, "unknown_key", f"Clave desconocida: {data.key}")
    patron = norm(data.pattern or u.label)
    db.add(m.QuestionPattern(pack=u.pack if data.scope == "pack" else "", key=data.key, language=u.language,
                             pattern=patron[:300], weight=11))
    u.mapped_key = data.key
    return {"id": u.id, "mapped_key": u.mapped_key, "pattern": patron}


@router.get("/question-patterns", summary="Patrones aprendidos")
def patterns(_: m.User = Depends(require_admin), db: Session = Depends(get_db)):
    return [{"id": p.id, "pack": p.pack, "key": p.key, "language": p.language, "pattern": p.pattern}
            for p in db.scalars(select(m.QuestionPattern).order_by(m.QuestionPattern.id))]


@router.delete("/question-patterns/{pid}", status_code=204, summary="Borrar un patrón aprendido")
def delete_pattern(pid: int, _: m.User = Depends(require_admin), db: Session = Depends(get_db)):
    p = db.get(m.QuestionPattern, pid)
    if p:
        db.delete(p)
