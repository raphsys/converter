from copy import deepcopy
import pickle
from unittest.mock import Mock
import zipfile

import pytest

from pdfexact.analysis.options import AnalysisOptions
from pdfexact.analysis.provenance import Evidence
from pdfexact.geometry import BBox, pt_vers_emu
from pdfexact.ir import Document, FontRef, Line, Page, ShapeEl, Span, TextBox
from pdfexact.render.native_contract import valider_contrat_word_native
from pdfexact.render.package import ecrire_docx
from pdfexact.render.render_plan import RenderPlan, SourceCoverage, build_document_render_plan
from pdfexact.scene import (
    ElementKind, ElementRecord, PageScene, SceneDocument, SourceKind,
    element_record_from_legacy, marquer_non_representable,
)


def _text(source_id, y=20):
    bbox = BBox(*(pt_vers_emu(value) for value in (20, y, 180, y + 12)))
    span = Span(
        source_id, FontRef("SourceFont", "Arial", False, False), 12, "123456",
        bbox=bbox, source_id=f"{source_id}:span", z_index=0,
    )
    line = Line(
        bbox, [span], pt_vers_emu(12), bbox.largeur,
        source_id=f"{source_id}:line", z_index=0,
    )
    return TextBox(bbox, [line], source_id=source_id, semantic_role="caption")


def _document(page_index=7):
    return Document([Page(page_index, pt_vers_emu(300), pt_vers_emu(200), [_text("visible")])])


def _forbid_writing(monkeypatch):
    opened = Mock(side_effect=AssertionError("ZIP opened before validation"))
    monkeypatch.setattr("pdfexact.render.package.zipfile.ZipFile", opened)
    font_table = Mock(side_effect=AssertionError("font packaging before validation"))
    monkeypatch.setattr("pdfexact.render.package._table_polices_xml", font_table)
    compat = Mock(side_effect=AssertionError("compat XML before validation"))
    monkeypatch.setattr("pdfexact.render.package.construire_document_xml_compat", compat)
    rewrite = Mock(side_effect=AssertionError("native XML before validation"))
    monkeypatch.setattr("pdfexact.render.word_native_rewriter.rewrite_document_xml", rewrite)
    return opened, font_table, compat, rewrite


@pytest.mark.parametrize("pages", [{}, {7: []}])
def test_contract_reconciles_empty_supplied_plan_with_nonempty_document(pages):
    document = _document()
    plan = RenderPlan(pages, AnalysisOptions())
    before_document, before_plan = pickle.dumps(document), pickle.dumps(plan)
    report = valider_contrat_word_native(document, plan)

    assert not report.conforme
    assert any("visible" in error for error in report.plan_errors)
    assert pickle.dumps(document) == before_document
    assert pickle.dumps(plan) == before_plan


@pytest.mark.parametrize("native_rewriter", [False, True])
@pytest.mark.parametrize("existing", [False, True])
def test_empty_plan_fails_before_zip_or_xml_and_preserves_destination(
    tmp_path, monkeypatch, native_rewriter, existing,
):
    target = tmp_path / "preserved.docx"
    original = b"existing document bytes\x00\xff"
    if existing:
        target.write_bytes(original)
    writes = _forbid_writing(monkeypatch)

    with pytest.raises(ValueError, match="visible"):
        ecrire_docx(
            _document(), target, native_rewriter=native_rewriter,
            render_plan=RenderPlan({}, AnalysisOptions()),
        )

    for write in writes:
        write.assert_not_called()
    if existing:
        assert target.read_bytes() == original
    else:
        assert not target.exists()


@pytest.mark.parametrize("native_rewriter", [False, True])
def test_partial_plan_reports_missing_source_before_opening_zip(tmp_path, monkeypatch, native_rewriter):
    document = _document()
    document.pages[0].elements.append(_text("omitted", y=120))
    plan = build_document_render_plan(document)
    assert len(plan.for_page(7)) == 2
    first = plan.for_page(7)[0]
    plan.pages[7] = [first]
    plan.elements_by_page[7] = plan.elements_by_page[7][:1]
    plan.instructions_by_page[7] = first.materialization.fragments
    target = tmp_path / "preserved.docx"
    target.write_bytes(b"keep me")
    writes = _forbid_writing(monkeypatch)

    with pytest.raises(ValueError, match="omitted"):
        ecrire_docx(document, target, native_rewriter=native_rewriter, render_plan=plan)

    assert target.read_bytes() == b"keep me"
    for write in writes:
        write.assert_not_called()


def test_valid_supplied_plan_requires_explicit_native_backend(tmp_path, monkeypatch):
    document = _document()
    plan = build_document_render_plan(document)
    target = tmp_path / "preserved.docx"
    target.write_bytes(b"keep me")
    writes = _forbid_writing(monkeypatch)

    with pytest.raises(ValueError, match="render-plan-requires-native-rewriter"):
        ecrire_docx(document, target, render_plan=plan)

    assert target.read_bytes() == b"keep me"
    for write in writes:
        write.assert_not_called()


def test_contract_consumes_supplied_decisions_without_replanning_or_mutation(monkeypatch):
    document = _document()
    plan = build_document_render_plan(document)
    before_document = pickle.dumps(document)
    before_plan = pickle.dumps(plan)
    forbidden = Mock(side_effect=AssertionError("validation replanned the document"))
    monkeypatch.setattr("pdfexact.render.native_contract.build_document_render_plan", forbidden)
    monkeypatch.setattr("pdfexact.render.native_contract.corriger_document_word_native", forbidden)

    report = valider_contrat_word_native(document, plan)

    assert report.conforme, report
    assert report.planned_element_ids == ("visible",)
    forbidden.assert_not_called()
    assert pickle.dumps(document) == before_document
    assert pickle.dumps(plan) == before_plan


def test_contract_without_plan_does_not_change_the_source_document():
    document = _document()
    before = pickle.dumps(document)

    report = valider_contrat_word_native(document)

    assert report.conforme, report
    assert pickle.dumps(document) == before


def _unavailable_source_plan(with_evidence=True):
    document = _document()
    plan = build_document_render_plan(document)
    page = document.pages[0]
    source = ShapeEl(
        page.elements[0].bbox, [], "FFFFFF", None, 0, source_id="unsupported-source",
    )
    record = element_record_from_legacy(source, page.index)
    reason = "unsupported-blend-mode"
    if with_evidence:
        record.evidence.append(Evidence(
            "non-representable", "source-capability-audit", 1.0,
            (("capability", reason),),
        ))
    marquer_non_representable(record, reason)
    document.scene = SceneDocument([
        PageScene(page.index, page.largeur_emu, page.hauteur_emu, [record]),
    ])
    plan.source_inventory[record.element_id] = deepcopy(record)
    plan.source_coverage[record.element_id] = SourceCoverage((), "non-representable", reason)
    return document, plan


def test_reasoned_nonrepresentable_source_is_reported_with_id_and_evidence(tmp_path):
    document, plan = _unavailable_source_plan()

    report = valider_contrat_word_native(document, plan)
    result = ecrire_docx(document, tmp_path / "declared-loss.docx", native_rewriter=True, render_plan=plan)

    assert report.conforme, report
    assert report.nonrepresentable_sources == (("unsupported-source", "unsupported-blend-mode"),)
    assert {
        "kind": "non-representable-source", "element_id": "unsupported-source",
        "reason": "unsupported-blend-mode",
    } in result.diagnostics.reader_risks


def test_nonrepresentable_source_without_evidence_cannot_allow_writing(tmp_path, monkeypatch):
    document, plan = _unavailable_source_plan(with_evidence=False)
    target = tmp_path / "preserved.docx"
    target.write_bytes(b"keep me")
    writes = _forbid_writing(monkeypatch)

    with pytest.raises(ValueError, match="unsupported-source") as failure:
        ecrire_docx(document, target, native_rewriter=True, render_plan=plan)

    assert "unsupported-blend-mode" in str(failure.value)
    assert target.read_bytes() == b"keep me"
    for write in writes:
        write.assert_not_called()


def test_supplied_falsey_plan_is_not_replaced(tmp_path, monkeypatch):
    class FalseyPlan(RenderPlan):
        def __bool__(self):
            return False

    forbidden = Mock(side_effect=AssertionError("supplied plan was replaced"))
    monkeypatch.setattr("pdfexact.render.render_plan.build_document_render_plan", forbidden)
    writes = _forbid_writing(monkeypatch)

    with pytest.raises(ValueError, match="visible"):
        ecrire_docx(
            _document(), tmp_path / "never-created.docx", native_rewriter=True,
            render_plan=FalseyPlan({}, AnalysisOptions()),
        )

    forbidden.assert_not_called()
    for write in writes:
        write.assert_not_called()


def test_contract_preserves_fonts_alpha_clipping_layers_and_orientation():
    document = _document()
    text = document.pages[0].elements[0]
    text.orientation = text.lignes[0].orientation = "vertical"
    text.angle_deg = text.lignes[0].angle_deg = 90
    shape = ShapeEl(
        text.bbox, [], "FFFFFF", None, 0, alpha=0.0, z_index=1,
        source_id="transparent-cover", clip_bbox=text.bbox, clip_ids=("source-clip",),
        paint_group_id="source-layer",
    )
    document.pages[0].elements.append(shape)
    plan = build_document_render_plan(document)
    before_document = pickle.dumps(document)
    before_plan = pickle.dumps(plan)

    report = valider_contrat_word_native(document, plan)

    assert report.conforme, report
    assert pickle.dumps(document) == before_document
    assert pickle.dumps(plan) == before_plan
    assert text.lignes[0].spans[0].police.font_id == "SourceFont"
    assert text.lignes[0].spans[0].texte == "visible"
    assert text.orientation == "vertical" and text.angle_deg == 90
    assert shape.alpha == 0.0 and shape.z_index == 1
    assert shape.clip_bbox == text.bbox and shape.clip_ids == ("source-clip",)
    assert shape.paint_group_id == "source-layer"


@pytest.mark.parametrize("source_location", ["discarded", "scene", "inventory"])
@pytest.mark.parametrize("native_rewriter", [False, True])
def test_unplanned_source_inventory_is_checked_beyond_plan_pages(
    tmp_path, monkeypatch, source_location, native_rewriter,
):
    document = _document()
    plan = build_document_render_plan(document)
    page = document.pages[0]
    source_id = f"missing-{source_location}"
    source = _text(source_id, y=50)
    if source_location == "discarded":
        source.decision_history.append({"event": "filtered", "reason_code": "covered-by-zone"})
        page.discarded_elements.append(source)
    elif source_location == "inventory":
        page.source_inventory[source_id] = source
    else:
        record = ElementRecord(
            source_id, page.index, ElementKind.TEXT, source.bbox, SourceKind.PDF_NATIVE,
            source_ids=(source_id,), text=source_id,
        )
        document.scene = SceneDocument([
            PageScene(page.index, page.largeur_emu, page.hauteur_emu, [record]),
        ])
    target = tmp_path / "preserved.docx"
    target.write_bytes(b"keep me")
    writes = _forbid_writing(monkeypatch)

    with pytest.raises(ValueError, match=source_id):
        ecrire_docx(document, target, native_rewriter=native_rewriter, render_plan=plan)

    assert target.read_bytes() == b"keep me"
    for write in writes:
        write.assert_not_called()


def test_source_page_indices_are_not_output_enumeration(tmp_path):
    document = _document(page_index=7)
    document.pages.append(Page(2, pt_vers_emu(300), pt_vers_emu(200), [_text("second")]))
    plan = build_document_render_plan(document)
    target = tmp_path / "selected.docx"

    result = ecrire_docx(document, target, native_rewriter=True, render_plan=plan)

    assert result.diagnostics.conforme
    assert {item.page_index for item in result.diagnostics.decisions} == {7, 2}
    with zipfile.ZipFile(target) as archive:
        xml = archive.read("word/document.xml").decode()
    assert "visible" in xml and "second" in xml


def test_auto_plan_failures_are_blocking_before_writing(tmp_path, monkeypatch):
    document = _document()
    plan = RenderPlan({}, AnalysisOptions())
    monkeypatch.setattr("pdfexact.render.render_plan.build_document_render_plan", lambda document: plan)
    writes = _forbid_writing(monkeypatch)

    with pytest.raises(ValueError, match="visible"):
        ecrire_docx(document, tmp_path / "never-created.docx", native_rewriter=True)

    for write in writes:
        write.assert_not_called()
