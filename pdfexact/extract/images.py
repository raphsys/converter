"""Extraction des images bitmap.

Une même image peut être placée plusieurs fois. Elle n'est stockée qu'une fois dans
word/media/ et référencée autant de fois que nécessaire : c'est la différence entre un
docx de 2 Mo et un de 40 Mo.
"""
import hashlib

import pymupdf

from pdfexact.geometry import bbox_depuis_rect
from pdfexact.ir import ImageEl, MediaItem

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


def extraire_images(page, doc, media: dict) -> list[ImageEl]:
    """Retourne les placements d'images de la page et enrichit le registre `media`.

    get_images() liste une entrée par référence dans les ressources de page, pas par
    image : une image placée deux fois y apparaît deux fois avec le même xref. Sans la
    déduplication ci-dessous, chaque placement serait compté une fois par entrée.
    """
    elements: list[ImageEl] = []

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
            boite = bbox_depuis_rect(rect)
            if boite.largeur > 0 and boite.hauteur > 0 and not _est_artefact_image(boite):
                elements.append(ImageEl(bbox=boite, media_ref=media_ref))

    return elements


def extraire_images_rasterisees(page, doc, media: dict, dpi: int = 200) -> list[ImageEl]:
    """Capture chaque placement d'image tel qu'il est rendu sur la page.

    Contrairement à `extract_image`, cette voie respecte la matrice de placement PDF
    (rotation, retournement, recadrage). Elle est plus lourde mais adaptée au reflow, où
    la fidélité des figures/formules prime sur la déduplication binaire.
    """
    from pdfexact.fallback.rasterize import rasteriser_region

    elements: list[ImageEl] = []
    vus: set[tuple[int, int, int, int]] = set()
    for xref in sorted({entree[0] for entree in page.get_images(full=True)}):
        for rect in page.get_image_rects(xref):
            boite = bbox_depuis_rect(rect)
            cle = (boite.x0, boite.y0, boite.x1, boite.y1)
            if (
                boite.largeur <= 0
                or boite.hauteur <= 0
                or _est_artefact_image(boite)
                or cle in vus
            ):
                continue
            vus.add(cle)
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


def extraire_images_inline(
    page, media: dict, deja_posees: list[ImageEl] | None = None
) -> list[ImageEl]:
    """Extrait les gros blocs image inline visibles dans le flux PDF.

    Plusieurs PDF anciens dessinent les figures, équations ou même des bouts de texte
    avec l'opérateur PDF inline image (BI/EI). `page.get_images()` ne les liste pas.
    On ne prend ici que les blocs assez grands pour éviter de dupliquer les glyphes
    bitmap qui doivent être remplacés par du vrai texte OCR.
    """
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

    for index, bloc in enumerate(page.get_text("dict").get("blocks", []), start=1):
        if bloc.get("type") != 1:
            continue
        boite_points = tuple(float(v) for v in bloc.get("bbox", (0, 0, 0, 0)))
        if _aire(boite_points) < SEUIL_IMAGE_INLINE_PT2:
            continue
        if any(_ratio_intersection(boite_points, existante) > 0.8 for existante in boites_deja_posees):
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

        boite = bbox_depuis_rect(pymupdf.Rect(*boite_points))
        if boite.largeur > 0 and boite.hauteur > 0 and not _est_artefact_image(boite):
            elements.append(ImageEl(bbox=boite, media_ref=media_ref))

    return elements


def extraire_images_inline_rasterisees(
    page, media: dict, deja_posees: list[ImageEl] | None = None, dpi: int = 200
) -> list[ImageEl]:
    """Capture les grosses images inline telles qu'elles apparaissent sur la page.

    Les octets bruts des images inline PDF peuvent avoir une orientation interne
    différente de la matrice d'affichage. En reflow on préfère donc rasteriser la zone
    visible, comme pour les images XRef.
    """
    from pdfexact.fallback.rasterize import rasteriser_region

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
        if _aire(boite_points) < SEUIL_IMAGE_INLINE_PT2:
            continue
        if any(_ratio_intersection(boite_points, existante) > 0.8 for existante in boites_deja_posees):
            continue

        boite = bbox_depuis_rect(pymupdf.Rect(*boite_points))
        cle = (boite.x0, boite.y0, boite.x1, boite.y1)
        if (
            boite.largeur <= 0
            or boite.hauteur <= 0
            or _est_artefact_image(boite)
            or cle in vus
        ):
            continue
        vus.add(cle)
        elements.append(rasteriser_region(page, boite, media, dpi=dpi))

    return elements
