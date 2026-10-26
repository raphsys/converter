"""Granularité de la segmentation : ``fine`` ou ``blocs``.

``fine`` : une bbox par ligne de texte et par composant visuel.
``blocs`` : une bbox par bloc de texte (paragraphe) ; les composants visuels qui
se touchent ou se chevauchent deviennent une seule image, rendue sur leur zone
commune. Les formes vectorielles ne sont jamais absorbées.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from pdfexact.extract.document import _lier_composants_raster
from pdfexact.fallback.rasterize import rasteriser_region
from pdfexact.geometry import BBox, pt_vers_emu
from pdfexact.ir import Document, FlowParagraph, ImageEl, LinkZone, RasterEl, ShapeEl, TableEl, TextBox

GRANULARITES = ("fine", "blocs")
_NATURES = ((TextBox, "text"), (FlowParagraph, "text"), (ImageEl, "image"), (RasterEl, "image"),
            (ShapeEl, "shape"), (TableEl, "table"), (LinkZone, "link"))
# Parts closer than this belong to the same image.
_CONTACT_EMU = pt_vers_emu(1)


@dataclass(frozen=True)
class Boite:
    page_index: int
    bbox: BBox
    kind: str
    # Position of the segmented element in its page, and of the line in ``fine``.
    element_index: int | None = None
    ligne_index: int | None = None


def ligne_visible(*lignes) -> bool:
    """At least one visible character in these lines (spaces drawn by the PDF are not)."""
    return any(span.texte.strip() for ligne in lignes for span in ligne.spans)


def boites(document: Document, granularite: str) -> list[Boite]:
    """The segmentation bboxes: a text block per paragraph, or per line in ``fine``."""
    resultat = []
    for page in document.pages:
        for element_index, element in enumerate(page.elements):
            kind = next((name for cls, name in _NATURES if isinstance(element, cls)), None)
            if kind == "text" and granularite == "fine" and getattr(element, "lignes", None):
                cadres = [(ligne.bbox, ligne_index) for ligne_index, ligne in enumerate(element.lignes)
                          if ligne_visible(ligne)]
            else:
                cadres = [(getattr(element, "bbox", None), None)]
            for bbox, ligne_index in cadres:
                if kind is not None and bbox is not None and bbox.largeur > 0 and bbox.hauteur > 0:
                    resultat.append(Boite(page.index, bbox, kind, element_index, ligne_index))
    return resultat


def _se_touchent(a: BBox, b: BBox) -> bool:
    return (a.x0 - _CONTACT_EMU <= b.x1 and b.x0 - _CONTACT_EMU <= a.x1
            and a.y0 - _CONTACT_EMU <= b.y1 and b.y0 - _CONTACT_EMU <= a.y1)


def _groupes(visuels: list) -> list[list]:
    """Touching parts, transitively (union-find)."""
    parent = list(range(len(visuels)))

    def racine(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, gauche in enumerate(visuels):
        for j in range(i + 1, len(visuels)):
            if _se_touchent(gauche.bbox, visuels[j].bbox):
                parent[racine(j)] = racine(i)
    groupes: dict[int, list] = {}
    for i, visuel in enumerate(visuels):
        groupes.setdefault(racine(i), []).append(visuel)
    return list(groupes.values())


def regrouper_visuels_en_blocs(document: Document, source_pdf: Path, *, dpi: int) -> None:
    """Replace each group of touching visual parts by one image of their zone."""
    a_regrouper = []
    for page in document.pages:
        visuels = [e for e in page.elements if isinstance(e, (ImageEl, RasterEl))]
        groupes = [groupe for groupe in _groupes(visuels) if len(groupe) > 1]
        if groupes:
            a_regrouper.append((page, groupes))
    if not a_regrouper:
        return
    with pymupdf.open(source_pdf) as pdf:
        for page, groupes in a_regrouper:
            for groupe in groupes:
                zone = BBox(min(e.bbox.x0 for e in groupe), min(e.bbox.y0 for e in groupe),
                            max(e.bbox.x1 for e in groupe), max(e.bbox.y1 for e in groupe))
                bloc = rasteriser_region(pdf[page.index], zone, document.media, dpi=dpi, purpose="visual-block")
                _lier_composants_raster(page, bloc, groupe, "visual-block", dpi=dpi)
                position = min(page.elements.index(e) for e in groupe)
                membres = {id(e) for e in groupe}
                restants = [e for e in page.elements if id(e) not in membres]
                restants.insert(min(position, len(restants)), bloc)
                page.elements = restants
