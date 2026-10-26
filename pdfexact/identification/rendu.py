"""PDF annotated by type: each identified box drawn in its family colour, with its type."""
from __future__ import annotations

from pathlib import Path

import pymupdf

from pdfexact.geometry import PageGeometry, preserver_etat_page

# One colour per family of the referential.
COULEURS = {
    "page": (0.45, 0.45, 0.45), "zone": (0.55, 0.35, 0.10), "texte": (0.85, 0.05, 0.05),
    "en_ligne": (0.95, 0.40, 0.55), "expression": (0.95, 0.55, 0.00), "liste": (0.80, 0.20, 0.45),
    "tableau": (0.55, 0.10, 0.70), "formule": (0.00, 0.55, 0.55), "image": (0.05, 0.25, 0.90),
    "vectoriel": (0.05, 0.55, 0.15), "visualisation": (0.20, 0.60, 0.85), "decoration": (0.40, 0.70, 0.20),
    "annotation": (0.85, 0.65, 0.05), "lien": (0.95, 0.50, 0.02), "formulaire": (0.50, 0.20, 0.20),
    "media": (0.30, 0.30, 0.65), "inconnu": (0.0, 0.0, 0.0),
}
_EPAISSEUR_PT = 0.8
_TAILLE_ETIQUETTE_PT = 5.0


def annoter_pdf_types(source_pdf, destination_pdf, resultat) -> None:
    """Copy the PDF and draw every identified box with its type as a label."""
    with pymupdf.open(source_pdf) as pdf:
        for element in resultat.elements:
            page = pdf[element.page_index]
            x, y, largeur, hauteur = element.bbox
            couleur = COULEURS.get(element.famille, COULEURS["inconnu"])
            # Boxes are in the displayed (rotated) space: read the geometry and the rotation
            # before unrotating the page to draw in its native space.
            geometrie, rotation, vers_natif = PageGeometry.depuis_page(page), page.rotation, page.derotation_matrix
            etiquette = f"{element.id} {element.type}" + ("" if element.statut == "identifie" else "?")
            with preserver_etat_page(page):
                page.set_rotation(0)
                page.draw_rect(geometrie.rect_affiche_vers_natif(pymupdf.Rect(x, y, x + largeur, y + hauteur)),
                               color=couleur, width=_EPAISSEUR_PT, overlay=True)
                # Label at the displayed top-left corner, upright for the reader.
                origine = pymupdf.Point(x + 1, y + _TAILLE_ETIQUETTE_PT) * vers_natif
                page.insert_text(origine, etiquette, fontsize=_TAILLE_ETIQUETTE_PT, color=couleur, rotate=rotation,
                                 overlay=True)
        destination = Path(destination_pdf)
        destination.parent.mkdir(parents=True, exist_ok=True)
        pdf.save(destination, garbage=4, deflate=True)
