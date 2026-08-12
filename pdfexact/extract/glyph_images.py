"""Repli texte par glyphes rendus.

Certains PDF natifs n'ont pas de table ToUnicode fiable : ils se rendent correctement,
mais les codes texte ne décrivent pas les caractères attendus. Ce module privilégie alors
la fidélité visuelle en découpant les glyphes réellement dessinés.
"""
import pymupdf

from pdfexact.fallback.rasterize import rasteriser_region
from pdfexact.geometry import bbox_depuis_rect, pt_vers_emu


def _bbox_elargie(boite, marge_pt: float = 0.75):
    x0, y0, x1, y1 = boite
    return bbox_depuis_rect(
        pymupdf.Rect(x0 - marge_pt, y0 - marge_pt, x1 + marge_pt, y1 + marge_pt)
    )


def _union(a, b):
    return (
        min(a[0], b[0]),
        min(a[1], b[1]),
        max(a[2], b[2]),
        max(a[3], b[3]),
    )


def extraire_glyphes_images(page, media: dict, dpi: int = 300):
    """Rastérise chaque trace texte en image transparente positionnée.

    On groupe par trace PyMuPDF plutôt que par caractère isolé pour éviter des dizaines de
    milliers de fichiers image, tout en gardant le découpage naturel police/taille/couleur.
    """
    elements = []
    page_bbox = (
        pt_vers_emu(page.rect.x0),
        pt_vers_emu(page.rect.y0),
        pt_vers_emu(page.rect.x1),
        pt_vers_emu(page.rect.y1),
    )

    for trace in page.get_texttrace():
        chars = trace.get("chars") or ()
        if not chars:
            continue

        boite_pt = chars[0][3]
        for _code, _gid, _origine, char_bbox in chars[1:]:
            boite_pt = _union(boite_pt, char_bbox)

        boite = _bbox_elargie(boite_pt)
        if boite.x1 <= page_bbox[0] or boite.y1 <= page_bbox[1]:
            continue
        if boite.x0 >= page_bbox[2] or boite.y0 >= page_bbox[3]:
            continue

        elements.append(
            rasteriser_region(page, boite, media, dpi=dpi, fond_transparent=True)
        )

    return elements
