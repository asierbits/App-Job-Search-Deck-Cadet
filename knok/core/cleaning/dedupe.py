"""Deduplicación: entre varias copias de la misma oferta, la original es la de la empresa.

Prioridad (menor = mejor):
  0  ATS de la empresa (Greenhouse, Lever, Ashby…) o enlace de solicitud que apunta a un ATS
  1  web de la empresa
  2  portal con API oficial (InfoJobs)
  3  agregador (Adzuna)
  4  captura de un portal hecha por la extensión (LinkedIn, Indeed…)
A igualdad, la que tiene descripción más completa y, después, la más antigua (se vio primero).
"""
from dataclasses import dataclass
from datetime import datetime

from knok.core.sources.ats.detect import PLATFORMS, detect

SOURCE_PRIORITY = {"company_site": 1, "infojobs": 2, "adzuna": 3, "capture": 4}


@dataclass
class Candidate:
    id: int
    source: str
    apply_url: str
    description_len: int
    first_seen: datetime | None


def priority(source: str, apply_url: str) -> int:
    if source in PLATFORMS and PLATFORMS[source].kind == "ats":
        return 0
    ref = detect(apply_url)
    if ref and ref.info.kind == "ats":
        return 0
    return SOURCE_PRIORITY.get(source, 3)


def pick_original(cands: list[Candidate]) -> Candidate:
    def clave(c: Candidate):
        return (priority(c.source, c.apply_url), -min(c.description_len, 2000) // 200,
                c.first_seen or datetime.max, c.id)
    return min(cands, key=clave)
