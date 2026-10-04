"""Relevancia de una oferta para una búsqueda: reglas fijas, explicables (cada punto lleva su motivo)."""
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache

from knok.core.geo import city_key
from knok.core.text import norm
from knok.packs.schema import MatchCfg


@dataclass
class MatchResult:
    matched: bool
    score: int = 0
    reasons: list[str] = field(default_factory=list)


@lru_cache(maxsize=4096)
def _rx(palabra: str) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9])" + re.escape(norm(palabra)) + r"(?![a-z0-9])")


def _hits(palabras, texto: str) -> list[str]:
    return [p for p in palabras if p and _rx(p).search(texto)]


def score_job(*, title: str, description: str, country: str, city: str, remote: bool,
              posted_at: datetime | None, match: MatchCfg, keywords: list[str], countries: list[str],
              cities: list[str], include_remote: bool = True) -> MatchResult:
    t, d = norm(title), norm(description)[:20000]
    r = MatchResult(matched=True)

    neg = _hits(match.negative, t + " " + d)
    if neg:
        return MatchResult(False, 0, [f"excluida por '{neg[0]}'"])

    # Ubicación (filtro duro por país; la ciudad suma)
    if countries and country and country not in countries and not (remote and include_remote):
        return MatchResult(False, 0, [f"país {country} fuera de la búsqueda"])
    if countries and not country:
        r.score -= 5
        r.reasons.append("país desconocido")
    if cities:
        claves = {city_key(c) for c in cities}
        if city_key(city) in claves:
            r.score += 20
            r.reasons.append(f"en {city}")
        elif remote and include_remote:
            r.score += 10
            r.reasons.append("remoto")

    # Palabras del usuario (obligatorias si las hay)
    if keywords:
        en_titulo, en_desc = _hits(keywords, t), _hits(keywords, d)
        if not en_titulo and not en_desc:
            return MatchResult(False, 0, ["no contiene tus palabras clave"])
        r.score += 50 * len(en_titulo) + 15 * len(set(en_desc) - set(en_titulo))
        r.reasons += [f"título: {k}" for k in en_titulo] + [f"descripción: {k}" for k in set(en_desc) - set(en_titulo)]

    # Palabras del pack (definen qué es del nicho)
    tk = [k for ks in match.title_keywords.values() for k in ks]
    kk = [k for ks in match.keywords.values() for k in ks]
    if tk or kk:
        t_tit, t_desc = _hits(tk, t)[:2], _hits(tk, d)[:2]
        k_tit, k_desc = _hits(kk, t)[:3], _hits(kk, d)[:3]
        pack_score = 40 * len(t_tit) + 10 * len(t_desc) + 20 * len(k_tit) + 8 * len(k_desc)
        relevante = bool(t_tit) or len(set(t_desc + k_tit + k_desc)) >= 2
        if not relevante and not keywords:
            return MatchResult(False, 0, ["no parece del nicho"])
        r.score += pack_score
        if t_tit:
            r.reasons.append(f"puesto del nicho: {t_tit[0]}")
        elif relevante:
            r.reasons.append("descripción del nicho")
    elif not keywords:
        r.score += 1

    if posted_at:
        pa = posted_at if posted_at.tzinfo else posted_at.replace(tzinfo=timezone.utc)
        dias = (datetime.now(timezone.utc) - pa).days
        if dias <= 7:
            r.score += 10
            r.reasons.append("publicada esta semana")
        elif dias <= 30:
            r.score += 5
        elif dias > 120:
            r.score -= 10
            r.reasons.append("antigua")
    return r
