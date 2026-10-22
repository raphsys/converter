"""Repli texte par glyphes rendus.

Certains PDF natifs n'ont pas de table ToUnicode fiable : ils se rendent correctement,
mais les codes texte ne décrivent pas les caractères attendus. Ce module privilégie alors
la fidélité visuelle en découpant les glyphes réellement dessinés.
"""
import pymupdf

from pdfexact.fallback.rasterize import rasteriser_region
from pdfexact.geometry import BBox, PageGeometry, bbox_depuis_rect
from pdfexact.analysis.geometry import rect_union


def _bbox_elargie(
    boite,
    marge_pt: float = 0.75,
    geometrie: PageGeometry | None = None,
):
    x0, y0, x1, y1 = boite
    rect = pymupdf.Rect(x0 - marge_pt, y0 - marge_pt, x1 + marge_pt, y1 + marge_pt)
    return geometrie.bbox_depuis_rect_natif(rect) if geometrie else bbox_depuis_rect(rect)


def _union(a, b):
    return rect_union(a, b)


def extraire_glyphes_images(
    page,
    media: dict,
    dpi: int = 300,
    geometrie: PageGeometry | None = None,
):
    """Rastérise chaque trace texte en image transparente positionnée.

    On groupe par trace PyMuPDF plutôt que par caractère isolé pour éviter des dizaines de
    milliers de fichiers image, tout en gardant le découpage naturel police/taille/couleur.
    """
    elements = []
    geometrie = geometrie or PageGeometry.depuis_page(page)
    page_bbox = BBox(0, 0, geometrie.largeur_emu, geometrie.hauteur_emu)

    for trace in page.get_texttrace():
        chars = trace.get("chars") or ()
        if not chars:
            continue

        boite_pt = chars[0][3]
        for _code, _gid, _origine, char_bbox in chars[1:]:
            boite_pt = _union(boite_pt, char_bbox)

        boite = _bbox_elargie(boite_pt, geometrie=geometrie)
        if boite.x1 <= page_bbox.x0 or boite.y1 <= page_bbox.y0:
            continue
        if boite.x0 >= page_bbox.x1 or boite.y0 >= page_bbox.y1:
            continue

        elements.append(
            rasteriser_region(page, boite, media, dpi=dpi, fond_transparent=True)
        )

    return elements
