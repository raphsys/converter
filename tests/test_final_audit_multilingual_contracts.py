"""Bounded RED contracts for the observation-only final audit APIs."""

import json
import pickle
import unicodedata
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pymupdf
import pytest

from pdfexact.final_audit import auditer_editability, construire_audit_elements
from pdfexact.geometry import BBox, pt_vers_emu
from pdfexact.ir import Document, FlowParagraph, FontRef, Line, Page, ShapeEl, Span, TextBox


_TEXTS = [
    pytest.param("Texte intact controle", "helv", id="latin"),
    pytest.param("\u041f\u0440\u0438\u0432\u0435\u0442 \u043c\u0438\u0440", "fixture", id="cyrillic"),
    pytest.param("\u4e2d\u6587\u6d4b\u8bd5", "china-s", id="cjk"),
    pytest.param("\u0391\u03bb\u03c6\u03b1 \u03b2\u03b7\u03c4\u03b1", "fixture", id="greek"),
    pytest.param("L", "helv", id="single-latin-L"),
    pytest.param("\u03a9", "fixture", id="single-greek"),
    pytest.param("\u042f", "fixture", id="single-cyrillic"),
    pytest.param("\u4e2d", "china-s", id="single-cjk"),
    pytest.param("\u00b1", "helv", id="symbol-plus-minus"),
    pytest.param("\u2211", "fixture", id="symbol-summation"),
    pytest.param("!", "helv", id="single-punctuation"),
]
_KINDS = [FlowParagraph, TextBox]
_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


@pytest.fixture
def pdf_factory(record_property):
    handles = []

    def create(page_count=1):
        handle = pymupdf.open()
        handles.append(handle)
        for _ in range(page_count):
            handle.new_page(width=300, height=200)
        return handle

    yield create

    for handle in handles:
        if not handle.is_closed:
            handle.close()
    closed = [bool(handle.is_closed) for handle in handles]
    record_property("pdf_handles_closed", json.dumps(closed))
    assert all(closed)


def _bbox(values):
    return BBox(*(pt_vers_emu(value) for value in values))


def _paint_text(page, text, *, kind=FlowParagraph, source_id="source-text", font="helv", color=(0, 0, 0), y=70):
    if font == "fixture":
        font_path = Path(__file__).resolve().parents[1] / "pdfexact/fonts/DejaVuSans.ttf"
        page.insert_font(fontname=font, fontfile=str(font_path))
    page.insert_text((30, y), text, fontname=font, fontsize=12, color=color)
    pdf_lines = [
        line
        for block in page.get_text("dict")["blocks"]
        for line in block.get("lines", [])
    ]
    pdf_line = next(line for line in pdf_lines if "".join(span["text"] for span in line["spans"]) == text)
    pdf_span = pdf_line["spans"][0]
    bbox = _bbox(pdf_line["bbox"])
    police = FontRef("fixture-font", pdf_span["font"], False, False)
    span = Span(text, police, 12, f"{pdf_span['color']:06X}", bbox=bbox)
    line = Line(bbox, [span], bbox.hauteur, bbox.largeur)
    if kind is TextBox:
        return TextBox(bbox, [line], source_id=source_id)
    return FlowParagraph(bbox, text, police, 12, span.couleur, lignes=[line], spans=[span], source_id=source_id)


def _ir_page(index, elements):
    return Page(index, pt_vers_emu(300), pt_vers_emu(200), elements)


def _observe(record_property, report, **fixture):
    record_property("fixture", json.dumps(fixture, ensure_ascii=True, sort_keys=True))
    record_property("audit_records", json.dumps([asdict(record) for record in report.records], sort_keys=True))
    record_property("audit_errors", json.dumps([record.element_id for record in report.errors]))
    record_property("audit_conforme", str(report.conforme))


@pytest.mark.parametrize("kind", _KINDS, ids=["paragraph", "textbox"])
@pytest.mark.parametrize("text,font", _TEXTS)
@pytest.mark.parametrize("preserved", [False, True], ids=["missing", "unchanged"])
def test_multilingual_source_always_has_a_record(pdf_factory, record_property, kind, text, font, preserved):
    source = pdf_factory()
    output = pdf_factory()
    element = _paint_text(source[0], text, kind=kind, font=font)
    assert source[0].get_text("text").strip() == text
    if preserved:
        _paint_text(output[0], text, font=font)
        assert output[0].get_text("text").strip() == text
    else:
        assert output[0].get_text("text").strip() == ""
    report = construire_audit_elements(Document(pages=[_ir_page(0, [element])]), output, source_pdf=source)
    _observe(record_property, report, source_text=text, output_preserved=preserved)

    assert len(report.records) == 1, "A nonempty source text must not silently disappear from the audit"
    record = report.records[0]
    assert record.element_id == element.source_id
    assert record.output_present is preserved
    assert record.visible is preserved
    assert record.token_recall == (1.0 if preserved else 0.0)
    assert record.status == ("ok" if preserved else "error")
    assert report.errors == ([] if preserved else [record])
    assert report.conforme is preserved


@pytest.mark.parametrize("kind", _KINDS, ids=["paragraph", "textbox"])
@pytest.mark.parametrize(
    "output_text,defect",
    [
        pytest.param("alpha bravo charlie delta alpha", None, id="unchanged"),
        pytest.param("bravo alpha charlie delta alpha", "order", id="reordered"),
        pytest.param("alpha bravo charlie delta bravo", "multiplicity", id="replaced-duplicate"),
        pytest.param("alpha bravo charlie delta", "multiplicity", id="dropped-duplicate"),
    ],
)
def test_text_order_and_multiplicity_are_blocking(pdf_factory, record_property, kind, output_text, defect):
    source = pdf_factory()
    output = pdf_factory()
    source_text = "alpha bravo charlie delta alpha"
    element = _paint_text(source[0], source_text, kind=kind, font="cour")
    _paint_text(output[0], output_text, font="cour")
    assert source[0].get_text("text").strip() == source_text
    assert output[0].get_text("text").strip() == output_text
    source_tokens = source_text.split()
    output_tokens = output_text.split()
    assert set(source_tokens) == set(output_tokens)
    if defect == "order":
        assert Counter(source_tokens) == Counter(output_tokens)
        assert source_tokens != output_tokens
    elif defect == "multiplicity":
        assert Counter(source_tokens) != Counter(output_tokens)
    else:
        assert source_tokens == output_tokens

    report = construire_audit_elements(Document(pages=[_ir_page(0, [element])]), output, source_pdf=source)
    _observe(
        record_property,
        report,
        source_text=source_text,
        output_text=output_text,
        source_tokens=source_tokens,
        output_tokens=output_tokens,
        defect=defect,
        font="cour",
        same_token_set=True,
    )
    assert len(report.records) == 1
    record = report.records[0]
    assert record.output_present and record.visible
    assert record.style_mismatches == []
    # The geometry gate must pass so it cannot mask the text-comparison defect.
    assert record.bbox_iou >= 0.70
    if defect is None:
        assert record.status == "ok"
        assert report.errors == [] and report.conforme
    else:
        assert record in report.errors, f"A {defect} defect must block despite an identical token set"
        assert record.status == "error" and not report.conforme
        assert record.causes
        assert record.text_sequence_matches is False
        if defect == "order":
            assert record.text_occurrences_match is True
            assert record.token_recall == record.token_precision == 1.0
            assert "text-order-mismatch" in record.causes
        else:
            assert record.text_occurrences_match is False
            assert "text-occurrence-mismatch" in record.causes


@pytest.mark.parametrize("kind", _KINDS, ids=["paragraph", "textbox"])
@pytest.mark.parametrize("reverse", [False, True], ids=["composed-source", "decomposed-source"])
def test_unicode_normalization_is_symmetric(pdf_factory, record_property, kind, reverse):
    source = pdf_factory()
    output = pdf_factory()
    texts = ["Caf\u00e9 texte", "Cafe\u0301 texte"]
    source_text, output_text = texts[::-1] if reverse else texts
    assert source_text != output_text
    assert unicodedata.normalize("NFC", source_text) == unicodedata.normalize("NFC", output_text)
    element = _paint_text(source[0], source_text, kind=kind, font="fixture")
    _paint_text(output[0], output_text, font="fixture")
    assert source[0].get_text("text").strip() == source_text
    assert output[0].get_text("text").strip() == output_text
    report = construire_audit_elements(Document(pages=[_ir_page(0, [element])]), output, source_pdf=source)
    _observe(record_property, report, source_text=source_text, output_text=output_text, normalization="NFC")
    assert len(report.records) == 1 and report.conforme
    record = report.records[0]
    assert record.token_recall == record.token_precision == 1.0
    assert record.text_sequence_matches is True and record.text_occurrences_match is True
    assert record.editability_verified is False


@pytest.mark.parametrize("kind", _KINDS, ids=["paragraph", "textbox"])
@pytest.mark.parametrize("color", [(0, 0, 0), (1, 0, 0)], ids=["exact-black", "red-output"])
def test_black_source_color_is_an_exact_requirement(pdf_factory, record_property, kind, color):
    source = pdf_factory()
    output = pdf_factory()
    text = "Couleur noire obligatoire"
    element = _paint_text(source[0], text, kind=kind)
    _paint_text(output[0], text, color=color)
    assert element.lignes[0].spans[0].couleur == "000000"
    actual_color = output[0].get_text("dict")["blocks"][0]["lines"][0]["spans"][0]["color"]
    assert actual_color == (0 if color == (0, 0, 0) else 0xFF0000)
    report = construire_audit_elements(Document(pages=[_ir_page(0, [element])]), output, source_pdf=source)
    _observe(record_property, report, expected_color="000000", output_color=f"{actual_color:06X}")

    assert len(report.records) == 1
    record = report.records[0]
    assert record.output_present and record.token_recall == 1.0
    if color == (0, 0, 0):
        assert record.style_mismatches == []
        assert record.status == "ok" and report.conforme
    else:
        assert record.style_mismatches, "Expected black must not act as a wildcard for red output"
        assert record in report.errors
        assert not report.conforme


@pytest.mark.parametrize("source_indices", [(0, 1), (2, 4)], ids=["from-page-one", "selected-pages-three-five"])
@pytest.mark.parametrize("contract", ["errors", "verdict", "source-page"])
def test_missing_requested_page_blocks_audit(pdf_factory, record_property, source_indices, contract):
    source = pdf_factory(max(source_indices) + 1)
    output = pdf_factory()
    first_index, missing_index = source_indices
    first = _paint_text(source[first_index], "Premiere page conservee", source_id="kept-source")
    missing = _paint_text(source[missing_index], "Derniere page demandee", source_id="missing-source")
    _paint_text(output[0], "Premiere page conservee")
    document = Document(pages=[_ir_page(first_index, [first]), _ir_page(missing_index, [missing])])
    report = construire_audit_elements(document, output, source_pdf=source)
    _observe(record_property, report, requested_source_indices=source_indices, rendered_pages=1)

    assert len(report.records) == 2
    assert report.records[0].status == "ok"
    record = next(record for record in report.records if record.element_id == missing.source_id)
    assert not record.output_present
    assert "output-page-missing" in record.causes
    if contract == "errors":
        assert record in report.errors, "A missing requested page must contribute a blocking error"
    elif contract == "verdict":
        assert not report.conforme, "A missing requested page must prevent a conforming verdict"
    else:
        assert record.page_index == missing_index, "Record identity must preserve the real source page index"


@pytest.mark.parametrize("source_index", [0, 2], ids=["page-one", "selected-page-three"])
def test_correct_selected_text_keeps_source_page_identity(pdf_factory, record_property, source_index):
    source = pdf_factory(source_index + 1)
    output = pdf_factory()
    element = _paint_text(source[source_index], "Texte de la page selectionnee")
    _paint_text(output[0], "Texte de la page selectionnee")
    report = construire_audit_elements(Document(pages=[_ir_page(source_index, [element])]), output, source_pdf=source)
    _observe(record_property, report, source_page_index=source_index, output_page_index=0)

    assert len(report.records) == 1
    record = report.records[0]
    assert record.output_present and record.status == "ok" and report.conforme
    assert record.page_index == source_index


@pytest.mark.parametrize("source_index", [0, 2], ids=["page-one", "selected-page-three"])
def test_unchanged_nontext_uses_real_source_page_without_inventing_text(pdf_factory, record_property, source_index):
    source = pdf_factory(source_index + 1)
    output = pdf_factory()
    rect = pymupdf.Rect(40, 40, 120, 120)
    source[source_index].draw_rect(rect, color=None, fill=(0, 0, 0))
    output[0].draw_rect(rect, color=None, fill=(0, 0, 0))
    shape = ShapeEl(_bbox(rect), [], "000000", None, 0, source_id="selected-shape")
    report = construire_audit_elements(Document(pages=[_ir_page(source_index, [shape])]), output, source_pdf=source)
    _observe(record_property, report, source_page_index=source_index, output_page_index=0, source_has_text=False)

    assert source[source_index].get_text("text").strip() == output[0].get_text("text").strip() == ""
    assert [record.kind for record in report.records] == ["ShapeEl"]
    assert report.records[0].output_present
    assert report.records[0].status == "ok"
    assert report.conforme
    assert report.records[0].page_index == source_index


def test_wrong_selected_visual_cannot_be_validated_by_page_one(pdf_factory, record_property):
    source = pdf_factory(3)
    output = pdf_factory()
    rect = pymupdf.Rect(40, 40, 120, 120)
    source[0].draw_rect(rect, color=None, fill=(0, 0, 0))
    source[2].draw_rect(rect, color=None, fill=(1, 1, 1))
    output[0].draw_rect(rect, color=None, fill=(0, 0, 0))
    shape = ShapeEl(_bbox(rect), [], "FFFFFF", None, 0, source_id="page-three-white-shape")
    report = construire_audit_elements(Document(pages=[_ir_page(2, [shape])]), output, source_pdf=source)
    _observe(record_property, report, source_page_index=2, output_matches_source_page_index=0)

    assert len(report.records) == 1
    assert report.records[0] in report.errors, "Output matching an unselected source page must not pass"
    assert not report.conforme


@pytest.mark.parametrize("kind", ["empty", "visual"])
def test_missing_requested_page_without_text_is_blocking(pdf_factory, record_property, kind):
    source = pdf_factory(5)
    output = pdf_factory()
    kept = _paint_text(source[2], "Premiere page conservee", source_id="kept-source")
    _paint_text(output[0], "Premiere page conservee")
    missing_elements = []
    if kind == "visual":
        rect = pymupdf.Rect(40, 40, 120, 120)
        source[4].draw_rect(rect, color=None, fill=(0, 0, 0))
        missing_elements.append(ShapeEl(_bbox(rect), [], "000000", None, 0, source_id="missing-shape"))
    report = construire_audit_elements(
        Document(pages=[_ir_page(2, [kept]), _ir_page(4, missing_elements)]), output, source_pdf=source,
    )
    _observe(record_property, report, requested_source_indices=[2, 4], missing_page_kind=kind)
    missing = [record for record in report.errors if record.page_index == 4]
    assert missing, "A requested page cannot silently disappear because it has no text"
    assert all("output-page-missing" in record.causes for record in missing)
    assert not report.conforme
    assert all(record.kind not in {"TextBox", "FlowParagraph"} for record in missing)
    if kind == "visual":
        assert any(record.element_id == "missing-shape" for record in missing)


@pytest.mark.parametrize("kind", ["text", "visual"])
@pytest.mark.parametrize("swapped", [False, True], ids=["unchanged", "swapped-output"])
def test_nonordered_selection_uses_source_identity_and_output_ordinal(pdf_factory, record_property, kind, swapped):
    source = pdf_factory(5)
    output = pdf_factory(2)
    indices = [4, 2]
    pages = []
    for ordinal, index in enumerate(indices):
        target = output[1 - ordinal if swapped else ordinal]
        if kind == "text":
            text = f"Texte distinct source {index}"
            element = _paint_text(source[index], text, source_id=f"source-{index}")
            _paint_text(target, text)
        else:
            rect = pymupdf.Rect(40, 40, 120, 120)
            fill = (0, 0, 0) if ordinal == 0 else (1, 1, 1)
            source[index].draw_rect(rect, color=None, fill=fill)
            target.draw_rect(rect, color=None, fill=fill)
            element = ShapeEl(_bbox(rect), [], "000000" if ordinal == 0 else "FFFFFF", None, 0,
                              source_id=f"source-{index}")
        pages.append(_ir_page(index, [element]))
    report = construire_audit_elements(Document(pages=pages), output, source_pdf=source)
    _observe(record_property, report, requested_source_indices=indices, swapped_output=swapped, kind=kind)
    assert len(report.records) == 2
    assert report.conforme is (not swapped)
    assert [record.page_index for record in report.records] == indices
    assert [asdict(record).get("output_page_index") for record in report.records] == [0, 1]
    if swapped:
        assert len(report.errors) == 2
    else:
        assert report.errors == []


@pytest.mark.parametrize("paths", [False, True], ids=["borrowed-handles", "file-paths"])
def test_element_audit_does_not_mutate_its_inputs(pdf_factory, tmp_path, record_property, paths):
    source = pdf_factory()
    output = pdf_factory()
    element = _paint_text(source[0], "Texte source intact")
    _paint_text(output[0], "Texte source intact")
    document = Document(pages=[_ir_page(0, [element])])
    before = pickle.dumps(document)
    source_path, output_path = tmp_path / "source.pdf", tmp_path / "output.pdf"
    source.save(source_path)
    output.save(output_path)
    original_files = [path.read_bytes() for path in (source_path, output_path)]
    report = construire_audit_elements(
        document, output_path if paths else output, source_pdf=source_path if paths else source,
    )
    _observe(record_property, report, input_mode="paths" if paths else "borrowed-handles")
    assert report.conforme
    assert pickle.dumps(document) == before
    assert [path.read_bytes() for path in (source_path, output_path)] == original_files
    assert not source.is_closed and not output.is_closed


def _write_docx(path, run_texts):
    ET.register_namespace("w", _WORD_NS)
    document = ET.Element(f"{{{_WORD_NS}}}document")
    body = ET.SubElement(document, f"{{{_WORD_NS}}}body")
    for text in run_texts:
        paragraph = ET.SubElement(body, f"{{{_WORD_NS}}}p")
        run = ET.SubElement(paragraph, f"{{{_WORD_NS}}}r")
        ET.SubElement(run, f"{{{_WORD_NS}}}t").text = text
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", ET.tostring(document, encoding="utf-8", xml_declaration=True))
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    assert archive.fp is None


@pytest.mark.parametrize("content", ["none", "complete-one-run", "unrelated-one-run", "nontext-only"])
def test_editability_evidence_and_per_element_mapping_gap(pdf_factory, tmp_path, record_property, content):
    source = pdf_factory()
    first = _paint_text(source[0], "Premier texte source", source_id="first-text", y=60)
    second = _paint_text(source[0], "Second texte source", source_id="second-text", y=110)
    elements = [first, second]
    if content == "nontext-only":
        elements = [ShapeEl(_bbox((40, 40, 120, 120)), [], "000000", None, 0, source_id="shape-only")]
    run_texts = {
        "none": [],
        "complete-one-run": [first.texte + "\n" + second.texte],
        "unrelated-one-run": ["Unrelated editable text"],
        "nontext-only": [],
    }[content]
    docx_path = tmp_path / "synthetic-editability.docx"
    _write_docx(docx_path, run_texts)
    with ZipFile(docx_path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
        observed_texts = [node.text for node in root.iter(f"{{{_WORD_NS}}}t")]
    assert archive.fp is None
    assert observed_texts == run_texts
    diagnostics = auditer_editability(Document(pages=[_ir_page(0, elements)]), docx_path)
    record_property("expected_source_ids", json.dumps([element.source_id for element in elements]))
    record_property("docx_run_texts", json.dumps(observed_texts))
    record_property("editability_diagnostics", json.dumps(diagnostics, sort_keys=True))
    record_property("zip_handles_closed", "True")

    if content == "none":
        assert any(item.get("cause") == "no-editable-text-runs" for item in diagnostics)
    elif content == "unrelated-one-run":
        assert all(element.texte not in run_texts[0] for element in elements)
        if not diagnostics:
            pytest.xfail("API GAP: two source texts, one unrelated w:t, no diagnostics; no per-element OOXML mapping is exposed")
        assert diagnostics
    else:
        assert diagnostics == []
