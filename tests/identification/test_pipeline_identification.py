"""identifier(): every segmentation box identified by the sources, expressions by characters, outputs."""
import json

import pymupdf

from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.identification import (RegistreExpressions, ResultatIdentification, Trouvaille, annoter_pdf_types,
                                     enregistrer_identification, identifier)
from pdfexact.identification.base import Candidat
from pdfexact.ir import Document, FontRef, Line, Page, ShapeEl, Span, TextBox
from pdfexact.layout.ai import LayoutAIZone
from pdfexact.segmentation import ResultatSegmentation

ARIAL = FontRef("f", "Arial", False, False)
TEXTES = ["Water is H2O here.", "See https://noaa.gov for data."]


def _box(x0, y0, x1, y1):
    return BBox(u(x0), u(y0), u(x1), u(y1))


class Filets:
    """Stands for the vision: says what a shape is."""

    nom = "filets"
    natures = frozenset({"shape"})

    def candidats(self, element, contexte):
        return [Candidat("separateur", 0.9, "test")]


class Urls:
    nom = "urls"

    def trouver(self, element, texte):
        debut = texte.find("https://")
        return [Trouvaille(debut, texte.find(" ", debut), "url", 0.9, "test")] if debut >= 0 else []


def _segmentation(tmp_path, granularite="blocs"):
    pdf = tmp_path / "page.pdf"
    with pymupdf.open() as doc:
        doc.new_page(width=612, height=792)
        doc.save(pdf)
    lignes = [Line(_box(72, 300 + 14 * i, 540, 312 + 14 * i), [Span(t, ARIAL, 10.0, "000000")], u(12), u(468))
              for i, t in enumerate(TEXTES)]
    texte = TextBox(_box(72, 300, 540, 326), lignes)
    filet = ShapeEl(_box(72, 400, 540, 401), [], None, "000000", u(1))
    page = Page(0, u(612), u(792), [texte, filet])
    page.zones_layout = [LayoutAIZone("z", "text", "text", 0.92, _box(70, 298, 542, 328), "paddlex", "test")]
    return ResultatSegmentation(Document([page]), granularite=granularite), pdf


def _identifier(segmentation, pdf, **kwargs):
    kwargs.setdefault("detecteurs", RegistreExpressions())
    return identifier(segmentation, pdf, doclayout=None, vision=None, formulenet=None, **kwargs)


def test_every_box_gets_a_closed_type_with_status_confidence_and_evidence(tmp_path):
    segmentation, pdf = _segmentation(tmp_path)
    resultat = _identifier(segmentation, pdf, identificateurs=[Filets()])
    assert isinstance(resultat, ResultatIdentification) and resultat.segmentation is segmentation
    assert [(e.id, e.type, e.statut) for e in resultat.elements] == [
        ("p0-e0", "paragraphe", "identifie"), ("p0-e1", "separateur", "identifie")]
    assert resultat.elements[0].indices and resultat.elements[1].bbox == (72.0, 400.0, 468.0, 1.0)
    assert resultat.identificateurs == ("faits-natifs", "pp-doclayout", "filets")


def test_a_box_no_source_can_tell_is_not_identified(tmp_path):
    segmentation, pdf = _segmentation(tmp_path)
    filet = _identifier(segmentation, pdf).elements[1]
    assert (filet.type, filet.statut) == ("inconnu", "non_identifie")


def test_fine_lines_inherit_the_type_of_their_element(tmp_path):
    segmentation, pdf = _segmentation(tmp_path, "fine")
    lignes = [e for e in _identifier(segmentation, pdf).elements if e.ligne_index is not None]
    assert [(e.id, e.type) for e in lignes] == [("p0-e0-l0", "paragraphe"), ("p0-e0-l1", "paragraphe")]
    assert lignes[0].indices[0] == "ligne de paragraphe"


def test_expressions_are_located_in_the_element_text(tmp_path):
    segmentation, pdf = _segmentation(tmp_path)
    detecteurs = RegistreExpressions([Urls()])
    expression = _identifier(segmentation, pdf, detecteurs=detecteurs).expressions[0]
    assert (expression.type, expression.texte, expression.element_id) == ("url", "https://noaa.gov", "p0-e0")
    assert expression.debut == len(TEXTES[0]) + 1 + len("See ")


def test_catalogue_holds_every_field_and_totals(tmp_path):
    segmentation, pdf = _segmentation(tmp_path)
    destination = tmp_path / "out.identification.json"
    enregistrer_identification(_identifier(segmentation, pdf, identificateurs=[Filets()]), pdf, destination)
    data = json.loads(destination.read_text(encoding="utf-8"))
    assert data["schema"] == "pdfexact.identification/1" and data["granularite"] == "blocs"
    element = data["elements"][0]
    assert set(element) >= {"id", "page_index", "element_index", "ligne_index", "bbox", "type", "famille", "statut",
                            "confiance", "alternatives", "indices"}
    assert element["ligne_index"] is None
    assert data["totaux"]["par_type"] == {"paragraphe": 1, "separateur": 1}


def test_types_pdf_draws_one_labelled_box_per_element(tmp_path):
    segmentation, pdf = _segmentation(tmp_path)
    destination = tmp_path / "types.pdf"
    annoter_pdf_types(pdf, destination, _identifier(segmentation, pdf, identificateurs=[Filets()]))
    with pymupdf.open(destination) as doc:
        assert len(doc[0].get_drawings()) == 2
        assert "paragraphe" in doc[0].get_text() and "separateur" in doc[0].get_text()


def test_zones_are_rendered_at_the_size_the_model_reads(tmp_path):
    from pdfexact.identification.pipeline import _rendeurs

    segmentation, pdf = _segmentation(tmp_path)
    page = segmentation.document.pages[0]
    with pymupdf.open(pdf) as doc:
        rendeurs = _rendeurs(doc, page)
        assert max(rendeurs["rendre"](_box(72, 300, 300, 350), 512).size) in (512, 513)
        assert max(rendeurs["rendre_marque"](_box(72, 300, 300, 350), 512).size) in (512, 513)
        assert rendeurs["rendre"](_box(72, 300, 144, 336)).size == (150, 75)


def test_progress_is_reported_element_by_element(tmp_path):
    segmentation, pdf = _segmentation(tmp_path)
    vus = []
    _identifier(segmentation, pdf, progres=lambda fait, total: vus.append((fait, total)))
    assert vus == [(1, 2), (2, 2)]


def test_zones_of_a_rotated_page_are_rendered_where_they_are_displayed(tmp_path):
    from pdfexact.identification.pipeline import _rendeurs

    pdf = tmp_path / "tournee.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=612, height=792)
        page.set_rotation(90)
        page.draw_rect(pymupdf.Rect(0, 0, 612, 792), color=None, fill=(1, 1, 1))
        doc.save(pdf)
    page_ir = Page(0, u(792), u(612), [])
    with pymupdf.open(pdf) as doc:
        image = _rendeurs(doc, page_ir)["rendre"](_box(100, 150, 400, 350))
    attendu = (300 * 150 / 72, 200 * 150 / 72)  # PyMuPDF rounds the render outwards
    assert all(abs(a - b) <= 2 for a, b in zip(image.size, attendu))


def test_types_pdf_of_a_rotated_page_draws_each_box_where_it_is_displayed_with_its_id(tmp_path):
    from pdfexact.identification import ElementIdentifie, ResultatIdentification

    source = tmp_path / "tournee.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=612, height=792)
        page.set_rotation(90)
        doc.save(source)
    # Displayed space: 792 x 612, box at x 100..300, y 150..190.
    element = ElementIdentifie("p0-e3", 0, 3, None, (100.0, 150.0, 200.0, 40.0), "paragraphe", "texte", "identifie",
                               0.9, (), ("pp-doclayout:text",))
    destination = tmp_path / "types.pdf"
    annoter_pdf_types(source, destination, ResultatIdentification(None, (element,), (), (), ()))
    with pymupdf.open(destination) as doc:
        page = doc[0]
        assert page.rotation == 90
        pix = page.get_pixmap(dpi=72, alpha=False)  # displayed orientation
        # A thin anti-aliased stroke: red dominates, on one of the two pixels around the edge.
        rouge = lambda x, y: any(pix.pixel(i, y)[0] - pix.pixel(i, y)[1] > 50 for i in (x - 1, x))  # noqa: E731
        assert rouge(100, 170) and rouge(300, 170)  # left and right edges of the box
        assert not rouge(150, 100)  # where the unconverted box used to land
        assert "p0-e3 paragraphe" in page.get_text()
