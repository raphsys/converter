"""PP-FormulaNet confirms a suspected formula; it never judges alone."""
from PIL import Image

from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.identification import formulenet
from pdfexact.identification.base import Candidat, ContextePage
from pdfexact.ir import ImageEl, Page


def test_only_structured_latex_counts_as_a_formula():
    assert formulenet.latex_structure(r"\mathsf{x}=\left(-b\pm\sqrt{b^{2}-4ac}\right)/2a")
    assert formulenet.latex_structure(r"\int_{0}^{1} f(x)\,dx")
    assert not formulenet.latex_structure(r"\textcircled{6}")
    assert not formulenet.latex_structure(r"\begin{array}{l}\textcircled{F}\textcircled{F}\end{array}")
    assert not formulenet.latex_structure("abc")


class _Modele:
    def __init__(self, latex):
        self.latex, self.appels = latex, 0

    def reconnaitre(self, image):
        self.appels += 1
        return self.latex


def _contexte(element):
    page = Page(0, u(612), u(792), [element])
    return ContextePage(page, extra={"rendre": lambda bbox: Image.new("RGB", (80, 20))})


def test_consulted_only_on_a_suspected_formula_of_reasonable_size():
    identificateur = formulenet.IdentificateurFormuleNet(_Modele("x=1"))
    zone = ImageEl(BBox(u(72), u(100), u(300), u(130)), "f")
    contexte = _contexte(zone)
    assert not identificateur.pertinent(zone, contexte, (Candidat("photo", 0.8, "x"),))
    assert identificateur.pertinent(zone, contexte, (Candidat("formule_bloc", 0.5, "pp-doclayout:formula"),))
    assert identificateur.pertinent(zone, contexte, (Candidat("formule_bloc", 0.3, "pp-doclayout-seuil-bas:formula"),))
    enorme = ImageEl(BBox(0, 0, u(612), u(700)), "g")
    assert not identificateur.pertinent(enorme, _contexte(enorme), (Candidat("formule_bloc", 0.5, "pp-doclayout:formula"),))


def test_a_formula_suspected_by_the_vision_model_alone_is_not_sent():
    # Measured: SmolVLM says "formula" on logos and banners, FormulaNet then invents LaTeX.
    identificateur = formulenet.IdentificateurFormuleNet(_Modele("x=1"))
    zone = ImageEl(BBox(u(72), u(100), u(300), u(130)), "f")
    assert not identificateur.pertinent(zone, _contexte(zone), (Candidat("formule_bloc", 0.6, "smolvlm: formula (2.5)"),))


def test_structured_latex_confirms_and_invented_latex_says_nothing():
    zone = ImageEl(BBox(u(72), u(100), u(300), u(130)), "f")
    confirme = formulenet.IdentificateurFormuleNet(_Modele(r"E=mc^{2}")).candidats(zone, _contexte(zone))
    assert confirme[0].type == "formule_bloc" and "E=mc^{2}" in confirme[0].indice
    assert formulenet.IdentificateurFormuleNet(_Modele(r"\textcircled{6}")).candidats(zone, _contexte(zone)) == []


def test_identical_zones_are_recognised_once():
    modele = _Modele(r"E=mc^{2}")
    identificateur = formulenet.IdentificateurFormuleNet(modele)
    zone = ImageEl(BBox(u(72), u(100), u(300), u(130)), "f")
    identificateur.candidats(zone, _contexte(zone))
    identificateur.candidats(zone, _contexte(zone))
    assert modele.appels == 1


def test_an_empty_render_is_not_shown_to_the_model():
    modele = _Modele(r"E=mc^{2}")
    zone = ImageEl(BBox(u(72), u(100), u(300), u(130)), "f")
    contexte = ContextePage(Page(0, u(612), u(792), [zone]), extra={"rendre": lambda bbox: Image.new("RGB", (0, 0))})
    assert formulenet.IdentificateurFormuleNet(modele).candidats(zone, contexte) == []
    assert modele.appels == 0
