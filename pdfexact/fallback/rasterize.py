"""Repli raster.

Certaines constructions PDF — dégradés, masques non rectangulaires, modes de fusion —
n'ont pas d'équivalent DrawingML fiable. Plutôt que de produire un rendu faux, on
rastérise la région concernée, et elle seule.

Le texte n'est jamais rastérisé : il est écrit par-dessus et reste réel, sélectionnable
et cherchable, même au-dessus d'une zone d'image.
"""
import itertools
import os
import re
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

from pdfexact.geometry import BBox, PageGeometry, emu_vers_pt, pt_vers_emu, se_chevauchent
from pdfexact.ir import FlowParagraph, ImageEl, MediaItem, RasterEl, TextBox

_compteur = itertools.count(1)


@lru_cache(maxsize=2)
def _lama_session(model_path: str):
    import onnxruntime as ort

    return ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])


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


def _pdf_tokens(contenu: bytes):
    """Tokenise les opérateurs géométriques sans interpréter les chaînes PDF."""
    index = 0
    longueur = len(contenu)
    while index < longueur:
        octet = contenu[index]
        if octet in b" \t\r\n\f\x00":
            index += 1
            continue
        if octet == ord("%"):
            fin = contenu.find(b"\n", index)
            index = longueur if fin < 0 else fin + 1
            continue
        if octet == ord("("):
            profondeur = 1
            index += 1
            while index < longueur and profondeur:
                if contenu[index] == ord("\\"):
                    index += 2
                    continue
                if contenu[index] == ord("("):
                    profondeur += 1
                elif contenu[index] == ord(")"):
                    profondeur -= 1
                index += 1
            continue
        if octet == ord("<"):
            if index + 1 < longueur and contenu[index + 1] == ord("<"):
                yield "<<"
                index += 2
                continue
            fin = contenu.find(b">", index + 1)
            index = longueur if fin < 0 else fin + 1
            continue
        if octet in b"[]{}":
            yield chr(octet)
            index += 1
            continue
        debut = index
        while index < longueur and contenu[index] not in b" \t\r\n\f\x00()<>[]{}%":
            index += 1
        if debut == index:
            index += 1
            continue
        token = contenu[debut:index].decode("latin1", "ignore")
        try:
            yield float(token)
        except ValueError:
            yield token


def _bbox_union_points(points: list[tuple[float, float]]):
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_intersection(a: BBox, b: BBox) -> BBox | None:
    x0 = max(a.x0, b.x0)
    y0 = max(a.y0, b.y0)
    x1 = min(a.x1, b.x1)
    y1 = min(a.y1, b.y1)
    if x1 <= x0 or y1 <= y0:
        return None
    return BBox(x0, y0, x1, y1)


def _bbox_contenu_vers_page(page, geometrie: PageGeometry, boite) -> BBox:
    """Convertit une bbox du repère PDF bas-gauche vers le repère de page."""
    x0, y0, x1, y1 = boite
    points = [
        pymupdf.Point(x0, y0) * page.transformation_matrix,
        pymupdf.Point(x1, y0) * page.transformation_matrix,
        pymupdf.Point(x1, y1) * page.transformation_matrix,
        pymupdf.Point(x0, y1) * page.transformation_matrix,
    ]
    return geometrie.bbox_depuis_rect_natif(
        pymupdf.Rect(
            min(point.x for point in points),
            min(point.y for point in points),
            max(point.x for point in points),
            max(point.y for point in points),
        )
    )


# Path-painting operators (and "n") end the current path.
_FIN_DE_CHEMIN = {"n", "S", "s", "f", "F", "f*", "B", "B*", "b", "b*"}


def extraire_zones_shading(doc, page, geometrie: PageGeometry) -> list[BBox]:
    """Retourne les zones effectivement peintes par les shadings PDF.

    La simple présence d'une ressource ``Shading`` ne doit pas contaminer toute la
    page : cette fonction localise les opérateurs ``sh`` et leur clipping.
    """
    try:
        ressource = doc.xref_get_key(page.xref, "Resources/Shading")
    except (RuntimeError, ValueError):
        return []
    if not ressource or ressource[0] in {"null", None}:
        return []

    zones: list[BBox] = []
    identite = pymupdf.Matrix(1, 0, 0, 1, 0, 0)
    for contenu_xref in page.get_contents() or []:
        try:
            contenu = doc.xref_stream(contenu_xref)
        except (RuntimeError, ValueError):
            continue
        ctm = identite
        pile: list[tuple[pymupdf.Matrix, tuple[float, float, float, float] | None]] = []
        operandes: list[object] = []
        chemin: list[tuple[float, float]] = []
        clipping: tuple[float, float, float, float] | None = None
        inline = False

        for token in _pdf_tokens(contenu):
            if inline:
                if token == "EI":
                    inline = False
                continue
            if token == "BI":
                inline = True
                operandes.clear()
                continue
            if isinstance(token, (float, int)) or str(token).startswith("/"):
                operandes.append(token)
                continue
            if token == "q":
                pile.append((ctm, clipping))
                operandes.clear()
                continue
            if token == "Q":
                if pile:
                    ctm, clipping = pile.pop()
                chemin.clear()
                operandes.clear()
                continue
            if token == "cm" and len(operandes) >= 6:
                ctm = ctm * pymupdf.Matrix(*(float(value) for value in operandes[-6:]))
                operandes.clear()
                continue
            if token in {"m", "l"} and len(operandes) >= 2:
                point = pymupdf.Point(float(operandes[-2]), float(operandes[-1])) * ctm
                chemin.append((point.x, point.y))
                operandes.clear()
                continue
            if token == "re" and len(operandes) >= 4:
                x, y, largeur, hauteur = (float(value) for value in operandes[-4:])
                chemin.extend(
                    (point.x, point.y)
                    for point in (
                        pymupdf.Point(x, y) * ctm,
                        pymupdf.Point(x + largeur, y) * ctm,
                        pymupdf.Point(x + largeur, y + hauteur) * ctm,
                        pymupdf.Point(x, y + hauteur) * ctm,
                    )
                )
                operandes.clear()
                continue
            if token in {"W", "W*"}:
                # A nested clip narrows the current one.
                nouveau = _bbox_union_points(chemin)
                if nouveau is not None and clipping is not None:
                    nouveau = (max(nouveau[0], clipping[0]), max(nouveau[1], clipping[1]),
                               min(nouveau[2], clipping[2]), min(nouveau[3], clipping[3]))
                clipping = nouveau or clipping
                operandes.clear()
                continue
            if token in _FIN_DE_CHEMIN:
                # A painted path is finished: it must not leak into the next clip.
                chemin.clear()
                operandes.clear()
                continue
            if token != "sh" or not operandes:
                operandes.clear()
                continue

            nom = str(operandes[-1]).lstrip("/")
            try:
                reference = doc.xref_get_key(page.xref, f"Resources/Shading/{nom}")[1]
                xref = int(str(reference).split()[0])
                objet = doc.xref_object(xref, compressed=False)
            except (RuntimeError, ValueError, TypeError, IndexError):
                operandes.clear()
                continue
            correspondance = re.search(r"/Coords\s*\[([^]]+)\]", objet)
            valeurs = []
            if correspondance:
                valeurs = [
                    float(value)
                    for value in re.findall(r"[-+]?\d*\.?\d+", correspondance.group(1))
                ]
            if len(valeurs) >= 6:
                rayon0, rayon1 = abs(valeurs[2]), abs(valeurs[5])
                points_source = [
                    (valeurs[0] - rayon0, valeurs[1] - rayon0),
                    (valeurs[0] + rayon0, valeurs[1] + rayon0),
                    (valeurs[3] - rayon1, valeurs[4] - rayon1),
                    (valeurs[3] + rayon1, valeurs[4] + rayon1),
                ]
            elif len(valeurs) >= 4:
                points_source = [(valeurs[0], valeurs[1]), (valeurs[2], valeurs[3])]
            else:
                points_source = [(0.0, 0.0), (1.0, 1.0)]
            points_pdf = [pymupdf.Point(x, y) * ctm for x, y in points_source]
            boite_pdf = _bbox_union_points([(point.x, point.y) for point in points_pdf])
            if boite_pdf is None:
                operandes.clear()
                continue
            zone = _bbox_contenu_vers_page(page, geometrie, boite_pdf)
            if clipping is not None:
                clip_display = _bbox_contenu_vers_page(page, geometrie, clipping)
                if zone.hauteur <= 0 or zone.largeur <= 0:
                    zone = clip_display
                else:
                    zone = _bbox_intersection(zone, clip_display)
            if zone is not None and zone.largeur > 0 and zone.hauteur > 0:
                zones.append(zone)
            operandes.clear()

    uniques: list[BBox] = []
    for zone in zones:
        if not any(_bbox_intersection(zone, autre) == zone for autre in uniques):
            uniques.append(zone)
    return uniques


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
    purpose: str | None = None,
) -> RasterEl:
    """Rend la région indiquée en PNG et retourne l'élément qui la remplace."""
    rect = pymupdf.Rect(
        emu_vers_pt(bbox.x0),
        emu_vers_pt(bbox.y0),
        emu_vers_pt(bbox.x1),
        emu_vers_pt(bbox.y1),
    ).intersect(page.rect)
    if rect.is_empty or rect.width <= 0 or rect.height <= 0:
        return _raster_vide(bbox, media)
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
    return RasterEl(bbox=bbox_affiche, media_ref=media_ref, purpose=purpose)


def _raster_vide(bbox: BBox, media: dict) -> RasterEl:
    sortie = BytesIO()
    Image.new("RGBA", (1, 1), (255, 255, 255, 0)).save(sortie, format="PNG")
    media_ref = f"raster{next(_compteur)}"
    media[media_ref] = MediaItem(media_ref=media_ref, donnees=sortie.getvalue(), extension="png")
    return RasterEl(
        bbox=BBox(bbox.x0, bbox.y0, max(bbox.x1, bbox.x0 + 1), max(bbox.y1, bbox.y0 + 1)),
        media_ref=media_ref,
    )


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
    ajouts = []
    for element in elements_visuels:
        if not isinstance(element, (ImageEl, RasterEl)):
            continue
        if getattr(element, "purpose", None) in {"formula", "symbol"}:
            continue
        item = media.get(element.media_ref)
        if item is None or item.extension.lower() not in {"png", "jpg", "jpeg"}:
            continue
        rects = []
        for zone in zones_texte:
            # Une ligne peut traverser la frontière de deux tuiles. Toute intersection
            # doit donc être nettoyée, même si le centre de la ligne est ailleurs.
            if not se_chevauchent(zone, element.bbox):
                continue
            rect = _bbox_emu_vers_pixels_auto(_etendre_bbox_simple(zone, pt_vers_emu(1.4)), element.bbox, item)
            if rect is not None:
                rects.append(rect)
        if not rects:
            continue
        try:
            image = Image.open(BytesIO(item.donnees)).convert("RGBA")
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


def resserrer_ancres_visuelles(elements: list, media: dict) -> int:
    """Resserre les images déjà produites par les branches OCR générales."""
    ajouts = []
    modifies = 0
    for element in list(elements):
        if not isinstance(element, (ImageEl, RasterEl)):
            continue
        if getattr(element, "purpose", None) in {"formula", "symbol"}:
            continue
        item = media.get(element.media_ref)
        if item is None or item.extension.lower() not in {"png", "jpg", "jpeg"}:
            continue
        try:
            image = Image.open(BytesIO(item.donnees)).convert("RGBA")
        except Exception:  # noqa: BLE001
            continue
        segments = _segmenter_tuile_visuelle(image, element.bbox)
        for indice, (segment, bbox) in enumerate(segments):
            sortie = BytesIO()
            segment.save(sortie, format="PNG")
            media_ref = f"{element.media_ref}_tight{next(_compteur)}"
            media[media_ref] = MediaItem(media_ref, sortie.getvalue(), "png")
            if indice == 0:
                element.media_ref = media_ref
                element.bbox = bbox
            elif isinstance(element, RasterEl):
                ajouts.append(RasterEl(bbox=bbox, media_ref=media_ref, purpose=element.purpose))
            else:
                ajouts.append(ImageEl(bbox=bbox, media_ref=media_ref))
            modifies += 1
    elements.extend(ajouts)
    return modifies


def nettoyer_image_page_depuis_source(
    page,
    elements_visuels: list,
    elements_texte: list,
    media: dict,
    dpi: int = 300,
    geometrie: PageGeometry | None = None,
) -> int:
    """Efface le texte OCR de l'image pleine page d'une page numerisee.

    On rend la page complete, on inpaint les boites OCR avec leur contexte voisin,
    puis on separe l'image nettoyee en ses composants visuels reels.
    """
    zones = _zones_elements_texte(elements_texte)
    if not zones:
        return 0
    geometrie = geometrie or PageGeometry.depuis_page(page)
    page_bbox = BBox(0, 0, geometrie.largeur_emu, geometrie.hauteur_emu)
    pixmap = page.get_pixmap(dpi=max(dpi, 150), alpha=False)
    image = Image.open(BytesIO(pixmap.tobytes("png"))).convert("RGB")
    # Le convertisseur de coordonnees ne lit que la taille de l'image.
    source = MediaItem("__page_source__", pixmap.tobytes("png"), "png")
    rects = []
    for zone in zones:
        rect = _bbox_emu_vers_pixels_auto(
            _etendre_bbox_inpainting(zone),
            page_bbox,
            source,
        )
        if rect is not None:
            rects.append(rect)
    if not rects:
        return 0
    image = _inpaint_regions(image, rects)

    tuiles = [page_bbox]
    nettoyes = 0
    ajouts = []
    for element in elements_visuels:
        if not isinstance(element, (ImageEl, RasterEl)):
            continue
        tuile = next(
            (
                zone
                for zone in tuiles
                if abs(zone.x0 - element.bbox.x0) <= pt_vers_emu(2)
                and abs(zone.y0 - element.bbox.y0) <= pt_vers_emu(2)
                and abs(zone.x1 - element.bbox.x1) <= pt_vers_emu(2)
                and abs(zone.y1 - element.bbox.y1) <= pt_vers_emu(2)
            ),
            None,
        )
        if tuile is None:
            continue
        rect = _bbox_emu_vers_pixels_auto(tuile, page_bbox, source)
        if rect is None:
            continue
        segments = _segmenter_tuile_visuelle(image.crop(rect), tuile)
        for indice, (tuile_image, tuile_bbox) in enumerate(segments):
            sortie = BytesIO()
            tuile_image.save(sortie, format="PNG")
            media_ref = f"{element.media_ref}_pageclean{next(_compteur)}"
            media[media_ref] = MediaItem(media_ref, sortie.getvalue(), "png")
            if indice == 0:
                element.media_ref = media_ref
                element.bbox = tuile_bbox
            elif isinstance(element, RasterEl):
                ajouts.append(RasterEl(bbox=tuile_bbox, media_ref=media_ref, purpose=element.purpose))
            else:
                ajouts.append(ImageEl(bbox=tuile_bbox, media_ref=media_ref))
            nettoyes += 1
    elements_visuels.extend(ajouts)
    return nettoyes


def _nettoyer_regions_texte(image: Image.Image, rects: list[tuple[int, int, int, int]]) -> Image.Image:
    return _inpaint_regions(image, rects)


def _zones_elements_texte(elements: list) -> list[BBox]:
    zones: list[BBox] = []
    for element in elements:
        if isinstance(element, TextBox):
            zones.extend(
                ligne.bbox
                for ligne in element.lignes
                if _ligne_inpainting_autorisee(ligne)
            )
        elif isinstance(element, FlowParagraph):
            if element.lignes:
                zones.extend(
                    ligne.bbox
                    for ligne in element.lignes
                    if _ligne_inpainting_autorisee(ligne)
                )
            elif _texte_inpainting_autorise(element.texte, element.bbox):
                zones.append(element.bbox)
    return zones


def _texte_inpainting_autorise(texte: str, bbox: BBox) -> bool:
    """Autorise l'effacement seulement pour un texte natif exploitable."""
    compact = re.sub(r"\s+", "", texte or "")
    if len(compact) < 2 or not any(car.isalnum() for car in compact):
        return False
    # Une boite quasi pleine page signale une mauvaise segmentation OCR : elle ne
    # doit jamais devenir un masque qui efface le bitmap entier.
    if bbox.largeur >= pt_vers_emu(500) and bbox.hauteur >= pt_vers_emu(100):
        return False
    return True


def _ligne_inpainting_autorisee(ligne) -> bool:
    texte = "".join(span.texte for span in ligne.spans)
    return _texte_inpainting_autorise(texte, ligne.bbox)


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


def _etendre_bbox_inpainting(bbox: BBox) -> BBox:
    """Marge minimale autour des glyphes, sans absorber les décorations voisines."""
    marge_x = max(pt_vers_emu(0.6), min(pt_vers_emu(2.0), int(bbox.largeur * 0.025)))
    marge_y = max(pt_vers_emu(0.6), min(pt_vers_emu(1.2), int(bbox.hauteur * 0.05)))
    return BBox(
        max(0, bbox.x0 - marge_x),
        max(0, bbox.y0 - marge_y),
        bbox.x1 + marge_x,
        bbox.y1 + marge_y,
    )


def _recadrer_tuile_visuelle(image: Image.Image, tuile: BBox) -> tuple[Image.Image, BBox]:
    """Retire les marges blanches d'une tuile sans toucher aux fonds pleins."""
    try:
        import numpy as np
    except Exception:  # noqa: BLE001
        return image, tuile
    pixels = np.asarray(image.convert("RGBA"))
    rgb = pixels[:, :, :3]
    if pixels.ndim != 3 or pixels.shape[0] < 8 or pixels.shape[1] < 8:
        return image, tuile
    masque = np.min(rgb, axis=2) < 238
    seuil_x = max(2, int(pixels.shape[0] * 0.006))
    seuil_y = max(2, int(pixels.shape[1] * 0.006))
    lignes = np.flatnonzero(masque.sum(axis=1) >= seuil_x)
    colonnes = np.flatnonzero(masque.sum(axis=0) >= seuil_y)
    if not len(lignes) or not len(colonnes):
        # Une tuile blanche ne doit pas conserver une grande ancre vide.
        # On garde seulement un pixel transparent au point d'origine.
        return Image.new("RGBA", (1, 1), (255, 255, 255, 0)), BBox(
            tuile.x0,
            tuile.y0,
            tuile.x0 + 1,
            tuile.y0 + 1,
        )
    y0, y1 = int(lignes[0]), int(lignes[-1] + 1)
    x0, x1 = int(colonnes[0]), int(colonnes[-1] + 1)
    x0, y0 = max(0, x0 - 2), max(0, y0 - 2)
    x1, y1 = min(image.width, x1 + 2), min(image.height, y1 + 2)
    if (x1 - x0) * (y1 - y0) >= image.width * image.height * 0.86:
        return image, tuile
    bbox = BBox(
        tuile.x0 + (tuile.largeur * x0) // image.width,
        tuile.y0 + (tuile.hauteur * y0) // image.height,
        tuile.x0 + (tuile.largeur * x1) // image.width,
        tuile.y0 + (tuile.hauteur * y1) // image.height,
    )
    return image.crop((x0, y0, x1, y1)), bbox


def _segmenter_tuile_visuelle(
    image: Image.Image,
    tuile: BBox,
) -> list[tuple[Image.Image, BBox]]:
    """Sépare les composants visuels éloignés d'une même tuile.

    Une tuile peut contenir, par exemple, une bordure à droite et un trait en bas.
    Leur union produirait une grande ancre vide entre les deux. Les composants sont
    donc exportés séparément avec transparence hors de leur masque.
    """
    try:
        import cv2
        import numpy as np
    except Exception:  # noqa: BLE001
        recadree, bbox = _recadrer_tuile_visuelle(image, tuile)
        return [(recadree, bbox)]

    rgba_source = np.asarray(image.convert("RGBA"))
    rgb = rgba_source[:, :, :3]
    alpha_source = rgba_source[:, :, 3]
    if rgb.ndim != 3 or rgb.shape[0] < 4 or rgb.shape[1] < 4:
        return [(image, tuile)]
    minimum = np.min(rgb, axis=2)
    contraste = np.max(rgb, axis=2) - minimum
    masque = ((minimum < 225) | ((contraste > 28) & (minimum < 245))).astype("uint8")
    # Les traits de bord de page ne doivent pas relier un élément au bord
    # opposé de la tuile et créer une ancre artificiellement grande.
    bordure = min(3, max(1, min(rgb.shape[0], rgb.shape[1]) // 40))
    masque[:bordure, :] = 0
    masque[-bordure:, :] = 0
    masque[:, :bordure] = 0
    masque[:, -bordure:] = 0
    masque = cv2.morphologyEx(masque, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    masque = cv2.morphologyEx(masque, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    masque = cv2.dilate(masque, np.ones((7, 7), np.uint8), iterations=1)
    nombre, labels, stats, _ = cv2.connectedComponentsWithStats(masque, connectivity=8)
    composantes: list[tuple[int, int, int, int]] = []
    for indice in range(1, nombre):
        x, y, largeur, hauteur, aire = stats[indice]
        if aire >= 8 or largeur >= max(5, rgb.shape[1] // 20) or hauteur >= max(5, rgb.shape[0] // 20):
            composantes.append((int(x), int(y), int(largeur), int(hauteur)))
    if not composantes:
        return _segmenter_tuile_vide(tuile)

    segments: list[tuple[Image.Image, BBox]] = []
    for x, y, largeur, hauteur in composantes:
        x0, y0 = max(0, x - 2), max(0, y - 2)
        x1, y1 = min(rgb.shape[1], x + largeur + 2), min(rgb.shape[0], y + hauteur + 2)
        alpha = (labels[y0:y1, x0:x1] > 0).astype("uint8") * 255
        alpha = cv2.dilate(alpha, np.ones((3, 3), np.uint8), iterations=1)
        alpha = np.minimum(alpha, alpha_source[y0:y1, x0:x1])
        rgba = np.dstack((rgb[y0:y1, x0:x1], alpha))
        bbox = BBox(
            tuile.x0 + (tuile.largeur * x0) // image.width,
            tuile.y0 + (tuile.hauteur * y0) // image.height,
            tuile.x0 + (tuile.largeur * x1) // image.width,
            tuile.y0 + (tuile.hauteur * y1) // image.height,
        )
        segments.append((Image.fromarray(rgba, mode="RGBA"), bbox))
    return segments


def _segmenter_tuile_vide(tuile: BBox) -> list[tuple[Image.Image, BBox]]:
    return [
        (
            Image.new("RGBA", (1, 1), (255, 255, 255, 0)),
            BBox(tuile.x0, tuile.y0, tuile.x0 + 1, tuile.y0 + 1),
        )
    ]


def _inpaint_regions(image: Image.Image, rects: list[tuple[int, int, int, int]]) -> Image.Image:
    try:
        import cv2
        import numpy as np
    except Exception:  # noqa: BLE001
        dessin = ImageDraw.Draw(image)
        for rect in rects:
            dessin.rectangle(rect, fill=_couleur_fond_locale(image, rect))
        return image

    if not rects:
        return image

    # Reprend la stratégie VYSI : patches locaux, contexte conservé, puis
    # recomposition dans l'image originale. Un inpainting plein-page dilue les
    # détails et salit les zones éloignées du texte.
    model_roots = [
        Path(os.environ["BACKGROUND_INPAINT_MODELS_ROOT"])
        if os.environ.get("BACKGROUND_INPAINT_MODELS_ROOT")
        else None,
        Path("/home/raphael/Mes_Projets/vysi/ai_models/inpainting"),
        Path(__file__).resolve().parents[2] / "ai_models" / "inpainting",
    ]
    model = next(
        (
            root / relative
            for root in model_roots
            if root is not None
            for relative in (Path("lama/lama_fp32.onnx"), Path("lama/model.onnx"), Path("lama.onnx"))
            if (root / relative).is_file()
        ),
        None,
    )
    preserve_alpha = "A" in image.getbands()
    rgba = np.asarray(image.convert("RGBA"))
    rgb = rgba[:, :, :3]
    alpha = rgba[:, :, 3].copy()
    sortie = rgb.copy()
    groupes = _fusionner_rects_inpainting(rects, max(6, min(18, image.width // 80)))
    backend_lama = model is not None and len(groupes) <= 12

    for x0, y0, x1, y1 in groupes:
        largeur = max(1, x1 - x0)
        hauteur = max(1, y1 - y0)
        marge = max(10, min(48, int(max(largeur, hauteur) * 0.16)))
        cx0, cy0 = max(0, x0 - marge), max(0, y0 - marge)
        cx1, cy1 = min(image.width, x1 + marge), min(image.height, y1 + marge)
        local = sortie[cy0:cy1, cx0:cx1].copy()
        masque = np.zeros((cy1 - cy0, cx1 - cx0), dtype=np.uint8)
        masque[max(0, y0 - cy0):min(cy1 - cy0, y1 - cy0), max(0, x0 - cx0):min(cx1 - cx0, x1 - cx0)] = 255
        masque = cv2.dilate(masque, np.ones((3, 3), np.uint8), iterations=1)
        local_image = Image.fromarray(local, mode="RGB")
        local_mask = Image.fromarray(masque, mode="L")
        pixels_fond = local[masque == 0]
        dominante = None
        dominante_ratio = 0.0
        if len(pixels_fond) > 32:
            buckets = {}
            for pixel in pixels_fond:
                cle = tuple((int(canal) // 18) * 18 for canal in pixel)
                buckets.setdefault(cle, []).append(pixel)
            valeurs = max(buckets.values(), key=len)
            dominante_ratio = len(valeurs) / len(pixels_fond)
            dominante = tuple(
                int(np.median(np.asarray(valeurs)[:, canal])) for canal in range(3)
            )
        fond_uniforme = (
            len(pixels_fond) > 32
            and float(np.std(pixels_fond, axis=0).max()) < 9.0
        )
        fond_majoritaire = (
            dominante is not None
            and dominante_ratio >= 0.72
            and float(np.std(np.asarray(valeurs), axis=0).max()) < 12.0
        )
        ratio_masque = float(np.count_nonzero(masque)) / max(masque.size, 1)
        grande_zone = (
            largeur >= local.shape[1] * 0.35
            or hauteur >= local.shape[0] * 0.45
        )
        utiliser_lama = (
            backend_lama
            and not fond_majoritaire
            and not fond_uniforme
        )
        try:
            if fond_majoritaire:
                local[masque > 0] = dominante
                local_image = Image.fromarray(local, mode="RGB")
            elif utiliser_lama:
                local_image = _lama_inpaint_local(local_image, local_mask, model)
            else:
                rayon = max(3, min(7, int(min(local_image.size) * 0.025)))
                repaired = cv2.inpaint(
                    cv2.cvtColor(local, cv2.COLOR_RGB2BGR),
                    masque,
                    rayon,
                    cv2.INPAINT_TELEA,
                )
                local_image = Image.fromarray(cv2.cvtColor(repaired, cv2.COLOR_BGR2RGB))
        except Exception:
            repaired = cv2.inpaint(
                cv2.cvtColor(local, cv2.COLOR_RGB2BGR),
                masque,
                3,
                cv2.INPAINT_TELEA,
            )
            local_image = Image.fromarray(cv2.cvtColor(repaired, cv2.COLOR_BGR2RGB))
        sortie[cy0:cy1, cx0:cx1] = np.asarray(local_image.convert("RGB"))
    if preserve_alpha:
        return Image.fromarray(np.dstack((sortie, alpha)), mode="RGBA")
    return Image.fromarray(sortie, mode="RGB")


def _fusionner_rects_inpainting(
    rects: list[tuple[int, int, int, int]],
    ecart: int,
) -> list[tuple[int, int, int, int]]:
    """Fusionne seulement les masques voisins qui partagent le même contexte."""
    groupes: list[list[int]] = []
    for rect in sorted(rects, key=lambda value: (value[1], value[0])):
        x0, y0, x1, y1 = rect
        cible = None
        for groupe in groupes:
            gx0, gy0, gx1, gy1 = groupe
            horizontal = x0 <= gx1 + ecart and x1 >= gx0 - ecart
            vertical = y0 <= gy1 + ecart and y1 >= gy0 - ecart
            if horizontal and vertical:
                cible = groupe
                break
        if cible is None:
            groupes.append([x0, y0, x1, y1])
        else:
            cible[0] = min(cible[0], x0)
            cible[1] = min(cible[1], y0)
            cible[2] = max(cible[2], x1)
            cible[3] = max(cible[3], y1)
    return [tuple(groupe) for groupe in groupes]


def _lama_inpaint_local(image: Image.Image, mask: Image.Image, model: Path) -> Image.Image:
    import numpy as np

    session = _lama_session(str(model))
    inputs = session.get_inputs()
    resized_image = image.resize((512, 512), Image.Resampling.LANCZOS)
    resized_mask = mask.resize((512, 512), Image.Resampling.NEAREST)
    image_arr = np.asarray(resized_image).astype("float32").transpose(2, 0, 1)[None] / 255.0
    mask_arr = np.asarray(resized_mask).astype("float32")[None, None] / 255.0
    output = session.run(None, {inputs[0].name: image_arr, inputs[1].name: mask_arr})[0][0]
    output = output.transpose(1, 2, 0)
    if float(output.max()) <= 1.5:
        output = output * 255.0
    output = output.clip(0, 255).astype("uint8")
    repaired = Image.fromarray(output, mode="RGB").resize(image.size, Image.Resampling.LANCZOS)
    return Image.composite(repaired, image, mask)


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
                    marge_pt = 1.0
                    if _couleur_presque_blanche(couleur):
                        marge_pt = max(0.8, min(1.5, taille * 0.06))
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
    if not pixels:
        return None

    buckets: dict[tuple[int, int, int], list[tuple[int, int, int]]] = {}
    for rgb in pixels:
        cle = tuple((canal // 18) * 18 for canal in rgb)
        buckets.setdefault(cle, []).append(rgb)
    _cle, valeurs = max(buckets.items(), key=lambda item: len(item[1]))
    valeurs.sort()
    milieu = len(valeurs) // 2
    return (
        int(sorted(rgb[0] for rgb in valeurs)[milieu]),
        int(sorted(rgb[1] for rgb in valeurs)[milieu]),
        int(sorted(rgb[2] for rgb in valeurs)[milieu]),
    )
