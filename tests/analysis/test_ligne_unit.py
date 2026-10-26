"""A row unit is the element with that single row; building it no longer copies every row."""
from copy import deepcopy

from pdfexact.analysis.text_segmentation import _ligne_unit
from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.ir import FlowParagraph, FontRef, Line, Span, TextBox

ARIAL = FontRef("f", "Arial", False, False)


def _lignes(n):
    resultat = []
    for i in range(n):
        box = BBox(u(72), u(100 + 14 * i), u(400), u(112 + 14 * i))
        resultat.append(Line(box, [Span(f"row {i}", ARIAL, 10.0, "000000", bbox=box)], box.hauteur, box.largeur))
    return resultat


def test_a_row_unit_does_not_depend_on_the_other_rows():
    lignes = _lignes(5)
    element = TextBox(BBox(u(72), u(100), u(400), u(168)), lignes, attributes={"k": [1, 2]})
    avant = deepcopy(element)
    seule = deepcopy(element)
    seule.lignes = [deepcopy(lignes[2])]
    assert _ligne_unit(element, lignes[2], 2, "element:0") == _ligne_unit(seule, seule.lignes[0], 2, "element:0")
    assert element == avant  # the source element is left as it was


def test_a_flow_paragraph_row_unit_keeps_only_its_row_spans():
    lignes = _lignes(4)
    element = FlowParagraph(BBox(u(72), u(100), u(400), u(154)), "row 0row 1row 2row 3", ARIAL, 10.0, "000000",
                            lignes=lignes, spans=[s for ligne in lignes for s in ligne.spans])
    avant = deepcopy(element)
    unit = _ligne_unit(element, lignes[1], 1, "element:0")
    assert [s.texte for s in unit.spans] == ["row 1"] and unit.texte == "row 1"
    assert element == avant


def test_building_a_row_unit_never_copies_the_other_rows(monkeypatch):
    import pdfexact.analysis.text_segmentation as module

    copies = []
    vraie = module.deepcopy

    def espion(valeur, *args):
        copies.append(len(getattr(valeur, "lignes", ()) or ()))
        return vraie(valeur, *args)

    monkeypatch.setattr(module, "deepcopy", espion)
    lignes = _lignes(6)
    _ligne_unit(TextBox(BBox(u(72), u(100), u(400), u(182)), lignes), lignes[3], 3, "element:0")
    assert max(copies) <= 1
