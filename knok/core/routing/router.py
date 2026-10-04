"""Enrutador: decide por qué vía se aplica a cada oferta o empresa. Reglas fijas, en orden.

Vías (route):
  ats_extension   el enlace de solicitud es el formulario de la empresa (Greenhouse, Lever…): lo rellena la extensión
  portal_api      portal con API oficial de candidatura (InfoJobs): se prepara por API
  portal_copilot  solo se puede aplicar dentro del portal (LinkedIn Easy Apply): copiloto en el portal
  email           sin formulario: borrador de correo directo al buzón genérico de la empresa
  manual          nada automatizable o prohibido (Indeed Apply, plataformas sin adaptador): se abre el enlace

Nunca se envía nada desde aquí: el enrutador solo decide cómo se PREPARA la candidatura.
"""
from dataclasses import dataclass, field

from knok.core.emails.generic import is_generic
from knok.core.sources.ats.detect import PLATFORMS, detect


@dataclass
class RouteInput:
    has_job: bool                         # False = solo empresa (candidatura espontánea)
    source: str = ""
    apply_url: str = ""
    url: str = ""
    easy_apply: bool = False
    apply_email: str = ""                 # correo de candidatura que da la propia oferta
    company_emails: list[str] = field(default_factory=list)   # buzones genéricos conocidos, el mejor primero
    careers_url: str = ""
    infojobs_connected: bool = False
    extra_roles: frozenset[str] = frozenset()


@dataclass
class RouteDecision:
    route: str
    platform: str = ""
    reason: str = ""
    adapter_ready: bool = False
    apply_url: str = ""
    contact_email: str = ""
    warnings: list[str] = field(default_factory=list)


def _primer_generico(emails: list[str], roles: frozenset[str]) -> str:
    return next((e for e in emails if e and is_generic(e, roles)), "")


def decide(i: RouteInput) -> RouteDecision:
    url = i.apply_url or i.url
    ref = detect(url)
    correo = _primer_generico([i.apply_email] if i.apply_email else [], i.extra_roles) or \
        _primer_generico(i.company_emails, i.extra_roles)

    if not i.has_job:
        if correo:
            return RouteDecision("email", "email", "Empresa sin oferta publicada con buzón genérico: correo directo.",
                                 True, contact_email=correo)
        return RouteDecision("manual", "", "Empresa sin oferta ni buzón genérico conocido: revisa su página de empleo.",
                             apply_url=i.careers_url)

    # 1. Formulario de un ATS
    if ref and ref.info.kind == "ats":
        p = ref.info
        if p.extension:
            return RouteDecision("ats_extension", p.name, f"La solicitud es el formulario de la empresa en {p.name}.",
                                 True, apply_url=url)
        return RouteDecision("manual", p.name, f"Formulario de {p.name}: aún sin adaptador en la extensión.",
                             apply_url=url)

    # 2. Portal con API oficial (InfoJobs)
    if i.source == "infojobs" or (ref and ref.platform == "infojobs"):
        if i.infojobs_connected:
            return RouteDecision("portal_api", "infojobs", "InfoJobs tiene API oficial de candidatura.", True,
                                 apply_url=url)
        return RouteDecision("manual", "infojobs", "Conecta tu cuenta de InfoJobs para preparar esta candidatura por API.",
                             apply_url=url, warnings=["infojobs_not_connected"])

    # 3. LinkedIn Easy Apply → copiloto (con aviso de riesgo)
    if ref and ref.platform == "linkedin":
        if i.easy_apply:
            return RouteDecision("portal_copilot", "linkedin", "Solo se puede solicitar dentro de LinkedIn (Easy Apply).",
                                 PLATFORMS["linkedin"].extension, apply_url=url, warnings=["linkedin_risk"])
        return RouteDecision("manual", "linkedin", "LinkedIn sin Easy Apply: abre la oferta y sigue su enlace externo.",
                             apply_url=url)

    # 4. Plataformas en las que no se automatiza (Indeed Apply, Wellfound, agregadores)
    if ref and not ref.info.autofill_allowed:
        if correo and ref.platform != "indeed":
            return RouteDecision("email", "email", f"{ref.platform}: no se automatiza; hay buzón genérico de la empresa.",
                                 True, contact_email=correo, apply_url=url)
        motivo = {"indeed": "Indeed Apply: sus condiciones prohíben automatizarlo. Solicítalo tú en Indeed.",
                  "wellfound": "Wellfound: se registra en el seguimiento y se prepara el mensaje; la solicitud la haces tú.",
                  "adzuna": "Oferta agregada por Adzuna: ábrela para llegar a la solicitud original."}
        return RouteDecision("manual", ref.platform, motivo.get(ref.platform, "Solicitud manual."), apply_url=url)

    # 5. La oferta pide el CV por correo (y es un buzón genérico)
    if correo:
        return RouteDecision("email", "email", "La oferta no tiene formulario; hay buzón genérico: correo directo.",
                             True, contact_email=correo, apply_url=url)

    # 6. Lo demás (web propia de la empresa sin formulario conocido)
    return RouteDecision("manual", "", "Solicitud en la web de la empresa sin adaptador: ábrela y aplica tú.",
                         apply_url=url)
