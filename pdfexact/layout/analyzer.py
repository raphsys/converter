"""Collecte des signaux bruts de layout depuis PyMuPDF."""
from __future__ import annotations

import contextlib
import io

import pymupdf

from pdfexact.geometry import BBox, PageGeometry, bbox_depuis_rect, preserver_etat_page
from pdfexact.analysis.geometry import bbox_area
from pdfexact.layout.model import LayoutBlock, LayoutPage


def analyser_page(page, geometrie: PageGeometry | None = None) -> LayoutPage:
    geometrie = geometrie or PageGeometry.depuis_page(page)
    text_blocks: list[LayoutBlock] = []
    image_blocks: list[LayoutBlock] = []
    drawing_blocks: list[LayoutBlock] = []
    table_candidates: list[LayoutBlock] = []
    native_line_count = 0
    char_count = 0

    for bloc in page.get_text("dict").get("blocks", []):
        bbox = _bbox_depuis_liste(bloc.get("bbox", (0, 0, 0, 0)), geometrie)
        if bloc.get("type") == 0:
            textes: list[str] = []
            line_bboxes: list[BBox] = []
            for ligne in bloc.get("lines", []):
                texte = "".join(span.get("text", "") for span in ligne.get("spans", []))
                if texte.strip():
                    textes.append(texte)
                    line_bboxes.append(_bbox_depuis_liste(ligne["bbox"], geometrie))
                    native_line_count += 1
                    char_count += len(texte)
            if textes:
                text_blocks.append(
                    LayoutBlock(
                        "text",
                        bbox,
                        "pymupdf-dict",
                        text="\n".join(textes),
                        metadata={"line_bboxes": tuple(line_bboxes), "line_count": len(line_bboxes)},
                    )
                )
        elif bloc.get("type") == 1:
            image_blocks.append(LayoutBlock("image", bbox, "pymupdf-dict"))

    for dessin in page.get_drawings():
        bbox = _bbox_dessin(dessin, geometrie)
        if bbox.largeur > 0 and bbox.hauteur > 0:
            drawing_blocks.append(
                LayoutBlock(
                    "drawing",
                    bbox,
                    "pymupdf-drawing",
                    metadata={
                        "has_fill": dessin.get("fill") is not None,
                        "has_stroke": dessin.get("color") is not None,
                    },
                )
            )

    if hasattr(page, "find_tables"):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with contextlib.suppress(Exception):
                with preserver_etat_page(page):
                    for table in page.find_tables().tables:
                        table_candidates.append(
                            LayoutBlock(
                                "table-candidate",
                                _bbox_depuis_liste(table.bbox, geometrie=None),
                                "pymupdf-find_tables",
                                metadata={
                                    "row_count": len(getattr(table, "rows", ()) or ()),
                                    "col_count": _col_count(table),
                                },
                            )
                        )

    aire_page = max(geometrie.largeur_emu * geometrie.hauteur_emu, 1)
    metrics = {
        "text_block_count": float(len(text_blocks)),
        "native_line_count": float(native_line_count),
        "char_count": float(char_count),
        "image_block_count": float(len(image_blocks)),
        "drawing_count": float(len(drawing_blocks)),
        "table_candidate_count": float(len(table_candidates)),
        "text_area_ratio": _aire_totale(text_blocks) / aire_page,
        "image_area_ratio": _aire_totale(image_blocks) / aire_page,
        "drawing_area_ratio": _aire_totale(drawing_blocks) / aire_page,
    }

    return LayoutPage(
        page_index=int(getattr(page, "number", -1)),
        width=geometrie.largeur_emu,
        height=geometrie.hauteur_emu,
        rotation=geometrie.rotation,
        text_blocks=tuple(text_blocks),
        image_blocks=tuple(image_blocks),
        drawing_blocks=tuple(drawing_blocks),
        table_candidates=tuple(table_candidates),
        metrics=metrics,
    )


analyze_page = analyser_page


def _bbox_depuis_liste(quadruplet, geometrie: PageGeometry | None) -> BBox:
    rect = pymupdf.Rect(
        float(quadruplet[0]),
        float(quadruplet[1]),
        float(quadruplet[2]),
        float(quadruplet[3]),
    )
    if geometrie is None:
        return bbox_depuis_rect(rect)
    return geometrie.bbox_depuis_rect_natif(rect)


def _bbox_dessin(dessin, geometrie: PageGeometry) -> BBox:
    rect = dessin.get("rect")
    if rect:
        return geometrie.bbox_depuis_rect_natif(rect)

    points = []
    for item in dessin.get("items", []):
        for valeur in item:
            if isinstance(valeur, pymupdf.Point):
                points.append(valeur)
            elif isinstance(valeur, pymupdf.Rect):
                points.extend([valeur.tl, valeur.br])
    if not points:
        return BBox(0, 0, 0, 0)
    rect = pymupdf.Rect(points[0], points[0])
    for point in points[1:]:
        rect.include_point(point)
    return geometrie.bbox_depuis_rect_natif(rect)


def _aire_totale(blocks: list[LayoutBlock]) -> float:
    return float(sum(bbox_area(block.bbox) for block in blocks))


def _col_count(table) -> int:
    valeur = getattr(table, "col_count", None)
    if isinstance(valeur, int):
        return valeur
    if valeur is not None:
        with contextlib.suppress(TypeError):
            return len(valeur)
    rows = getattr(table, "rows", ()) or ()
    return max((len(getattr(row, "cells", ()) or ()) for row in rows), default=0)
