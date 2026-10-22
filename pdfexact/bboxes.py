"""Bbox outputs of an extracted Document: an annotated PDF copy and an empty DOCX.

One rectangle per top-level element, in the page coordinate space of the IR
(origin top-left, EMU). Nothing is rendered inside the rectangles.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import zipfile

import pymupdf

from pdfexact.geometry import BBox, PageGeometry, emu_vers_pt, preserver_etat_page, pt_vers_emu, pt_vers_twips
from pdfexact.ir import Document, FlowParagraph, ImageEl, LinkZone, RasterEl, ShapeEl, TableEl, TextBox

_KINDS = ((TextBox, "text"), (FlowParagraph, "text"), (ImageEl, "image"), (RasterEl, "image"),
          (ShapeEl, "shape"), (TableEl, "table"), (LinkZone, "link"))
_COLORS = {
    "text": (0.90, 0.05, 0.05),
    "image": (0.05, 0.25, 0.90),
    "shape": (0.05, 0.55, 0.15),
    "table": (0.60, 0.10, 0.70),
    "link": (0.95, 0.50, 0.02),
}
_LINE_WIDTH_PT = 0.8


@dataclass(frozen=True)
class BBoxRecord:
    page_index: int
    bbox: BBox
    kind: str

    @property
    def color(self) -> tuple[float, float, float]:
        return _COLORS[self.kind]


def collect_bbox_records(document: Document) -> list[BBoxRecord]:
    """One record per top-level element with a non-empty bbox."""
    records = []
    for page in document.pages:
        for element in page.elements:
            kind = next((name for cls, name in _KINDS if isinstance(element, cls)), None)
            bbox = getattr(element, "bbox", None)
            if kind is not None and bbox is not None and bbox.largeur > 0 and bbox.hauteur > 0:
                records.append(BBoxRecord(page.index, bbox, kind))
    return records


def annotate_pdf_bboxes(source_pdf, destination_pdf, document: Document) -> list[BBoxRecord]:
    """Copy the PDF and draw every bbox over its pages."""
    records = collect_bbox_records(document)
    with pymupdf.open(source_pdf) as pdf:
        for record in records:
            page = pdf[record.page_index]
            geometry = PageGeometry.depuis_page(page)
            rect = pymupdf.Rect(*(emu_vers_pt(value) for value in (record.bbox.x0, record.bbox.y0, record.bbox.x1, record.bbox.y1)))
            # IR boxes are in displayed space; draw in native space, unrotated.
            with preserver_etat_page(page):
                page.set_rotation(0)
                page.draw_rect(geometry.rect_affiche_vers_natif(rect), color=record.color, width=_LINE_WIDTH_PT, overlay=True)
        destination = Path(destination_pdf)
        destination.parent.mkdir(parents=True, exist_ok=True)
        pdf.save(destination, garbage=4, deflate=True)
    return records


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/></Relationships>'
)
_DOCUMENT_START = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"><w:body>'
)


def _section(page) -> str:
    width, height = (pt_vers_twips(emu_vers_pt(value)) for value in (page.largeur_emu, page.hauteur_emu))
    orientation = ' w:orient="landscape"' if page.largeur_emu > page.hauteur_emu else ""
    return (f'<w:sectPr><w:type w:val="nextPage"/><w:pgSz w:w="{width}" w:h="{height}"{orientation}/>'
            '<w:pgMar w:top="0" w:right="0" w:bottom="0" w:left="0" w:header="0" w:footer="0" w:gutter="0"/></w:sectPr>')


def _frame(record: BBoxRecord, identifier: int) -> str:
    box = record.bbox
    width, height = max(box.largeur, 1), max(box.hauteur, 1)
    color = "".join(f"{round(channel * 255):02X}" for channel in record.color)
    return (
        '<w:r><w:drawing><wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" '
        f'relativeHeight="{identifier}" behindDoc="0" locked="0" layoutInCell="0" allowOverlap="1">'
        '<wp:simplePos x="0" y="0"/>'
        f'<wp:positionH relativeFrom="page"><wp:posOffset>{max(box.x0, 0)}</wp:posOffset></wp:positionH>'
        f'<wp:positionV relativeFrom="page"><wp:posOffset>{max(box.y0, 0)}</wp:posOffset></wp:positionV>'
        f'<wp:extent cx="{width}" cy="{height}"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>'
        f'<wp:docPr id="{identifier}" name="BBox {identifier}"/>'
        '<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        '<wps:wsp><wps:cNvSpPr/><wps:spPr>'
        f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{width}" cy="{height}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/>'
        f'<a:ln w="{pt_vers_emu(_LINE_WIDTH_PT)}"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill></a:ln>'
        '</wps:spPr><wps:bodyPr/></wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing></w:r>'
    )


def write_bbox_docx(document: Document, destination_docx) -> list[BBoxRecord]:
    """Write a DOCX with one page per PDF page holding only the bbox frames."""
    records = collect_bbox_records(document)
    body, identifier = [], 1
    for position, page in enumerate(document.pages):
        frames = []
        for record in records:
            if record.page_index == page.index:
                frames.append(_frame(record, identifier))
                identifier += 1
        last = position == len(document.pages) - 1
        # A section's properties close its last paragraph; the final section is the body's.
        properties = '<w:spacing w:before="0" w:after="0" w:line="1" w:lineRule="exact"/>' + ("" if last else _section(page))
        body.append(f"<w:p><w:pPr>{properties}</w:pPr>{''.join(frames)}</w:p>")
        if last:
            body.append(_section(page))
    destination = Path(destination_docx)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", _CONTENT_TYPES)
        package.writestr("_rels/.rels", _RELS)
        package.writestr("word/document.xml", _DOCUMENT_START + "".join(body) + "</w:body></w:document>")
    return records
