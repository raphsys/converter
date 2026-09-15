"""Conversions d'unités et boîtes englobantes.

Toute la chaîne travaille en EMU (English Metric Units) : 914400 par pouce, 12700 par
point. La conversion depuis les points de PyMuPDF se fait ici et nulle part ailleurs,
pour qu'il n'existe qu'un seul endroit où se tromper d'unité.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from math import ceil, floor

import pymupdf

EMU_PER_PT = 12700
TWIPS_PER_PT = 20
GRILLE_DIXIEME_MM_EMU = 3600


def pt_vers_emu(valeur: float) -> int:
    return round(valeur * EMU_PER_PT)


def pt_vers_twips(valeur: float) -> int:
    return round(valeur * TWIPS_PER_PT)


def emu_vers_pt(valeur: int) -> float:
    return valeur / EMU_PER_PT


def quantifier_coord(valeur: int, grille_emu: int = GRILLE_DIXIEME_MM_EMU) -> int:
    return round(valeur / grille_emu) * grille_emu


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


def quantifier_bbox(bbox: BBox, grille_emu: int = GRILLE_DIXIEME_MM_EMU) -> BBox:
    """Quantifie en conservant l'enveloppe : floor en haut/gauche, ceil en bas/droite."""
    x0 = floor(bbox.x0 / grille_emu) * grille_emu
    y0 = floor(bbox.y0 / grille_emu) * grille_emu
    return BBox(
        x0,
        y0,
        max(x0 + 1, ceil(bbox.x1 / grille_emu) * grille_emu),
        max(y0 + 1, ceil(bbox.y1 / grille_emu) * grille_emu),
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


@dataclass(frozen=True)
class PageState:
    """Etat PyMuPDF qui influence tous les reperes de coordonnees d'une page."""

    mediabox: object | None
    cropbox: object | None
    rotation: int


def etat_page(page) -> PageState:
    """Capture l'etat de page dont PyMuPDF peut se servir pour transformer les bboxes."""
    mediabox = _copie_rect(getattr(page, "mediabox", None))
    cropbox = _copie_rect(getattr(page, "cropbox", None))
    rotation = int(getattr(page, "rotation", 0) or 0)
    return PageState(mediabox=mediabox, cropbox=cropbox, rotation=rotation)


@contextmanager
def preserver_etat_page(page):
    """Restaure cropbox/rotation apres un appel PyMuPDF potentiellement mutateur.

    Certaines versions de PyMuPDF modifient la cropbox en appelant `find_tables()`.
    Sur une page tournee avec cropbox non nulle, ce changement de repere decale ensuite
    texte, images et formes d'environ la valeur de la cropbox. Toute extraction doit donc
    revenir a l'etat initial avant de continuer.
    """
    original = etat_page(page)
    try:
        yield
    finally:
        restaurer_etat_page(page, original)


def restaurer_etat_page(page, state: PageState) -> None:
    """Restaure au mieux l'etat capture sans masquer l'erreur de l'appelant."""
    if state.mediabox is not None and hasattr(page, "set_mediabox"):
        with _ignore_page_state_error():
            if not _rects_proches(getattr(page, "mediabox", None), state.mediabox):
                page.set_mediabox(state.mediabox)
    if state.cropbox is not None and hasattr(page, "set_cropbox"):
        with _ignore_page_state_error():
            if not _rects_proches(getattr(page, "cropbox", None), state.cropbox):
                page.set_cropbox(state.cropbox)
    if hasattr(page, "set_rotation"):
        with _ignore_page_state_error():
            if int(getattr(page, "rotation", 0) or 0) != state.rotation:
                page.set_rotation(state.rotation)


@contextmanager
def _ignore_page_state_error():
    try:
        yield
    except Exception:  # noqa: BLE001
        pass


def _copie_rect(rect):
    if rect is None:
        return None
    return pymupdf.Rect(rect)


def _rects_proches(a, b, tolerance: float = 1e-5) -> bool:
    if a is None or b is None:
        return a is b
    ra = pymupdf.Rect(a)
    rb = pymupdf.Rect(b)
    return (
        abs(ra.x0 - rb.x0) <= tolerance
        and abs(ra.y0 - rb.y0) <= tolerance
        and abs(ra.x1 - rb.x1) <= tolerance
        and abs(ra.y1 - rb.y1) <= tolerance
    )


def union(a: BBox, b: BBox) -> BBox:
    return BBox(min(a.x0, b.x0), min(a.y0, b.y0), max(a.x1, b.x1), max(a.y1, b.y1))


def se_chevauchent(a: BBox, b: BBox) -> bool:
    """Vrai si les deux boîtes ont une intersection d'aire non nulle."""
    return a.x0 < b.x1 and b.x0 < a.x1 and a.y0 < b.y1 and b.y0 < a.y1
