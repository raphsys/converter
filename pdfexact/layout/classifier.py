"""Classification des hypotheses layout en regions documentaires."""
from __future__ import annotations

from typing import TYPE_CHECKING

from pdfexact.geometry import BBox, pt_vers_emu, union
from pdfexact.layout.model import LayoutPage, LayoutRegion

if TYPE_CHECKING:
    from pdfexact.layout.understanding import PageUnderstanding


def classer_regions(
    analyse: LayoutPage,
    comprehension: "PageUnderstanding | None" = None,
) -> list[LayoutRegion]:
    if comprehension is not None:
        return sorted(
            (_region_depuis_element(element) for element in comprehension.elements),
            key=lambda region: (region.bbox.y0, region.bbox.x0, region.kind),
        )

    regions: list[LayoutRegion] = []
    aire_page = max(analyse.width * analyse.height, 1)

    for block in analyse.table_candidates:
        regions.append(
            LayoutRegion(
                kind="table-candidate",
                bbox=block.bbox,
                confidence=0.55,
                editable=True,
                strategy="word-table",
                style_hints={"source": block.source, **block.metadata},
            )
        )

    for block in analyse.image_blocks:
        fullpage = _aire(block.bbox) / aire_page > 0.82
        regions.append(
            LayoutRegion(
                kind="scanned-page" if fullpage else "image",
                bbox=block.bbox,
                confidence=0.65,
                editable=False,
                strategy="raster-image",
                style_hints={"source": block.source},
            )
        )

    for block in analyse.drawing_blocks:
        regions.append(
            LayoutRegion(
                kind="shape-background" if block.metadata.get("has_fill") else "shape",
                bbox=block.bbox,
                confidence=0.45,
                editable=False,
                strategy="shape-background" if block.metadata.get("has_fill") else "shape",
                style_hints={"source": block.source, **block.metadata},
            )
        )

    colonnes = detecter_regions_colonnes(analyse.native_line_bboxes(), analyse.width, analyse.height)
    if colonnes:
        for index, colonne in enumerate(colonnes):
            regions.append(
                LayoutRegion(
                    kind="text-column",
                    bbox=colonne,
                    confidence=0.70,
                    editable=True,
                    strategy="word-text",
                    style_hints={"source": "native-lines", "column": index + 1, "columns": len(colonnes)},
                )
            )
    else:
        for block in analyse.text_blocks:
            regions.append(
                LayoutRegion(
                    kind="text",
                    bbox=block.bbox,
                    confidence=0.60,
                    editable=True,
                    strategy="word-text",
                    style_hints={"source": block.source, "line_count": block.metadata.get("line_count", 0)},
                )
            )

    return sorted(regions, key=lambda region: (region.bbox.y0, region.bbox.x0, region.kind))


classify_regions = classer_regions


def _region_depuis_element(element) -> LayoutRegion:
    return LayoutRegion(
        kind=element.role,
        bbox=element.bbox,
        confidence=element.confidence,
        editable=element.editable,
        strategy=element.strategy,
        style_hints={
            "kind": element.kind,
            "source": element.source,
            "context": element.context,
            "reasons": element.reasons,
        },
    )


def _aire(bbox) -> int:
    return max(0, bbox.largeur) * max(0, bbox.hauteur)


def detecter_regions_colonnes(
    lignes: list[BBox],
    largeur_page: int,
    hauteur_page: int = 0,
) -> list[BBox]:
    candidates = [
        ligne
        for ligne in lignes
        if ligne.largeur >= pt_vers_emu(24)
        and ligne.largeur <= largeur_page * 0.72
    ]
    if len(candidates) < 8:
        return []
    lignes_par_centre = sorted(
        (((ligne.x0 + ligne.x1) // 2, ligne) for ligne in candidates),
        key=lambda item: (item[0], item[1].y0, item[1].x0),
    )
    groupes: list[list[BBox]] = []
    tolerance = max(pt_vers_emu(42), largeur_page // 12)
    centres_groupes: list[list[int]] = []
    for centre, ligne in lignes_par_centre:
        if not centres_groupes or abs(centre - centres_groupes[-1][-1]) > tolerance:
            centres_groupes.append([centre])
            groupes.append([ligne])
        else:
            centres_groupes[-1].append(centre)
            groupes[-1].append(ligne)
    minimum = max(3, len(candidates) // 12)
    groupes = [groupe for groupe in groupes if len(groupe) >= minimum]
    if len(groupes) <= 1:
        return []
    regions: list[BBox] = []
    marge_x = pt_vers_emu(3)
    marge_y = pt_vers_emu(2)
    for groupe in groupes[:4]:
        bbox = groupe[0]
        for ligne in groupe[1:]:
            bbox = union(bbox, ligne)
        regions.append(
            _clip_bbox(
                BBox(bbox.x0 - marge_x, bbox.y0 - marge_y, bbox.x1 + marge_x, bbox.y1 + marge_y),
                largeur_page,
                hauteur_page or max(bbox.y1 + marge_y, pt_vers_emu(1)),
            )
        )
    regions.sort(key=lambda item: item.x0)
    if not _colonnes_separees(regions):
        return []
    return regions


def _clip_bbox(bbox: BBox, largeur: int, hauteur: int) -> BBox:
    x0 = max(0, min(bbox.x0, largeur - 1))
    y0 = max(0, min(bbox.y0, hauteur - 1))
    x1 = max(x0 + 1, min(bbox.x1, largeur))
    y1 = max(y0 + 1, min(bbox.y1, hauteur))
    return BBox(x0, y0, x1, y1)


def _colonnes_separees(regions: list[BBox]) -> bool:
    if len(regions) < 2:
        return False
    marge_negative_toleree = pt_vers_emu(4)
    for gauche, droite in zip(regions, regions[1:]):
        chevauchement = max(0, min(gauche.x1, droite.x1) - max(gauche.x0, droite.x0))
        if chevauchement / max(min(gauche.largeur, droite.largeur), 1) > 0.08:
            return False
        if droite.x0 - gauche.x1 < -marge_negative_toleree:
            return False
    return True
