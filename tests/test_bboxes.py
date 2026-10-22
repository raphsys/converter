"""Bbox outputs: one rectangle per top-level element, in an annotated PDF and an empty DOCX."""
import zipfile
from xml.etree import ElementTree

import pymupdf

from pdfexact.bboxes import annotate_pdf_bboxes, collect_bbox_records, write_bbox_docx
from pdfexact.geometry import BBox, pt_vers_emu as u, pt_vers_twips
from pdfexact.ir import Document, FontRef, Line, Page, ShapeEl, Span, TextBox

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WPS = "{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}"


def document():
    text_box = BBox(u(72), u(100), u(300), u(120))
    span = Span("Hello", FontRef("f", "Arial", False, False), 12, "000000", bbox=text_box)
    text = TextBox(text_box, [Line(text_box, [span], text_box.hauteur, text_box.largeur)])
    shape = ShapeEl(BBox(u(72), u(200), u(540), u(201)), [], "000000", None, 0)
    empty = ShapeEl(BBox(u(10), u(10), u(10), u(30)), [], "000000", None, 0)
    return Document([Page(0, u(612), u(792), [text, shape, empty]), Page(1, u(612), u(792), [])])


def test_one_record_per_visible_top_level_element():
    records = collect_bbox_records(document())
    assert [(record.page_index, record.kind) for record in records] == [(0, "text"), (0, "shape")]


def test_docx_holds_one_frame_per_record_and_one_section_per_page(tmp_path):
    destination = tmp_path / "boxes.docx"
    records = write_bbox_docx(document(), destination)
    with zipfile.ZipFile(destination) as package:
        assert {"[Content_Types].xml", "_rels/.rels", "word/document.xml"} <= set(package.namelist())
        root = ElementTree.fromstring(package.read("word/document.xml"))
    assert len(root.findall(f".//{WPS}wsp")) == len(records) == 2
    sizes = root.findall(f".//{W}pgSz")
    assert len(sizes) == 2
    assert all(size.get(f"{W}w") == str(pt_vers_twips(612)) for size in sizes)


def test_pdf_copy_is_annotated_without_changing_page_count(tmp_path):
    source, destination = tmp_path / "source.pdf", tmp_path / "boxes.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page(width=612, height=792)
        pdf.new_page(width=612, height=792)
        pdf.save(source)
    records = annotate_pdf_bboxes(source, destination, document())
    with pymupdf.open(destination) as pdf:
        assert pdf.page_count == 2
        assert len(pdf[0].get_drawings()) == len(records) == 2
