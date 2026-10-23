"""Identification rules: one closed type per element, with status, confidence and evidence."""
import pytest

from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.identification.referentiel import famille
from pdfexact.identification.regles import Candidat, contexte_page, decider, decider_element
from pdfexact.ir import FontRef, ImageEl, Line, LinkZone, Page, RasterEl, ShapeEl, Span, TableEl, TextBox
from pdfexact.layout.ai import LayoutAIZone

ARIAL = FontRef("f", "Arial", False, False)


def _box(x0, y0, x1, y1):
    return BBox(u(x0), u(y0), u(x1), u(y1))


def _texte(text, box, size=10.0, police=ARIAL, **kwargs):
    lignes = [Line(box, [Span(ligne, police, size, "000000")], box.hauteur, box.largeur) for ligne in text.split("\n")]
    return TextBox(box, lignes, **kwargs)


def _corps(n=3):
    return [_texte("Body text of the page that sets the dominant size.", _box(72, 300 + 20 * i, 540, 312 + 20 * i))
            for i in range(n)]


def _page(elements, index=0, zones=()):
    page = Page(index, u(612), u(792), list(elements))
    page.zones_layout = list(zones)
    return page


def _zone(label, box, confidence=0.9):
    return LayoutAIZone("z", label, "text", confidence, box, "paddlex", "test")


def _decision(element, page, premiere_page=False):
    return decider_element(element, page, contexte_page(page, premiere_page))


def test_scores_of_one_type_combine_and_settle_the_status():
    decision = decider([Candidat("intertitre", 0.6, "a"), Candidat("intertitre", 0.5, "b"), Candidat("paragraphe", 0.4, "c")])
    assert (decision.type, decision.famille, decision.statut) == ("intertitre", "texte", "identifie")
    assert decision.confiance == pytest.approx(0.8)
    assert decision.alternatives == (("paragraphe", 0.4),)


def test_close_scores_are_ambiguous_and_no_candidate_is_not_identified():
    assert decider([Candidat("intertitre", 0.7, "a"), Candidat("paragraphe", 0.65, "b")]).statut == "ambigu"
    vide = decider([])
    assert (vide.type, vide.statut, vide.confiance) == ("inconnu", "non_identifie", 0.0)
    assert decider([], repli="image_generique").type == "image_generique"


def test_only_types_of_the_referential_can_come_out():
    assert famille("paragraphe") == "texte"
    with pytest.raises(ValueError):
        famille("bold_word")
    with pytest.raises(ValueError):
        decider([Candidat("bold_word", 0.9, "x")])


def test_a_text_in_a_paddlex_title_zone_is_a_heading():
    titre = _texte("Methodology", _box(72, 100, 300, 116))
    page = _page([titre, *_corps()], zones=[_zone("paragraph_title", _box(70, 98, 302, 118))])
    decision = _decision(titre, page)
    assert decision.type == "intertitre" and decision.statut == "identifie"
    assert any("paddlex:paragraph_title" in indice for indice in decision.indices)


def test_large_type_is_a_heading_and_the_largest_on_the_first_page_is_the_document_title():
    titre = _texte("Hurricane Katrina", _box(72, 60, 500, 90), size=24)
    inter = _texte("1. Introduction", _box(72, 200, 300, 216), size=14)
    page = _page([titre, inter, *_corps()])
    assert _decision(titre, page, premiere_page=True).type == "titre_document"
    assert _decision(inter, page, premiere_page=True).type == "intertitre"


def test_caption_page_number_and_list_item_are_told_by_their_text():
    legende = _texte("Figure 3 – Mississippi coastal counties", _box(72, 400, 400, 412))
    numero = _texte("12", _box(300, 760, 312, 772))
    item = _texte("first item of the list", _box(90, 500, 400, 512), list_marker="•")
    page = _page([legende, numero, item, *_corps()])
    assert _decision(legende, page).type == "legende"
    assert _decision(numero, page).type == "numero_page"
    assert _decision(item, page).type == "element_liste"


def test_a_full_page_image_is_a_scan_when_it_carries_ocr_text_otherwise_a_background():
    image = RasterEl(_box(0, 0, 612, 792), "scan")
    ocr = _texte("Scanned text", _box(72, 100, 300, 112), source_kind="ocr")
    assert _decision(image, _page([image, ocr])).type == "page_numerisee"
    assert _decision(image, _page([image, *_corps()])).type == "arriere_plan"


def test_shapes_rule_band_and_page_border():
    filet = ShapeEl(_box(72, 400, 540, 401), [], None, "000000", u(1))
    bande = ShapeEl(_box(50, 500, 560, 560), [], "DDEEFF", None, 0)
    cadre = ShapeEl(_box(20, 20, 592, 772), [], None, "0000FF", u(1))
    dans_bande = _texte("Word bank", _box(72, 510, 300, 522))
    page = _page([filet, bande, cadre, dans_bande, *_corps()])
    assert _decision(filet, page).type == "separateur"
    assert _decision(bande, page).type == "bandeau"
    assert _decision(cadre, page).type == "bordure_page"


def test_links_tables_and_chart_zones():
    externe = LinkZone(_box(72, 100, 200, 112), uri="https://example.org")
    interne = LinkZone(_box(72, 120, 200, 132), page_cible=4)
    tableau = TableEl(_box(72, 200, 540, 400), [], [], ARIAL, 10.0)
    graphique = ImageEl(_box(72, 420, 400, 600), "g")
    page = _page([externe, interne, tableau, graphique], zones=[_zone("chart", _box(70, 418, 402, 602))])
    assert _decision(externe, page).type == "lien"
    assert _decision(interne, page).type == "renvoi"
    assert _decision(tableau, page).type == "tableau"
    assert _decision(graphique, page).type == "graphique"
