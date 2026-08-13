"""Repli raster.

Certaines constructions PDF — dégradés, masques non rectangulaires, modes de fusion —
n'ont pas d'équivalent DrawingML fiable. Plutôt que de produire un rendu faux, on
rastérise la région concernée, et elle seule.

Le texte n'est jamais rastérisé : il est écrit par-dessus et reste réel, sélectionnable
et cherchable, même au-dessus d'une zone d'image.
"""
import itertools
from io import BytesIO

import pymupdf
from PIL import Image

from pdfexact.geometry import emu_vers_pt
from pdfexact.ir import MediaItem, RasterEl

_compteur = itertools.count(1)


def page_a_des_degrades(doc, page) -> bool:
    """Vrai si les ressources de la page déclarent un shading.

    PyMuPDF n'expose pas les dégradés dans get_drawings() : on interroge directement le
    dictionnaire de ressources de la page.
    """
    try:
        valeur = doc.xref_get_key(page.xref, "Resources/Shading")
    except (RuntimeError, ValueError):
        return False
    return bool(valeur) and valeur[0] not in ("null", None)


def _blanc_vers_transparent(octets: bytes) -> bytes:
    image = Image.open(BytesIO(octets)).convert("RGBA")
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            r, g, b, a = pixels[x, y]
            if r > 245 and g > 245 and b > 245:
                pixels[x, y] = (255, 255, 255, 0)
            else:
                pixels[x, y] = (r, g, b, a)
    sortie = BytesIO()
    image.save(sortie, format="PNG")
    return sortie.getvalue()


def rasteriser_region(
    page,
    bbox,
    media: dict,
    dpi: int = 300,
    fond_transparent: bool = False,
) -> RasterEl:
    """Rend la région indiquée en PNG et retourne l'élément qui la remplace."""
    rect = pymupdf.Rect(
        emu_vers_pt(bbox.x0),
        emu_vers_pt(bbox.y0),
        emu_vers_pt(bbox.x1),
        emu_vers_pt(bbox.y1),
    ).intersect(page.rect)

    pixmap = page.get_pixmap(clip=rect, dpi=dpi, alpha=fond_transparent)
    octets = pixmap.tobytes("png")
    if fond_transparent:
        octets = _blanc_vers_transparent(octets)

    media_ref = f"raster{next(_compteur)}"
    media[media_ref] = MediaItem(
        media_ref=media_ref, donnees=octets, extension="png"
    )
    return RasterEl(bbox=bbox, media_ref=media_ref)
