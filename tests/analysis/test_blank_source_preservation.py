"""Whitespace observations must survive normalization as real source children."""
from copy import deepcopy

import pytest

from pdfexact.analysis import text_segmentation as segmentation
from pdfexact.analysis.provenance import observation_is_preserved, observation_signature
from pdfexact.analysis.text_geometry import geometry_contract_for, line_has_text, paragraph_bbox_from_lines
from pdfexact.extract.text import dedoublonner_textboxes_paragraphes
from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.ir import Document, FontRef, Line, Page, Span, TextBox, element_source_ids
from pdfexact.render.render_plan import build_render_plan
from pdfexact.scene import _snapshot_value, capture_source_observations


def row(text, y):
    bbox = BBox(u(30), u(y), u(180 if text.strip() else 42), u(y + 10))
    span = Span(text, FontRef("source-font", "Arial", False, False), 10, "314159",
                bbox=bbox, source_kind="pdf-native", z_index=0,
                souligne=True, espacement_twips=2,
                baseline_points=((bbox.x0, bbox.y1), (bbox.x1, bbox.y1)),
                quad=((bbox.x0, bbox.y0), (bbox.x1, bbox.y0),
                      (bbox.x1, bbox.y1), (bbox.x0, bbox.y1)),
                font_metrics={"ascent": 0.8, "descent": -0.2})
    span.opacity = 0.0 if not text.strip() else 1.0
    span.attributes["source-characters"] = tuple(text)
    return Line(bbox, [span], bbox.hauteur, bbox.largeur,
                source_kind="pdf-native", z_index=0)


def block(rows):
    bbox = BBox(min(line.bbox.x0 for line in rows), min(line.bbox.y0 for line in rows),
                max(line.bbox.x1 for line in rows), max(line.bbox.y1 for line in rows))
    return TextBox(bbox, rows, source_kind="pdf-native", z_index=0)


def source_document(*elements):
    page = Page(0, u(300), u(240), list(elements))
    capture_source_observations(page, page.elements)
    document = Document([page])
    assert build_render_plan(document).validate() == []
    return document


def assert_children_preserved(original, outputs):
    for source in original.lignes:
        copies = [line for output in outputs for line in output.lignes
                  if line.source_id == source.source_id]
        assert len(copies) == 1, f"source row missing or duplicated: {source.source_id!r}"
        assert observation_signature(copies[0]) == observation_signature(source)
        assert copies[0].spans == source.spans
    assert observation_is_preserved(original, outputs)


@pytest.mark.parametrize("whitespace", [" ", "\t ", "\u00a0\u00a0"])
def test_dedup_preserves_entirely_blank_source_block(whitespace):
    source = block([row(whitespace, 10), row(whitespace, 24)])
    document = source_document(source)
    original = deepcopy(source)
    inventory = _snapshot_value(document.pages[0].source_inventory)

    document.pages[0].elements = dedoublonner_textboxes_paragraphes(document.pages[0].elements)

    assert document.pages[0].elements == [original]
    assert_children_preserved(original, document.pages[0].elements)
    assert _snapshot_value(document.pages[0].source_inventory) == inventory
    plan = build_render_plan(document)
    assert plan.validate() == []
    assert set(element_source_ids(original)) <= set(plan.source_coverage)


def test_segmentation_preserves_blank_block_next_to_visible_block(monkeypatch):
    blank = block([row(" \t", 10), row("\u00a0", 24)])
    visible = block([row("Visible paragraph.", 60)])
    document = source_document(blank, visible)
    original = deepcopy(blank)
    inventory = _snapshot_value(document.pages[0].source_inventory)
    monkeypatch.setattr(segmentation, "comprendre_segmentation_page", lambda *args, **kwargs: None)

    segmentation.segmenter_page_textes(document.pages[0])

    assert_children_preserved(original, document.pages[0].elements)
    assert _snapshot_value(document.pages[0].source_inventory) == inventory
    assert build_render_plan(document).validate() == []


def test_mixed_blank_rows_keep_exact_children_and_source_coverage(monkeypatch):
    source = block([row(" \t", 10), row("First paragraph.", 24), row("   ", 38),
                    row("Second paragraph.", 52), row("\u00a0 ", 66)])
    document = source_document(source)
    original = deepcopy(source)
    inventory = _snapshot_value(document.pages[0].source_inventory)
    attempts = []

    def unavailable(*args, **kwargs):
        attempts.append((args, kwargs))
        return None

    monkeypatch.setattr(segmentation, "comprendre_segmentation_page", unavailable)
    segmentation.segmenter_page_textes(document.pages[0])

    assert attempts, "blank preservation must not silently bypass visible-text analysis"
    assert attempts[0][0][0] == ["First paragraph.", "Second paragraph."]
    assert_children_preserved(original, document.pages[0].elements)
    assert _snapshot_value(document.pages[0].source_inventory) == inventory
    plan = build_render_plan(document)
    assert plan.validate() == []
    assert set(element_source_ids(original)) <= set(plan.source_coverage)
    for output in document.pages[0].elements:
        visible = [line for line in output.lignes if line_has_text(line)]
        assert output.bbox == paragraph_bbox_from_lines(visible)
        assert output.geometry == geometry_contract_for(output)
        assert output.presentation["line_count"] == len(visible)
    normalized = _snapshot_value(document.pages[0].elements)
    segmentation.segmenter_page_textes(document.pages[0])
    assert _snapshot_value(document.pages[0].elements) == normalized


def test_line_unit_does_not_claim_unconsumed_sibling_source_ids():
    source = block([row("First paragraph.", 10), row(" ", 24), row("Second paragraph.", 38)])
    source_document(source)

    unit = segmentation._ligne_unit(source, source.lignes[0], 0, "owner")

    sibling_ids = {ident for line in source.lignes[1:] for ident in element_source_ids(line)}
    assert not sibling_ids.intersection(unit.source_ids)
    assert set(element_source_ids(source.lignes[0])) <= set(element_source_ids(unit))
    assert set(unit.source_ids) <= {source.source_id, *element_source_ids(source.lignes[0])}


def test_two_blank_blocks_are_retained_without_claiming_a_verified_duplicate():
    first = block([row(" ", 10)])
    second = deepcopy(first)
    document = source_document(first, second)
    sources = deepcopy(document.pages[0].elements)

    document.pages[0].elements = dedoublonner_textboxes_paragraphes(document.pages[0].elements)

    assert document.pages[0].elements == sources
    assert first.source_id != second.source_id
    assert all("duplicate_verified" not in source.attributes for source in document.pages[0].elements)
    assert build_render_plan(document).validate() == []


def test_visible_only_control_already_has_exact_source_coverage(monkeypatch):
    source = block([row("Visible first line", 10), row("and its continuation.", 24)])
    document = source_document(source)
    original = deepcopy(source)
    monkeypatch.setattr(segmentation, "comprendre_segmentation_page", lambda *args, **kwargs: None)

    segmentation.segmenter_page_textes(document.pages[0])

    assert_children_preserved(original, document.pages[0].elements)
    assert build_render_plan(document).validate() == []
