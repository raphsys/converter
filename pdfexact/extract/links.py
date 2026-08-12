"""Liens.

Deux formes coexistent, et le partage est net : un lien qui recouvre du texte est porté
par les spans concernés et devient un `w:hyperlink` ; un lien qui ne recouvre aucun texte
devient une forme rectangulaire invisible cliquable.
"""
import pymupdf

from pdfexact.geometry import bbox_depuis_rect, se_chevauchent
from pdfexact.ir import LinkZone


def appliquer_liens(page, blocs) -> list[LinkZone]:
    """Pose les liens sur les spans recouverts, retourne les liens de zone restants."""
    zones: list[LinkZone] = []

    for lien in page.get_links():
        boite = bbox_depuis_rect(pymupdf.Rect(lien["from"]))
        uri = lien.get("uri")
        page_cible = lien.get("page") if lien.get("kind") == pymupdf.LINK_GOTO else None
        if page_cible is not None and page_cible < 0:
            page_cible = None

        recouvre_du_texte = False
        if uri:
            for bloc in blocs:
                if not se_chevauchent(bloc.bbox, boite):
                    continue
                for ligne in bloc.lignes:
                    if not se_chevauchent(ligne.bbox, boite):
                        continue
                    for span in ligne.spans:
                        span.lien = uri
                        recouvre_du_texte = True

        if not recouvre_du_texte:
            zones.append(LinkZone(bbox=boite, uri=uri, page_cible=page_cible))

    return zones
