"""Détection locale de blocs de page.

Cette couche reprend le principe des catalogues Vysi : décider d'abord de la nature
des régions de page, puis déléguer la conversion fine à l'intérieur du bloc.
"""
from dataclasses import dataclass

from pdfexact.geometry import BBox, union
from pdfexact.analysis.geometry import bbox_area, center_in, overlap_ratio


@dataclass(frozen=True)
class PageBlock:
    kind: str
    bbox: BBox
    source: str
    confidence: float | None = None


@dataclass(frozen=True)
class OcrLine:
    texte: str
    score: float | None
    bbox: BBox
    spans: tuple = ()
    angle_deg: float = 0.0
    orientation: str = "horizontal"
    quad_points: tuple[tuple[float, float], ...] = ()
    semantic_role: str | None = None


def _aire(boite: BBox) -> int:
    return bbox_area(boite)


def ratio_couverture(boite: BBox, zone: BBox) -> float:
    return overlap_ratio(boite, zone)


def centre_dans(boite: BBox, zone: BBox) -> bool:
    return center_in(boite, zone)


def est_dans_zone(boite: BBox, zones: list[BBox], seuil: float = 0.25) -> bool:
    return any(ratio_couverture(boite, zone) > seuil for zone in zones)


def _proche_verticalement(precedente: BBox, courante: BBox) -> bool:
    hauteur = max(precedente.hauteur, courante.hauteur, 1)
    ecart = courante.y0 - precedente.y1
    return ecart <= hauteur * 1.9


def _compatible_horizontalement(a: BBox, b: BBox) -> bool:
    chevauchement = min(a.x1, b.x1) - max(a.x0, b.x0)
    largeur_min = max(min(a.largeur, b.largeur), 1)
    proches = abs(a.x0 - b.x0) <= max(a.hauteur, b.hauteur) * 4
    return chevauchement / largeur_min > 0.2 or proches


def detecter_blocs_texte(
    lignes: list[OcrLine],
    zones_non_texte: list[BBox],
) -> list[PageBlock]:
    """Groupe les lignes OCR en blocs texte, hors figures/formules."""
    candidates = [
        ligne
        for ligne in lignes
        if ligne.texte.strip() and not est_dans_zone(ligne.bbox, zones_non_texte)
    ]
    candidates.sort(key=lambda item: (item.bbox.y0, item.bbox.x0))

    groupes: list[list[OcrLine]] = []
    for ligne in candidates:
        if not groupes:
            groupes.append([ligne])
            continue

        dernier_groupe = groupes[-1]
        bbox_groupe = dernier_groupe[0].bbox
        for existante in dernier_groupe[1:]:
            bbox_groupe = union(bbox_groupe, existante.bbox)

        if _proche_verticalement(dernier_groupe[-1].bbox, ligne.bbox) and _compatible_horizontalement(
            bbox_groupe, ligne.bbox
        ):
            dernier_groupe.append(ligne)
        else:
            groupes.append([ligne])

    blocs: list[PageBlock] = []
    for groupe in groupes:
        bbox = groupe[0].bbox
        scores = []
        for ligne in groupe:
            bbox = union(bbox, ligne.bbox)
            if ligne.score is not None:
                scores.append(ligne.score)
        confiance = sum(scores) / len(scores) if scores else None
        blocs.append(PageBlock("text", bbox, "rapidocr-lines", confiance))
    return blocs


def detecter_blocs_page(
    lignes: list[OcrLine],
    zones_non_texte: list[BBox],
) -> list[PageBlock]:
    blocs = [
        PageBlock("visual", zone, "pdf-image", None)
        for zone in sorted(zones_non_texte, key=lambda item: (item.y0, item.x0))
    ]
    blocs.extend(detecter_blocs_texte(lignes, zones_non_texte))
    blocs.sort(key=lambda item: (item.bbox.y0, item.bbox.x0))
    return blocs
