"""Motor de relleno sin IA: reconocimiento multilingüe, opciones, deducciones y lo que NUNCA se rellena."""
import pytest

from knok.core.filling.engine import FillContext, FormField, fill
from knok.core.filling.matcher import match_field, pack_patterns
from knok.core.filling.options import pick_option
from knok.core.sources.ats.greenhouse import parse_questions
from knok.core.sources.infojobs import parse_questions as ij_questions
from knok.core.text import norm
from knok.packs.loader import get_pack
from tests.conftest import fixture_json

PERFIL = {"first_name": "Ana", "last_name": "Pérez", "email": "ana@example.com", "phone": "+34 600 000 000",
          "city": "Bilbao", "country": "es", "links": {"linkedin": "https://linkedin.com/in/ana"},
          "languages": [{"code": "en", "level": "C1"}, {"code": "es", "level": "nativo"}],
          "pack_data": {"titulacion": "Grado en Náutica", "titulacion_en": "BSc Nautical Science"}}


def ctx(**kw):
    base = dict(profile=PERFIL, language="en", job_country="es",
                documents={"cv": [{"id": 7, "filename": "cv-ana.pdf", "language": "", "is_default": True}]})
    base.update(kw)
    return FillContext(**base)


@pytest.mark.parametrize("etiqueta,clave", [
    ("First Name", "first_name"), ("Nachname", "last_name"), ("Prénom", "first_name"),
    ("Correo electrónico", "email"), ("Teléfono móvil", "phone"), ("Lebenslauf", "resume"),
    ("What are your salary expectations?", "salary_expectation"), ("Pretensión salarial", "salary_expectation"),
    ("Gehaltsvorstellung", "salary_expectation"), ("Years of experience with Python", "years_experience"),
    ("¿Cuántos años de experiencia tienes?", "years_experience"), ("Notice period", "notice_period"),
    ("Are you legally authorized to work in Germany?", "work_authorization"),
    ("Do you require visa sponsorship?", "needs_sponsorship"), ("How did you hear about this job?", "how_did_you_hear"),
    ("Carta de presentación", "cover_letter"), ("I agree to the privacy policy", "consent"),
    ("Gender", "eeo_gender"), ("Date of birth", "date_of_birth"),
])
def test_reconocimiento_multilingue(etiqueta, clave):
    assert match_field(etiqueta).key == clave


def test_pistas_tecnicas_ganan_a_la_etiqueta():
    assert match_field("Your answer", name="urls[LinkedIn]").key == "linkedin"
    assert match_field("Campo 3", autocomplete="given-name").key == "first_name"


def test_patrones_del_pack():
    pats = pack_patterns(get_pack("marina_mercante"))
    assert match_field("Seaman's book number", patterns=pats).key == "seaman_book"
    assert match_field("Seaman's book number").key is None   # sin el pack, desconocida


def test_formulario_greenhouse_completo():
    campos = [FormField.from_dict(x) for x in parse_questions(fixture_json("ats/greenhouse_job_questions.json"))]
    r = fill(campos, ctx(answers={"work_authorization": {"*": ["EU"]}, "salary_expectation": {"en": "35k EUR"}}))
    v = {f["id"]: f for f in r["fields"]}
    assert v["first_name"]["value"] == "Ana" and v["first_name"]["origin"] == "profile"
    assert v["resume"]["value"] == {"document_id": 7, "filename": "cv-ana.pdf"}
    assert v["resume_text"]["value"] is None and not v["resume_text"]["needs_review"]
    assert v["question_101"]["value"] == "https://linkedin.com/in/ana"
    assert v["question_102"]["value"] == "1" and v["question_102"]["display"] == "Yes"   # autorizado en España (UE)
    assert v["question_103"]["value"] == "0" and v["question_103"]["origin"] == "deduced"  # no necesita visado
    assert v["question_104"]["value"] == "35k EUR"
    assert v["question_105"]["value"] is None and v["question_105"]["needs_review"]       # desconocida: vacía
    assert r["unknown"] == ["Describe a project you are proud of"] and r["missing"] == []


def test_permiso_de_trabajo_segun_el_pais_de_la_pregunta():
    campos = [FormField("q", "Are you legally authorized to work in the United States?", "select", True,
                        [{"label": "Yes", "value": "y"}, {"label": "No", "value": "n"}])]
    r = fill(campos, ctx(answers={"work_authorization": {"*": "ES, EU"}}))
    assert r["fields"][0]["value"] == "n"


def test_nombre_junto_a_apellidos_es_nombre_de_pila():
    r = fill([FormField("a", "Nombre"), FormField("b", "Apellidos")], ctx(language="es"))
    assert [f["value"] for f in r["fields"]] == ["Ana", "Pérez"]
    r = fill([FormField("a", "Nombre")], ctx(language="es"))
    assert r["fields"][0]["value"] == "Ana Pérez"


def test_lo_que_nunca_se_rellena_solo():
    campos = [FormField("c", "I agree to the privacy policy", "checkbox", True),
              FormField("g", "Gender", "select", False, [{"label": "Female", "value": "f"},
                                                        {"label": "Decline to self-identify", "value": "d"}]),
              FormField("x", "What is your favourite colour?", "text", True)]
    r = fill(campos, ctx())
    assert all(f["value"] is None and f["needs_review"] for f in r["fields"])
    assert set(r["missing"]) == {"c", "x"}
    # el dato sensible solo se rellena si el usuario lo guardó explícitamente
    r = fill(campos[1:2], ctx(answers={"eeo_gender": {"*": "Decline to self-identify"}}))
    assert r["fields"][0]["value"] == "d"


def test_respuesta_ya_dada_por_el_usuario():
    r = fill([FormField("x", "What is your favourite colour?")], ctx(custom={norm("What is your favourite colour?"): "Azul"}))
    f = r["fields"][0]
    assert f["value"] == "Azul" and f["origin"] == "custom" and not f["needs_review"]


def test_infojobs_killer_questions():
    campos = [FormField.from_dict(x) for x in ij_questions(fixture_json("infojobs/questions.json"))]
    r = fill(campos, ctx(language="es", answers={"work_authorization": {"*": ["ES"]}, "years_experience": {"*": 2}},
                         cover_letter="Me interesa mucho."))
    v = {f["id"]: f for f in r["fields"]}
    assert v["killer:11"]["value"] == "111"                # Sí
    assert v["killer:12"]["value"] == "122"                # "Entre 1 y 3"
    assert v["open:21"]["value"] == "Me interesa mucho."   # carta generada con la plantilla


def test_opcion_que_no_encaja_queda_para_revisar():
    campos = [FormField("s", "Expected salary", "select", True, [{"label": "< 20k", "value": "a"}, {"label": "20k-30k", "value": "b"}])]
    r = fill(campos, ctx(answers={"salary_expectation": {"*": "negociable"}}))
    assert r["fields"][0]["value"] is None and r["fields"][0]["needs_review"] and "no coincide" in r["fields"][0]["reason"]


def test_idiomas_y_titulacion_del_perfil():
    r = fill([FormField("l", "Languages"), FormField("d", "Degree")], ctx(language="en"))
    assert r["fields"][0]["value"] == "English (C1), Spanish (nativo)"
    assert r["fields"][1]["value"] == "BSc Nautical Science"


@pytest.mark.parametrize("valor,opciones,esperado", [
    (True, [{"label": "Sí", "value": "1"}, {"label": "No", "value": "2"}], "1"),
    ("no", [{"label": "Yes", "value": "y"}, {"label": "No", "value": "n"}], "n"),
    (7, [{"label": "0-2", "value": "a"}, {"label": "3-5", "value": "b"}, {"label": "More than 5", "value": "c"}], "c"),
    (0, [{"label": "Less than 1 year", "value": "a"}, {"label": "1-3 years", "value": "b"}], "a"),
    ("Germany", [{"label": "Spain", "value": "ES"}, {"label": "Germany", "value": "DE"}], "DE"),
])
def test_opciones(valor, opciones, esperado):
    assert pick_option(valor, opciones)[0] == esperado
