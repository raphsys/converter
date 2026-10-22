"""Planification des strategies de rendu/extraction par region."""
from __future__ import annotations

from dataclasses import dataclass

from typing import Iterable

from pdfexact.geometry import BBox, pt_vers_emu, se_chevauchent, union
from pdfexact.analysis.geometry import bbox_area, center_in, intersection_area
from pdfexact.analysis.provenance import expliquer_filtrage
from pdfexact.ir import FlowParagraph, TextBox
from pdfexact.layout.model import LayoutRegion, ProtectedZone
from pdfexact.layout.understanding import EDITABLE_STRATEGIES, LAYOUT_PROTECTED_STRATEGIES, OCR_PROTECTED_STRATEGIES

LAYOUT_ONLY_STRATEGIES = frozenset({"shape-background"})


@dataclass(frozen=True)
class LayoutPlanItem:
    kind: str
    bbox: BBox
    strategy: str
    editable: bool
    confidence: float
    region: LayoutRegion


def planifier_regions(regions: list[LayoutRegion]) -> list[LayoutPlanItem]:
    return [
        LayoutPlanItem(
            kind=region.kind,
            bbox=region.bbox,
            strategy=region.strategy,
            editable=region.editable or region.strategy in EDITABLE_STRATEGIES,
            confidence=region.confidence,
            region=region,
        )
        for region in sorted(regions, key=lambda item: (item.bbox.y0, item.bbox.x0, item.kind))
    ]


def zones_protegees_du_plan(plan: list[LayoutPlanItem]) -> list[ProtectedZone]:
    zones: list[ProtectedZone] = []
    for item in plan:
        source = str(item.region.style_hints.get("source", "layout-plan"))
        protect_ocr = item.strategy in OCR_PROTECTED_STRATEGIES
        if item.strategy == "word-table" and source != "pdf-table":
            protect_ocr = False
        protect_layout = (
            protect_ocr
            or item.strategy in LAYOUT_PROTECTED_STRATEGIES
            or item.strategy in LAYOUT_ONLY_STRATEGIES
        )
        if protect_ocr or protect_layout:
            zones.append(
                ProtectedZone(
                    kind=item.kind,
                    bbox=item.bbox,
                    source=source,
                    protect_ocr=protect_ocr,
                    protect_layout=protect_layout,
                )
            )
    return zones


def zones_ocr_du_plan(plan: list[LayoutPlanItem]) -> list[BBox]:
    return _fusionner_zones(zone.bbox for zone in zones_protegees_du_plan(plan) if zone.protect_ocr)


def zones_ocr_dur_du_plan(plan: list[LayoutPlanItem]) -> list[BBox]:
    """Zones où l'OCR est interdit, en laissant les images être sondées."""
    return _fusionner_zones(
        item.bbox
        for item in plan
        if item.strategy in OCR_PROTECTED_STRATEGIES
        and item.strategy != "raster-image"
    )


def zones_layout_du_plan(plan: list[LayoutPlanItem]) -> list[BBox]:
    return _fusionner_zones(zone.bbox for zone in zones_protegees_du_plan(plan) if zone.protect_layout)


def filtrer_elements_selon_plan(
    elements: list,
    plan: list[LayoutPlanItem],
    *,
    preserver_texte_natif: bool = False,
) -> list:
    zones_protegees = zones_protegees_du_plan(plan)
    zones = _fusionner_zones(zone.bbox for zone in zones_protegees if zone.protect_ocr)
    if not zones:
        return elements
    zones_texte = _zones_texte_du_plan(plan)
    zones_formules = _fusionner_zones(
        zone.bbox
        for zone in zones_protegees
        if zone.protect_ocr
        and zone.kind in {"formula", "formula-or-complex-vector"}
    )
    filtres = []
    for element in elements:
        bbox = getattr(element, "bbox", None)
        if bbox is None:
            filtres.append(element)
            continue
        if isinstance(element, (TextBox, FlowParagraph)) and _texte_dans_zone_protegee(bbox, zones):
            if _texte_dans_zone_autorisee(bbox, zones_texte):
                filtres.append(element)
                continue
            if preserver_texte_natif and not _texte_dans_zone_protegee(bbox, zones_formules):
                filtres.append(element)
                continue
            expliquer_filtrage(element, "protected-by-layout-plan")
            continue
        filtres.append(element)
    return filtres


def _zones_texte_du_plan(plan: list[LayoutPlanItem]) -> list[BBox]:
    zones_protegees_images = [
        item.bbox
        for item in plan
        if item.strategy == "raster-image"
    ]
    return _fusionner_zones(
        item.bbox
        for item in plan
        if item.strategy == "word-text"
        and item.kind in {"text-column", "caption", "heading", "list", "ai-zone"}
        and not (
            item.region.style_hints.get("kind") == "ai-zone"
            and any(
                _intersection(item.bbox, zone) / max(_aire(item.bbox), 1) >= 0.50
                for zone in zones_protegees_images
            )
        )
    )


def _fusionner_zones(zones: Iterable[BBox]) -> list[BBox]:
    result: list[BBox] = []
    marge = pt_vers_emu(1.5)
    for zone in sorted(zones, key=lambda item: (item.y0, item.x0)):
        etendue = BBox(zone.x0 - marge, zone.y0 - marge, zone.x1 + marge, zone.y1 + marge)
        fusion = None
        for index, existante in enumerate(result):
            if se_chevauchent(etendue, existante):
                fusion = index
                break
        if fusion is None:
            result.append(zone)
        else:
            result[fusion] = union(result[fusion], zone)
    return sorted(result, key=lambda item: (item.y0, item.x0))


def _touche_zone(bbox: BBox, zones: list[BBox], seuil: float = 0.12) -> bool:
    aire = max(_aire(bbox), 1)
    for zone in zones:
        if _centre_dans(bbox, zone):
            return True
        if _intersection(bbox, zone) / aire >= seuil:
            return True
    return False


def _texte_dans_zone_protegee(bbox: BBox, zones: list[BBox]) -> bool:
    aire = max(_aire(bbox), 1)
    for zone in zones:
        if _centre_dans(bbox, zone):
            return True
        if _intersection(bbox, zone) / aire >= 0.62:
            return True
    return False


def _texte_dans_zone_autorisee(bbox: BBox, zones: list[BBox]) -> bool:
    aire = max(_aire(bbox), 1)
    for zone in zones:
        if _centre_dans(bbox, zone):
            return True
        if _intersection(bbox, zone) / aire >= 0.70:
            return True
    return False


def _aire(bbox: BBox) -> int:
    return bbox_area(bbox)


def _intersection(a: BBox, b: BBox) -> int:
    return intersection_area(a, b)


def _centre_dans(bbox: BBox, zone: BBox) -> bool:
    return center_in(bbox, zone)


plan_regions = planifier_regions
