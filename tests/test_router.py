"""Enrutador: cada regla y su orden."""
from knok.core.routing.router import RouteInput, decide

GH = "https://boards.greenhouse.io/acme/jobs/1"


def test_ats_con_adaptador_va_a_la_extension():
    d = decide(RouteInput(has_job=True, source="adzuna", apply_url=GH))
    assert (d.route, d.platform, d.adapter_ready) == ("ats_extension", "greenhouse", True)


def test_ats_sin_adaptador_es_manual():
    d = decide(RouteInput(has_job=True, apply_url="https://acme.wd3.myworkdayjobs.com/en-US/Ext/job/X_R-1"))
    assert (d.route, d.platform) == ("manual", "workday")


def test_infojobs_por_api_solo_si_esta_conectado():
    url = "https://www.infojobs.net/madrid/x/of-iabc"
    assert decide(RouteInput(has_job=True, source="infojobs", url=url, infojobs_connected=True)).route == "portal_api"
    d = decide(RouteInput(has_job=True, source="infojobs", url=url))
    assert d.route == "manual" and "infojobs_not_connected" in d.warnings


def test_linkedin_easy_apply_copiloto_con_aviso():
    url = "https://www.linkedin.com/jobs/view/123"
    d = decide(RouteInput(has_job=True, apply_url=url, easy_apply=True))
    assert d.route == "portal_copilot" and "linkedin_risk" in d.warnings
    assert decide(RouteInput(has_job=True, apply_url=url)).route == "manual"


def test_indeed_apply_nunca_se_automatiza_ni_por_correo():
    d = decide(RouteInput(has_job=True, apply_url="https://es.indeed.com/viewjob?jk=1",
                          company_emails=["jobs@acme.com"]))
    assert d.route == "manual" and d.platform == "indeed"


def test_indeed_que_redirige_a_un_ats_se_rellena_el_ats():
    assert decide(RouteInput(has_job=True, source="capture", url="https://es.indeed.com/viewjob?jk=1",
                             apply_url=GH)).route == "ats_extension"


def test_oferta_con_correo_generico():
    d = decide(RouteInput(has_job=True, url="https://acme.com/jobs/1", apply_email="jobs@acme.com"))
    assert (d.route, d.contact_email) == ("email", "jobs@acme.com")


def test_correo_personal_nunca_se_usa():
    d = decide(RouteInput(has_job=True, url="https://acme.com/jobs/1", apply_email="ana.lopez@acme.com"))
    assert d.route == "manual"


def test_empresa_sin_oferta():
    d = decide(RouteInput(has_job=False, company_emails=["ana@acme.com", "rrhh@acme.com"]))
    assert (d.route, d.contact_email) == ("email", "rrhh@acme.com")
    d = decide(RouteInput(has_job=False, careers_url="https://acme.com/empleo"))
    assert d.route == "manual" and d.apply_url == "https://acme.com/empleo"


def test_adzuna_sin_ats_usa_correo_de_empresa_si_hay():
    d = decide(RouteInput(has_job=True, apply_url="https://www.adzuna.es/land/ad/1", company_emails=["info@acme.com"]))
    assert d.route == "email"
    assert decide(RouteInput(has_job=True, apply_url="https://www.adzuna.es/land/ad/1")).route == "manual"
