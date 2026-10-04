"""Fuentes: parseo de cada API con datos de ejemplo (sin red)."""
from knok.core.http import FakeHttp, HttpError
from knok.core.sources import adzuna, infojobs
from knok.core.sources.ats import ashby, greenhouse, lever
from knok.core.sources.ats.detect import detect
from tests.conftest import fixture_json

import pytest


def test_greenhouse_parse_y_descripcion_doblemente_escapada():
    jobs = greenhouse.parse_jobs(fixture_json("ats/greenhouse_jobs.json"), "acme", "Acme Corp")
    a, b = jobs
    assert a.source_job_id == "acme:4012345" and a.title == "Backend Engineer (m/f/d)"
    assert (a.city, a.country, a.remote) == ("Madrid", "es", False)
    assert "APIs in Python" in a.description and "<" not in a.description and "• PostgreSQL" in a.description
    assert a.ats == "greenhouse" and a.posted_at.year == 2026
    assert b.remote and b.country == "de"  # país sacado de la oficina


def test_greenhouse_fetch_board_con_nombre_de_empresa():
    http = FakeHttp({
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs": fixture_json("ats/greenhouse_jobs.json"),
        "https://boards-api.greenhouse.io/v1/boards/acme": fixture_json("ats/greenhouse_board.json"),
    })
    nombre, jobs = greenhouse.fetch_board(http, "acme")
    assert nombre == "Acme Corp" and len(jobs) == 2


def test_greenhouse_tablero_inexistente():
    with pytest.raises(HttpError) as e:
        greenhouse.fetch_board(FakeHttp(), "nadie")
    assert e.value.status == 404


def test_greenhouse_preguntas():
    campos = greenhouse.parse_questions(fixture_json("ats/greenhouse_job_questions.json"))
    ids = [c["id"] for c in campos]
    assert "question_106" not in ids  # ocultas fuera
    sel = next(c for c in campos if c["id"] == "question_102")
    assert sel["type"] == "select" and sel["options"][0] == {"label": "Yes", "value": "1"} and sel["required"]
    assert next(c for c in campos if c["id"] == "resume")["type"] == "file"


def test_lever():
    jobs = lever.parse_jobs(fixture_json("ats/lever.json"), "acme")
    assert jobs[0].title == "Operations Manager" and jobs[0].country == "es" and jobs[0].city == "Barcelona"
    assert "Requirements" in jobs[0].description and "3 years" in jobs[0].description
    assert jobs[1].remote and jobs[1].country == "de"
    assert jobs[0].apply_url.endswith("/apply")


def test_lever_prueba_la_region_ue_si_la_global_da_404():
    http = FakeHttp({"https://api.eu.lever.co/v0/postings/acme": fixture_json("ats/lever.json")})
    _, jobs = lever.fetch_board(http, "acme")
    assert len(jobs) == 2


def test_ashby_omite_no_listadas():
    jobs = ashby.parse_jobs(fixture_json("ats/ashby.json"), "Acme")
    assert len(jobs) == 1
    j = jobs[0]
    assert (j.city, j.country) == ("Lisbon", "pt") and j.salary == "€50K – €60K"


def test_adzuna():
    jobs = adzuna.parse_results(fixture_json("adzuna/search.json"), "es")
    assert jobs[0].title == "Backend Engineer" and jobs[0].company_name == "Acme Corp"
    assert jobs[0].city == "Madrid" and jobs[0].salary == "40000-55000"
    assert detect(jobs[0].apply_url).platform == "adzuna"
    assert adzuna.search(FakeHttp(), "id", "key", "xx", "python") == []  # país no soportado: sin llamada


def test_infojobs():
    jobs = infojobs.parse_offers(fixture_json("infojobs/offers.json"))
    assert jobs[0].company_name == "Acme Corp" and jobs[0].country == "es" and jobs[0].language == "es"
    campos = infojobs.parse_questions(fixture_json("infojobs/questions.json"))
    assert campos[0]["id"] == "killer:11" and campos[0]["options"][0] == {"label": "Sí", "value": "111"}
    assert campos[2] == {"id": "open:21", "label": "¿Por qué te interesa este puesto?", "type": "textarea",
                         "required": True, "options": []}
    cuerpo = infojobs.build_application("cv-1", [{"id": "killer:11", "value": "111"},
                                                 {"id": "open:21", "value": "Me encanta"}], "Hola")
    assert cuerpo == {"curriculumCode": "cv-1", "killerQuestions": [{"id": 11, "answerId": 111}],
                      "openQuestions": [{"id": 21, "answer": "Me encanta"}], "coverLetter": {"text": "Hola"}}


@pytest.mark.parametrize("url,plataforma,slug,job", [
    ("https://boards.greenhouse.io/acme/jobs/4012345", "greenhouse", "acme", "4012345"),
    ("https://job-boards.eu.greenhouse.io/acme/jobs/1", "greenhouse", "acme", "1"),
    ("https://boards.greenhouse.io/embed/job_app?for=acme&token=55", "greenhouse", "acme", "55"),
    ("https://jobs.lever.co/Acme/0f9b1c2d-1111-2222-3333-444455556666/apply", "lever", "acme",
     "0f9b1c2d-1111-2222-3333-444455556666"),
    ("https://jobs.ashbyhq.com/Acme/9a8b7c6d-1111-2222-3333-444455556666", "ashby", "Acme",
     "9a8b7c6d-1111-2222-3333-444455556666"),
    ("https://acme.wd5.myworkdayjobs.com/en-US/External/job/Madrid/Engineer_R-123", "workday", "acme", "R-123"),
    ("https://www.linkedin.com/jobs/view/backend-engineer-at-acme-3901234567/", "linkedin", "", "3901234567"),
    ("https://es.indeed.com/viewjob?jk=abc123", "indeed", "", "abc123"),
    ("https://www.infojobs.net/madrid/x/of-i1234abcd", "infojobs", "", "1234abcd"),
    ("https://apply.workable.com/acme/j/ABC123/", "workable", "acme", "ABC123"),
])
def test_detectar_plataforma(url, plataforma, slug, job):
    ref = detect(url)
    assert (ref.platform, ref.slug, ref.job_id) == (plataforma, slug, job)


def test_url_sin_plataforma():
    assert detect("https://www.acme.com/careers") is None and detect("") is None
