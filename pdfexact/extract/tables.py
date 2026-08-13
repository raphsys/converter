"""Extraction des tableaux à grille visible.

PyMuPDF sait reconstruire les lignes et cellules quand un tableau PDF est dessiné avec
des traits. On transforme cette structure en IR Word réel : le texte reste éditable et
les cellules gardent leurs dimensions.
"""
from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass

import pymupdf

from pdfexact.extract.text import _couleur_hexa, _resoudre_police, _style_depuis_nom
from pdfexact.extract.styles import decorations_texte
from pdfexact.geometry import BBox, PageGeometry, bbox_depuis_rect, pt_vers_emu, pt_vers_twips
from pdfexact.ir import FontRef, Span, TableBorder, TableCell, TableEl, TableRow


@dataclass(frozen=True)
class FillCandidate:
    bbox: BBox
    couleur: str


@dataclass(frozen=True)
class LineCandidate:
    bbox: BBox
    couleur: str
    sz: int
    orientation: str


def _bbox_depuis_tuple(rect_tuple) -> BBox:
    return bbox_depuis_rect(pymupdf.Rect(*rect_tuple))


def _intersection(a: BBox, b: BBox) -> int:
    x0 = max(a.x0, b.x0)
    y0 = max(a.y0, b.y0)
    x1 = min(a.x1, b.x1)
    y1 = min(a.y1, b.y1)
    return max(0, x1 - x0) * max(0, y1 - y0)


def _aire(bbox: BBox) -> int:
    return max(0, bbox.largeur) * max(0, bbox.hauteur)


def _union(a: BBox, b: BBox) -> BBox:
    return BBox(min(a.x0, b.x0), min(a.y0, b.y0), max(a.x1, b.x1), max(a.y1, b.y1))


def _bbox_dessin(dessin, geometrie: PageGeometry) -> BBox:
    rect_pt = dessin.get("rect")
    if rect_pt:
        return geometrie.bbox_depuis_rect_natif(rect_pt)

    boite = None
    for item in dessin.get("items", []):
        points = []
        for valeur in item:
            if isinstance(valeur, pymupdf.Point):
                points.append(valeur)
            elif isinstance(valeur, pymupdf.Rect):
                points.extend([valeur.tl, valeur.br])
        if points:
            rect = pymupdf.Rect(points[0], points[0])
            for point in points[1:]:
                rect.include_point(point)
            bbox = geometrie.bbox_depuis_rect_natif(rect)
            boite = bbox if boite is None else _union(boite, bbox)
    return boite or BBox(0, 0, 0, 0)


def _est_noir(couleur: str) -> bool:
    return couleur.upper() in {"000000", "010101", "020202"}


def _analyse_dessins_table(page, table_bbox: BBox, geometrie: PageGeometry) -> tuple[list[FillCandidate], list[LineCandidate]]:
    """Classe les dessins utiles aux tableaux : vrais fonds et vrais traits."""
    fonds: list[FillCandidate] = []
    lignes: list[LineCandidate] = []

    for dessin in page.get_drawings():
        bbox = _bbox_dessin(dessin, geometrie)
        if _intersection(bbox, table_bbox) <= 0:
            continue

        fill = dessin.get("fill")
        if fill is not None:
            couleur = _couleur_hexa(fill)
            aire = _aire(bbox)
            ratio_table = aire / max(_aire(table_bbox), 1)
            mince = bbox.largeur <= pt_vers_emu(1.5) or bbox.hauteur <= pt_vers_emu(1.5)
            # Les PDF avec tableaux complexes contiennent souvent du texte converti en
            # petits rectangles noirs. Un fond de cellule noir n'est fiable que s'il
            # couvre une vraie zone rectangulaire, pas une succession de glyphes.
            if (
                not mince
                and ratio_table <= 0.95
                and (not _est_noir(couleur) or aire >= pt_vers_emu(18) * pt_vers_emu(10))
            ):
                fonds.append(FillCandidate(bbox=bbox, couleur=couleur))

        couleur_trait = dessin.get("color")
        if couleur_trait is None:
            # Certaines bordures PDF sont des rectangles remplis très minces.
            couleur_trait = fill
        if couleur_trait is None:
            continue

        largeur = bbox.largeur
        hauteur = bbox.hauteur
        if largeur <= 0 or hauteur <= 0:
            continue

        orientation = None
        if hauteur <= pt_vers_emu(2.5) and largeur >= pt_vers_emu(8):
            orientation = "h"
        elif largeur <= pt_vers_emu(2.5) and hauteur >= pt_vers_emu(8):
            orientation = "v"
        if orientation is None:
            continue

        width_pt = float(dessin.get("width", 0.5) or 0.5)
        if fill is not None and dessin.get("color") is None:
            width_pt = max(width_pt, 0.25)
        lignes.append(
            LineCandidate(
                bbox=bbox,
                couleur=_couleur_hexa(couleur_trait),
                sz=max(2, min(24, round(pt_vers_twips(width_pt) / 2))),
                orientation=orientation,
            )
        )

    return fonds, lignes


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


def _span_cellule(page, polices: dict, cell_bbox: BBox, texte: str, geometrie: PageGeometry) -> list[Span]:
    if not texte:
        return []
    police, size_pt, couleur = _style_table(page, polices, cell_bbox, geometrie)
    decoration = decorations_texte(page, cell_bbox, geometrie)
    return [
        Span(
            texte=texte,
            police=police,
            size_pt=size_pt,
            couleur=couleur,
            souligne=decoration.souligne,
            barre=decoration.barre,
        )
    ]


def _direction_texte_cellule(cell_bbox: BBox, texte: str, fond: str | None) -> str | None:
    """Détecte les en-têtes de tableau tournés dans des cellules hautes et étroites."""
    if not texte.strip():
        return None
    if cell_bbox.largeur <= 0 or cell_bbox.hauteur <= 0:
        return None

    largeur_pt = cell_bbox.largeur / pt_vers_emu(1)
    ratio = cell_bbox.hauteur / max(cell_bbox.largeur, 1)
    if fond and _est_noir(fond) and largeur_pt <= 48 and ratio >= 1.25:
        return "btLr"
    return None


def _couleur_fond_cellule(cell: BBox, fonds: list[FillCandidate]) -> str | None:
    scores: dict[str, int] = {}
    for fond in fonds:
        aire = _intersection(fond.bbox, cell)
        if aire <= 0:
            continue
        couverture = aire / max(_aire(cell), 1)
        if couverture < 0.28:
            continue
        # Un remplissage doit être de la taille d'une cellule ou d'un bandeau couvrant
        # plusieurs cellules. Les très petites formes noires restent du contenu.
        if _est_noir(fond.couleur) and couverture < 0.82:
            continue
        scores[fond.couleur] = scores.get(fond.couleur, 0) + aire
    if not scores:
        return None
    return max(scores.items(), key=lambda item: item[1])[0]


def _recouvrement_ligne(a: BBox, b: BBox, orientation: str) -> int:
    if orientation == "h":
        return max(0, min(a.x1, b.x1) - max(a.x0, b.x0))
    return max(0, min(a.y1, b.y1) - max(a.y0, b.y0))


def _bordure_cellule(cell: BBox, lignes: list[LineCandidate]) -> dict[str, TableBorder]:
    marge = pt_vers_emu(1.6)
    cotes = {
        "top": BBox(cell.x0 - marge, cell.y0 - marge, cell.x1 + marge, cell.y0 + marge),
        "bottom": BBox(cell.x0 - marge, cell.y1 - marge, cell.x1 + marge, cell.y1 + marge),
        "left": BBox(cell.x0 - marge, cell.y0 - marge, cell.x0 + marge, cell.y1 + marge),
        "right": BBox(cell.x1 - marge, cell.y0 - marge, cell.x1 + marge, cell.y1 + marge),
    }
    resultat: dict[str, TableBorder] = {}
    for cote, zone in cotes.items():
        orientation = "h" if cote in {"top", "bottom"} else "v"
        meilleur = None
        meilleur_score = 0
        longueur_attendue = cell.largeur if orientation == "h" else cell.hauteur
        for ligne in lignes:
            if ligne.orientation != orientation or _intersection(ligne.bbox, zone) <= 0:
                continue
            score = _recouvrement_ligne(ligne.bbox, cell, orientation)
            if score > meilleur_score:
                meilleur = ligne
                meilleur_score = score
        if meilleur is not None and meilleur_score >= longueur_attendue * 0.35:
            resultat[cote] = TableBorder(couleur=meilleur.couleur, sz=meilleur.sz)
    return resultat


def _bordure_table_depuis_lignes(lignes: list[LineCandidate]) -> tuple[str, int]:
    if not lignes:
        return "000000", 4
    couleurs: dict[str, int] = {}
    tailles: list[int] = []
    for ligne in lignes:
        couleurs[ligne.couleur] = couleurs.get(ligne.couleur, 0) + 1
        tailles.append(ligne.sz)
    return max(couleurs.items(), key=lambda item: item[1])[0], sorted(tailles)[len(tailles) // 2]


def _bordure_table(page, bbox: BBox, geometrie: PageGeometry) -> tuple[str, int]:
    couleurs: dict[str, int] = {}
    epaisseurs: list[float] = []
    for dessin in page.get_drawings():
        couleur = dessin.get("color")
        if couleur is None:
            continue
        rect_pt = dessin.get("rect")
        rect = geometrie.bbox_depuis_rect_natif(rect_pt)
        if _intersection(rect, bbox) <= 0:
            continue
        if rect.largeur > bbox.largeur * 0.20 or rect.hauteur > bbox.hauteur * 0.20:
            hexa = _couleur_hexa(couleur)
            couleurs[hexa] = couleurs.get(hexa, 0) + 1
            epaisseurs.append(float(dessin.get("width", 0.5) or 0.5))

    couleur = max(couleurs.items(), key=lambda item: item[1])[0] if couleurs else "000000"
    epaisseur_pt = sorted(epaisseurs)[len(epaisseurs) // 2] if epaisseurs else 0.5
    return couleur, max(2, min(24, round(pt_vers_twips(epaisseur_pt) / 2)))


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

        fonds, lignes = _analyse_dessins_table(page, bbox, geometrie)
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
                fond = _couleur_fond_cellule(cell_bbox, fonds)
                cells.append(
                    TableCell(
                        bbox=cell_bbox,
                        texte=texte,
                        col_span=span,
                        fond=fond,
                        spans=_span_cellule(page, polices, cell_bbox, texte, geometrie),
                        bordures=_bordure_cellule(cell_bbox, lignes),
                        direction_texte=_direction_texte_cellule(cell_bbox, texte, fond),
                    )
                )
                col_index = next_index

            if cells:
                rows.append(TableRow(bbox=_bbox_depuis_tuple(row.bbox), cells=cells))

        if not rows:
            continue

        police, size_pt, couleur = _style_table(page, polices, bbox, geometrie)
        bordure_couleur, bordure_sz = _bordure_table_depuis_lignes(lignes)
        if not lignes:
            bordure_couleur, bordure_sz = _bordure_table(page, bbox, geometrie)
        elements.append(
            TableEl(
                bbox=bbox,
                rows=rows,
                col_widths_emu=_col_widths(rows, bbox, table.col_count),
                police=police,
                size_pt=size_pt,
                couleur=couleur,
                bordure_couleur=bordure_couleur,
                bordure_sz=bordure_sz,
            )
        )

    return elements
