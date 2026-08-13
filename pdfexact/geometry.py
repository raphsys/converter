"""Conversions d'unités et boîtes englobantes.

Toute la chaîne travaille en EMU (English Metric Units) : 914400 par pouce, 12700 par
point. La conversion depuis les points de PyMuPDF se fait ici et nulle part ailleurs,
pour qu'il n'existe qu'un seul endroit où se tromper d'unité.
"""
from dataclasses import dataclass

EMU_PER_PT = 12700
TWIPS_PER_PT = 20


def pt_vers_emu(valeur: float) -> int:
    return round(valeur * EMU_PER_PT)


def pt_vers_twips(valeur: float) -> int:
    return round(valeur * TWIPS_PER_PT)


def emu_vers_pt(valeur: int) -> float:
    return valeur / EMU_PER_PT


@dataclass(frozen=True)
class BBox:
    """Boîte englobante en EMU, origine en haut à gauche — même convention que Word."""

    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def largeur(self) -> int:
        return self.x1 - self.x0

    @property
    def hauteur(self) -> int:
        return self.y1 - self.y0


def bbox_depuis_rect(rect) -> BBox:
    """Convertit un pymupdf.Rect exprimé en points vers une BBox en EMU."""
    return BBox(
        pt_vers_emu(rect.x0),
        pt_vers_emu(rect.y0),
        pt_vers_emu(rect.x1),
        pt_vers_emu(rect.y1),
    )


@dataclass(frozen=True)
class PageGeometry:
    """Geometrie d'une page, avec conversion natif PDF <-> page affichee."""

    largeur_pt: float
    hauteur_pt: float
    rotation: int
    rotation_matrix: object
    derotation_matrix: object

    @classmethod
    def depuis_page(cls, page):
        return cls(
            largeur_pt=float(page.rect.width),
            hauteur_pt=float(page.rect.height),
            rotation=int(getattr(page, "rotation", 0) or 0),
            rotation_matrix=page.rotation_matrix,
            derotation_matrix=page.derotation_matrix,
        )

    @property
    def largeur_emu(self) -> int:
        return pt_vers_emu(self.largeur_pt)

    @property
    def hauteur_emu(self) -> int:
        return pt_vers_emu(self.hauteur_pt)

    @property
    def paysage(self) -> bool:
        return self.largeur_pt > self.hauteur_pt

    def rect_natif_vers_affiche(self, rect):
        if self.rotation % 360 == 0:
            return rect
        return rect * self.rotation_matrix

    def rect_affiche_vers_natif(self, rect):
        if self.rotation % 360 == 0:
            return rect
        return rect * self.derotation_matrix

    def bbox_depuis_rect_natif(self, rect) -> BBox:
        return bbox_depuis_rect(self.rect_natif_vers_affiche(rect))

    def bbox_depuis_rect_affiche(self, rect) -> BBox:
        return bbox_depuis_rect(rect)


def union(a: BBox, b: BBox) -> BBox:
    return BBox(min(a.x0, b.x0), min(a.y0, b.y0), max(a.x1, b.x1), max(a.y1, b.y1))


def se_chevauchent(a: BBox, b: BBox) -> bool:
    """Vrai si les deux boîtes ont une intersection d'aire non nulle."""
    return a.x0 < b.x1 and b.x0 < a.x1 and a.y0 < b.y1 and b.y0 < a.y1
