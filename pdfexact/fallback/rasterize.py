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
from PIL import Image, ImageDraw

from pdfexact.geometry import BBox, PageGeometry, bbox_depuis_rect, emu_vers_pt, pt_vers_emu, se_chevauchent
from pdfexact.ir import FlowParagraph, ImageEl, MediaItem, RasterEl, TextBox

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
    bbox_affiche = BBox(
        pt_vers_emu(rect.x0),
        pt_vers_emu(rect.y0),
        pt_vers_emu(rect.x1),
        pt_vers_emu(rect.y1),
    )

    pixmap = page.get_pixmap(clip=rect, dpi=dpi, alpha=fond_transparent)
    octets = pixmap.tobytes("png")
    if fond_transparent:
        octets = _blanc_vers_transparent(octets)

    media_ref = f"raster{next(_compteur)}"
    media[media_ref] = MediaItem(
        media_ref=media_ref, donnees=octets, extension="png"
    )
    return RasterEl(bbox=bbox_affiche, media_ref=media_ref)


def rasteriser_region_sans_texte(
    page,
    bbox,
    media: dict,
    dpi: int = 300,
    geometrie: PageGeometry | None = None,
) -> RasterEl:
    """Rend une région visuelle en supprimant les glyphes natifs du bitmap.

    Pour les schémas, le bitmap ne sert alors que de fond graphique. Les textes PDF
    natifs sont ensuite réécrits par-dessus en Word, à leurs boîtes exactes.
    """
    geometrie = geometrie or PageGeometry.depuis_page(page)
    rect_affiche = pymupdf.Rect(
        emu_vers_pt(bbox.x0),
        emu_vers_pt(bbox.y0),
        emu_vers_pt(bbox.x1),
        emu_vers_pt(bbox.y1),
    ).intersect(page.rect)
    bbox_affiche = BBox(
        pt_vers_emu(rect_affiche.x0),
        pt_vers_emu(rect_affiche.y0),
        pt_vers_emu(rect_affiche.x1),
        pt_vers_emu(rect_affiche.y1),
    )
    pixmap = page.get_pixmap(clip=rect_affiche, dpi=dpi, alpha=False)
    image = Image.open(BytesIO(pixmap.tobytes("png"))).convert("RGB")
    scale = dpi / 72.0
    zones_pixels: list[tuple[int, int, int, int]] = []

    for zone_texte in _zones_texte_natif(page, bbox_affiche, geometrie):
        rect_px = _bbox_emu_vers_pixels(zone_texte, bbox_affiche, scale, image.size)
        if rect_px is None:
            continue
        zones_pixels.append(rect_px)

    if zones_pixels:
        image = _nettoyer_regions_texte(image, zones_pixels)

    sortie = BytesIO()
    image.save(sortie, format="PNG")
    media_ref = f"raster{next(_compteur)}"
    media[media_ref] = MediaItem(media_ref=media_ref, donnees=sortie.getvalue(), extension="png")
    return RasterEl(bbox=bbox_affiche, media_ref=media_ref)


def nettoyer_images_fond_texte_positionne(elements_visuels: list, elements_texte: list, media: dict) -> int:
    """Efface dans les bitmaps de fond les zones où le texte Word est réinjecté."""
    zones_texte = _zones_elements_texte(elements_texte)
    if not zones_texte:
        return 0
    nettoyes = 0
    for element in elements_visuels:
        if not isinstance(element, (ImageEl, RasterEl)):
            continue
        item = media.get(element.media_ref)
        if item is None or item.extension.lower() not in {"png", "jpg", "jpeg"}:
            continue
        rects = []
        for zone in zones_texte:
            if not _bbox_appartient_zone(zone, element.bbox):
                continue
            rect = _bbox_emu_vers_pixels_auto(_etendre_bbox_simple(zone, pt_vers_emu(1.4)), element.bbox, item)
            if rect is not None:
                rects.append(rect)
        if not rects:
            continue
        try:
            image = Image.open(BytesIO(item.donnees)).convert("RGB")
        except Exception:  # noqa: BLE001
            continue
        image = _nettoyer_regions_texte(image, rects)
        sortie = BytesIO()
        image.save(sortie, format="PNG")
        media_ref = f"{element.media_ref}_notext{next(_compteur)}"
        media[media_ref] = MediaItem(media_ref=media_ref, donnees=sortie.getvalue(), extension="png")
        element.media_ref = media_ref
        nettoyes += 1
    return nettoyes


def _nettoyer_regions_texte(image: Image.Image, rects: list[tuple[int, int, int, int]]) -> Image.Image:
    if _regions_sur_fond_complexe(rects):
        dessin = ImageDraw.Draw(image)
        for rect in rects:
            dessin.rectangle(rect, fill=_couleur_fond_locale(image, rect))
        return image
    return _inpaint_regions(image, rects)


def _zones_elements_texte(elements: list) -> list[BBox]:
    zones: list[BBox] = []
    for element in elements:
        if isinstance(element, TextBox):
            zones.extend(ligne.bbox for ligne in element.lignes if _ligne_non_vide(ligne))
        elif isinstance(element, FlowParagraph):
            if element.lignes:
                zones.extend(ligne.bbox for ligne in element.lignes if _ligne_non_vide(ligne))
            elif element.texte.strip():
                zones.append(element.bbox)
    return zones


def _ligne_non_vide(ligne) -> bool:
    return any(span.texte.strip() for span in ligne.spans)


def _bbox_emu_vers_pixels_auto(
    bbox: BBox,
    origine: BBox,
    media_item: MediaItem,
) -> tuple[int, int, int, int] | None:
    try:
        image = Image.open(BytesIO(media_item.donnees))
        taille = image.size
    except Exception:  # noqa: BLE001
        return None
    scale_x = taille[0] / max(origine.largeur, 1)
    scale_y = taille[1] / max(origine.hauteur, 1)
    x0 = round((bbox.x0 - origine.x0) * scale_x)
    y0 = round((bbox.y0 - origine.y0) * scale_y)
    x1 = round((bbox.x1 - origine.x0) * scale_x)
    y1 = round((bbox.y1 - origine.y0) * scale_y)
    largeur, hauteur = taille
    x0 = max(0, min(x0, largeur - 1))
    y0 = max(0, min(y0, hauteur - 1))
    x1 = max(x0 + 1, min(x1, largeur))
    y1 = max(y0 + 1, min(y1, hauteur))
    return x0, y0, x1, y1


def _etendre_bbox_simple(bbox: BBox, marge: int) -> BBox:
    return BBox(
        max(0, bbox.x0 - marge),
        max(0, bbox.y0 - marge),
        bbox.x1 + marge,
        bbox.y1 + marge,
    )


def _regions_sur_fond_complexe(rects: list[tuple[int, int, int, int]]) -> bool:
    if len(rects) >= 12:
        return True
    hauteur_totale = sum(max(0, y1 - y0) for _x0, y0, _x1, y1 in rects)
    return hauteur_totale >= 180


def _inpaint_regions(image: Image.Image, rects: list[tuple[int, int, int, int]]) -> Image.Image:
    try:
        import cv2
        import numpy as np
    except Exception:  # noqa: BLE001
        dessin = ImageDraw.Draw(image)
        for rect in rects:
            dessin.rectangle(rect, fill=_couleur_fond_locale(image, rect))
        return image

    mask = Image.new("L", image.size, 0)
    dessin_mask = ImageDraw.Draw(mask)
    for rect in rects:
        dessin_mask.rectangle(rect, fill=255)

    mask_arr = np.asarray(mask)
    kernel = np.ones((3, 3), np.uint8)
    mask_arr = cv2.dilate(mask_arr, kernel, iterations=1)
    rgb = np.asarray(image)
    repaired = cv2.inpaint(
        cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
        mask_arr,
        3,
        cv2.INPAINT_TELEA,
    )
    return Image.fromarray(cv2.cvtColor(repaired, cv2.COLOR_BGR2RGB))


def _zones_texte_natif(page, zone: BBox, geometrie: PageGeometry) -> list[BBox]:
    zones: list[BBox] = []
    for bloc in page.get_text("dict").get("blocks", []):
        if bloc.get("type") != 0:
            continue
        for ligne in bloc.get("lines", []):
            for span in ligne.get("spans", []):
                if not span.get("text", "").strip():
                    continue
                rect = pymupdf.Rect(span.get("bbox", ligne.get("bbox", (0, 0, 0, 0))))
                bbox_span = geometrie.bbox_depuis_rect_natif(rect)
                if _bbox_texte_verticale(bbox_span, span.get("text", "")):
                    continue
                if _bbox_appartient_zone(bbox_span, zone):
                    taille = float(span.get("size", 10.0) or 10.0)
                    couleur = int(span.get("color", 0) or 0)
                    marge_pt = 2.4
                    if _couleur_presque_blanche(couleur):
                        marge_pt = max(3.5, min(9.0, taille * 0.24))
                    zones.append(_etendre_bbox(bbox_span, pt_vers_emu(marge_pt), geometrie))
    return zones


def _bbox_texte_verticale(bbox: BBox, texte: str) -> bool:
    if len((texte or "").strip()) < 3:
        return False
    return bbox.hauteur >= max(pt_vers_emu(18), bbox.largeur * 3)


def _bbox_appartient_zone(bbox: BBox, zone: BBox) -> bool:
    if not se_chevauchent(bbox, zone):
        return False
    aire = max(bbox.largeur * bbox.hauteur, 1)
    intersection = (
        max(0, min(bbox.x1, zone.x1) - max(bbox.x0, zone.x0))
        * max(0, min(bbox.y1, zone.y1) - max(bbox.y0, zone.y0))
    )
    centre_x = (bbox.x0 + bbox.x1) // 2
    centre_y = (bbox.y0 + bbox.y1) // 2
    return intersection / aire >= 0.45 or (
        zone.x0 <= centre_x <= zone.x1 and zone.y0 <= centre_y <= zone.y1
    )


def _etendre_bbox(bbox: BBox, marge: int, geometrie: PageGeometry) -> BBox:
    return BBox(
        max(0, bbox.x0 - marge),
        max(0, bbox.y0 - marge),
        min(geometrie.largeur_emu, bbox.x1 + marge),
        min(geometrie.hauteur_emu, bbox.y1 + marge),
    )


def _bbox_emu_vers_pixels(
    bbox: BBox,
    origine: BBox,
    scale: float,
    taille_image: tuple[int, int],
) -> tuple[int, int, int, int] | None:
    x0 = round(emu_vers_pt(bbox.x0 - origine.x0) * scale)
    y0 = round(emu_vers_pt(bbox.y0 - origine.y0) * scale)
    x1 = round(emu_vers_pt(bbox.x1 - origine.x0) * scale)
    y1 = round(emu_vers_pt(bbox.y1 - origine.y0) * scale)
    largeur, hauteur = taille_image
    x0 = max(0, min(x0, largeur - 1))
    y0 = max(0, min(y0, hauteur - 1))
    x1 = max(x0 + 1, min(x1, largeur))
    y1 = max(y0 + 1, min(y1, hauteur))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _couleur_fond_locale(image: Image.Image, rect: tuple[int, int, int, int]) -> tuple[int, int, int]:
    x0, y0, x1, y1 = rect
    largeur, hauteur = image.size
    marge = max(5, min(18, max(x1 - x0, y1 - y0) // 2))
    sx0 = max(0, x0 - marge)
    sy0 = max(0, y0 - marge)
    sx1 = min(largeur, x1 + marge)
    sy1 = min(hauteur, y1 + marge)
    pixels: list[tuple[int, int, int]] = []
    source = image.load()
    for y in range(sy0, sy1):
        for x in range(sx0, sx1):
            if x0 <= x < x1 and y0 <= y < y1:
                continue
            pixels.append(source[x, y])
    if not pixels:
        return (255, 255, 255)
    fond = _couleur_dominante_non_blanche(pixels)
    if fond is not None:
        return fond
    pixels.sort(key=lambda rgb: 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2])
    return pixels[len(pixels) // 2]


def _couleur_presque_blanche(couleur: int) -> bool:
    r = (couleur >> 16) & 255
    g = (couleur >> 8) & 255
    b = couleur & 255
    return r >= 238 and g >= 238 and b >= 238


def _couleur_dominante_non_blanche(pixels: list[tuple[int, int, int]]) -> tuple[int, int, int] | None:
    candidats: list[tuple[int, int, int]] = []
    for r, g, b in pixels:
        if r >= 235 and g >= 235 and b >= 235:
            continue
        luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
        saturation = max(r, g, b) - min(r, g, b)
        if luminance > 232 and saturation < 28:
            continue
        candidats.append((r, g, b))
    if not candidats:
        return None

    buckets: dict[tuple[int, int, int], list[tuple[int, int, int]]] = {}
    for rgb in candidats:
        cle = tuple((canal // 12) * 12 for canal in rgb)
        buckets.setdefault(cle, []).append(rgb)
    _cle, valeurs = max(buckets.items(), key=lambda item: len(item[1]))
    valeurs.sort()
    milieu = len(valeurs) // 2
    return (
        int(sorted(rgb[0] for rgb in valeurs)[milieu]),
        int(sorted(rgb[1] for rgb in valeurs)[milieu]),
        int(sorted(rgb[2] for rgb in valeurs)[milieu]),
    )
