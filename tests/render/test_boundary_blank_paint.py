"""Boundary decorations must not displace native body text."""
from copy import deepcopy
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from pdfexact.analysis.text_segmentation import segmenter_page_textes
from pdfexact.geometry import BBox, GRILLE_DIXIEME_MM_EMU, emu_vers_pt, pt_vers_emu as u, pt_vers_twips, quantifier_bbox
from pdfexact.ir import Document, FontRef, Line, Page, Span, TextBox, element_source_ids
from pdfexact.layout import text_comprehension as comprehension
from pdfexact.render.render_plan import build_render_plan
from pdfexact.render.geometry_adapter import prepare_text_geometry, twips
from pdfexact.render.text_backend import prepare_text_instructions
from pdfexact.render.text_backend import render_native_paragraph
from pdfexact.scene import _snapshot_value, capture_source_observations


NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
W = "{" + NS["w"] + "}"


@pytest.fixture(autouse=True)
def isolated_provider():
    token = comprehension._ANALYSE.set(comprehension._AnalysisState(None))
    yield
    comprehension._ANALYSE.reset(token)


def source_document(side, decoration, ys=(10, 24, 38)):
    rows = []
    for text, y, decorated in (("   ", ys[0], side in {"leading", "both"}),
                               ("Native body", ys[1], False),
                               ("   ", ys[2], side in {"trailing", "both"})):
        box = BBox(u(30), u(y), u(190), u(y + 10))
        baseline = ((box.x0, u(y + 8)), (box.x1, u(y + 8)))
        span = Span(text, FontRef("Arial", "Arial", False, False), 10, "000000",
                    bbox=box, baseline_points=baseline, source_kind="pdf-native")
        if decorated and decoration:
            setattr(span, decoration, True)
        rows.append(Line(box, [span], box.hauteur, box.largeur,
                         baseline_points=baseline, source_kind="pdf-native"))
    block = TextBox(BBox(u(30), u(ys[0]), u(190), u(ys[2] + 10)), rows,
                    source_kind="pdf-native", opacity=1.0)
    page = Page(3, u(300), u(240), [block])
    capture_source_observations(page, page.elements)
    return Document([page])


def normalize(document, monkeypatch):
    monkeypatch.setattr("pdfexact.analysis.text_segmentation.comprendre_segmentation_page",
                        lambda *args, **kwargs: None)
    segmenter_page_textes(document.pages[0])
    assert len(document.pages[0].elements) == 1
    return document.pages[0].elements[0]


@pytest.mark.parametrize("side", ["leading", "trailing"])
@pytest.mark.parametrize("decoration", ["souligne", "barre"])
def test_producer_envelope_includes_boundary_paint_only(side, decoration, monkeypatch):
    doc = source_document(side, decoration)
    inventory = _snapshot_value(doc.pages[0].source_inventory)
    original = deepcopy(doc.pages[0].elements[0])

    block = normalize(doc, monkeypatch)

    expected = quantifier_bbox(BBox(u(30), u(10 if side == "leading" else 24),
                                   u(190), u(34 if side == "leading" else 48)))
    assert block.bbox == expected
    assert [line.spans for line in block.lignes] == [line.spans for line in original.lignes]
    assert _snapshot_value(doc.pages[0].source_inventory) == inventory
    plan = build_render_plan(doc)
    assert plan.validate(doc) == []
    assert set(element_source_ids(original)) <= set(plan.source_coverage)


@pytest.mark.parametrize("side", ["leading", "trailing"])
@pytest.mark.parametrize("decoration", ["souligne", "barre"])
def test_native_xml_anchor_and_row_offsets_preserve_body_baseline(side, decoration, monkeypatch):
    doc = source_document(side, decoration)
    block = normalize(doc, monkeypatch)
    plan = build_render_plan(doc)
    assert plan.validate(doc) == []
    instructions = plan.instructions_for_page(3)
    assert len(instructions) == 2
    assert len({item.instruction_id for item in instructions}) == 2
    root = ET.fromstring(f'<root xmlns:w="{NS["w"]}">' + "".join(
        render_native_paragraph(item.text) for item in instructions) + "</root>")
    painted_y = 10 if side == "leading" else 38
    paragraphs = {"".join(node.text or "" for node in p.findall(".//w:t", NS)): p
                  for p in root.findall("w:p", NS)}
    for content, y in (("Native body", 24), ("   ", painted_y)):
        anchor_y = int(paragraphs[content].find("w:pPr/w:framePr", NS).get(W + "y"))
        expected_anchor = twips(quantifier_bbox(BBox(u(30), u(y), u(190), u(y + 10))).y0)
        assert anchor_y == expected_anchor
        # Same source font and baseline offset as the corresponding one-row
        # control; source quantization is the only allowed translation error.
        assert abs(anchor_y + twips(u(8)) - twips(u(y + 8))) <= twips(GRILLE_DIXIEME_MM_EMU) + 1
    tag = "w:u" if decoration == "souligne" else "w:strike"
    assert root.find(".//w:rPr/" + tag, NS) is not None
    assert not root.findall(".//w:br", NS)
    line_ids = [line.source_id for item in instructions for line in item.element.lignes]
    assert len(line_ids) == len(set(line_ids)) == len(block.lignes)
    for item in instructions:
        selected = {node.source_id for line in item.element.lignes for node in (line, *line.spans)}
        siblings = {node.source_id for line in block.lignes for node in (line, *line.spans)} - selected
        assert not siblings.intersection(item.element.source_ids)
        assert all(token.width_percent == 100 for token in item.text.native_runs)


def test_ordinary_boundary_whitespace_does_not_enlarge_or_shift_body(monkeypatch):
    doc = source_document("leading", None)
    block = normalize(doc, monkeypatch)
    expected = quantifier_bbox(BBox(u(30), u(24), u(190), u(34)))
    assert block.bbox == expected
    plan = build_render_plan(doc)
    assert plan.validate(doc) == []
    text = plan.instructions_for_page(3)[0].text
    xml = render_native_paragraph(text)
    root = ET.fromstring(f'<root xmlns:w="{NS["w"]}">{xml}</root>')
    assert root.find(".//w:framePr", NS).get(W + "y") == str(twips(expected.y0))
    assert not root.findall(".//w:br", NS)
    assert [node.text for node in root.findall(".//w:t", NS)] == ["Native body"]


def test_irregular_boundary_paint_uses_original_native_positions_not_uniform_approximation(monkeypatch):
    doc = source_document("both", "souligne", ys=(10, 24, 45))
    original = deepcopy(doc.pages[0].elements[0])
    normalize(doc, monkeypatch)
    plan = build_render_plan(doc)
    assert plan.validate(doc) == []
    instructions = plan.instructions_for_page(3)
    assert len(instructions) == len({item.instruction_id for item in instructions}) == 3
    assert [item.text.geometry.bbox.y0 for item in instructions] == [
        quantifier_bbox(line.bbox).y0 for line in original.lignes
    ]
    for item, line in zip(instructions, original.lignes):
        assert item.element.lignes[0].source_id == line.source_id
        assert item.element.lignes[0].spans == line.spans
        assert "<w:br/>" not in render_native_paragraph(item.text)


@pytest.mark.parametrize("count", [1, 2, 5])
def test_exact_source_rows_use_ink_height_plus_baseline_steps_not_height_divided_by_count(count):
    lines = []
    for index in range(count):
        y = 10 + index * 14
        bbox = BBox(u(30), u(y), u(190), u(y + 10))
        baseline = ((bbox.x0, u(y + 8)), (bbox.x1, u(y + 8)))
        span = Span("Source row", FontRef("Arial", "Arial", False, False), 10, "000000", bbox=bbox)
        lines.append(Line(bbox, [span], u(10), bbox.largeur, baseline_points=baseline))
    bbox = BBox(u(30), u(10), u(190), u(20 + (count - 1) * 14))
    text = prepare_text_instructions(TextBox(bbox, lines), preserve_line_boundaries=True)
    assert text.geometry.native_height == twips(quantifier_bbox(bbox).hauteur)
    assert text.geometry.native_line_height == twips(u(14 if count > 1 else 10))
    assert text.geometry.native_height < count * twips(u(14))
    assert all(token.width_percent == 100 and token.span.size_pt == 10
               for token in text.native_runs if token.span is not None)


@pytest.mark.parametrize("nonexact", ["orientation", "embedded-break"])
def test_source_step_formula_does_not_claim_nonexact_native_row_contract(nonexact):
    doc = source_document("leading", None)
    block = doc.pages[0].elements[0]
    block.lignes = block.lignes[:2]
    block.bbox = BBox(u(30), u(10), u(190), u(34))
    block.lignes[0].spans[0].texte = "First row"
    if nonexact == "orientation":
        block.angle_deg = 30
        block.orientation = "oblique-down"
    else:
        block.lignes[0].spans[0].texte = "First\nrow"
    text = prepare_text_instructions(block, preserve_line_boundaries=True)
    assert text.geometry.native_line_height != twips(u(14))


def test_expanded_native_height_is_capped_in_twips_before_next_source_bbox():
    doc = source_document("leading", None)
    line = doc.pages[0].elements[0].lignes[1]
    block = TextBox(line.bbox, [line])
    following = BBox(u(30), u(39), u(190), u(49))
    composition = SimpleNamespace(preserve_lines=False, estimated_line_count=3)
    uncapped, _ = prepare_text_geometry(block, [line], composition)
    capped, _ = prepare_text_geometry(block, [line], composition, (following,))
    available_twips = pt_vers_twips(emu_vers_pt(following.y0 - u(0.5) - capped.bbox.y0))
    source_twips = pt_vers_twips(emu_vers_pt(capped.bbox.hauteur))

    assert source_twips < available_twips < uncapped.native_height
    assert capped.native_height == available_twips
    assert capped.native_line_height == uncapped.native_line_height
    assert capped.bbox == uncapped.bbox == quantifier_bbox(line.bbox)


def _rows(steps, ink=10.0):
    lines, y = [], 100.0
    for index in range(len(steps) + 1):
        bbox = BBox(u(72), u(y), u(540), u(y + ink))
        baseline = ((bbox.x0, u(y + 8)), (bbox.x1, u(y + 8)))
        span = Span(f"Table {index}. Row label", FontRef("Arial", "Arial", True, False), 10, "000000", bbox=bbox)
        lines.append(Line(bbox, [span], u(ink), bbox.largeur, baseline_points=baseline))
        if index < len(steps):
            y += steps[index]
    return lines


@pytest.mark.parametrize("steps", [(14.5,) * 5, (14.5, 14.45, 14.55, 14.5, 14.48)])
def test_separate_rows_keep_the_source_pitch_instead_of_ink_height_divided_by_count(steps):
    lines = _rows(steps)
    block = TextBox(BBox(lines[0].bbox.x0, lines[0].bbox.y0, lines[-1].bbox.x1, lines[-1].bbox.y1), lines)
    composition = SimpleNamespace(preserve_lines=False, estimated_line_count=len(lines))
    geometry, _ = prepare_text_geometry(block, lines, composition)
    assert abs(geometry.native_line_height - twips(u(14.5))) <= 1


@pytest.mark.parametrize("steps", [(14.5, 14.45, 14.55, 14.5, 14.48)])
def test_exact_rows_tolerate_rounding_jitter_between_source_steps(steps):
    lines = _rows(steps)
    block = TextBox(BBox(lines[0].bbox.x0, lines[0].bbox.y0, lines[-1].bbox.x1, lines[-1].bbox.y1), lines)
    text = prepare_text_instructions(block, preserve_line_boundaries=True)
    assert abs(text.geometry.native_line_height - twips(u(14.5))) <= 1
