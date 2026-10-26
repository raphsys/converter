"""Segmentation granularity: fine (lines, every visual part) or blocs (paragraphs, whole images)."""
import pymupdf
import pytest

from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.ir import Document, FontRef, ImageEl, Line, Page, RasterEl, ShapeEl, Span, TextBox
from pdfexact.segmentation import OptionsSegmentation
from pdfexact.segmentation.granularite import boites, regrouper_visuels_en_blocs


def _box(x0, y0, x1, y1):
    return BBox(u(x0), u(y0), u(x1), u(y1))


def _texte():
    lines = [Line(_box(72, 100 + 14 * i, 300, 110 + 14 * i), [Span(f"line {i}", FontRef("f", "Arial", False, False), 10, "000000")],
                  u(10), u(228)) for i in range(2)]
    return TextBox(_box(72, 100, 300, 124), lines)


def _document(tmp_path):
    pdf = tmp_path / "page.pdf"
    with pymupdf.open() as doc:
        doc.new_page(width=612, height=792)
        doc.save(pdf)
    logo_a = ImageEl(_box(50, 50, 120, 120), "a", source_id="logo-part-a")
    logo_b = ImageEl(_box(100, 60, 160, 130), "b", source_id="logo-part-b")
    separate = ImageEl(_box(300, 300, 400, 400), "c", source_id="photo")
    frame = ShapeEl(_box(20, 20, 592, 772), [], None, "0000FF", u(1))
    page = Page(0, u(612), u(792), [frame, logo_a, logo_b, separate, _texte()])
    return Document([page], media={}), pdf


def test_touching_visual_parts_become_one_image_in_blocs(tmp_path):
    document, pdf = _document(tmp_path)
    regrouper_visuels_en_blocs(document, pdf, dpi=72)
    visuels = [e for e in document.pages[0].elements if isinstance(e, (ImageEl, RasterEl))]
    assert len(visuels) == 2
    bloc = next(e for e in visuels if isinstance(e, RasterEl))
    assert bloc.bbox == _box(50, 50, 160, 130)
    assert set(bloc.source_component_ids) == {"logo-part-a", "logo-part-b"}
    assert bloc.media_ref in document.media
    assert any(e.source_id == "photo" for e in visuels)


def test_shapes_and_text_are_not_absorbed_by_visual_blocs(tmp_path):
    document, pdf = _document(tmp_path)
    regrouper_visuels_en_blocs(document, pdf, dpi=72)
    elements = document.pages[0].elements
    assert sum(isinstance(e, ShapeEl) for e in elements) == 1
    assert sum(isinstance(e, TextBox) for e in elements) == 1


def test_fine_draws_one_text_box_per_line_and_blocs_one_per_paragraph(tmp_path):
    document, _pdf = _document(tmp_path)
    assert len([b for b in boites(document, "fine") if b.kind == "text"]) == 2
    assert len([b for b in boites(document, "blocs") if b.kind == "text"]) == 1


def test_granularity_defaults_to_blocs_and_rejects_unknown_values():
    assert OptionsSegmentation().granularite == "blocs"
    assert OptionsSegmentation(granularite="fine").granularite == "fine"
    with pytest.raises(ValueError):
        OptionsSegmentation(granularite="moyenne")


def test_each_box_points_to_its_element_and_in_fine_to_its_line(tmp_path):
    document, _pdf = _document(tmp_path)
    texte = 4  # frame, logo_a, logo_b, separate, then the text block
    fines = [b for b in boites(document, "fine") if b.kind == "text"]
    assert [(b.element_index, b.ligne_index) for b in fines] == [(texte, 0), (texte, 1)]
    blocs = [b for b in boites(document, "blocs") if b.kind == "text"]
    assert [(b.element_index, b.ligne_index) for b in blocs] == [(texte, None)]


def test_pages_keep_their_layout_zones():
    from pdfexact.ir import Page

    assert Page(0, 1, 1).zones_layout == []


def _ligne(texte, y):
    return Line(_box(72, y, 300, y + 10), [Span(texte, FontRef("f", "Arial", False, False), 10, "000000")], u(10), u(228))


def test_a_text_without_any_visible_character_is_not_segmented():
    from pdfexact.segmentation.pipeline import _normaliser_texte

    vide = TextBox(_box(540, 173, 545, 189), [_ligne("  ", 175)])
    plein = TextBox(_box(72, 100, 300, 110), [_ligne("Final report", 100)])
    document = Document([Page(0, u(612), u(792), [vide, plein])], media={})
    _normaliser_texte(document)
    textes = [e for e in document.pages[0].elements if isinstance(e, TextBox)]
    assert ["".join(s.texte for l in e.lignes for s in l.spans) for e in textes] == ["Final report"]


def test_fine_skips_the_empty_lines_of_a_text_block():
    bloc = TextBox(_box(72, 100, 300, 134), [_ligne("first", 100), _ligne("  ", 112), _ligne("third", 124)])
    document = Document([Page(0, u(612), u(792), [bloc])], media={})
    assert [b.ligne_index for b in boites(document, "fine")] == [0, 2]
    assert len(boites(document, "blocs")) == 1
