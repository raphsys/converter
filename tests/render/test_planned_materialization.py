from dataclasses import replace
from xml.etree import ElementTree as ET

import pytest

from pdfexact.geometry import BBox, pt_vers_emu
from pdfexact.ir import Document, FontRef, Line, LinkZone, Page, ShapeEl, Span, TextBox
from pdfexact.render.package import GestionnaireRelations
from pdfexact.render.render_plan import PlannedElement, RenderPlan, build_document_render_plan, build_page_render_plan
from pdfexact.render.word_native_rewriter import rewrite_document_xml


NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}


def _text():
    box = BBox(*(pt_vers_emu(v) for v in (40, 80, 200, 92)))
    span = Span("Earlier native text", FontRef("test", "Arial", False, False), 10, "000000", bbox=box, z_index=2)
    later_box = replace(box, y0=pt_vers_emu(100), y1=pt_vers_emu(112))
    lines = [
        Line(box, [span], pt_vers_emu(12), box.largeur, z_index=2),
        Line(later_box, [replace(span, texte="Later native text", bbox=later_box, z_index=4)], pt_vers_emu(12), box.largeur, z_index=4),
    ]
    return TextBox(replace(box, y1=later_box.y1), lines, source_id="paragraph", presentation={"paragraph_validated": True})


def _page(index=0, cover=False):
    elements = [_text()]
    if cover:
        box = BBox(*(pt_vers_emu(v) for v in (30, 70, 220, 130)))
        elements.append(ShapeEl(box, [], "FFFFFF", None, 0, alpha=0.5, z_index=3))
    return Page(index, pt_vers_emu(320), pt_vers_emu(280), elements)


def _render(document, plan):
    return rewrite_document_xml(document, GestionnaireRelations(), render_plan=plan)


def test_supplied_plan_never_plans_during_xml_consumption(monkeypatch):
    document = Document([_page()])
    plan = build_document_render_plan(document)

    def forbidden(*args, **kwargs):
        raise AssertionError("planning during XML consumption")

    monkeypatch.setattr("pdfexact.render.word_native_rewriter.comprendre_reflow_paragraphe", forbidden)
    monkeypatch.setattr("pdfexact.render.word_native_rewriter._regrouper_flow_paragraphes", forbidden)
    monkeypatch.setattr("pdfexact.render.drawing.planifier_paragraphe", forbidden)
    monkeypatch.setattr("pdfexact.render.bbox_debug.planifier_paragraphe", forbidden)
    monkeypatch.setattr("pdfexact.layout.paragraph_planner.planifier_paragraphe", forbidden)
    monkeypatch.setattr("pdfexact.render.text_backend.planifier_paragraphe", forbidden)
    monkeypatch.setattr("pdfexact.render.render_plan.prepare_text_instructions", forbidden)
    result = _render(document, plan)
    assert result.diagnostics.conforme
    assert "Earlier native text" in result.xml


def test_changed_source_after_compilation_is_rejected():
    document = Document([_page()])
    plan = build_document_render_plan(document)
    document.pages[0].elements[0].lignes[0].spans[0].texte = "changed after planning"
    with pytest.raises(ValueError, match="source-mutated-after-plan|missing-source-inventory"):
        _render(document, plan)


def test_bbox_consumers_use_only_stored_instructions(tmp_path, monkeypatch):
    from pdfexact.render.bbox_debug import fill_existing_bbox_docx, fill_existing_bbox_docx_with_native_paragraphs, write_bbox_only_docx

    document = Document([_page(3, cover=True)])
    plan = build_document_render_plan(document)
    skeleton, nontext, final = [tmp_path / name for name in ('bbox.docx', 'nontext.docx', 'final.docx')]
    write_bbox_only_docx(document, skeleton, render_plan=plan)

    def forbidden(*args, **kwargs):
        raise AssertionError('planning during bbox consumption')

    for path in (
        'pdfexact.render.bbox_debug._text_paint_fragments',
        'pdfexact.render.bbox_debug._ordonner_non_textuels',
        'pdfexact.render.bbox_debug.planifier_paragraphe',
        'pdfexact.render.text_backend.planifier_paragraphe',
        'pdfexact.render.render_plan.prepare_text_instructions',
        'pdfexact.render.render_plan.build_render_plan',
        'pdfexact.analysis.semantic.regrouper_paragraphes',
    ):
        monkeypatch.setattr(path, forbidden)
    fill_existing_bbox_docx(skeleton, document, nontext, render_plan=plan)
    fill_existing_bbox_docx_with_native_paragraphs(nontext, document, final, render_plan=plan)
    import zipfile
    with zipfile.ZipFile(final) as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
    assert sorted(int(anchor.get('relativeHeight')) for anchor in root.findall('.//wp:anchor', NS)) == [120, 130, 140]


def test_paint_ties_follow_acquisition_not_geometry_or_hash():
    from pdfexact.scene import capture_source_observations

    lower = BBox(*(pt_vers_emu(v) for v in (20, 80, 100, 120)))
    upper = replace(lower, y0=pt_vers_emu(70), y1=pt_vers_emu(110))
    first = ShapeEl(lower, [], 'FF0000', None, 0, z_index=0)
    second = ShapeEl(upper, [], '0000FF', None, 0, z_index=0)
    page = Page(3, pt_vers_emu(320), pt_vers_emu(280), [first, second])
    capture_source_observations(page, page.elements)
    page.elements.reverse()
    plan = build_page_render_plan(page, page.elements)
    assert [instruction.element.remplissage for instruction in plan.instructions_for_page(3)] == ['FF0000', '0000FF']


@pytest.mark.parametrize(('angle', 'orientation'), [(180, 'rotated'), (-135, 'oblique-up'), (-90, 'vertical'), (30, 'oblique-down')])
def test_always_policy_keeps_precomputed_directed_angles(angle, orientation):
    from pdfexact.analysis.options import AnalysisOptions

    text = _text()
    text.angle_deg, text.orientation = angle, orientation
    for line in text.lignes:
        line.angle_deg, line.orientation = angle, orientation
    page = _page(3)
    page.elements = [text]
    plan = build_page_render_plan(page, page.elements, AnalysisOptions(preserve_line_boundaries='always'))
    result = _render(Document([page]), plan)
    rotation = 0 if orientation == 'vertical' else round(-angle * 60000)
    assert f'<wps:bodyPr rot="{rotation}"' in result.xml
    assert f'rotation:{round(-angle)};' in result.xml
    assert 'Earlier native text' in result.xml


def test_planned_paint_barriers_keep_both_editable_fragments():
    page = _page(cover=True)
    plan = build_page_render_plan(page, page.elements)
    result = _render(Document([page]), plan)
    root = ET.fromstring(result.xml)
    anchors = root.findall(".//wp:anchor", NS)
    text_layers = {
        "".join(node.text or "" for node in anchor.findall(".//w:t", NS)): int(anchor.get("relativeHeight"))
        for anchor in anchors if anchor.findall(".//w:t", NS)
    }
    assert text_layers == {"Earlier native text": 120, "Later native text": 140}
    assert [int(anchor.get("relativeHeight")) for anchor in anchors] == [120, 130, 140]
    assert all(anchor.get("behindDoc") == "0" for anchor in anchors)


def test_plan_preserves_zero_paint_and_zero_alpha():
    page = _page(cover=True)
    page.elements[1] = replace(page.elements[1], z_index=0, alpha=0.0)
    plan = build_page_render_plan(page, page.elements)
    item = plan.for_index(0, 1)
    assert item.element.z_order == item.decision.expected_z_order == 0
    assert item.element.opacity == 0.0
    assert 'val="0"' in _render(Document([page]), plan).xml


def test_selected_source_page_three_uses_actual_page_index():
    page = _page(index=3)
    result = _render(Document([page]), build_page_render_plan(page, page.elements))
    assert result.diagnostics.conforme
    assert {decision.page_index for decision in result.diagnostics.decisions} == {3}


def test_link_kind_materializes_hyperlink_zone():
    page = _page()
    page.elements = [LinkZone(page.elements[0].bbox, uri="https://example.invalid/target")]
    result = _render(Document([page]), build_page_render_plan(page, page.elements))
    assert result.diagnostics.conforme
    assert result.diagnostics.anchored_links == 1
    assert "a:hlinkClick" in result.xml


def test_missing_materialization_is_rejected_before_xml():
    page = _page()
    complete = build_page_render_plan(page, page.elements)
    item = complete.for_page(0)[0]
    incomplete = RenderPlan(
        {0: [PlannedElement(item.page_index, item.source_index, item.element, item.decision)]},
        complete.options,
        elements_by_page=complete.elements_by_page,
    )
    assert any("missing-materialization" in error for error in incomplete.validate())
    with pytest.raises(ValueError, match="missing-materialization"):
        _render(Document([page]), incomplete)
