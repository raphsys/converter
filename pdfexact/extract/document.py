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
from pdfexact.extract.layout_map import construire_layout_map
from pdfexact.extract.ocr import extraire_ocr, extraire_rapidocr
from pdfexact.extract.tables import extraire_tableaux
from pdfexact.extract.text import extraire_texte, extraire_texte_glyphes
from pdfexact.extract.vector import (
    SEUIL_CHEMINS_PAR_DEFAUT,
    boite_du_cluster,
    doit_rasteriser,
    extraire_vectoriel,
    regrouper,
)
from pdfexact.fallback.rasterize import page_a_des_degrades, rasteriser_region
from pdfexact.geometry import BBox, PageGeometry, pt_vers_emu
from pdfexact.ir import Document, FlowParagraph, ImageEl, LinkZone, Page, RasterEl, ShapeEl, TableEl, TextBox
from pdfexact.report import PageDegradee, Rapport


def _aire(bbox: BBox) -> int:
    return max(0, bbox.largeur) * max(0, bbox.hauteur)


def _intersection(a: BBox, b: BBox) -> int:
    x0 = max(a.x0, b.x0)
    y0 = max(a.y0, b.y0)
    x1 = min(a.x1, b.x1)
    y1 = min(a.y1, b.y1)
    return max(0, x1 - x0) * max(0, y1 - y0)


def _recouvrement_min(a: BBox, b: BBox) -> float:
    return _intersection(a, b) / max(min(_aire(a), _aire(b)), 1)


def _fond_vectoriel_significatif(cluster: list[ShapeEl], aire_page: int) -> bool:
    """Garde les grands aplats utiles au layout, pas les artefacts de glyphes/traits."""
    min_dimension = pt_vers_emu(4)
    min_aire = max(int(aire_page * 0.001), pt_vers_emu(8) * pt_vers_emu(8))
    for element in cluster:
        if not isinstance(element, ShapeEl) or not element.remplissage:
            continue
        couleur = element.remplissage.upper()
        if couleur in {"FFFFFF", "FEFEFE"}:
            continue
        if element.bbox.largeur < min_dimension or element.bbox.hauteur < min_dimension:
            continue
        if _aire(element.bbox) >= min_aire:
            return True
    return False


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
    geometrie = PageGeometry.depuis_page(page_pdf)
    degrades = page_a_des_degrades(doc, page_pdf)
    zones_visuelles: list[BBox] = []
    aire_page = max(page_ir.largeur_emu * page_ir.hauteur_emu, 1)
    tableaux_detectes: list[TableEl] = []
    zones_tableaux: list[BBox] = []

    if text_mode == "rapidocr" and ocr_layout == "hybrid":
        tableaux_detectes = extraire_tableaux(page_pdf, polices, geometrie=geometrie)
        zones_tableaux = [tableau.bbox for tableau in tableaux_detectes]

    for cluster in regrouper(extraire_vectoriel(page_pdf, geometrie=geometrie)):
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
            if (
                ocr_layout == "hybrid"
                and _fond_vectoriel_significatif(cluster, aire_page)
                and not any(_recouvrement_min(boite_cluster, zone) > 0.18 for zone in zones_tableaux)
            ):
                page_ir.elements.extend(cluster)
            continue
        else:
            page_ir.elements.extend(cluster)

    if text_mode == "rapidocr" and ocr_layout in {"reflow", "hybrid"}:
        images = extraire_images_rasterisees(
            page_pdf,
            doc,
            document.media,
            dpi=dpi,
            geometrie=geometrie,
        )
        images_inline = extraire_images_inline_rasterisees(
            page_pdf,
            document.media,
            deja_posees=images,
            dpi=dpi,
            geometrie=geometrie,
        )
    else:
        images = extraire_images(page_pdf, doc, document.media, geometrie=geometrie)
        images_inline = extraire_images_inline(
            page_pdf,
            document.media,
            deja_posees=images,
            geometrie=geometrie,
        )
    page_ir.elements.extend(images)
    page_ir.elements.extend(images_inline)
    zones_images = zones_visuelles + [image.bbox for image in images + images_inline]
    if verbose and images_inline:
        print(f"      images inline: {len(images_inline)} bloc(s)", file=sys.stderr)
    if verbose and zones_visuelles:
        print(f"      zones vectorielles immuables: {len(zones_visuelles)}", file=sys.stderr)

    tableaux = []
    if text_mode == "rapidocr" and ocr_layout == "hybrid":
        tableaux = tableaux_detectes
        if tableaux:
            page_ir.elements.extend(tableaux)
            zones_images.extend(tableau.bbox for tableau in tableaux)
            if verbose:
                print(f"      tableaux Word: {len(tableaux)}", file=sys.stderr)

    layout_map = None
    if text_mode == "rapidocr" and ocr_layout == "hybrid":
        layout_map = construire_layout_map(
            page_pdf,
            zones_visuelles=zones_images,
            dpi=dpi,
            geometrie=geometrie,
        )

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
                layout_map=layout_map,
                geometrie=geometrie,
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
            geometrie = PageGeometry.depuis_page(page_pdf)
            page_ir = Page(
                index=index,
                largeur_emu=geometrie.largeur_emu,
                hauteur_emu=geometrie.hauteur_emu,
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
                elif isinstance(element, TableEl):
                    rapport.tableaux += 1
                elif isinstance(element, LinkZone):
                    rapport.liens += 1
        rapport.liens += sum(
            1
            for page in document.pages
            for element in page.elements
            if isinstance(element, TextBox)
            for ligne in element.lignes
            for span in ligne.spans
            if span.lien
        )

        return document
    finally:
        doc.close()
