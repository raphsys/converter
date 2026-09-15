"""Extraction des images bitmap.

Une même image peut être placée plusieurs fois. Elle n'est stockée qu'une fois dans
word/media/ et référencée autant de fois que nécessaire : c'est la différence entre un
docx de 2 Mo et un de 40 Mo.
"""
import hashlib
from io import BytesIO

import pymupdf
from PIL import Image

from pdfexact.geometry import BBox, PageGeometry, bbox_depuis_rect
from pdfexact.ir import ImageEl, MediaItem, RasterEl

EXTENSIONS_SUPPORTEES = {"png", "jpeg", "jpg"}
SEUIL_IMAGE_INLINE_PT2 = 1500.0


def _est_artefact_image(boite) -> bool:
    """Écarte les pseudo-images qui ne sont que des filets ou des fragments de bordure."""
    largeur_pt = boite.largeur / 12700.0
    hauteur_pt = boite.hauteur / 12700.0
    if largeur_pt < 4 or hauteur_pt < 4:
        return True
    if largeur_pt < 12 and hauteur_pt > 40:
        return True
    if hauteur_pt < 12 and largeur_pt > 150:
        return True
    return False


def _octets_et_extension(doc, xref) -> tuple[bytes, str]:
    """Retourne les octets de l'image, en la transcodant en PNG si le format est exotique."""
    extrait = doc.extract_image(xref)
    extension = extrait["ext"].lower()
    if extension in EXTENSIONS_SUPPORTEES:
        return extrait["image"], extension

    # JPX, JBIG2, CCITT… : formats que Word ne sait pas lire. On repasse par un PNG.
    pixmap = pymupdf.Pixmap(doc, xref)
    if pixmap.n - pixmap.alpha >= 4:
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
    return pixmap.tobytes("png"), "png"


def _bbox_image(rect, geometrie: PageGeometry | None = None):
    if geometrie is None:
        return bbox_depuis_rect(rect)
    return geometrie.bbox_depuis_rect_natif(rect)


def extraire_images(page, doc, media: dict, geometrie: PageGeometry | None = None) -> list[ImageEl]:
    """Retourne les placements d'images de la page et enrichit le registre `media`.

    get_images() liste une entrée par référence dans les ressources de page, pas par
    image : une image placée deux fois y apparaît deux fois avec le même xref. Sans la
    déduplication ci-dessous, chaque placement serait compté une fois par entrée.
    """
    elements: list[ImageEl | RasterEl] = []

    for xref in sorted({entree[0] for entree in page.get_images(full=True)}):
        media_ref = f"image{xref}"

        if media_ref not in media:
            try:
                octets, extension = _octets_et_extension(doc, xref)
            except Exception:  # noqa: BLE001 — une image illisible ne doit pas tout arrêter
                continue
            media[media_ref] = MediaItem(
                media_ref=media_ref, donnees=octets, extension=extension
            )

        for rect in page.get_image_rects(xref):
            boite = _bbox_image(rect, geometrie)
            if boite.largeur > 0 and boite.hauteur > 0 and not _est_artefact_image(boite):
                elements.append(ImageEl(bbox=boite, media_ref=media_ref))

    return elements


def extraire_images_rasterisees(
    page,
    doc,
    media: dict,
    dpi: int = 200,
    geometrie: PageGeometry | None = None,
    supprimer_texte_natif: bool = False,
) -> list[ImageEl | RasterEl]:
    """Capture chaque placement d'image tel qu'il est rendu sur la page.

    Contrairement à `extract_image`, cette voie respecte la matrice de placement PDF
    (rotation, retournement, recadrage). Elle est plus lourde mais adaptée au reflow, où
    la fidélité des figures/formules prime sur la déduplication binaire.
    """
    from pdfexact.fallback.rasterize import rasteriser_region, rasteriser_region_sans_texte

    elements: list[ImageEl | RasterEl] = []
    vus: set[tuple[int, int, int, int]] = set()
    for xref in sorted({entree[0] for entree in page.get_images(full=True)}):
        for rect in page.get_image_rects(xref):
            boite = _bbox_image(rect, geometrie)
            cle = (boite.x0, boite.y0, boite.x1, boite.y1)
            if (
                boite.largeur <= 0
                or boite.hauteur <= 0
                or _est_artefact_image(boite)
                or cle in vus
            ):
                continue
            vus.add(cle)
            if supprimer_texte_natif and _zone_contient_texte_natif(page, boite, geometrie):
                try:
                    octets_test, _extension_test = _octets_et_extension(doc, xref)
                except Exception:  # noqa: BLE001
                    octets_test = None
                if _image_ressemble_fragment_texte_octets(octets_test, boite, page, geometrie):
                    continue
            if supprimer_texte_natif:
                elements.append(rasteriser_region_sans_texte(page, boite, media, dpi=dpi, geometrie=geometrie))
            else:
                elements.append(rasteriser_region(page, boite, media, dpi=dpi))
    return elements


def _aire(boite) -> float:
    x0, y0, x1, y1 = boite
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _ratio_intersection(a, b) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    x0 = max(ax0, bx0)
    y0 = max(ay0, by0)
    x1 = min(ax1, bx1)
    y1 = min(ay1, by1)
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    aire = _aire(a)
    return intersection / aire if aire else 0.0


def _bbox_intersection(a: BBox, b: BBox) -> int:
    x0 = max(a.x0, b.x0)
    y0 = max(a.y0, b.y0)
    x1 = min(a.x1, b.x1)
    y1 = min(a.y1, b.y1)
    return max(0, x1 - x0) * max(0, y1 - y0)


def _bbox_source_ratio(a: BBox, b: BBox) -> float:
    return _bbox_intersection(a, b) / max(a.largeur * a.hauteur, 1)


def _zone_contient_texte_natif(page, zone: BBox, geometrie: PageGeometry | None, minimum: int = 2) -> bool:
    geometrie = geometrie or PageGeometry.depuis_page(page)
    touches = 0
    for bloc in page.get_text("dict").get("blocks", []):
        if bloc.get("type") != 0:
            continue
        for ligne in bloc.get("lines", []):
            texte = "".join(span.get("text", "") for span in ligne.get("spans", [])).strip()
            if not texte:
                continue
            bbox = geometrie.bbox_depuis_rect_natif(pymupdf.Rect(ligne.get("bbox", (0, 0, 0, 0))))
            centre_x = (bbox.x0 + bbox.x1) // 2
            centre_y = (bbox.y0 + bbox.y1) // 2
            if zone.x0 <= centre_x <= zone.x1 and zone.y0 <= centre_y <= zone.y1:
                touches += 1
            elif _bbox_source_ratio(bbox, zone) >= 0.45:
                touches += 1
            if touches >= minimum:
                return True
    return False


def _image_inline_ressemble_fragment_texte(bloc: dict, boite: BBox, page, geometrie: PageGeometry | None) -> bool:
    """Détecte les images inline qui ne sont qu'une capture parasite de texte déjà natif."""
    return _image_ressemble_fragment_texte_octets(
        bloc.get("image"),
        boite,
        page,
        geometrie,
    )


def _image_ressemble_fragment_texte_octets(
    donnees: bytes | None,
    boite: BBox,
    page,
    geometrie: PageGeometry | None,
) -> bool:
    """Détecte les images qui ne sont qu'une capture parasite de texte déjà natif."""
    largeur_pt = boite.largeur / 12700.0
    hauteur_pt = boite.hauteur / 12700.0
    aire_pt2 = largeur_pt * hauteur_pt
    if aire_pt2 > 18000 or largeur_pt > 190 or hauteur_pt > 170:
        return False
    if not _zone_contient_texte_natif(page, boite, geometrie, minimum=2):
        return False

    if not donnees:
        return False
    try:
        image = Image.open(BytesIO(donnees)).convert("RGB")
        image.thumbnail((96, 96))
    except Exception:  # noqa: BLE001
        return False

    pixels = list(image.getdata())
    if not pixels:
        return False
    blancs_gris = 0
    colores = 0
    for r, g, b in pixels:
        ecart = max(r, g, b) - min(r, g, b)
        luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
        if luminance >= 210 and ecart <= 28:
            blancs_gris += 1
        if ecart >= 45 and luminance <= 235:
            colores += 1
    total = len(pixels)
    return blancs_gris / total >= 0.90 and colores / total <= 0.04


def extraire_images_inline(
    page,
    media: dict,
    deja_posees: list[ImageEl] | None = None,
    geometrie: PageGeometry | None = None,
) -> list[ImageEl | RasterEl]:
    """Extrait les gros blocs image inline visibles dans le flux PDF.

    Plusieurs PDF anciens dessinent les figures, équations ou même des bouts de texte
    avec l'opérateur PDF inline image (BI/EI). `page.get_images()` ne les liste pas.
    On ne prend ici que les blocs assez grands pour éviter de dupliquer les glyphes
    bitmap qui doivent être remplacés par du vrai texte OCR.
    """
    elements: list[ImageEl | RasterEl] = []
    boites_deja_posees = [
        (
            image.bbox.x0 / 12700.0,
            image.bbox.y0 / 12700.0,
            image.bbox.x1 / 12700.0,
            image.bbox.y1 / 12700.0,
        )
        for image in (deja_posees or [])
    ]

    for index, bloc in enumerate(page.get_text("dict").get("blocks", []), start=1):
        if bloc.get("type") != 1:
            continue
        boite_points = tuple(float(v) for v in bloc.get("bbox", (0, 0, 0, 0)))
        boite = _bbox_image(pymupdf.Rect(*boite_points), geometrie)
        boite_affiche_points = (
            boite.x0 / 12700.0,
            boite.y0 / 12700.0,
            boite.x1 / 12700.0,
            boite.y1 / 12700.0,
        )
        if _aire(boite_affiche_points) < SEUIL_IMAGE_INLINE_PT2:
            continue
        if any(_ratio_intersection(boite_affiche_points, existante) > 0.8 for existante in boites_deja_posees):
            continue

        donnees = bloc.get("image")
        extension = (bloc.get("ext") or "png").lower()
        if not donnees:
            continue
        if extension not in EXTENSIONS_SUPPORTEES:
            extension = "png"

        empreinte = hashlib.sha1(donnees).hexdigest()[:16]
        media_ref = f"inline{page.number + 1}_{index}_{empreinte}"
        if media_ref not in media:
            media[media_ref] = MediaItem(
                media_ref=media_ref, donnees=donnees, extension=extension
            )

        if boite.largeur > 0 and boite.hauteur > 0 and not _est_artefact_image(boite):
            elements.append(ImageEl(bbox=boite, media_ref=media_ref))

    return elements


def extraire_images_inline_rasterisees(
    page,
    media: dict,
    deja_posees: list[ImageEl] | None = None,
    dpi: int = 200,
    geometrie: PageGeometry | None = None,
    supprimer_texte_natif: bool = False,
) -> list[ImageEl | RasterEl]:
    """Capture les grosses images inline telles qu'elles apparaissent sur la page.

    Les octets bruts des images inline PDF peuvent avoir une orientation interne
    différente de la matrice d'affichage. En reflow on préfère donc rasteriser la zone
    visible, comme pour les images XRef.
    """
    from pdfexact.fallback.rasterize import rasteriser_region, rasteriser_region_sans_texte

    elements: list[ImageEl] = []
    boites_deja_posees = [
        (
            image.bbox.x0 / 12700.0,
            image.bbox.y0 / 12700.0,
            image.bbox.x1 / 12700.0,
            image.bbox.y1 / 12700.0,
        )
        for image in (deja_posees or [])
    ]
    vus: set[tuple[int, int, int, int]] = set()

    for bloc in page.get_text("dict").get("blocks", []):
        if bloc.get("type") != 1:
            continue
        boite_points = tuple(float(v) for v in bloc.get("bbox", (0, 0, 0, 0)))
        boite = _bbox_image(pymupdf.Rect(*boite_points), geometrie)
        boite_affiche_points = (
            boite.x0 / 12700.0,
            boite.y0 / 12700.0,
            boite.x1 / 12700.0,
            boite.y1 / 12700.0,
        )
        if _aire(boite_affiche_points) < SEUIL_IMAGE_INLINE_PT2:
            continue
        if any(_ratio_intersection(boite_affiche_points, existante) > 0.8 for existante in boites_deja_posees):
            continue

        cle = (boite.x0, boite.y0, boite.x1, boite.y1)
        if (
            boite.largeur <= 0
            or boite.hauteur <= 0
            or _est_artefact_image(boite)
            or cle in vus
        ):
            continue
        if supprimer_texte_natif and _image_inline_ressemble_fragment_texte(bloc, boite, page, geometrie):
            continue
        vus.add(cle)
        if supprimer_texte_natif:
            elements.append(rasteriser_region_sans_texte(page, boite, media, dpi=dpi, geometrie=geometrie))
        else:
            elements.append(rasteriser_region(page, boite, media, dpi=dpi))

    return elements
