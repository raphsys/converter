from io import BytesIO
import zipfile
from types import SimpleNamespace
from xml.etree import ElementTree

from PIL import Image
import pytest

from pdfexact.geometry import BBox, pt_vers_emu, pt_vers_twips, emu_vers_pt, quantifier_bbox
from pdfexact.ir import Document, FontRef, ImageEl, Line, MediaItem, Page, Span, TextBox
from pdfexact.render.bbox_debug import (
    fill_existing_bbox_docx,
    fill_existing_bbox_docx_with_native_paragraphs,
    write_bbox_only_docx,
)


NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}
W = "{" + NS["w"] + "}"


def _document(counts):
    font = FontRef("Test", "Arial", False, False)
    document = Document()
    for position, count in enumerate(counts):
        page_index = 3 + position * 4
        media_ref = f"page_{page_index}"
        image = BytesIO()
        Image.new("RGB", (2, 2), (position * 60, 80, 150)).save(image, format="PNG")
        document.media[media_ref] = MediaItem(media_ref, image.getvalue(), "png")
        elements = [ImageEl(BBox(*(pt_vers_emu(v) for v in (280, 20, 320, 60))), media_ref)]
        for number in range(count):
            bbox = BBox(*(pt_vers_emu(v) for v in (40, 30 + number * 20, 240, 42 + number * 20)))
            span = Span(f"Page {page_index} paragraph {number} caf\u00e9", font, 10, "000000")
            elements.append(TextBox(bbox, [Line(bbox, [span], bbox.hauteur, bbox.largeur)]))
        document.pages.append(Page(
            page_index, pt_vers_emu(400 + position * 20), pt_vers_emu(600 + position * 20), elements,
        ))
    return document


def _parts(path):
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _sections(xml):
    root = ElementTree.fromstring(xml)
    body = root.find("w:body", NS)
    sections, nodes = [], []
    for node in body:
        if node.tag == W + "sectPr":
            assert node is body[-1]
            sections.append((nodes, node))
            nodes = []
            continue
        nodes.append(node)
        section = node.find("w:pPr/w:sectPr", NS)
        if section is not None:
            sections.append((nodes, section))
            nodes = []
    assert not nodes, "Content appears after the final section"
    return sections


def _text(node):
    return "".join(part.text or "" for part in node.findall(".//w:t", NS))


def _non_text_stage(tmp_path, document, render_plan=None):
    bbox_path = tmp_path / "bbox.docx"
    non_text_path = tmp_path / "non_text.docx"
    write_bbox_only_docx(document, bbox_path, render_plan=render_plan)
    fill_existing_bbox_docx(bbox_path, document, non_text_path, render_plan=render_plan)
    return non_text_path


def _assert_page_ownership(source_parts, final_parts, document, render_plan=None):
    source_sections = _sections(source_parts["word/document.xml"])
    final_sections = _sections(final_parts["word/document.xml"])
    assert len(final_sections) == len(document.pages)
    for page, (source_nodes, source_section), (nodes, section) in zip(
        document.pages, source_sections, final_sections,
    ):
        elements = render_plan.elements_for_page(page.index) if render_plan else page.elements
        expected = [element for element in elements if isinstance(element, TextBox)]
        paragraphs = [node for node in nodes if node.find("w:pPr/w:framePr", NS) is not None]
        assert [_text(node) for node in paragraphs] == [
            "".join(span.texte for line in element.lignes for span in line.spans)
            for element in expected
        ], f"Native paragraphs escaped source page {page.index}"
        for paragraph, element in zip(paragraphs, expected):
            frame = paragraph.find("w:pPr/w:framePr", NS)
            bbox = quantifier_bbox(element.bbox)
            assert frame.get(W + "x") == str(pt_vers_twips(emu_vers_pt(bbox.x0)))
            assert frame.get(W + "y") == str(pt_vers_twips(emu_vers_pt(bbox.y0)))
            assert frame.get(W + "hAnchor") == "page"
            assert frame.get(W + "vAnchor") == "page"
        assert ElementTree.tostring(section) == ElementTree.tostring(source_section)
        source_anchors = [anchor for node in source_nodes for anchor in node.findall(".//wp:anchor", NS)]
        anchors = [anchor for node in nodes for anchor in node.findall(".//wp:anchor", NS)]
        assert [ElementTree.tostring(anchor) for anchor in anchors] == [
            ElementTree.tostring(anchor) for anchor in source_anchors
        ]
    assert {name: data for name, data in final_parts.items() if name != "word/document.xml"} == {
        name: data for name, data in source_parts.items() if name != "word/document.xml"
    }


@pytest.mark.parametrize("counts", [(2, 3, 1), (2, 0, 3), (0, 2, 0), (11, 14, 25)])
def test_bbox_non_text_native_fill_keeps_every_paragraph_in_its_page_section(tmp_path, counts):
    document = _document(counts)
    source = _non_text_stage(tmp_path, document)
    destination = tmp_path / "native.docx"

    fill_existing_bbox_docx_with_native_paragraphs(source, document, destination)

    _assert_page_ownership(_parts(source), _parts(destination), document)


def test_native_page_ownership_uses_the_finalized_render_plan(tmp_path):
    document = _document((3, 3, 3))
    planned = {
        page.index: [page.elements[0], *page.elements[1:position + 2]]
        for position, page in enumerate(document.pages)
    }
    plan = SimpleNamespace(elements_for_page=planned.get)
    source = _non_text_stage(tmp_path, document, render_plan=plan)
    destination = tmp_path / "native.docx"

    fill_existing_bbox_docx_with_native_paragraphs(source, document, destination, render_plan=plan)

    _assert_page_ownership(_parts(source), _parts(destination), document, render_plan=plan)


def test_bookmarks_and_nested_paragraphs_do_not_change_page_ownership(tmp_path):
    document = _document((2, 3, 1))
    source = _non_text_stage(tmp_path, document)
    parts = _parts(source)
    decoration = (
        '<w:p><w:bookmarkStart w:id="17" w:name="page_note"/>'
        '<w:r><w:t>Existing caf\u00e9 note</w:t></w:r><w:bookmarkEnd w:id="17"/></w:p>'
        '<w:sdt><w:sdtContent><w:p><w:r><w:t>Nested note</w:t></w:r></w:p></w:sdtContent></w:sdt>'
    )
    xml = parts["word/document.xml"].decode("utf-8")
    parts["word/document.xml"] = xml.replace("<w:body>", "<w:body>" + decoration, 1).encode("utf-8")
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    destination = tmp_path / "native.docx"

    fill_existing_bbox_docx_with_native_paragraphs(source, document, destination)

    final_parts = _parts(destination)
    _assert_page_ownership(parts, final_parts, document)
    nodes = _sections(final_parts["word/document.xml"])[0][0]
    assert [_text(node) for node in nodes[:2]] == ["Existing caf\u00e9 note", "Nested note"]
    assert nodes[0].find("w:bookmarkStart", NS).get(W + "name") == "page_note"


def test_oriented_text_stays_in_its_source_page_section(tmp_path):
    document = _document((1, 1, 1))
    for page in document.pages:
        page.elements[1].orientation = "vertical"
    source = _non_text_stage(tmp_path, document)
    destination = tmp_path / "native.docx"

    fill_existing_bbox_docx_with_native_paragraphs(source, document, destination)

    sections = _sections(_parts(destination)["word/document.xml"])
    assert len(sections) == 3
    for page, (nodes, _section) in zip(document.pages, sections):
        paragraphs = [node for node in nodes if node.findall(".//w:t", NS)]
        assert len(paragraphs) == 1
        assert {part.text for part in paragraphs[0].findall(".//w:t", NS)} == {
            page.elements[1].lignes[0].spans[0].texte,
        }


@pytest.mark.parametrize("text_pages", (1, 4))
def test_native_fill_rejects_mismatched_source_page_sections(tmp_path, text_pages):
    source = _non_text_stage(tmp_path, _document((1, 1, 1)))
    destination = tmp_path / "native.docx"

    with pytest.raises(ValueError, match="pages texte"):
        fill_existing_bbox_docx_with_native_paragraphs(source, _document((1,) * text_pages), destination)

    assert not destination.exists()
