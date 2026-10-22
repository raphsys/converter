from io import BytesIO
from copy import deepcopy
from dataclasses import replace
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pymupdf
import pytest
from PIL import Image, ImageDraw

from pdfexact.extract.images import _octets_et_extension, extraire_images
from pdfexact.extract.vector import extraire_vectoriel
from pdfexact.extract.text import extraire_texte
from pdfexact.geometry import BBox, PageGeometry, bbox_depuis_rect
from pdfexact.ir import Document, FontAsset, FontRef, Line, Page, ShapeEl, Span, TextBox
from pdfexact.render.bbox_debug import (
    _ordonner_non_textuels,
    _text_paint_fragments,
    fill_existing_bbox_docx,
    fill_existing_bbox_docx_with_native_paragraphs,
    write_bbox_only_docx,
)
from pdfexact.render.drawing import forme_xml
from pdfexact.render.native_contract import _paragraphe_depuis_groupe, _paragraphe_depuis_ligne
from pdfexact.render.package import ecrire_docx


NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
}


def _png(color="white", alpha=False):
    image = Image.new("RGBA" if alpha else "RGB", (64, 64), color)
    ImageDraw.Draw(image).rectangle((18, 18, 45, 45), fill="red")
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


@pytest.mark.parametrize("rotation", (0, 90, 180, 270))
@pytest.mark.parametrize("crop", (False, True))
def test_extracted_objects_retain_pdf_paint_sequence(rotation, crop, monkeypatch):
    monkeypatch.setattr("pdfexact.extract.images.probe_visible_bbox", lambda *args: None)
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=320, height=280)
        page.draw_rect((30, 30, 290, 250), color=None, fill=(1, 1, 1))
        page.draw_rect((20, 20, 300, 260), color=None, fill=(0, .5, .2))
        page.insert_image((90, 70, 170, 150), stream=_png("blue"))
        page.draw_rect((90, 70, 170, 150), color=(1, 1, 1), fill=None)
        page.draw_rect((180, 100, 260, 180), color=None, fill=(1, 1, 1))
        page.insert_image((180, 100, 260, 180), stream=_png("yellow"))
        if crop:
            page.set_cropbox(pymupdf.Rect(10, 10, 310, 270))
        page.set_rotation(rotation)
        geometry = PageGeometry.depuis_page(page)
        shapes = extraire_vectoriel(page, geometry)
        media = {}
        images = extraire_images(page, pdf, media, geometry)
        # Resource/type order is deliberately not the source paint order.
        ordered = [el for _, el in _ordonner_non_textuels([*images, *reversed(shapes)])]
        assert [getattr(el, "z_index", None) for el in ordered] == list(range(6))
        assert ordered[0].remplissage == "FFFFFF"
        assert ordered[1].remplissage == "008033"
        assert shapes[2].remplissage is None
        for image, source in zip(images, page.get_image_info()):
            assert image.bbox == geometry.bbox_depuis_rect_natif(pymupdf.Rect(source["bbox"]))


@pytest.mark.parametrize("alpha", (False, True))
def test_image_extraction_preserves_white_artwork_and_pdf_soft_mask(alpha):
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        xref = page.insert_image((20, 20, 100, 100), stream=_png((255, 255, 255, 96) if alpha else "white", alpha))
        smask = page.get_images(full=True)[0][1]
        data, _ = _octets_et_extension(pdf, xref, smask)
        result = Image.open(BytesIO(data)).convert("RGBA")
        assert result.getpixel((0, 0)) == (255, 255, 255, 96 if alpha else 255)
        assert result.getpixel((30, 30)) == (255, 0, 0, 255)


def _shape(box, fill, seq, alpha=1):
    bbox = bbox_depuis_rect(pymupdf.Rect(box))
    points = ((bbox.x0, bbox.y0), (bbox.x1, bbox.y0), (bbox.x1, bbox.y1), (bbox.x0, bbox.y1))
    shape = ShapeEl(bbox, [[("move", (points[0],)), *[("line", (p,)) for p in points[1:]], ("close", ())]], fill, None, 0, alpha=alpha)
    shape.z_index = seq
    return shape


def _text(seq=2):
    bbox = bbox_depuis_rect(pymupdf.Rect(40, 80, 200, 96))
    line = Line(bbox, [Span("Editable source paragraph", FontRef("test", "Arial", False, False), 10, "000000")], bbox.hauteur, bbox.largeur, z_index=seq)
    return TextBox(bbox, [line])


def test_layered_fill_keeps_background_behind_native_text_and_foreground_in_front(tmp_path):
    background = _shape((20, 20, 240, 240), "FFFFFF", 0)
    green = _shape((20, 20, 240, 240), "008033", 1)
    foreground = _shape((190, 80, 210, 96), "FFFFFF", 3, alpha=.5)
    text = _text()
    document = Document(pages=[Page(0, 320 * 12700, 280 * 12700, [foreground, text, green, background])])
    bbox, nontext, final = (tmp_path / name for name in ("bbox.docx", "nontext.docx", "native.docx"))
    write_bbox_only_docx(document, bbox)
    fill_existing_bbox_docx(bbox, document, nontext)
    fill_existing_bbox_docx_with_native_paragraphs(nontext, document, final)
    with ZipFile(final) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    anchors = root.findall(".//wp:anchor", NS)
    shapes = [a for a in anchors if a.find(".//wps:spPr/a:solidFill", NS) is not None]
    assert [a.find(".//wps:spPr/a:solidFill/a:srgbClr", NS).get("val") for a in shapes] == ["FFFFFF", "008033", "FFFFFF"]
    assert [a.get("behindDoc") for a in shapes] == ["0", "0", "0"]
    text_anchor = next(a for a in anchors if a.find(".//w:txbxContent", NS) is not None)
    assert text_anchor.get("relativeHeight") == "120"
    assert [a.get("relativeHeight") for a in shapes] == ["100", "110", "130"]
    assert text_anchor.find(".//wps:spPr/a:noFill", NS) is not None
    assert shapes[-1].find(".//a:alpha", NS).get("val") == "50000"
    assert "Editable source paragraph" in "".join(t.text or "" for t in root.findall(".//w:t", NS))


def test_vector_paths_do_not_turn_source_white_artwork_into_rounded_rectangles():
    shape = _shape((20, 20, 240, 40), "FFFFFF", 0)
    xml = forme_xml(shape, 1, 1)
    assert "roundRect" not in xml
    assert '<a:solidFill><a:srgbClr val="FFFFFF"' in xml
    assert "a:custGeom" in xml


def test_partial_metadata_never_reorders_known_source_layers():
    first = _shape((0, 0, 240, 240), "FFFFFF", 0)
    second = _shape((0, 0, 240, 240), "008033", 1)
    unknown = _shape((0, 0, 10, 10), None, None)
    actual = [item for _, item in _ordonner_non_textuels([second, unknown, first])]
    assert actual.index(first) < actual.index(second)


def test_native_contract_copies_line_and_span_paint_provenance():
    first = _text().lignes[0]
    first.spans[0].z_index = 2
    first.layout_frame_id = "body"
    first.layout_frame_role = "text-column"
    second = replace(first, bbox=BBox(first.bbox.x0, first.bbox.y0 + 20 * 12700, first.bbox.x1, first.bbox.y1 + 20 * 12700), z_index=4, spans=[replace(first.spans[0], texte="continues with a later native run", z_index=4)])
    paragraph = _paragraphe_depuis_groupe([first, second], 320 * 12700)
    assert [line.z_index for line in paragraph.lignes] == [2, 4]
    assert [span.z_index for line in paragraph.lignes for span in line.spans] == [2, 4]


def test_native_contract_single_line_retains_paint_provenance():
    line = _text().lignes[0]
    line.spans[0].z_index = 2
    paragraph = _paragraphe_depuis_ligne(line, 320 * 12700)
    assert paragraph.lignes[0].z_index == 2
    assert paragraph.lignes[0].spans[0].z_index == 2


@pytest.mark.parametrize("overlap", (False, True))
def test_multi_paint_paragraph_splits_only_at_overlapping_paint_barriers(overlap):
    original = _text()
    first = replace(original.lignes[0].spans[0], texte="Earlier painted text", bbox=original.bbox, z_index=2)
    later_box = BBox(original.bbox.x0, original.bbox.y0 + 20 * 12700, original.bbox.x1, original.bbox.y1 + 20 * 12700)
    second = replace(first, texte="Later painted text", bbox=later_box, z_index=4)
    original.lignes = [
        replace(original.lignes[0], spans=[first]),
        replace(original.lignes[0], bbox=later_box, spans=[second], z_index=4),
    ]
    original.bbox = BBox(original.bbox.x0, original.bbox.y0, later_box.x1, later_box.y1)
    saved = deepcopy(original)
    visual = _shape((20, 70, 240, 130) if overlap else (250, 20, 310, 40), "FFFFFF", 3)
    fragments = _text_paint_fragments(original, [visual])
    assert len(fragments) == (2 if overlap else 1)
    assert original == saved
    assert [span.texte for fragment in fragments for line in fragment.lignes for span in line.spans] == [first.texte, second.texte]
    if overlap:
        assert [fragment.z_index for fragment in fragments] == [2, 4]
        assert [fragment.bbox for fragment in fragments] == [original.lignes[0].bbox, later_box]


def test_extraction_retains_same_style_text_on_both_sides_of_image_paint(monkeypatch):
    monkeypatch.setattr("pdfexact.extract.text._corriger_espacement", lambda *args: None)
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=320, height=240)
        page.insert_text((40, 80), "Earlier", fontsize=10)
        page.insert_image((30, 60, 220, 120), stream=_png("blue"))
        page.insert_text((90, 80), "later", fontsize=10)
        fonts = {"Helvetica": FontAsset("Helvetica", "Arial", None, "ttf", False)}
        text = extraire_texte(page, fonts, PageGeometry.depuis_page(page))
        spans = [span for block in text for line in block.lignes for span in line.spans if span.texte.strip()]
        assert [(span.texte.strip(), span.z_index) for span in spans] == [("Earlier", 0), ("later", 2)]


def test_fill_and_stroke_do_not_fuse_across_an_image_paint():
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=200, height=200)
        page.draw_rect((40, 40, 160, 160), fill=(1, 1, 1), color=None)
        page.insert_image((40, 40, 160, 160), stream=_png("blue"))
        page.draw_rect((40, 40, 160, 160), fill=None, color=(1, 1, 1))
        shapes = extraire_vectoriel(page, PageGeometry.depuis_page(page))
        assert [(shape.z_index, shape.remplissage, shape.contour) for shape in shapes] == [(0, "FFFFFF", None), (2, None, "FFFFFF")]


@pytest.mark.parametrize("compat", (False, True))
def test_editable_native_paint_fragments_stay_on_either_side_of_foreground(compat, tmp_path):
    text = _text(2)
    first = replace(text.lignes[0].spans[0], texte="Earlier native text", z_index=2, bbox=text.bbox)
    later_box = BBox(text.bbox.x0, text.bbox.y0 + 20 * 12700, text.bbox.x1, text.bbox.y1 + 20 * 12700)
    second = replace(first, texte="later native text", z_index=4, bbox=later_box)
    text.lignes = [replace(text.lignes[0], spans=[first]), replace(text.lignes[0], bbox=later_box, spans=[second], z_index=4)]
    text.bbox = BBox(text.bbox.x0, text.bbox.y0, later_box.x1, later_box.y1)
    saved = deepcopy(text)
    cover = _shape((30, 70, 220, 130), "FFFFFF", 3)
    document = Document(pages=[Page(0, 320 * 12700, 280 * 12700, [text, cover])])
    final = tmp_path / "native.docx"
    if compat:
        ecrire_docx(document, final, native_rewriter=False)
    else:
        bbox, nontext = tmp_path / "bbox.docx", tmp_path / "nontext.docx"
        write_bbox_only_docx(document, bbox)
        fill_existing_bbox_docx(bbox, document, nontext)
        fill_existing_bbox_docx_with_native_paragraphs(nontext, document, final)
    with ZipFile(final) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    anchors = root.findall(".//wp:anchor", NS)
    text_layers = {
        "".join(node.text or "" for node in anchor.findall(".//w:t", NS)): int(anchor.get("relativeHeight"))
        for anchor in anchors if anchor.find(".//w:txbxContent", NS) is not None
    }
    assert text_layers == {"Earlier native text": 120, "later native text": 140}
    assert next(anchor for anchor in anchors if anchor.find(".//wps:spPr/a:solidFill", NS) is not None).get("relativeHeight") == "130"
    assert text == saved


def test_rotated_native_fallback_uses_the_same_source_layer_as_drawingml(tmp_path):
    text = _text(2)
    text.angle_deg = text.lignes[0].angle_deg = 90
    text.orientation = text.lignes[0].orientation = "vertical"
    cover = _shape((20, 20, 240, 240), "FFFFFF", 3)
    document = Document(pages=[Page(0, 320 * 12700, 280 * 12700, [text, cover])])
    path = tmp_path / "rotated.docx"
    ecrire_docx(document, path, native_rewriter=False)
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    native = next(anchor for anchor in root.findall(".//wp:anchor", NS) if anchor.find(".//w:txbxContent", NS) is not None)
    vml = root.find(".//{urn:schemas-microsoft-com:vml}shape")
    assert native.get("relativeHeight") == "120"
    assert "z-index:120;" in vml.get("style")


def test_compat_writer_preserves_genuine_late_page_sized_white_cover(tmp_path):
    white = _shape((0, 0, 320, 280), "FFFFFF", 5)
    text = _text(2)
    document = Document(pages=[Page(0, 320 * 12700, 280 * 12700, [white, text])])
    path = tmp_path / "late_cover.docx"
    ecrire_docx(document, path, native_rewriter=False)
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    anchors = root.findall(".//wp:anchor", NS)
    cover = next((a for a in anchors if a.find(".//wps:spPr/a:solidFill/a:srgbClr", NS) is not None), None)
    assert cover is not None
    text_anchor = next(a for a in anchors if a.find(".//w:txbxContent", NS) is not None)
    assert cover.get("behindDoc") == text_anchor.get("behindDoc") == "0"
    assert int(cover.get("relativeHeight")) > int(text_anchor.get("relativeHeight"))


def test_nontext_and_layered_native_fill_ignore_nested_paragraphs_for_page_ownership(tmp_path):
    pages = []
    for index in range(3):
        text = _text(1)
        text.lignes[0].spans[0].texte = f"Native page {index}"
        shape = _shape((20, 20, 240, 240), ("FFFFFF", "008033", "001122")[index], 0)
        pages.append(Page(index, 320 * 12700, 280 * 12700, [shape, text]))
    document = Document(pages=pages)
    bbox, nontext, final = (tmp_path / name for name in ("bbox.docx", "nontext.docx", "native.docx"))
    write_bbox_only_docx(document, bbox)
    with ZipFile(bbox) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    note = '<w:sdt><w:sdtContent><w:p><w:r><w:t>Nested note</w:t></w:r></w:p></w:sdtContent></w:sdt>'
    parts["word/document.xml"] = parts["word/document.xml"].replace(b"<w:body>", b"<w:body>" + note.encode(), 1)
    with ZipFile(bbox, "w") as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    fill_existing_bbox_docx(bbox, document, nontext)
    fill_existing_bbox_docx_with_native_paragraphs(nontext, document, final)
    with ZipFile(final) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    owner = 0
    for child in root.find("w:body", NS):
        for anchor in child.findall(".//wp:anchor", NS):
            text = "".join(node.text or "" for node in anchor.findall(".//w:t", NS))
            if text:
                assert text == f"Native page {owner}"
            else:
                color = anchor.find(".//wps:spPr/a:solidFill/a:srgbClr", NS).get("val")
                assert color == ("FFFFFF", "008033", "001122")[owner]
        if child.find("w:pPr/w:sectPr", NS) is not None:
            owner += 1
