"""Inférence des styles visuels autour d'une zone de texte.

Le PDF ne porte pas toujours "underline" ou "strike" comme attribut texte : souvent ce
sont de simples traits dessinés sous ou à travers les glyphes. Cette couche relie ces
traits et fonds colorés à une boîte de texte.
"""
from __future__ import annotations

from dataclasses import dataclass

import pymupdf

from pdfexact.extract.text import _couleur_hexa
from pdfexact.geometry import BBox, PageGeometry, bbox_depuis_rect, emu_vers_pt


@dataclass(frozen=True)
class TextDecoration:
    souligne: bool = False
    barre: bool = False
    surlignage: str | None = None


_HIGHLIGHT_WORD = {
    "FFFF00": "yellow",
    "00FF00": "green",
    "00FFFF": "cyan",
    "FF00FF": "magenta",
    "0000FF": "blue",
    "FF0000": "red",
}


def _intersection(a: BBox, b: BBox) -> int:
    x0 = max(a.x0, b.x0)
    y0 = max(a.y0, b.y0)
    x1 = min(a.x1, b.x1)
    y1 = min(a.y1, b.y1)
    return max(0, x1 - x0) * max(0, y1 - y0)


def _bbox_dessin(dessin, geometrie: PageGeometry | None = None) -> BBox:
    rect = dessin.get("rect")
    return geometrie.bbox_depuis_rect_natif(rect) if geometrie else bbox_depuis_rect(rect)


def _couleur_highlight(valeur) -> str | None:
    hexa = _couleur_hexa(valeur)
    return _HIGHLIGHT_WORD.get(hexa)


def decorations_texte(page, bbox: BBox, geometrie: PageGeometry | None = None) -> TextDecoration:
    """Infère souligné, barré et surlignage depuis les dessins proches."""
    souligne = False
    barre = False
    surlignage = None
    hauteur_pt = max(emu_vers_pt(bbox.hauteur), 1.0)

    for dessin in page.get_drawings():
        boite = _bbox_dessin(dessin, geometrie)
        if boite.largeur <= 0 or boite.hauteur <= 0:
            continue

        fill = dessin.get("fill")
        if fill is not None:
            aire = _intersection(boite, bbox)
            if aire >= max(bbox.largeur * bbox.hauteur * 0.35, 1):
                surlignage = _couleur_highlight(fill) or surlignage
            continue

        contour = dessin.get("color")
        if contour is None:
            continue
        largeur_commune = max(0, min(boite.x1, bbox.x1) - max(boite.x0, bbox.x0))
        if largeur_commune < bbox.largeur * 0.35:
            continue
        if emu_vers_pt(boite.hauteur) > max(2.5, hauteur_pt * 0.22):
            continue

        centre_y = (boite.y0 + boite.y1) / 2
        bas_texte = bbox.y1
        haut_texte = bbox.y0
        if haut_texte + bbox.hauteur * 0.45 <= centre_y <= haut_texte + bbox.hauteur * 0.72:
            barre = True
        elif bas_texte - bbox.hauteur * 0.18 <= centre_y <= bas_texte + bbox.hauteur * 0.38:
            souligne = True

    return TextDecoration(souligne=souligne, barre=barre, surlignage=surlignage)
