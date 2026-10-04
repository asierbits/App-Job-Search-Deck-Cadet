import pytest

from knok.packs.loader import all_packs, answer_keys_for, get_pack, parse_template


def test_packs_cargan_y_validan():
    packs = all_packs()
    assert {"general", "marina_mercante", "doctorados_investigacion"} <= set(packs)
    for p in packs.values():
        for lang in p.languages:
            assert p.template("email", "company", lang) is not None


def test_noruega_no_se_convierte_en_false():
    p = get_pack("marina_mercante")
    assert "no" in p.sources.wikidata.countries
    assert any(d.country == "no" for d in p.sources.directories)


def test_plantilla_del_pack_sustituye_a_la_base():
    p = get_pack("marina_mercante")
    assert "Deck Cadet" in p.template("email", "company", "en").subject
    # La plantilla de seguimiento no la define el pack: viene de _base
    assert p.template("followup", "company", "es") is not None


def test_claves_del_banco_incluyen_globales_y_del_pack():
    claves = {k.key for k in answer_keys_for(get_pack("marina_mercante"))}
    assert {"years_experience", "salary_expectation", "stcw_certificates", "seaman_book"} <= claves
    claves_phd = {k.key for k in answer_keys_for(get_pack("doctorados_investigacion"))}
    assert "research_proposal" in claves_phd and "stcw_certificates" not in claves_phd


def test_parse_template():
    t = parse_template("Subject: Hola {nombre}\n\nCuerpo\n")
    assert t.subject == "Hola {nombre}" and t.body == "Cuerpo\n"


@pytest.mark.parametrize("slug", ["marina_mercante", "doctorados_investigacion"])
def test_el_nucleo_no_contiene_el_nicho(slug):
    """Principio 7: nada específico de un nicho fuera de su pack."""
    import pathlib
    raiz = pathlib.Path(__file__).parents[1] / "knok"
    palabras = {"marina_mercante": ["crewing", "naviera", "cadete"],
                "doctorados_investigacion": ["doctorado", "predoctoral"]}[slug]
    for f in raiz.rglob("*.py"):
        if "packs" in f.parts:
            continue
        texto = f.read_text(encoding="utf-8").lower()
        for p in palabras:
            assert p not in texto, f"'{p}' aparece en {f} (debería vivir en el pack)"
