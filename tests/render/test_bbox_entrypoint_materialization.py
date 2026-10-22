"""The user bbox facade must materialize the complete supplied plan."""
from copy import deepcopy
import json
import sys
import zipfile
from xml.etree import ElementTree as ET

import pytest

from pdfexact.geometry import BBox, pt_vers_emu
from pdfexact.ir import (
    Document, FontRef, Line, LinkZone, Page, ShapeEl, Span,
    TableCell, TableEl, TableRow, TextBox,
)
from pdfexact.layout import text_comprehension
from pdfexact.render import bbox_debug, package
from pdfexact.scene import capture_source_observations
from scripts import reconstruct_bbox_native as entrypoint


NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}
ZONE_URL = "https://example.invalid/source-zone"
TEXT_URL = "https://example.invalid/source-run"
MANIFEST = "pdfexact/render-manifest.json"


@pytest.fixture(autouse=True)
def no_model_provider():
    with text_comprehension.contexte_comprehension_texte():
        text_comprehension.configurer_fournisseur_comprehension_texte(None)
        yield


def _box(*coordinates):
    return BBox(*(pt_vers_emu(value) for value in coordinates))


def _document():
    font = FontRef("entrypoint-font", "Arial", False, False)
    text_box = _box(30, 30, 220, 44)
    span = Span(
        "Editable linked source", font, 10, "123456", bbox=text_box,
        lien=TEXT_URL, source_kind="pdf-native",
    )
    text = TextBox(
        text_box, [Line(text_box, [span], text_box.hauteur, text_box.largeur)],
        source_kind="pdf-native", semantic_role="caption",
    )
    table_box = _box(30, 100, 230, 125)
    cells = []
    for label, box in (
        ("Source cell A", _box(30, 100, 130, 125)),
        ("Source cell B", _box(130, 100, 230, 125)),
    ):
        cells.append(TableCell(
            box, label,
            spans=[Span(label, font, 10, "234567", bbox=box, source_kind="pdf-native")],
        ))
    table = TableEl(
        table_box, [TableRow(table_box, cells)],
        [cell.bbox.largeur for cell in cells], font, 10,
        source_kind="pdf-native",
    )
    link = LinkZone(_box(30, 160, 130, 180), uri=ZONE_URL, source_kind="pdf-native")
    shape = ShapeEl(
        _box(250, 100, 275, 125), [], "456789", None, 0,
        alpha=0.5, source_kind="pdf-native",
    )
    page = Page(3, pt_vers_emu(320), pt_vers_emu(240), [text, table, link, shape])
    capture_source_observations(page, page.elements, source_kind="pdf-native")
    return Document([page])


@pytest.fixture
def compiled():
    document = _document()
    plan = entrypoint._construire_plan_unique(document)
    assert plan.validate(document) == []
    assert set(plan.source_inventory) == set(plan.source_coverage)
    assert {item.container for item in plan.instructions_for_page(3)} >= {"table", "link"}
    return document, plan


def _non_text_stage(tmp_path, document, plan):
    skeleton = tmp_path / "source.bboxes.docx"
    non_text = tmp_path / "source.non_text.docx"
    entrypoint._ecrire_docx_vierge(document, skeleton, plan)
    entrypoint._remplir_non_textes(skeleton, document, non_text, plan)
    return skeleton, non_text


def _final_stage(tmp_path, document, plan):
    skeleton, non_text = _non_text_stage(tmp_path, document, plan)
    final = tmp_path / "source.docx"
    entrypoint._remplir_textes(non_text, document, final, plan)
    return skeleton, non_text, final


def _xml(path):
    with zipfile.ZipFile(path) as archive:
        return ET.fromstring(archive.read("word/document.xml"))


def _relationships(path):
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
    return {node.get("Id"): node.attrib for node in root}


def test_covered_table_is_an_actual_editable_positioned_table(compiled, tmp_path):
    document, plan = compiled
    table_item = next(item for item in plan.for_page(3) if item.materialization.fragments[0].container == "table")
    assert plan.source_coverage[table_item.element.element_id].target_ids
    _, _, final = _final_stage(tmp_path, document, plan)

    tables = _xml(final).findall(".//w:tbl", NS)
    assert len(tables) == 1, "covered native table is absent from the final user DOCX"
    assert tables[0].find("./w:tblPr/w:tblpPr", NS) is not None
    assert [node.text for node in tables[0].findall(".//w:t", NS)] == ["Source cell A", "Source cell B"]


def test_covered_link_zone_has_an_actual_clickable_anchor(compiled, tmp_path):
    document, plan = compiled
    link_item = next(item for item in plan.for_page(3) if item.materialization.fragments[0].container == "link")
    assert plan.source_coverage[link_item.element.element_id].target_ids
    _, _, final = _final_stage(tmp_path, document, plan)

    links = _xml(final).findall(".//a:hlinkClick", NS)
    assert len(links) == 1, "covered link zone is absent from the final user DOCX"
    relation = _relationships(final)[links[0].get(f"{{{NS['r']}}}id")]
    assert relation["Target"] == ZONE_URL and relation["TargetMode"] == "External"
    assert relation["Type"].endswith("/hyperlink")


def test_native_linked_run_keeps_its_external_relationship(compiled, tmp_path):
    document, plan = compiled
    _, _, final = _final_stage(tmp_path, document, plan)

    links = _xml(final).findall(".//w:hyperlink", NS)
    assert len(links) == 1, "native run text survived but its hyperlink was discarded"
    assert "".join(node.text or "" for node in links[0].findall(".//w:t", NS)) == "Editable linked source"
    relation = _relationships(final)[links[0].get(f"{{{NS['r']}}}id")]
    assert relation["Target"] == TEXT_URL and relation["TargetMode"] == "External"


def test_final_facade_delegates_to_the_main_writer_with_the_same_plan(compiled, tmp_path, monkeypatch):
    document, plan = compiled
    _, non_text = _non_text_stage(tmp_path, document, plan)
    final = tmp_path / "source.docx"
    calls = []
    original = package.ecrire_docx

    def write(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(package, "ecrire_docx", write)
    monkeypatch.setattr(bbox_debug, "ecrire_docx", write)
    entrypoint._remplir_textes(non_text, document, final, plan)

    assert len(calls) == 1, "the facade still owns a separate final XML/ZIP writer"
    assert calls[0][1]["render_plan"] is plan
    assert calls[0][1]["native_rewriter"] is True
    assert package.valider_package_ooxml(final) == []


def test_final_package_validation_refusal_preserves_existing_destination(compiled, tmp_path, monkeypatch):
    document, plan = compiled
    _, non_text = _non_text_stage(tmp_path, document, plan)
    final = tmp_path / "source.docx"
    original = b"existing destination must remain intact"
    final.write_bytes(original)
    monkeypatch.setattr(package, "valider_package_ooxml", lambda *_args, **_kwargs: ["entrypoint-validator-sentinel"])

    with pytest.raises(ValueError, match="entrypoint-validator-sentinel"):
        entrypoint._remplir_textes(non_text, document, final, plan)

    assert final.read_bytes() == original


def test_final_manifest_retains_all_acquired_sources_without_claiming_xml_proof(compiled, tmp_path):
    document, plan = compiled
    _, _, final = _final_stage(tmp_path, document, plan)
    with zipfile.ZipFile(final) as archive:
        assert MANIFEST in archive.namelist(), "final user DOCX exports no source coverage"
        manifest = json.loads(archive.read(MANIFEST))

    assert set(manifest["sources"]) == set(plan.source_inventory)
    for source_id, coverage in plan.source_coverage.items():
        assert manifest["sources"][source_id]["coverage"]["target_ids"] == list(coverage.target_ids)
    assert manifest["provenance"] == {"status": "incomplete", "reason": "xml-source-mapping-unavailable"}


def test_main_writer_already_materializes_the_complete_same_plan(compiled, tmp_path):
    document, plan = compiled
    destination = tmp_path / "principal.docx"
    result = package.ecrire_docx(
        document, destination, native_rewriter=True, render_plan=plan,
        package_options={"include_scene_manifest": True},
    )

    assert result.diagnostics.conforme
    assert result.diagnostics.real_tables == result.diagnostics.anchored_links == 1
    root = _xml(destination)
    assert len(root.findall(".//w:tbl", NS)) == 1
    assert len(root.findall(".//a:hlinkClick", NS)) == 1
    assert len(root.findall(".//w:hyperlink", NS)) == 1
    assert package.valider_package_ooxml(destination) == []


def test_source_coverage_guard_is_still_required_before_final_writing(compiled, tmp_path):
    document, plan = compiled
    _, non_text = _non_text_stage(tmp_path, document, plan)
    final = tmp_path / "source.docx"
    original = b"existing destination must remain intact"
    final.write_bytes(original)
    source_id = next(iter(plan.source_inventory))
    del plan.source_coverage[source_id]

    with pytest.raises(ValueError, match="uncovered-source"):
        entrypoint._remplir_textes(non_text, document, final, plan)

    assert final.read_bytes() == original


def test_diagnostic_contours_stay_separate_from_real_native_content(compiled, tmp_path):
    document, plan = compiled
    skeleton, _, final = _final_stage(tmp_path, document, plan)

    with zipfile.ZipFile(skeleton) as archive:
        diagnostic_xml = archive.read("word/document.xml").decode("utf-8")
    with zipfile.ZipFile(final) as archive:
        final_xml = archive.read("word/document.xml").decode("utf-8")
    assert "E60D0D" in diagnostic_xml
    assert "E60D0D" not in final_xml
    assert "456789" in final_xml and "Editable linked source" in final_xml


def test_user_main_builds_once_and_passes_one_plan_to_every_output(tmp_path, monkeypatch):
    document = _document()
    original_inventory = deepcopy(document.pages[0].source_inventory)
    plans, consumed = [], []
    original_build = entrypoint.build_document_render_plan

    def forbidden(*_args, **_kwargs):
        raise AssertionError("the writer tried to plan again")

    def build(*args, **kwargs):
        assert not plans, "user entry point rebuilt its plan"
        plan = original_build(*args, **kwargs)
        plans.append(plan)
        monkeypatch.setattr("pdfexact.render.render_plan.build_render_plan", forbidden)
        monkeypatch.setattr("pdfexact.render.render_plan.build_document_render_plan", forbidden)
        monkeypatch.setattr("pdfexact.render.word_native_rewriter.build_rewrite_render_plan", forbidden)
        monkeypatch.setattr("pdfexact.render.text_backend.planifier_paragraphe", forbidden)
        return plan

    monkeypatch.setattr(entrypoint, "build_document_render_plan", build)
    monkeypatch.setattr(entrypoint, "_extraire_scene", lambda *_args: document)
    monkeypatch.setattr(entrypoint, "_enregistrer_catalogue", lambda *_args: None)

    def annotate(_source, _destination, actual_document, plan):
        assert actual_document is document
        consumed.append(plan)
        return []

    monkeypatch.setattr(entrypoint, "_ecrire_bboxes_pdf", annotate)
    for name in ("_ecrire_docx_vierge", "_remplir_non_textes", "_remplir_textes"):
        original = getattr(entrypoint, name)

        def consume(*args, _original=original):
            consumed.append(args[-1])
            return _original(*args)

        monkeypatch.setattr(entrypoint, name, consume)
    monkeypatch.setattr(sys, "argv", [
        "reconstruct_bbox_native.py", str(tmp_path / "unused.pdf"),
        "--pdf-out", str(tmp_path / "bboxes.pdf"), "--docx-out", str(tmp_path / "final.docx"),
        "--pages", "4",
    ])

    assert entrypoint.main() == 0
    assert len(plans) == 1 and len(consumed) == 4
    assert all(plan is plans[0] for plan in consumed)
    assert document.pages[0].source_inventory == original_inventory
