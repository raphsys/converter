"""PP-DocLayout at a low threshold gives a second look to elements the segmentation's zones missed."""
from PIL import Image

from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.identification import doclayout
from pdfexact.identification.base import Candidat, ContextePage
from pdfexact.identification.identificateurs import contexte_page, decider_element, registre_par_defaut
from pdfexact.ir import FontRef, Line, Page, Span, TextBox
from pdfexact.layout.ai import LayoutAIZone

ARIAL = FontRef("f", "Arial", False, False)


def _box(x0, y0, x1, y1):
    return BBox(u(x0), u(y0), u(x1), u(y1))


def _texte(text, box):
    return TextBox(box, [Line(box, [Span(text, ARIAL, 10.0, "000000")], box.hauteur, box.largeur)])


class _Modele:
    def __init__(self, zones):
        self.zones_, self.appels = zones, 0

    def zones(self, image, largeur_pt, hauteur_pt):
        self.appels += 1
        return list(self.zones_)


def _contexte(page):
    contexte = contexte_page(page)
    contexte.extra["rendre_page"] = lambda echelle: Image.new("RGB", (int(612 * echelle), int(792 * echelle)))
    return contexte


def test_a_weak_zone_found_at_a_low_threshold_gives_a_weak_candidate():
    reference = _texte("FEMA-1604-DR-MS, Task Orders 413", _box(31, 569, 472, 596))
    page = Page(0, u(612), u(792), [reference])
    modele = _Modele([LayoutAIZone("z", "text", "text", 0.43, _box(29, 571, 473, 592), "paddlex", "t")])
    identificateur = doclayout.IdentificateurDocLayout(modele)
    candidats = identificateur.candidats(reference, _contexte(page))
    assert candidats == [Candidat("paragraphe", 0.43, "pp-doclayout-seuil-bas:text")]


def test_the_page_is_analysed_once_and_only_for_elements_no_source_settled():
    a, b = _texte("a", _box(72, 100, 200, 112)), _texte("b", _box(72, 120, 200, 132))
    page = Page(0, u(612), u(792), [a, b])
    modele = _Modele([])
    identificateur = doclayout.IdentificateurDocLayout(modele)
    contexte = _contexte(page)
    assert not identificateur.pertinent(a, contexte, (Candidat("paragraphe", 0.9, "pp-doclayout:text"),))
    assert identificateur.pertinent(a, contexte, ())
    identificateur.candidats(a, contexte)
    identificateur.candidats(b, contexte)
    assert modele.appels == 1


def test_without_a_page_renderer_nothing_is_said():
    texte = _texte("a", _box(72, 100, 200, 112))
    page = Page(0, u(612), u(792), [texte])
    assert doclayout.IdentificateurDocLayout(_Modele([])).candidats(texte, ContextePage(page)) == []


def test_it_comes_after_the_segmentation_zones_in_the_cascade():
    texte = _texte("Title", _box(72, 100, 300, 120))
    page = Page(0, u(612), u(792), [texte])
    page.zones_layout = [LayoutAIZone("z", "doc_title", "text", 0.9, _box(70, 98, 302, 122), "paddlex", "t")]
    modele = _Modele([LayoutAIZone("z", "text", "text", 0.3, _box(70, 98, 302, 122), "paddlex", "t")])
    registre = registre_par_defaut(doclayout.IdentificateurDocLayout(modele))
    assert decider_element(texte, page, _contexte(page), registre).type == "titre_document"
    assert modele.appels == 0


def test_absent_model_gives_no_identificateur(tmp_path):
    assert doclayout.creer_identificateur_doclayout(tmp_path) is None
