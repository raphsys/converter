"""Construit le document IR des textes natifs d'un PDF pour les outils bbox."""
from __future__ import annotations

from pathlib import Path
from hashlib import sha256
from contextlib import nullcontext

import pymupdf

from pdfexact.extract.catalog import construire_catalogue, enregistrer_catalogue
from pdfexact.extract.fonts import collecter_polices
from pdfexact.extract.text import dedoublonner_textboxes_paragraphes, extraire_texte
from pdfexact.fontlib import construire, dossiers_par_defaut
from pdfexact.geometry import PageGeometry
from pdfexact.ir import Document, Page, element_source_ids
from pdfexact.scene import capture_source_observations, record_source_transformation, scene_from_legacy_document
from pdfexact.layout.text_comprehension import (
    configurer_fournisseur_comprehension_texte,
    contexte_comprehension_texte,
)
from pdfexact.layout.text_comprehension_ai import creer_fournisseur_comprehension_texte_ai


def pages_depuis_expression(expression: str | None) -> list[int] | None:
    if not expression:
        return None
    selected: list[int] = []
    for token in expression.split(","):
        token = token.strip()
        if "-" in token:
            start, end = (int(part) for part in token.split("-", 1))
            selected.extend(range(start - 1, end))
        else:
            selected.append(int(token) - 1)
    return selected


def extraire_document_texte_natif(
    source_pdf: str | Path,
    *,
    pages: list[int] | None = None,
    catalog_path: str | Path | None = None,
    text_understanding_ai: bool = False,
    text_understanding_url: str | None = None,
    text_understanding_timeout: float = 3.0,
    model_root: str | Path | None = None,
    reuse_text_understanding_context: bool = False,
) -> Document:
    """Extrait les blocs natifs et restaure le contexte de son appelant.

    Avec reuse=True, le fournisseur reste celui deja configure par l'appelant;
    les options de configuration ne s'appliquent qu'au mode autonome.
    """
    scope = nullcontext() if reuse_text_understanding_context else contexte_comprehension_texte()
    with scope:
        if not reuse_text_understanding_context:
            configurer_fournisseur_comprehension_texte(
                creer_fournisseur_comprehension_texte_ai(
                    url=text_understanding_url,
                    timeout=text_understanding_timeout,
                    model_root=model_root,
                ),
                annoncer=True,
            )
        return _extraire_document_texte_natif(
            source_pdf, pages=pages, catalog_path=catalog_path,
            text_understanding_ai=text_understanding_ai,
        )


def _extraire_document_texte_natif(
    source_pdf: str | Path,
    *,
    pages: list[int] | None,
    catalog_path: str | Path | None,
    text_understanding_ai: bool,
) -> Document:
    pdf = pymupdf.open(source_pdf)
    page_rotations: dict[int, int] = {}
    try:
        indices = list(range(pdf.page_count)) if pages is None else pages
        polices = collecter_polices(pdf, construire(dossiers=dossiers_par_defaut()))
        document = Document(polices=polices, source_pdf_id=sha256(Path(source_pdf).read_bytes()).hexdigest(),
                            options_snapshot={"extraction_mode": "pdf-native", "text_understanding_ai": text_understanding_ai})
        for index in indices:
            pdf_page = pdf[index]
            page_rotations[index] = int(getattr(pdf_page, "rotation", 0) or 0)
            geometry = PageGeometry.depuis_page(pdf_page)
            page = Page(
                index=index,
                largeur_emu=geometry.largeur_emu,
                hauteur_emu=geometry.hauteur_emu,
                coordinate_space=geometry.repere,
                orientation=geometry.orientation,
                format_name=geometry.format_nom,
                rotation_pdf=geometry.rotation,
                source_pdf_id=document.source_pdf_id,
                options_snapshot=dict(document.options_snapshot),
                native_width_pt=(
                    geometry.coordinate_system.media_width_pt
                    if geometry.coordinate_system is not None
                    else None
                ),
                native_height_pt=(
                    geometry.coordinate_system.media_height_pt
                    if geometry.coordinate_system is not None
                    else None
                ),
            )
            acquired = extraire_texte(pdf_page, polices, geometrie=geometry)
            capture_source_observations(page, acquired, source_kind="pdf-native")
            elements = dedoublonner_textboxes_paragraphes(acquired)
            for removed in acquired:
                if any(removed is item for item in elements):
                    continue
                winner = next((item for item in elements if item.source_id == removed.attributes.get("duplicate_of")), None)
                record_source_transformation(page, [removed], [winner] if winner else [], "native-text-deduplication",
                                             duplicate_of=winner.source_id if winner else None,
                                             duplicate_verified=removed.attributes.get("duplicate_verified", False))

            # La lettrine est souvent un objet PDF d'une seule lettre qui chevauche
            # le premier bloc. Elle doit rester dans le paragraphe qu'elle initie.
            for candidate in list(elements):
                if len(candidate.lignes) != 1 or len(
                    "".join(span.texte for span in candidate.lignes[0].spans).strip()
                ) != 1:
                    continue
                for target in elements:
                    if target is candidate or not target.lignes:
                        continue
                    overlap_x = min(candidate.bbox.x1, target.bbox.x1) - max(
                        candidate.bbox.x0, target.bbox.x0
                    )
                    overlap_y = min(candidate.bbox.y1, target.bbox.y1) - max(
                        candidate.bbox.y0, target.bbox.y0
                    )
                    if (
                        overlap_x <= 0
                        or overlap_y <= 0
                        or candidate.bbox.hauteur < target.lignes[0].hauteur_ligne_emu * 2
                    ):
                        continue
                    first_span = target.lignes[0].spans[0]
                    first_span.texte = "".join(
                        span.texte for span in candidate.lignes[0].spans
                    ) + first_span.texte
                    elements.remove(candidate)
                    target.source_ids = tuple(dict.fromkeys((*element_source_ids(target), *element_source_ids(candidate))))
                    target.attributes.setdefault("replaces", []).append(candidate.source_id)
                    record_source_transformation(page, [candidate], [target], "drop-cap-prefix-insertion",
                                                 proof={"inserted_text": "".join(span.texte for span in candidate.lignes[0].spans),
                                                        "overlap_x": overlap_x, "overlap_y": overlap_y})
                    break

            page.elements.extend(elements)
            document.pages.append(page)
    finally:
        pdf.close()

    if catalog_path is not None:
        enregistrer_catalogue(
            construire_catalogue(
                document,
                source_pdf=source_pdf,
                extraction_mode="pdf-native",
                page_rotations=page_rotations,
            ),
            catalog_path,
        )
    document.scene = scene_from_legacy_document(document)
    return document
