"""Extraction des tableaux à grille visible.

PyMuPDF sait reconstruire les lignes et cellules quand un tableau PDF est dessiné avec
des traits. On transforme cette structure en IR Word réel : le texte reste éditable et
les cellules gardent leurs dimensions.
"""
from __future__ import annotations

import contextlib
import io

import pymupdf

from pdfexact.extract.text import _couleur_hexa, _resoudre_police, _style_depuis_nom
from pdfexact.geometry import BBox, PageGeometry, bbox_depuis_rect, pt_vers_emu
from pdfexact.ir import FontRef, TableCell, TableEl, TableRow


def _bbox_depuis_tuple(rect_tuple) -> BBox:
    return bbox_depuis_rect(pymupdf.Rect(*rect_tuple))


def _intersection(a: BBox, b: BBox) -> int:
    x0 = max(a.x0, b.x0)
    y0 = max(a.y0, b.y0)
    x1 = min(a.x1, b.x1)
    y1 = min(a.y1, b.y1)
    return max(0, x1 - x0) * max(0, y1 - y0)


def _style_table(
    page,
    polices: dict,
    bbox: BBox,
    geometrie: PageGeometry | None = None,
) -> tuple[FontRef, float, str]:
    meilleur = None
    meilleur_score = 0
    for trace in page.get_texttrace():
        rect_pt = pymupdf.Rect(trace.get("bbox", (0, 0, 0, 0)))
        rect = geometrie.bbox_depuis_rect_natif(rect_pt) if geometrie else bbox_depuis_rect(rect_pt)
        score = _intersection(rect, bbox)
        if score > meilleur_score:
            meilleur = trace
            meilleur_score = score

    if meilleur is None:
        return FontRef("Table", "Arial", False, False), 8.0, "000000"

    font_id = _resoudre_police(meilleur.get("font", ""), polices)
    asset = polices[font_id]
    gras, italique = _style_depuis_nom(
        meilleur.get("font", ""), int(meilleur.get("flags", 0))
    )
    return (
        FontRef(font_id, asset.famille, gras, italique),
        max(5.0, min(round(float(meilleur.get("size", 8.0)), 2), 10.0)),
        _couleur_hexa(meilleur.get("color", 0)),
    )


def _couleur_fond_cellule(page, cell: BBox, geometrie: PageGeometry | None = None) -> str | None:
    meilleure = None
    meilleure_aire = 0
    for dessin in page.get_drawings():
        fill = dessin.get("fill")
        if fill is None:
            continue
        rect_pt = dessin.get("rect")
        rect = geometrie.bbox_depuis_rect_natif(rect_pt) if geometrie else bbox_depuis_rect(rect_pt)
        aire = _intersection(rect, cell)
        if aire > meilleure_aire:
            meilleure = fill
            meilleure_aire = aire
    if meilleure is None or meilleure_aire < max(cell.largeur * cell.hauteur * 0.35, 1):
        return None
    return _couleur_hexa(meilleure)


def _col_widths(rows: list[TableRow], bbox: BBox, col_count: int) -> list[int]:
    widths = [max(1, bbox.largeur // max(col_count, 1)) for _ in range(col_count)]
    for row in rows:
        simples = [cell for cell in row.cells if cell.col_span == 1]
        if len(simples) == col_count:
            return [max(1, cell.bbox.largeur) for cell in simples]
    return widths


def extraire_tableaux(page, polices: dict, geometrie: PageGeometry | None = None) -> list[TableEl]:
    """Retourne les tableaux détectés par lignes/cellules PDF."""
    if not hasattr(page, "find_tables"):
        return []

    geometrie = geometrie or PageGeometry.depuis_page(page)
    try:
        tampon = io.StringIO()
        with contextlib.redirect_stdout(tampon), contextlib.redirect_stderr(tampon):
            tables = page.find_tables().tables
    except Exception:  # noqa: BLE001
        return []

    elements: list[TableEl] = []
    for table in tables:
        if table.row_count < 2 or table.col_count < 2:
            continue
        bbox = _bbox_depuis_tuple(table.bbox)
        if bbox.largeur < pt_vers_emu(60) or bbox.hauteur < pt_vers_emu(30):
            continue

        textes = table.extract()
        rows: list[TableRow] = []
        for row_index, row in enumerate(table.rows):
            cells: list[TableCell] = []
            col_index = 0
            while col_index < len(row.cells):
                cell_rect = row.cells[col_index]
                if cell_rect is None:
                    col_index += 1
                    continue

                span = 1
                next_index = col_index + 1
                while next_index < len(row.cells) and row.cells[next_index] is None:
                    span += 1
                    next_index += 1

                texte = ""
                if row_index < len(textes) and col_index < len(textes[row_index]):
                    texte = textes[row_index][col_index] or ""
                cell_bbox = _bbox_depuis_tuple(cell_rect)
                cells.append(
                    TableCell(
                        bbox=cell_bbox,
                        texte=texte,
                        col_span=span,
                        fond=_couleur_fond_cellule(page, cell_bbox, geometrie),
                    )
                )
                col_index = next_index

            if cells:
                rows.append(TableRow(bbox=_bbox_depuis_tuple(row.bbox), cells=cells))

        if not rows:
            continue

        police, size_pt, couleur = _style_table(page, polices, bbox, geometrie)
        elements.append(
            TableEl(
                bbox=bbox,
                rows=rows,
                col_widths_emu=_col_widths(rows, bbox, table.col_count),
                police=police,
                size_pt=size_pt,
                couleur=couleur,
            )
        )

    return elements
