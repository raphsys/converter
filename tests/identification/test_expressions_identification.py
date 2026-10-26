"""Expressions inside a text: detectors plugged in a registry, located by characters."""
import pytest

from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.identification.expressions import (DetecteurAppelsNote, RegistreExpressions, Trouvaille,
                                                 detecteurs_par_defaut, trouver)
from pdfexact.ir import FontRef, Line, Span, TextBox

ARIAL = FontRef("f", "Arial", False, False)


def _element(*lignes):
    box = BBox(0, 0, u(400), u(40))
    return TextBox(box, [Line(box, list(spans), u(12), u(400)) for spans in lignes])


def _span(texte, exposant=False):
    return Span(texte, ARIAL, 10.0, "000000", exposant=exposant)


class _Fixe:
    def __init__(self, nom, trouvailles):
        self.nom, self._trouvailles = nom, trouvailles

    def trouver(self, element, texte):
        return list(self._trouvailles)


def test_a_superscript_flagged_by_the_pdf_is_a_note_call():
    element = _element([_span("Katrina"), _span("12", exposant=True), _span(" made landfall")])
    trouvaille = trouver(element, RegistreExpressions([DetecteurAppelsNote()]))[0]
    assert (trouvaille.debut, trouvaille.fin, trouvaille.type) == (7, 9, "appel_de_note")


def test_a_small_digit_without_the_pdf_flag_is_not_guessed_to_be_a_note_call():
    element = _element([_span("Katrina"), Span("12", ARIAL, 6.0, "000000"), _span(" made landfall")])
    assert trouver(element, RegistreExpressions([DetecteurAppelsNote()])) == []


def test_overlapping_expressions_keep_the_longest_and_positions_span_lines():
    element = _element([_span("See doi 10.1/x")], [_span("on 3 May 2005.")])
    registre = RegistreExpressions([
        _Fixe("a", [Trouvaille(8, 14, "identifiant", 0.9, "a"), Trouvaille(18, 28, "date", 0.9, "a")]),
        _Fixe("b", [Trouvaille(4, 14, "identifiant", 0.6, "b"), Trouvaille(18, 19, "grandeur", 0.9, "b")]),
    ])
    assert [(t.debut, t.fin, t.type, t.indice) for t in trouver(element, registre)] == [
        (4, 14, "identifiant", "b"), (18, 28, "date", "a")]


def test_registry_refuses_duplicates_and_non_detectors():
    registre = RegistreExpressions([_Fixe("a", [])])
    with pytest.raises(ValueError):
        registre.enregistrer(_Fixe("a", []))
    with pytest.raises(TypeError):
        registre.enregistrer(object())
    assert registre.noms == ("a",)


def test_types_outside_the_referential_are_refused():
    element = _element([_span("hello")])
    with pytest.raises(ValueError):
        trouver(element, RegistreExpressions([_Fixe("x", [Trouvaille(0, 5, "mot_gras", 0.9, "x")])]))


def test_default_detectors_are_the_ai_and_the_native_note_calls(tmp_path):
    assert detecteurs_par_defaut(tmp_path).noms == ("appels-note",)
    assert detecteurs_par_defaut(gliner=_Fixe("gliner", [])).noms == ("gliner", "appels-note")
