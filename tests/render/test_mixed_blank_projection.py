"""Layout projections never delete retained source observations."""
from copy import deepcopy
from dataclasses import asdict, replace
from xml.etree import ElementTree as ET
import zipfile

import pytest

from pdfexact.analysis.options import AnalysisOptions
from pdfexact.analysis.text_geometry import presentation_for
from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.ir import Document, FlowParagraph, FontRef, Line, Page, Span, TextBox, element_source_ids
from pdfexact.layout import text_comprehension as comprehension
from pdfexact.render.package import GestionnaireRelations
from pdfexact.render.render_plan import build_render_plan
from pdfexact.render.text_backend import prepare_text_instructions, render_native_paragraph
from pdfexact.render.word_native_rewriter import rewrite_document_xml
from pdfexact.scene import _snapshot_value, capture_source_observations


NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
FONT = FontRef("source-font", "Arial", False, False)


@pytest.fixture(autouse=True)
def isolated_provider():
    token = comprehension._ANALYSE.set(comprehension._AnalysisState(None))
    yield
    comprehension._ANALYSE.reset(token)


def row(text, y, **style):
    bbox = BBox(u(30), u(y), u(190), u(y + 10))
    return Line(bbox, [Span(text, FONT, 10, "314159", bbox=bbox, **style)],
                u(10), bbox.largeur)


def mixed(*, padded=False, flow=False):
    rows = [row(" \t", 10), row("Exact first line", 24), row("   ", 38),
            row("and exact continuation.", 52), row("\u00a0 ", 66)]
    bbox = BBox(u(30), u(10 if padded else 24), u(190), u(76 if padded else 62))
    if flow:
        return FlowParagraph(bbox, "Exact first line and exact continuation.", FONT, 10,
                             "314159", lignes=rows, spans=[span for line in rows for span in line.spans])
    return TextBox(bbox, rows, presentation={"paragraph_validated": True})


def document(source):
    page = Page(3, u(300), u(240), [source])
    capture_source_observations(page, page.elements)
    return Document([page])


def span_texts(tokens):
    return [item.span.texte for item in tokens if item.span is not None]


@pytest.mark.parametrize("padded", [False, True])
@pytest.mark.parametrize("flow", [False, True])
@pytest.mark.parametrize("preserve", [False, True])
def test_mixed_layout_matches_visible_control_without_changing_source(padded, flow, preserve):
    source = mixed(padded=padded, flow=flow)
    source_lines = tuple(source.lignes)
    original = deepcopy(source)
    control = deepcopy(source)
    control.lignes = [line for line in control.lignes if any(span.texte.strip() for span in line.spans)]
    if flow:
        control.spans = [span for line in control.lignes for span in line.spans]
    expected = prepare_text_instructions(control, preserve_line_boundaries=preserve)

    actual = prepare_text_instructions(source, preserve_line_boundaries=preserve)

    assert actual.geometry == expected.geometry  # Same source bbox, no cropping assumption.
    assert actual.composition == expected.composition
    for name in ("native_runs", "flow_runs", "frame_runs", "slices", "vertical_lines"):
        assert getattr(actual, name) == getattr(expected, name)
    assert source == original
    assert source.bbox == original.bbox
    assert all(a is b for a, b in zip(source.lignes, source_lines))
    xml = render_native_paragraph(actual)
    assert xml.count("<w:br/>") == render_native_paragraph(expected).count("<w:br/>")


def test_projection_retains_full_payload_inventory_and_real_page_index():
    source = mixed()
    doc = document(source)
    original = _snapshot_value(source)
    inventory = _snapshot_value(doc.pages[0].source_inventory)
    plan = build_render_plan(doc, AnalysisOptions(preserve_line_boundaries="always"))

    assert plan.validate(doc) == []
    assert set(element_source_ids(source)) <= set(plan.source_coverage)
    instruction = plan.instructions_for_page(3)[0]
    assert _snapshot_value(instruction.element) == original
    assert span_texts(instruction.text.native_runs) == ["Exact first line", "and exact continuation."]
    assert instruction.text.composition.estimated_line_count == 2
    assert render_native_paragraph(instruction.text).count("<w:br/>") == 1
    assert _snapshot_value(source) == original
    assert _snapshot_value(doc.pages[0].source_inventory) == inventory


@pytest.mark.parametrize("text", [" ", "\t ", "\u00a0", " \n "])
def test_entirely_blank_block_keeps_original_native_path(text):
    source = TextBox(BBox(u(30), u(10), u(190), u(34)), [row(text, 10), row(text, 24)])
    doc = document(source)
    plan = build_render_plan(doc)
    assert plan.validate(doc) == []
    tokens = plan.instructions_for_page(3)[0].text.native_runs
    assert span_texts(tokens) == [text, text]
    result = rewrite_document_xml(doc, GestionnaireRelations(), render_plan=plan)
    assert result.diagnostics.conforme
    assert result.diagnostics.anchored_frames + result.diagnostics.direct_body_paragraphs == 1
    assert ET.fromstring(result.xml).findall(".//w:r", NS)


@pytest.mark.parametrize(("style", "xml_tag"), [
    ({"souligne": True}, "w:u"), ({"barre": True}, "w:strike"),
    ({"surlignage": "yellow"}, "w:highlight"),
])
def test_decorated_whitespace_line_stays_editable_and_rendered(style, xml_tag):
    source = mixed()
    source.lignes[2].spans[0] = replace(source.lignes[2].spans[0], **style)
    plan = build_render_plan(document(source))
    assert plan.validate() == []
    text = plan.instructions_for_page(3)[0].text
    assert span_texts(text.native_runs) == ["Exact first line", "   ", "and exact continuation."]
    result = rewrite_document_xml(Document([Page(3, u(300), u(240), [source])]),
                                  GestionnaireRelations(), render_plan=plan)
    root = ET.fromstring(result.xml)
    assert result.diagnostics.conforme
    assert any(run.find("w:rPr/" + xml_tag, NS) is not None
               and run.find("w:t", NS).text == "   " for run in root.findall(".//w:r", NS)
               if run.find("w:t", NS) is not None)


@pytest.mark.parametrize("level", ["block", "line", "span"])
@pytest.mark.parametrize("storage", ["attribute", "field"])
def test_unknown_paint_properties_keep_whitespace_conservatively(level, storage):
    source = mixed()
    target = {"block": source, "line": source.lignes[2], "span": source.lignes[2].spans[0]}[level]
    if storage == "attribute":
        target.attributes["unrecognized-paint"] = {"fill": "FF0000"}
    else:
        target.custom_effect = "shadow"
    text = prepare_text_instructions(source)
    assert "   " in span_texts(text.native_runs)


@pytest.mark.parametrize("text", ["\n", "\r\n", "\u2028", "\u2029"])
def test_explicit_hard_breaks_are_not_projection_candidates(text):
    source = mixed()
    source.lignes[2].spans[0].texte = text
    assert text in span_texts(prepare_text_instructions(source).native_runs)


def test_inline_spaces_and_newlines_are_not_rewritten():
    source = mixed()
    source.lignes[1].spans[0].texte = "  Exact\nfirst line  "
    text = prepare_text_instructions(source)
    assert span_texts(text.native_runs) == ["  Exact\nfirst line  ", "and exact continuation."]
    assert "<w:br/>" in render_native_paragraph(text)


def test_visible_analysis_attempt_and_failure_diagnostic_remain(caplog):
    calls = []

    def unavailable(kind, lines, *args):
        calls.append((kind, lines))
        return None

    comprehension.configurer_fournisseur_comprehension_texte(unavailable)
    prepare_text_instructions(mixed())
    assert calls == [("paragraph-reflow", ("Exact first line", "and exact continuation."))]
    assert "empty-response" in caplog.text


def test_existing_layout_metadata_does_not_disable_mixed_projection():
    source = mixed(flow=True)
    source.presentation.update(asdict(presentation_for(source)))
    for line in source.lignes:
        for span in line.spans:
            span.attributes.update(source_font_name="ArialMT", source_origin=(30, 24),
                                   source_size_pt=10, source_alpha=255)
    assert span_texts(prepare_text_instructions(source).native_runs) == [
        "Exact first line", "and exact continuation.",
    ]


@pytest.mark.parametrize("boundary", ["boundary_before", "boundary_after"])
def test_explicit_blank_line_boundary_is_retained(boundary):
    source = mixed()
    setattr(source.lignes[2], boundary, "hard-break")
    assert "   " in span_texts(prepare_text_instructions(source).native_runs)


@pytest.mark.parametrize("detail", ["glyph_ids", "to_unicode_status"])
def test_unresolved_whitespace_glyph_contract_is_not_projected(detail):
    source = mixed()
    setattr(source.lignes[2].spans[0], detail, (42,) if detail == "glyph_ids" else "unknown")
    assert "   " in span_texts(prepare_text_instructions(source).native_runs)


def test_supplied_plan_uses_projection_in_both_xml_consumers(tmp_path, monkeypatch):
    from pdfexact.render.bbox_debug import (
        fill_existing_bbox_docx, fill_existing_bbox_docx_with_native_paragraphs, write_bbox_only_docx,
    )
    doc = document(mixed())
    plan = build_render_plan(doc, AnalysisOptions(preserve_line_boundaries="always"))

    def forbidden(*args, **kwargs):
        raise AssertionError("planning during supplied-plan consumption")

    monkeypatch.setattr("pdfexact.render.text_backend.prepare_text_instructions", forbidden)
    monkeypatch.setattr("pdfexact.render.text_backend.planifier_paragraphe", forbidden)
    result = rewrite_document_xml(doc, GestionnaireRelations(), render_plan=plan)
    assert result.diagnostics.conforme
    assert result.xml.count("<w:br/>") == 1
    skeleton, nontext, final = [tmp_path / name for name in ("bbox.docx", "nontext.docx", "final.docx")]
    write_bbox_only_docx(doc, skeleton, render_plan=plan)
    fill_existing_bbox_docx(skeleton, doc, nontext, render_plan=plan)
    fill_existing_bbox_docx_with_native_paragraphs(nontext, doc, final, render_plan=plan)
    with zipfile.ZipFile(final) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    assert len(root.findall(".//w:br", NS)) == 1
    assert [node.text for node in root.findall(".//w:t", NS)] == ["Exact first line", "and exact continuation."]


@pytest.mark.parametrize("decorated", [False, True])
def test_guard_still_rejects_forged_empty_native_instructions(decorated):
    source = mixed()
    if decorated:
        source.lignes[2].spans[0].souligne = True
    plan = build_render_plan(document(source))
    item = plan.for_page(3)[0]
    instruction = item.materialization.fragments[0]
    forged = replace(instruction, text=replace(instruction.text, native_runs=()))
    plan.pages[3] = [replace(item, materialization=replace(item.materialization, fragments=(forged,)))]
    plan.instructions_by_page[3] = (forged,)
    assert any("empty-text-materialization" in error for error in plan.validate())
