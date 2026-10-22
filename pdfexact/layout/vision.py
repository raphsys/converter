"""Zone vision: what each visual zone is and whether it holds text.

Each visual zone (image or raster) is classified by type and by whether it
holds readable text: text inside images must be read (OCR) and translated,
photos and logos must not. A zone that is not understood is marked, never
guessed.
"""
from __future__ import annotations

import re

from PIL import Image

from pdfexact.geometry import PageGeometry, emu_vers_pt, pt_vers_emu
from pdfexact.ir import ImageEl, RasterEl

TYPES = ("photo", "logo", "chart", "diagram", "map", "table", "text", "formula", "decoration")
QUESTION = (
    "What is this image region? Answer with one word among: " + ", ".join(TYPES)
    + ". Then answer yes or no: does it contain readable text? Format: <word>, <yes|no>"
)
# Below this size a zone holds no readable content (rules, bullets, specks).
COTE_MIN_PT = 36.0
# Rendering resolution of a zone, longest edge in pixels: text stays legible.
COTE_RENDU_PX = 1024


def _lire_reponse(text: str):
    words = re.findall(r"[a-z]+", str(text).casefold())
    kind = next((word for word in words if word in TYPES), None)
    flag = next((word for word in words if word in {"yes", "no"}), None)
    if kind is None or flag is None:
        return None
    # Text in an image is translatable, except a logo (a brand name stays as is).
    return {"type": kind, "contains_text": flag == "yes", "translatable": flag == "yes" and kind != "logo"}


def zones_a_voir(page) -> list:
    minimum = pt_vers_emu(COTE_MIN_PT)
    return [element for element in page.elements
            if isinstance(element, (ImageEl, RasterEl))
            and element.bbox.largeur >= minimum and element.bbox.hauteur >= minimum]


def zones_texte_image(page) -> list:
    """Visual zones to read by OCR: text seen by vision, or zones not understood."""
    zones = []
    for element in page.elements:
        seen = (getattr(element, "attributes", None) or {}).get("vision")
        if isinstance(element, (ImageEl, RasterEl)) and seen and (
                seen.get("contains_text") is True or seen.get("status") == "non-compris"):
            zones.append(element.bbox)
    return zones


def _image_zone(pdf_page, element, geometry) -> Image.Image:
    import pymupdf

    rect = pymupdf.Rect(*(emu_vers_pt(value) for value in (element.bbox.x0, element.bbox.y0, element.bbox.x1, element.bbox.y1)))
    clip = geometry.rect_affiche_vers_natif(rect)
    zoom = COTE_RENDU_PX / max(clip.width, clip.height, 1.0)
    pixmap = pdf_page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False)
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def annoter_zones_visuelles(document, source_pdf, vision) -> list[dict]:
    """Classify every readable visual zone; zones not understood are marked."""
    import pymupdf

    zones = [(page, zones_a_voir(page)) for page in document.pages]
    if not any(elements for _, elements in zones):
        return []
    modele = getattr(vision, "model", None)
    rapports, vus = [], {}
    with pymupdf.open(source_pdf) as pdf:
        for page, elements in zones:
            if not elements:
                continue
            pdf_page = pdf[page.index]
            geometry = PageGeometry.depuis_page(pdf_page)
            for element in elements:
                key = (getattr(element, "media_ref", None), element.bbox)
                if key not in vus:
                    if vision is None:
                        vus[key] = {"status": "non-compris", "reason": "sans-modele-vision", "model": None}
                    else:
                        try:
                            answer = vision.repondre(_image_zone(pdf_page, element, geometry))
                            result = _lire_reponse(answer)
                            vus[key] = ({**result, "status": "compris", "model": modele} if result
                                        else {"status": "non-compris", "reason": f"unreadable-answer:{answer[:80]}", "model": modele})
                        except Exception as exc:  # noqa: BLE001 - the zone is marked, the run goes on
                            vus[key] = {"status": "non-compris", "reason": groq.raison_erreur(exc), "model": modele}
                element.attributes["vision"] = dict(vus[key])
                rapports.append({"page": page.index, **vus[key]})
    return rapports
