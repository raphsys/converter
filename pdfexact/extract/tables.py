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
from pdfexact.geometry import (
    BBox,
    PageGeometry,
    bbox_depuis_rect,
    preserver_etat_page,
    pt_vers_emu,
    pt_vers_twips,
)
from pdfexact.analysis.geometry import bbox_area, intersection_area
from pdfexact.geometry import union as union_bbox
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


@dataclass(frozen=True)
class WordCandidate:
    bbox: BBox
    texte: str
    police: FontRef
    size_pt: float
    couleur: str


def _bbox_table_depuis_tuple(rect_tuple) -> BBox:
    """Convertit les bboxes de find_tables.

    PyMuPDF renvoie les cellules de find_tables dans l'espace affiche de la page,
    meme quand la page PDF porte une rotation 90/270. Les re-rotater decale les
    tableaux paysage et casse aussi la zone qui protege l'OCR.
    """
    rect = pymupdf.Rect(*rect_tuple)
    return bbox_depuis_rect(rect)


def _intersection(a: BBox, b: BBox) -> int:
    return intersection_area(a, b)


def _aire(bbox: BBox) -> int:
    return bbox_area(bbox)


def _union(a: BBox, b: BBox) -> BBox:
    return union_bbox(a, b)


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
        max(1.0, round(float(meilleur.get("size", 8.0)), 2)),
        _couleur_hexa(meilleur.get("color", 0)),
    )


def _style_depuis_span_dict(span: dict, polices: dict) -> tuple[FontRef, float, str]:
    font_id = _resoudre_police(span.get("font", ""), polices)
    asset = polices[font_id]
    gras, italique = _style_depuis_nom(span.get("font", ""), int(span.get("flags", 0)))
    return (
        FontRef(font_id, asset.famille, gras, italique),
        max(1.0, round(float(span.get("size", 8.0)), 2)),
        _couleur_hexa(span.get("color", 0)),
    )


def _spans_styles_page(page, polices: dict, geometrie: PageGeometry):
    par_ligne: dict[tuple[int, int], list[dict]] = {}
    tous: list[dict] = []
    for bloc_index, bloc in enumerate(page.get_text("dict").get("blocks", [])):
        if bloc.get("type") != 0:
            continue
        for ligne_index, ligne in enumerate(bloc.get("lines", [])):
            styles = []
            for span in ligne.get("spans", []):
                texte = span.get("text", "")
                if not texte:
                    continue
                item = {
                    "bbox": _bbox_span_affiche(span, geometrie),
                    "span": span,
                }
                styles.append(item)
                tous.append(item)
            if styles:
                par_ligne[(bloc_index, ligne_index)] = styles
    return par_ligne, tous


def _style_mot(word_bbox: BBox, word_tuple, styles_ligne: dict, styles_tous: list[dict], polices: dict) -> tuple[FontRef, float, str]:
    candidats = []
    if len(word_tuple) >= 7:
        candidats = styles_ligne.get((int(word_tuple[5]), int(word_tuple[6])), [])
    if not candidats:
        candidats = styles_tous

    meilleur = None
    meilleur_score = 0
    cx = (word_bbox.x0 + word_bbox.x1) // 2
    cy = (word_bbox.y0 + word_bbox.y1) // 2
    for candidat in candidats:
        bbox = candidat["bbox"]
        score = _intersection(word_bbox, bbox)
        if bbox.x0 <= cx <= bbox.x1 and bbox.y0 <= cy <= bbox.y1:
            score += _aire(word_bbox)
        if score > meilleur_score:
            meilleur = candidat["span"]
            meilleur_score = score
    if meilleur is None:
        return FontRef("Table", "Arial", False, False), 8.0, "000000"
    return _style_depuis_span_dict(meilleur, polices)


def _mots_page(page, polices: dict, geometrie: PageGeometry) -> list[WordCandidate]:
    styles_ligne, styles_tous = _spans_styles_page(page, polices, geometrie)
    mots: list[WordCandidate] = []
    for mot in page.get_text("words"):
        texte = str(mot[4] if len(mot) >= 5 else "").strip()
        if not texte:
            continue
        bbox = geometrie.bbox_depuis_rect_natif(pymupdf.Rect(mot[:4]))
        police, size_pt, couleur = _style_mot(bbox, mot, styles_ligne, styles_tous, polices)
        mots.append(WordCandidate(bbox=bbox, texte=texte, police=police, size_pt=size_pt, couleur=couleur))
    return mots


def _mots_dans_table(mots: list[WordCandidate], table_bbox: BBox) -> list[WordCandidate]:
    marge = pt_vers_emu(1.0)
    zone = BBox(table_bbox.x0 - marge, table_bbox.y0 - marge, table_bbox.x1 + marge, table_bbox.y1 + marge)
    resultat = []
    for mot in mots:
        cx = (mot.bbox.x0 + mot.bbox.x1) // 2
        cy = (mot.bbox.y0 + mot.bbox.y1) // 2
        if zone.x0 <= cx <= zone.x1 and zone.y0 <= cy <= zone.y1:
            resultat.append(mot)
    return resultat


def _spans_cellule_depuis_mots(mots: list[WordCandidate], cell_bbox: BBox) -> list[Span]:
    marge = pt_vers_emu(0.5)
    zone = BBox(cell_bbox.x0 - marge, cell_bbox.y0 - marge, cell_bbox.x1 + marge, cell_bbox.y1 + marge)
    candidats = []
    for mot in mots:
        cx = (mot.bbox.x0 + mot.bbox.x1) // 2
        cy = (mot.bbox.y0 + mot.bbox.y1) // 2
        if zone.x0 <= cx <= zone.x1 and zone.y0 <= cy <= zone.y1:
            candidats.append(mot)
    if not candidats:
        return []

    groupes: list[list[WordCandidate]] = []
    tolerance = pt_vers_emu(2.0)
    for mot in sorted(candidats, key=lambda item: (item.bbox.y0, item.bbox.x0)):
        centre = (mot.bbox.y0 + mot.bbox.y1) // 2
        if groupes:
            centre_groupe = sum((item.bbox.y0 + item.bbox.y1) // 2 for item in groupes[-1]) // len(groupes[-1])
            if abs(centre - centre_groupe) <= tolerance:
                groupes[-1].append(mot)
                continue
        groupes.append([mot])

    resultat: list[Span] = []
    for index_ligne, groupe in enumerate(groupes):
        if index_ligne and resultat:
            precedent = resultat[-1]
            resultat[-1] = Span(
                texte=f"{precedent.texte.rstrip()}\n",
                police=precedent.police,
                size_pt=precedent.size_pt,
                couleur=precedent.couleur,
                espacement_twips=precedent.espacement_twips,
                lien=precedent.lien,
                invisible=precedent.invisible,
                souligne=precedent.souligne,
                barre=precedent.barre,
                capitales=precedent.capitales,
                exposant=precedent.exposant,
                indice=precedent.indice,
                surlignage=precedent.surlignage,
                bbox=precedent.bbox,
            )
        ligne = sorted(groupe, key=lambda item: item.bbox.x0)
        for index_mot, mot in enumerate(ligne):
            resultat.append(
                Span(
                    texte=mot.texte + (" " if index_mot < len(ligne) - 1 else ""),
                    police=mot.police,
                    size_pt=mot.size_pt,
                    couleur=mot.couleur,
                    bbox=mot.bbox,
                )
            )
    return resultat


def _texte_depuis_spans(spans: list[Span]) -> str:
    return "".join(span.texte for span in spans).strip()


def _span_cellule(page, polices: dict, cell_bbox: BBox, texte: str, geometrie: PageGeometry, mots_table: list[WordCandidate] | None = None) -> list[Span]:
    decoration = decorations_texte(page, cell_bbox, geometrie)
    spans = _spans_cellule_depuis_mots(mots_table or [], cell_bbox)
    if spans:
        for span in spans:
            span.souligne = decoration.souligne
            span.barre = decoration.barre
        return spans
    if mots_table is not None:
        return []
    if texte:
        spans = _spans_cellule_depuis_texte_natif(page, polices, cell_bbox, texte, geometrie)
    if spans:
        for span in spans:
            span.souligne = decoration.souligne
            span.barre = decoration.barre
        return spans
    if not texte:
        return []

    police, size_pt, couleur = _style_table(page, polices, cell_bbox, geometrie)
    return [
        Span(
            texte=texte,
            police=police,
            size_pt=size_pt,
            couleur=couleur,
            souligne=decoration.souligne,
            barre=decoration.barre,
            bbox=cell_bbox,
        )
    ]


def _bbox_span_affiche(span: dict, geometrie: PageGeometry) -> BBox:
    return geometrie.bbox_depuis_rect_natif(pymupdf.Rect(span.get("bbox", (0, 0, 0, 0))))


def _texte_cellule_compatible(texte_span: str, texte_cellule: str) -> bool:
    attendu = " ".join(str(texte_cellule or "").split()).casefold()
    obtenu = " ".join(str(texte_span or "").split()).casefold()
    if not attendu or not obtenu:
        return False
    attendu_compact = "".join(attendu.split())
    obtenu_compact = "".join(obtenu.split())
    if len(attendu_compact) <= 3:
        return obtenu_compact == attendu_compact
    if len(attendu_compact) <= 12:
        return obtenu_compact == attendu_compact or attendu_compact.startswith(obtenu_compact)
    return obtenu_compact in attendu_compact or attendu_compact in obtenu_compact


def _spans_cellule_depuis_texte_natif(
    page,
    polices: dict,
    cell_bbox: BBox,
    texte_cellule: str,
    geometrie: PageGeometry,
) -> list[Span]:
    """Préserve les positions réelles du texte dans une cellule de table.

    Les bboxes de `get_text("dict")` doivent être projetées dans l'espace affiché,
    comme les bboxes de `find_tables()`.
    """
    lignes: list[tuple[BBox, list[Span]]] = []
    marge = pt_vers_emu(1.0)
    zone = BBox(cell_bbox.x0 - marge, cell_bbox.y0 - marge, cell_bbox.x1 + marge, cell_bbox.y1 + marge)
    for bloc in page.get_text("dict").get("blocks", []):
        if bloc.get("type") != 0:
            continue
        for ligne in bloc.get("lines", []):
            spans_ligne: list[Span] = []
            bbox_ligne: BBox | None = None
            for span in ligne.get("spans", []):
                texte = span.get("text", "")
                if not texte:
                    continue
                if not _texte_cellule_compatible(texte, texte_cellule):
                    continue
                bbox = _bbox_span_affiche(span, geometrie)
                centre_x = (bbox.x0 + bbox.x1) // 2
                centre_y = (bbox.y0 + bbox.y1) // 2
                if not (zone.x0 <= centre_x <= zone.x1 and zone.y0 <= centre_y <= zone.y1):
                    continue
                font_id = _resoudre_police(span.get("font", ""), polices)
                asset = polices[font_id]
                gras, italique = _style_depuis_nom(span.get("font", ""), int(span.get("flags", 0)))
                spans_ligne.append(
                    Span(
                        texte=texte,
                        police=FontRef(font_id, asset.famille, gras, italique),
                        size_pt=max(1.0, round(float(span.get("size", 8.0)), 2)),
                        couleur=_couleur_hexa(span.get("color", 0)),
                        bbox=bbox,
                    )
                )
                bbox_ligne = bbox if bbox_ligne is None else _union(bbox_ligne, bbox)
            if spans_ligne and bbox_ligne is not None:
                lignes.append((bbox_ligne, spans_ligne))

    if not lignes:
        return []

    resultat: list[Span] = []
    for index, (_bbox, spans_ligne) in enumerate(sorted(lignes, key=lambda item: (item[0].y0, item[0].x0))):
        if index:
            precedent = resultat[-1]
            resultat[-1] = Span(
                texte=f"{precedent.texte}\n",
                police=precedent.police,
                size_pt=precedent.size_pt,
                couleur=precedent.couleur,
                espacement_twips=precedent.espacement_twips,
                lien=precedent.lien,
                invisible=precedent.invisible,
                souligne=precedent.souligne,
                barre=precedent.barre,
                capitales=precedent.capitales,
                exposant=precedent.exposant,
                indice=precedent.indice,
                surlignage=precedent.surlignage,
                bbox=precedent.bbox,
            )
        resultat.extend(spans_ligne)
    return resultat


def _bbox_spans(spans: list[Span]) -> BBox | None:
    bboxes = [span.bbox for span in spans if span.bbox is not None]
    if not bboxes:
        return None
    bbox = bboxes[0]
    for item in bboxes[1:]:
        bbox = _union(bbox, item)
    return bbox


def _alignement_cellule(cell_bbox: BBox, spans: list[Span]) -> str:
    bbox = _bbox_spans(spans)
    if bbox is None:
        return "center"
    gauche = max(0, bbox.x0 - cell_bbox.x0)
    droite = max(0, cell_bbox.x1 - bbox.x1)
    tolerance = max(pt_vers_emu(2.0), int(cell_bbox.largeur * 0.12))
    if abs(gauche - droite) <= tolerance:
        return "center"
    if droite < gauche * 0.55:
        return "right"
    return "left"


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




def _positions_x_table(table) -> list[int]:
    """Construit une grille X robuste depuis toutes les cellules détectées.

    `find_tables()` insère parfois de très fines colonnes vides autour des cellules
    fusionnées d'en-tête. Si on les transmet telles quelles à Word, les en-têtes
    multi-niveaux se fragmentent et les lignes suivantes se décalent. On garde donc les
    vraies frontières majoritaires et on absorbe les micro-intervalles dans le voisin.
    """
    positions = [
        _bbox_table_depuis_tuple(table.bbox).x0,
        _bbox_table_depuis_tuple(table.bbox).x1,
    ]
    occurrences: dict[int, int] = {}
    for row in table.rows:
        for cell in row.cells:
            if cell is None:
                continue
            bbox = _bbox_table_depuis_tuple(cell)
            positions.extend([bbox.x0, bbox.x1])
            occurrences[bbox.x0] = occurrences.get(bbox.x0, 0) + 1
            occurrences[bbox.x1] = occurrences.get(bbox.x1, 0) + 1

    positions = sorted(set(positions))
    seuil_micro = pt_vers_emu(7.5)
    index = 0
    while index < len(positions) - 1:
        gauche = positions[index]
        droite = positions[index + 1]
        if droite - gauche > seuil_micro:
            index += 1
            continue

        if index == 0:
            del positions[index + 1]
        elif index + 1 == len(positions) - 1:
            del positions[index]
        else:
            score_gauche = occurrences.get(gauche, 0)
            score_droite = occurrences.get(droite, 0)
            if score_gauche > score_droite:
                del positions[index + 1]
            else:
                del positions[index]
                index = max(index - 1, 0)
        if index:
            index -= 1

    return positions


def _position_proche(positions: list[int], valeur: int) -> int:
    return min(range(len(positions)), key=lambda index: abs(positions[index] - valeur))


def _colonnes_cellule(cell_bbox: BBox, positions: list[int]) -> tuple[int, int]:
    debut = _position_proche(positions, cell_bbox.x0)
    fin = _position_proche(positions, cell_bbox.x1)
    if fin <= debut:
        fin = min(debut + 1, len(positions) - 1)
    return debut, fin


def _cellule_vide(
    row_bbox: BBox,
    positions: list[int],
    colonne: int,
    fonds: list[FillCandidate],
    lignes: list[LineCandidate],
) -> TableCell:
    bbox = BBox(positions[colonne], row_bbox.y0, positions[colonne + 1], row_bbox.y1)
    return TableCell(
        bbox=bbox,
        texte="",
        fond=_couleur_fond_cellule(bbox, fonds),
        bordures=_bordure_cellule(bbox, lignes),
    )


def _colonnes_ligne(row: TableRow) -> dict[tuple[int, int], TableCell]:
    colonnes: dict[tuple[int, int], TableCell] = {}
    courant = 0
    for cell in row.cells:
        debut = courant
        fin = courant + max(cell.col_span, 1)
        colonnes[(debut, fin)] = cell
        courant = fin
    return colonnes


def _appliquer_fusions_verticales_entete(rows: list[TableRow], table_bbox: BBox) -> None:
    """Reconstitue les fusions verticales d'en-tête perdues par find_tables().

    Quand une cellule fusionnée verticalement existe dans le PDF, PyMuPDF expose
    souvent la cellule du haut puis des trous `None` dans les lignes suivantes. Après
    remplissage de ces trous pour préserver la grille Word, il faut convertir ces
    cellules vides en `vMerge` pour éviter les en-têtes fragmentés.
    """
    if len(rows) < 2:
        return

    limite_entete = table_bbox.y0 + int(table_bbox.hauteur * 0.35)
    for index in range(1, len(rows)):
        row = rows[index]
        if row.bbox.y0 > limite_entete:
            break
        precedent = _colonnes_ligne(rows[index - 1])
        courant = _colonnes_ligne(row)
        for plage, cell in courant.items():
            if cell.texte.strip() or not cell.fond:
                continue
            au_dessus = precedent.get(plage)
            if au_dessus is None or au_dessus.fond != cell.fond:
                continue
            if not au_dessus.texte.strip() and au_dessus.v_merge != "continue":
                continue
            if au_dessus.v_merge is None:
                au_dessus.v_merge = "restart"
            cell.v_merge = "continue"


def _mots(texte: str) -> int:
    return len([mot for mot in texte.replace("\n", " ").split(" ") if mot.strip()])


def _textes_aplatis(textes: list[list[str]]) -> list[str]:
    return [
        (cellule or "").strip()
        for ligne in textes
        for cellule in ligne
        if cellule is not None
    ]


def _semble_faux_tableau_de_mise_en_page(
    *,
    bbox: BBox,
    page_width: int,
    page_height: int,
    row_count: int,
    col_count: int,
    textes: list[list[str]],
    lignes_grille: int = 0,
) -> bool:
    """Rejette les cadres/colonnes que `find_tables()` prend pour des tableaux.

    Dans les mises en page magazine, des cadres verticaux et horizontaux entourent des
    colonnes de texte. PyMuPDF les expose parfois comme une table 2x2/3x2 couvrant une
    grande zone. Ce n'est pas un tableau documentaire : le rendre en Word Table casse
    la lecture, compresse les colonnes et superpose le texte.
    """
    if row_count <= 0 or col_count <= 0:
        return True

    total = max(row_count * col_count, 1)
    textes_cellules = _textes_aplatis(textes)
    non_vides = len([texte for texte in textes_cellules if texte])
    ratio_vide = 1.0 - non_vides / total
    ratio_page = _aire(bbox) / max(page_width * page_height, 1)
    petite_grille = row_count <= 3 and col_count <= 3
    grande_zone = ratio_page >= 0.14
    grille_attendue = max(row_count - 1, 1) + max(col_count - 1, 1)
    grille_insuffisante = (
        row_count >= 4
        and col_count >= 4
        and lignes_grille < max(4, int(grille_attendue * 0.30))
    )

    textes_longs = [
        texte
        for texte in textes_cellules
        if len(texte) >= 70 or _mots(texte) >= 10
    ]

    if petite_grille and grande_zone and ratio_vide >= 0.32:
        return True

    if petite_grille and grande_zone and len(textes_longs) >= 2:
        return True

    if row_count <= 3 and col_count <= 2 and ratio_page >= 0.10 and non_vides <= total * 0.55:
        return True

    # Une vraie table compacte peut être 2x2, mais une grande grille 2x2 dont chaque
    # cellule contient du paragraphe est presque toujours un faux tableau de colonnes.
    if row_count <= 2 and col_count <= 2 and ratio_page >= 0.20 and any(textes_longs):
        return True

    # Les diagrammes composés de boîtes colorées alignées sont parfois exposés par
    # PyMuPDF comme des tables 10x8, 13x9, etc. Une vraie table dense porte une
    # ossature de lignes détectables; une pseudo-grille très vide avec presque aucune
    # ligne est un schéma, pas une table Word.
    if grille_insuffisante and ratio_vide >= 0.45:
        return True

    if grille_insuffisante and len(textes_longs) >= 1 and ratio_vide >= 0.25:
        return True

    if grille_insuffisante and non_vides <= total * 0.35 and len(textes_cellules) >= 20:
        return True

    return False


def extraire_tableaux(page, polices: dict, geometrie: PageGeometry | None = None) -> list[TableEl]:
    """Retourne les tableaux détectés par lignes/cellules PDF."""
    if not hasattr(page, "find_tables"):
        return []

    geometrie = geometrie or PageGeometry.depuis_page(page)
    try:
        tampon = io.StringIO()
        with contextlib.redirect_stdout(tampon), contextlib.redirect_stderr(tampon):
            with preserver_etat_page(page):
                tables = page.find_tables().tables
    except Exception:  # noqa: BLE001
        return []

    mots_page = _mots_page(page, polices, geometrie)
    elements: list[TableEl] = []
    for table in tables:
        if table.row_count < 2 or table.col_count < 2:
            continue
        bbox = _bbox_table_depuis_tuple(table.bbox)
        if bbox.largeur < pt_vers_emu(60) or bbox.hauteur < pt_vers_emu(30):
            continue

        fonds, lignes = _analyse_dessins_table(page, bbox, geometrie)
        with preserver_etat_page(page):
            textes = table.extract()
        mots_table = _mots_dans_table(mots_page, bbox)
        positions_x = _positions_x_table(table)
        col_count = max(len(positions_x) - 1, 1)
        if _semble_faux_tableau_de_mise_en_page(
            bbox=bbox,
            page_width=geometrie.largeur_emu,
            page_height=geometrie.hauteur_emu,
            row_count=table.row_count,
            col_count=col_count,
            textes=textes,
            lignes_grille=len(lignes),
        ):
            continue

        rows: list[TableRow] = []
        for row_index, row in enumerate(table.rows):
            row_bbox = _bbox_table_depuis_tuple(row.bbox)
            cellules_positionnees = []
            for col_index, cell_rect in enumerate(row.cells):
                if cell_rect is None:
                    continue

                texte = ""
                if row_index < len(textes) and col_index < len(textes[row_index]):
                    texte = textes[row_index][col_index] or ""
                cell_bbox_brute = _bbox_table_depuis_tuple(cell_rect)
                if not texte.strip() and cell_bbox_brute.largeur <= pt_vers_emu(7.5):
                    continue
                debut, fin = _colonnes_cellule(cell_bbox_brute, positions_x)
                cell_bbox = BBox(positions_x[debut], row_bbox.y0, positions_x[fin], row_bbox.y1)
                fond = _couleur_fond_cellule(cell_bbox, fonds)
                source_mots = mots_table if mots_table else None
                spans = _span_cellule(page, polices, cell_bbox, texte, geometrie, source_mots)
                texte_ir = _texte_depuis_spans(spans) if source_mots is not None else texte
                cellules_positionnees.append(
                    (
                        debut,
                        fin,
                        TableCell(
                            bbox=cell_bbox,
                            texte=texte_ir,
                            col_span=max(fin - debut, 1),
                            fond=fond,
                            spans=spans,
                            alignement=_alignement_cellule(cell_bbox, spans),
                            bordures=_bordure_cellule(cell_bbox, lignes),
                            direction_texte=_direction_texte_cellule(cell_bbox, texte, fond),
                        ),
                    ),
                )

            cells: list[TableCell] = []
            colonne_courante = 0
            for debut, fin, cell in sorted(cellules_positionnees, key=lambda item: item[0]):
                if fin <= colonne_courante:
                    continue
                debut = max(debut, colonne_courante)
                while colonne_courante < debut:
                    cells.append(
                        _cellule_vide(row_bbox, positions_x, colonne_courante, fonds, lignes)
                    )
                    colonne_courante += 1
                cell.bbox = BBox(positions_x[debut], cell.bbox.y0, positions_x[fin], cell.bbox.y1)
                cell.col_span = max(fin - debut, 1)
                cells.append(cell)
                colonne_courante = fin
            while colonne_courante < col_count:
                cells.append(_cellule_vide(row_bbox, positions_x, colonne_courante, fonds, lignes))
                colonne_courante += 1
            if cells:
                rows.append(TableRow(bbox=row_bbox, cells=cells))

        if not rows:
            continue

        _appliquer_fusions_verticales_entete(rows, bbox)

        police, size_pt, couleur = _style_table(page, polices, bbox, geometrie)
        bordure_couleur, bordure_sz = _bordure_table_depuis_lignes(lignes)
        if not lignes:
            bordure_couleur, bordure_sz = _bordure_table(page, bbox, geometrie)
        elements.append(
            TableEl(
                bbox=bbox,
                rows=rows,
                col_widths_emu=[
                    max(1, positions_x[index + 1] - positions_x[index])
                    for index in range(col_count)
                ],
                police=police,
                size_pt=size_pt,
                couleur=couleur,
                bordure_couleur=bordure_couleur,
                bordure_sz=bordure_sz,
            )
        )

    return elements


def extraire_tableaux_listing(page, polices: dict, geometrie: PageGeometry | None = None) -> list[TableEl]:
    """Reconstruit les listings tabulaires à colonnes fixes non vus par find_tables()."""
    geometrie = geometrie or PageGeometry.depuis_page(page)
    lignes = _lignes_texte_natif(page, geometrie)
    if not _semble_listing_subject_number_percent(lignes):
        return []

    traits = _traits_listing(page, geometrie)
    table_bbox = _bbox_listing_depuis_traits(traits, lignes)
    if table_bbox is None:
        table_bbox = _bbox_listing_depuis_lignes(lignes)
    if table_bbox is None:
        return []

    colonnes = _colonnes_listing_snp(lignes, table_bbox)
    groupes = _grouper_lignes_listing(lignes, table_bbox)
    if len(groupes) < 12:
        return []
    # Word/LibreOffice ne rend pas correctement les listings tres denses en vrai
    # tableau positionne: les lignes sont clippees et du texte disparait. Dans ce
    # cas on conserve les textes positionnes et les traits vectoriels natifs.
    hauteurs = sorted(max(1, _bbox_groupe_lignes(groupe, table_bbox).hauteur) for groupe in groupes)
    hauteur_mediane_pt = hauteurs[len(hauteurs) // 2] / pt_vers_emu(1)
    if len(groupes) > 45 or hauteur_mediane_pt < 9.5:
        return []

    rows: list[TableRow] = []
    for index, groupe in enumerate(groupes):
        row_bbox = _bbox_groupe_lignes(groupe, table_bbox)
        cells: list[TableCell] = []
        textes = [[] for _ in range(len(colonnes) - 1)]
        bboxes = [[] for _ in range(len(colonnes) - 1)]
        for ligne in groupe:
            col = _colonne_listing(ligne["bbox"], colonnes)
            textes[col].append(ligne["text"])
            bboxes[col].append(ligne["bbox"])
        for col_index in range(len(colonnes) - 1):
            cell_bbox = BBox(colonnes[col_index], row_bbox.y0, colonnes[col_index + 1], row_bbox.y1)
            texte = " ".join(textes[col_index]).strip()
            alignement = "right" if col_index in {1, 2, 4, 5} else "left"
            bordures = _bordures_listing_cellule(index, col_index, len(groupes))
            cells.append(
                TableCell(
                    bbox=cell_bbox,
                    texte=texte,
                    spans=_span_cellule(page, polices, cell_bbox, texte, geometrie) if texte else [],
                    alignement=alignement,
                    bordures=bordures,
                )
            )
        rows.append(TableRow(bbox=row_bbox, cells=cells))

    police, size_pt, couleur = _style_table(page, polices, table_bbox, geometrie)
    return [
        TableEl(
            bbox=table_bbox,
            rows=rows,
            col_widths_emu=[max(1, colonnes[i + 1] - colonnes[i]) for i in range(len(colonnes) - 1)],
            police=police,
            size_pt=size_pt,
            couleur=couleur,
            bordure_couleur="231F20",
            bordure_sz=4,
            bordures_globales=False,
        )
    ]


def _lignes_texte_natif(page, geometrie: PageGeometry) -> list[dict]:
    lignes = []
    for bloc in page.get_text("dict").get("blocks", []):
        if bloc.get("type") != 0:
            continue
        for ligne in bloc.get("lines", []):
            texte = "".join(span.get("text", "") for span in ligne.get("spans", [])).strip()
            if not texte:
                continue
            lignes.append({"text": texte, "bbox": geometrie.bbox_depuis_rect_natif(pymupdf.Rect(ligne["bbox"]))})
    return sorted(lignes, key=lambda item: (item["bbox"].y0, item["bbox"].x0))


def _semble_listing_subject_number_percent(lignes: list[dict]) -> bool:
    textes = [ligne["text"].strip().casefold() for ligne in lignes]
    if sum(1 for texte in textes if texte == "subject") < 2:
        return False
    if sum(1 for texte in textes if texte == "number") < 2:
        return False
    if sum(1 for texte in textes if texte == "percent") < 2:
        return False
    pointilles = sum(1 for texte in textes if ". ." in texte or "..." in texte)
    return pointilles >= 20


def _traits_listing(page, geometrie: PageGeometry) -> list[LineCandidate]:
    bbox_page = BBox(0, 0, geometrie.largeur_emu, geometrie.hauteur_emu)
    return _analyse_dessins_table(page, bbox_page, geometrie)[1]


def _bbox_listing_depuis_traits(traits: list[LineCandidate], lignes: list[dict]) -> BBox | None:
    headers = [ligne["bbox"] for ligne in lignes if ligne["text"].strip().casefold() == "subject"]
    if len(headers) < 2:
        return None
    header_y = min(header.y0 for header in headers)
    horizontaux = [trait.bbox for trait in traits if trait.orientation == "h" and trait.bbox.largeur >= pt_vers_emu(120)]
    utiles = [
        trait
        for trait in horizontaux
        if trait.y0 >= header_y - pt_vers_emu(10)
    ]
    if len(utiles) < 2:
        return None
    x0 = min(trait.x0 for trait in utiles)
    x1 = max(trait.x1 for trait in utiles)
    proches_entete = [trait for trait in utiles if trait.y0 <= header_y + pt_vers_emu(18)]
    y0 = min((trait.y0 for trait in proches_entete), default=min(trait.y0 for trait in utiles))
    y1 = max(trait.y1 for trait in utiles)
    return BBox(x0, y0, x1, y1)


def _bbox_listing_depuis_lignes(lignes: list[dict]) -> BBox | None:
    utiles = [ligne["bbox"] for ligne in lignes if ". ." in ligne["text"] or ligne["text"].casefold() in {"subject", "number", "percent"}]
    if len(utiles) < 20:
        return None
    bbox = utiles[0]
    for ligne in utiles[1:]:
        bbox = _union(bbox, ligne)
    return BBox(bbox.x0, bbox.y0 - pt_vers_emu(3), bbox.x1, bbox.y1 + pt_vers_emu(3))


def _colonnes_listing_snp(lignes: list[dict], table_bbox: BBox) -> list[int]:
    headers = {cle: [] for cle in ("subject", "number", "percent")}
    for ligne in lignes:
        cle = ligne["text"].strip().casefold()
        if cle in headers:
            headers[cle].append(ligne["bbox"])
    subjects = sorted(headers["subject"], key=lambda bbox: bbox.x0)
    numbers = sorted(headers["number"], key=lambda bbox: bbox.x0)
    percents = sorted(headers["percent"], key=lambda bbox: bbox.x0)
    if len(subjects) >= 2 and len(numbers) >= 2 and len(percents) >= 2:
        left_num = (subjects[0].x1 + numbers[0].x0) // 2
        left_pct = (numbers[0].x1 + percents[0].x0) // 2
        mid = (percents[0].x1 + subjects[1].x0) // 2
        right_num = (subjects[1].x1 + numbers[1].x0) // 2
        right_pct = (numbers[1].x1 + percents[1].x0) // 2
        return [table_bbox.x0, left_num, left_pct, mid, right_num, right_pct, table_bbox.x1]
    largeur = table_bbox.largeur
    return [
        table_bbox.x0,
        table_bbox.x0 + int(largeur * 0.36),
        table_bbox.x0 + int(largeur * 0.44),
        table_bbox.x0 + int(largeur * 0.50),
        table_bbox.x0 + int(largeur * 0.86),
        table_bbox.x0 + int(largeur * 0.94),
        table_bbox.x1,
    ]


def _grouper_lignes_listing(lignes: list[dict], table_bbox: BBox) -> list[list[dict]]:
    candidates = [
        ligne
        for ligne in lignes
        if table_bbox.x0 - pt_vers_emu(4) <= ligne["bbox"].x0 <= table_bbox.x1 + pt_vers_emu(4)
        and table_bbox.y0 - pt_vers_emu(3) <= ligne["bbox"].y0 <= table_bbox.y1 + pt_vers_emu(3)
    ]
    groupes: list[list[dict]] = []
    tolerance = pt_vers_emu(3.0)
    for ligne in sorted(candidates, key=lambda item: (item["bbox"].y0, item["bbox"].x0)):
        centre = (ligne["bbox"].y0 + ligne["bbox"].y1) // 2
        if groupes:
            centre_groupe = sum((item["bbox"].y0 + item["bbox"].y1) // 2 for item in groupes[-1]) // len(groupes[-1])
            if abs(centre - centre_groupe) <= tolerance:
                groupes[-1].append(ligne)
                continue
        groupes.append([ligne])
    return [sorted(groupe, key=lambda item: item["bbox"].x0) for groupe in groupes]


def _bbox_groupe_lignes(groupe: list[dict], table_bbox: BBox) -> BBox:
    y0 = min(item["bbox"].y0 for item in groupe)
    y1 = max(item["bbox"].y1 for item in groupe)
    return BBox(table_bbox.x0, y0, table_bbox.x1, y1)


def _colonne_listing(bbox: BBox, colonnes: list[int]) -> int:
    centre = (bbox.x0 + bbox.x1) // 2
    for index in range(len(colonnes) - 1):
        if colonnes[index] <= centre < colonnes[index + 1]:
            return index
    return max(0, min(len(colonnes) - 2, len(colonnes) - 2))


def _bordures_listing_cellule(row_index: int, col_index: int, row_count: int) -> dict[str, TableBorder]:
    border = TableBorder("231F20", 4)
    bordures: dict[str, TableBorder] = {}
    if row_index == 0:
        bordures["top"] = border
        bordures["bottom"] = border
    if row_index == row_count - 1:
        bordures["bottom"] = border
    if col_index in {0, 1, 3, 4}:
        bordures["right"] = border
    if col_index == 2:
        bordures["right"] = border
    return bordures
