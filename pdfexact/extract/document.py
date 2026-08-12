"""Ouverture du PDF et assemblage du Document.

L'ordre de construction des éléments d'une page fixe leur superposition : vectoriel et
zones rastérisées d'abord — ce sont les fonds —, puis les images, puis le texte, qui doit
rester au-dessus et lisible en toute circonstance.
"""
import pymupdf
import sys

from pdfexact.extract.fonts import collecter_polices
from pdfexact.extract.glyph_images import extraire_glyphes_images
from pdfexact.extract.images import (
    extraire_images,
    extraire_images_inline,
    extraire_images_inline_rasterisees,
    extraire_images_rasterisees,
)
from pdfexact.extract.links import appliquer_liens
from pdfexact.extract.ocr import extraire_ocr, extraire_rapidocr
from pdfexact.extract.text import extraire_texte, extraire_texte_glyphes
from pdfexact.extract.vector import (
    SEUIL_CHEMINS_PAR_DEFAUT,
    boite_du_cluster,
    doit_rasteriser,
    extraire_vectoriel,
    regrouper,
)
from pdfexact.fallback.rasterize import page_a_des_degrades, rasteriser_region
from pdfexact.geometry import BBox, pt_vers_emu
from pdfexact.ir import Document, FlowParagraph, ImageEl, LinkZone, Page, RasterEl, ShapeEl
from pdfexact.report import PageDegradee, Rapport


def _remplir_page(
    page_ir,
    page_pdf,
    doc,
    document,
    polices,
    dpi,
    seuil_raster,
    rapport,
    text_mode,
    ocr_granularity,
    ocr_layout,
    verbose,
):
    """Construit les éléments d'une page, dans l'ordre de superposition."""
    degrades = page_a_des_degrades(doc, page_pdf)
    zones_visuelles: list[BBox] = []
    aire_page = max(page_ir.largeur_emu * page_ir.hauteur_emu, 1)

    for cluster in regrouper(extraire_vectoriel(page_pdf)):
        boite_cluster = boite_du_cluster(cluster)
        if doit_rasteriser(cluster, degrades, seuil_raster):
            raster = rasteriser_region(page_pdf, boite_cluster, document.media, dpi=dpi)
            page_ir.elements.append(raster)
            aire_cluster = max(raster.bbox.largeur, 0) * max(raster.bbox.hauteur, 0)
            if aire_cluster / aire_page <= 0.18:
                zones_visuelles.append(raster.bbox)
            rapport.clusters_rasterises += 1
        elif text_mode == "rapidocr" and ocr_layout in {"reflow", "hybrid"}:
            # En reflow, le texte devient un vrai flux Word. Les petits traits PDF
            # (soulignements, filets de page, artefacts glyphiques) ne doivent plus
            # rester en coordonnées absolues : ils se décorrèlent des paragraphes.
            continue
        else:
            page_ir.elements.extend(cluster)

    if text_mode == "rapidocr" and ocr_layout in {"reflow", "hybrid"}:
        images = extraire_images_rasterisees(page_pdf, doc, document.media, dpi=dpi)
        images_inline = extraire_images_inline_rasterisees(
            page_pdf, document.media, deja_posees=images, dpi=dpi
        )
    else:
        images = extraire_images(page_pdf, doc, document.media)
        images_inline = extraire_images_inline(page_pdf, document.media, deja_posees=images)
    page_ir.elements.extend(images)
    page_ir.elements.extend(images_inline)
    zones_images = zones_visuelles + [image.bbox for image in images + images_inline]
    if verbose and images_inline:
        print(f"      images inline: {len(images_inline)} bloc(s)", file=sys.stderr)
    if verbose and zones_visuelles:
        print(f"      zones vectorielles immuables: {len(zones_visuelles)}", file=sys.stderr)

    if text_mode == "glyph-images":
        page_ir.elements.extend(extraire_glyphes_images(page_pdf, document.media, dpi=dpi))
        return

    if text_mode == "rapidocr":
        page_ir.elements.extend(
            extraire_rapidocr(
                page_pdf,
                polices,
                dpi=dpi,
                verbose=verbose,
                granularite=ocr_granularity,
                layout=ocr_layout,
                zones_ignorees=zones_images,
                media=document.media,
            )
        )
        return

    blocs = extraire_texte_glyphes(page_pdf, polices) if text_mode == "glyphs" else extraire_texte(page_pdf, polices)
    page_ir.elements.extend(blocs)
    page_ir.elements.extend(appliquer_liens(page_pdf, blocs))


def extraire(
    chemin_pdf,
    pages=None,
    bibliotheque=None,
    dpi: int = 300,
    seuil_raster: int = SEUIL_CHEMINS_PAR_DEFAUT,
    strict: bool = False,
    rasteriser_pages: bool = False,
    text_mode: str = "spans",
    ocr_layer: bool = False,
    ocr_lang: str = "eng",
    ocr_visible: bool = False,
    ocr_granularity: str = "word",
    ocr_layout: str = "blocks",
    verbose: bool = False,
    rapport: Rapport | None = None,
) -> Document:
    """Construit l'IR complet à partir d'un PDF.

    Aucune page ne peut faire échouer la conversion : une page en erreur est remplacée
    par son rendu raster et signalée dans le rapport. `strict` renverse ce comportement.
    """
    rapport = rapport if rapport is not None else Rapport()

    doc = pymupdf.open(chemin_pdf)
    try:
        polices = {} if rasteriser_pages else collecter_polices(doc, bibliotheque)
        rapport.polices_reconnues = [a.font_id for a in polices.values() if a.reconnue]
        rapport.polices_non_reconnues = [
            a.font_id for a in polices.values() if not a.reconnue
        ]

        if pages is None:
            indices = list(range(doc.page_count))
        else:
            indices = list(pages)
            hors_bornes = [i + 1 for i in indices if not 0 <= i < doc.page_count]
            if hors_bornes:
                raise ValueError(
                    f"page(s) {', '.join(map(str, hors_bornes))} absente(s) : "
                    f"le document en compte {doc.page_count}"
                )

        document = Document(polices=polices)

        for position, index in enumerate(indices, start=1):
            if verbose:
                modes = []
                if rasteriser_pages:
                    modes.append("raster-page")
                else:
                    modes.append(f"texte={text_mode}")
                if ocr_layer:
                    modes.append(f"ocr={ocr_lang}{'/visible' if ocr_visible else ''}")
                print(
                    f"  page {position}/{len(indices)} (PDF {index + 1}) - {', '.join(modes)}",
                    file=sys.stderr,
                )
            page_pdf = doc[index]
            page_ir = Page(
                index=index,
                largeur_emu=pt_vers_emu(page_pdf.rect.width),
                hauteur_emu=pt_vers_emu(page_pdf.rect.height),
            )

            if rasteriser_pages:
                if verbose:
                    print("    rasterisation pleine page", file=sys.stderr)
                page_ir.elements.append(
                    rasteriser_region(
                        page_pdf,
                        BBox(0, 0, page_ir.largeur_emu, page_ir.hauteur_emu),
                        document.media,
                        dpi=dpi,
                    )
                )
                if ocr_layer:
                    if verbose:
                        print("    OCR Tesseract", file=sys.stderr)
                    page_ir.elements.extend(
                        extraire_ocr(
                            page_pdf,
                            dpi=dpi,
                            langue=ocr_lang,
                            visible=ocr_visible,
                            verbose=verbose,
                        )
                    )
                document.pages.append(page_ir)
                continue

            try:
                if verbose:
                    print("    extraction éléments PDF", file=sys.stderr)
                _remplir_page(
                    page_ir,
                    page_pdf,
                    doc,
                    document,
                    polices,
                    dpi,
                    seuil_raster,
                    rapport,
                    text_mode,
                    ocr_granularity,
                    ocr_layout,
                    verbose,
                )
            except Exception as erreur:  # noqa: BLE001 — une page ne fait jamais tout échouer
                if strict:
                    raise
                page_ir.elements = [
                    rasteriser_region(
                        page_pdf,
                        BBox(0, 0, page_ir.largeur_emu, page_ir.hauteur_emu),
                        document.media,
                        dpi=dpi,
                    )
                ]
                rapport.pages_degradees.append(
                    PageDegradee(index=index, motif=f"{type(erreur).__name__}: {erreur}")
                )

            if ocr_layer:
                if verbose:
                    print("    OCR Tesseract", file=sys.stderr)
                page_ir.elements.extend(
                    extraire_ocr(
                        page_pdf,
                        dpi=dpi,
                        langue=ocr_lang,
                        visible=ocr_visible,
                        verbose=verbose,
                    )
                )

            document.pages.append(page_ir)

        rapport.pages_totales = len(document.pages)
        for page in document.pages:
            for element in page.elements:
                if isinstance(element, (ImageEl, RasterEl)):
                    rapport.images += 1
                elif isinstance(element, ShapeEl):
                    rapport.formes += 1
                elif isinstance(element, LinkZone):
                    rapport.liens += 1
        rapport.liens += sum(
            1
            for page in document.pages
            for element in page.elements
            if not isinstance(element, (FlowParagraph, ImageEl, ShapeEl, RasterEl, LinkZone))
            for ligne in element.lignes
            for span in ligne.spans
            if span.lien
        )

        return document
    finally:
        doc.close()
