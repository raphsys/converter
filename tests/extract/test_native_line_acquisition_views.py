"""Derived reading frames must not change acquired native components."""
from copy import deepcopy

import pymupdf
import pytest

from pdfexact.analysis.ocr_correspondence import _digest
from pdfexact.extract import ocr
from pdfexact.extract.document import _attacher_frames_texte, _extraire_texte_pdf_natif_word_native
from pdfexact.extract.fonts import collecter_polices
from pdfexact.extract.text import extraire_texte
from pdfexact.geometry import BBox, PageGeometry, pt_vers_emu as u
from pdfexact.ir import Document, FontRef, Line, Page, Span, TextBox, element_source_ids, element_text
from pdfexact.layout.model import LayoutRegion
from pdfexact.layout.planner import LayoutPlanItem
from pdfexact.layout.text_comprehension import contexte_comprehension_texte, configurer_fournisseur_comprehension_texte
from pdfexact.scene import _snapshot_value, capture_source_observations


def frame(bbox, kind="text-column"):
    region = LayoutRegion(kind=kind, bbox=bbox, confidence=None, editable=True,
                          strategy="word-text", style_hints={"source": "pure-frame-test"})
    return LayoutPlanItem(kind=kind, bbox=bbox, strategy="word-text", editable=True,
                          confidence=None, region=region)


@pytest.fixture(autouse=True)
def no_comprehension_provider():
    with contexte_comprehension_texte():
        configurer_fournisseur_comprehension_texte(None)
        yield


@pytest.fixture
def native_selection(pdf_texte):
    with pymupdf.open(pdf_texte) as pdf:
        page_pdf = pdf[0]
        geometry = PageGeometry.depuis_page(page_pdf)
        fonts = collecter_polices(pdf)
        discovered = extraire_texte(page_pdf, fonts, geometry)
        page = Page(0, geometry.largeur_emu, geometry.hauteur_emu)
        observations = ocr._capture_ocr_lines(
            page_pdf,
            [ocr.OcrLine(element_text(line), .91, line.bbox)
             for source in discovered for line in source.lignes],
            page, "pure-native-frame-test",
        )
        native = ocr._acquerir_sources_natives(page_pdf, fonts, geometry, page)
        selected = {line.source_id for source in native for line in source.lignes}
        page.elements = ocr._sortie_sources_natives(page_pdf, native, selected, observations, page, geometry)
        return Document([page], polices=fonts)






def test_unacquired_lines_can_receive_initial_frame_metadata():
    bbox = BBox(u(40), u(60), u(200), u(72))
    span = Span("Not acquired yet", FontRef("font", "Arial", False, False), 12, "000000")
    line = Line(bbox, [span], u(12), bbox.largeur)
    root = TextBox(bbox, [line])
    result = _attacher_frames_texte([root], [frame(bbox)])
    assert result[0].lignes[0].layout_frame_id
    assert result[0].layout_frame_role == "text-column"


def test_native_paragraph_adapter_keeps_owner_frame_and_acquired_line(pdf_texte):
    with pymupdf.open(pdf_texte) as pdf:
        page_pdf = pdf[0]
        geometry = PageGeometry.depuis_page(page_pdf)
        fonts = collecter_polices(pdf)
        page = Page(0, geometry.largeur_emu, geometry.hauteur_emu)
        whole_page = BBox(0, 0, page.largeur_emu, page.hauteur_emu)
        paragraphs = _extraire_texte_pdf_natif_word_native(
            page_pdf, fonts, [frame(whole_page)], [], [], page, Document(), geometrie=geometry,
        )
    assert paragraphs
    assert all(paragraph.layout_frame_role == "text-column" for paragraph in paragraphs)
    assert all(paragraph.layout_frame_bbox == whole_page for paragraph in paragraphs)
    for paragraph in paragraphs:
        line = paragraph.lignes[0]
        assert _digest(line) == _digest(page.source_inventory[line.source_id])
