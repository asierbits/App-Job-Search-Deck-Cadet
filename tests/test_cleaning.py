"""Limpieza: normalización, huella, original frente a copia y buzones genéricos."""
from datetime import datetime, timezone

import pytest

from knok.core.cleaning.dedupe import Candidate, pick_original
from knok.core.cleaning.normalize import company_key_name, fingerprint, title_key
from knok.core.domains import domain_of
from knok.core.emails.generic import is_generic
from knok.core.emails.score import MailboxRules, best
from knok.packs.loader import get_pack


@pytest.mark.parametrize("a,b", [
    ("Software Engineer (m/w/d)", "Software Engineer (h/m/x)"),
    ("Software Engineer - Remote", "Software engineer"),
    ("Ingeniero/a de Software (all genders)", "Ingeniero/a de software"),
])
def test_titulos_equivalentes(a, b):
    assert title_key(a) == title_key(b)


@pytest.mark.parametrize("nombre,clave", [
    ("Acme Shipping, S.L.", "acme shipping"), ("ACME Shipping GmbH & Co. KG", "acme shipping"),
    ("Naviera Ejemplo S.A.", "naviera ejemplo"), ("Holland Bulk Shipping B.V.", "holland bulk shipping"),
])
def test_nombre_de_empresa_sin_forma_juridica(nombre, clave):
    assert company_key_name(nombre) == clave


def test_huella_misma_oferta_en_distintas_ciudades_y_alias():
    a = fingerprint("c1", "", "Backend Engineer (m/f/d)", "Sevilla")
    assert a == fingerprint("c1", "", "Backend engineer", "Seville, Spain")
    assert a != fingerprint("c1", "", "Backend engineer", "Madrid")
    assert a != fingerprint("c2", "", "Backend engineer", "Sevilla")


def test_original_es_la_del_ats():
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    cands = [Candidate(1, "adzuna", "https://www.adzuna.es/land/ad/1", 500, t),
             Candidate(2, "capture", "https://www.linkedin.com/jobs/view/1", 3000, t),
             Candidate(3, "greenhouse", "https://boards.greenhouse.io/acme/jobs/1", 100, t),
             Candidate(4, "infojobs", "https://www.infojobs.net/x/of-i1", 900, t)]
    assert pick_original(cands).id == 3
    # una captura cuyo enlace de solicitud es el ATS cuenta como original
    assert pick_original([cands[0], Candidate(5, "capture", "https://jobs.lever.co/acme/x", 10, t)]).id == 5
    assert pick_original([cands[0], cands[3]]).id == 4


@pytest.mark.parametrize("email,generico", [
    ("info@acme.com", True), ("rrhh@acme.es", True), ("jobs-es@acme.com", True), ("rrhh.madrid@acme.es", True),
    ("talent.acquisition@acme.com", True), ("careers2@acme.com", True),
    ("ana.lopez@acme.com", False), ("jsmith@acme.com", False), ("a.perez@acme.com", False),
    ("maria@acme.com", False), ("noreply@acme.com", False), ("privacy@acme.com", False),
])
def test_genericos_frente_a_personales(email, generico):
    assert is_generic(email) is generico


def test_roles_del_pack_cuentan_como_genericos():
    assert not is_generic("crewing@naviera.com")
    roles = frozenset(get_pack("marina_mercante").crawl.extra_generic)
    assert is_generic("crewing@naviera.com", roles) and is_generic("marine.hr@naviera.com", roles)


def test_prioridad_de_buzones_por_pack():
    emails = [("info@naviera.com", False), ("sales@naviera.com", False), ("crewing@naviera.com", False),
              ("jobs@naviera.com", False), ("crew@otra-empresa.com", False)]
    marina = best(emails, "naviera.com", MailboxRules.for_pack(get_pack("marina_mercante")))
    assert marina[0] == "crewing@naviera.com" and marina[-1] == "sales@naviera.com"
    assert "crew@otra-empresa.com" not in marina   # nunca el de otra empresa
    general = best(emails, "naviera.com", MailboxRules.for_pack(get_pack("general")))
    assert general[0] == "jobs@naviera.com"


def test_dominios():
    assert domain_of("https://careers.acme.co.uk/jobs") == "acme.co.uk"
    assert domain_of("rrhh@mail.acme.es") == "acme.es"
    assert domain_of("https://naviera.example.com") == "naviera.example.com"
