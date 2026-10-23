"""Expressions inside a text, located by characters: formulas, protected tokens, note calls."""
from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.identification.expressions import RegistreExpressions, Trouvaille, detecteurs_par_defaut, trouver
from pdfexact.identification.formules import est_formule_bloc, formules_en_ligne
from pdfexact.ir import FontRef, Line, Span, TextBox

ARIAL = FontRef("f", "Arial", False, False)
COURIER = FontRef("c", "Courier New", False, False)


def _element(*spans_par_ligne):
    lignes = []
    for i, spans in enumerate(spans_par_ligne):
        box = BBox(u(72), u(100 + 14 * i), u(540), u(112 + 14 * i))
        lignes.append(Line(box, list(spans), box.hauteur, box.largeur))
    return TextBox(BBox(u(72), u(100), u(540), u(112 + 14 * (len(lignes) - 1))), lignes)


def _types(texte):
    element = _element([Span(texte, ARIAL, 10.0, "000000")])
    return [(texte[t.debut:t.fin], t.type) for t in trouver(element, detecteurs_par_defaut())]


def _formules(texte):
    return [texte[a:b] for a, b in formules_en_ligne(texte)]


def test_inline_math_keeps_the_formula_and_not_the_surrounding_prose():
    assert _formules("The area is A = πr² for circles.") == ["A = πr²"]
    assert _formules("Energy E = mc² and ∑ x_i ≤ 10.") == ["E = mc²", "∑ x_i ≤ 10"]
    assert _formules("the well-being of x") == []


def test_chemical_formulas_and_reactions_but_not_acronyms():
    assert _formules("Reaction: 2H2 + O2 → 2H2O") == ["2H2 + O2 → 2H2O"]
    assert _formules("Water is H2O and salt is NaCl, measured by USGS in 2005.") == ["H2O", "NaCl"]


def test_a_text_block_of_math_symbols_or_math_fonts_is_a_formula():
    assert est_formule_bloc("∫ f(x) dx = F(b) − F(a)", [("CMMI10", 10)])
    assert est_formule_bloc("α + β ≤ γ", [("Arial", 5)])
    assert not est_formule_bloc("The quick brown fox jumps over the dog", [("Arial", 30)])


def test_protected_tokens_are_typed_and_located():
    found = _types("See https://noaa.gov/x or mail info@noaa.gov, doi 10.1000/xyz123, on 12/05/2005 at 35 °C or 12%.")
    assert ("https://noaa.gov/x", "url") in found
    assert ("info@noaa.gov", "email") in found
    assert ("10.1000/xyz123", "identifiant") in found
    assert ("12/05/2005", "date") in found
    assert ("35 °C", "grandeur") in found and ("12%", "grandeur") in found


def test_acronyms_but_not_roman_numerals_nor_all_caps_text():
    assert ("USGS", "acronyme") in _types("Data from the USGS and FEMA in chapter IV.")
    assert ("IV", "acronyme") not in _types("Data from the USGS and FEMA in chapter IV.")
    assert _types("ALL CAPS HEADING TEXT") == []


def test_superscript_digit_is_a_note_call_and_monospace_word_is_inline_code():
    element = _element([Span("Water rises", ARIAL, 10.0, "000000"), Span("12", ARIAL, 6.0, "000000", exposant=True),
                        Span(" when ", ARIAL, 10.0, "000000"), Span("run()", COURIER, 10.0, "000000"),
                        Span(" is called.", ARIAL, 10.0, "000000")])
    found = {(t.type, t.debut, t.fin) for t in trouver(element, detecteurs_par_defaut())}
    assert ("appel_de_note", 11, 13) in found
    assert ("code_en_ligne", 19, 24) in found


def test_overlaps_keep_the_longest_and_new_detectors_plug_in():
    class Mots:
        nom = "mot-cle"

        def trouver(self, element, texte):
            debut = texte.find("tide")
            return [Trouvaille(debut, debut + 4, "acronyme", 0.5, "test")] if debut >= 0 else []

    registre = detecteurs_par_defaut()
    registre.enregistrer(Mots())
    element = _element([Span("high tide at E = mc² now", ARIAL, 10.0, "000000")])
    trouvailles = trouver(element, registre)
    assert [(t.type, element.lignes[0].spans[0].texte[t.debut:t.fin]) for t in trouvailles] == [
        ("acronyme", "tide"), ("formule_en_ligne", "E = mc²")]
    assert isinstance(registre, RegistreExpressions) and "mot-cle" in registre.noms
