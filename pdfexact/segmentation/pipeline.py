"""Étapes de la segmentation : extraction, segmentation du texte, texte des images."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

import pymupdf

from pdfexact.analysis.text_segmentation import segmenter_page_textes
from pdfexact.extract.catalog import construire_catalogue, enregistrer_catalogue as _ecrire_catalogue
from pdfexact.extract.document import extraire
from pdfexact.extract.ocr import lire_texte_des_images
from pdfexact.extract.text import dedoublonner_textboxes_paragraphes
from pdfexact.fontlib import construire, dossiers_par_defaut
from pdfexact.ir import Document, FlowParagraph, TextBox
from pdfexact.layout.text_comprehension import (
    configurer_fournisseur_comprehension_texte,
    contexte_comprehension_texte,
    diagnostics_comprehension_texte,
)
from pdfexact.layout.text_comprehension_ai import creer_fournisseur_comprehension_texte_ai
from pdfexact.layout.vision import annoter_zones_visuelles
from pdfexact.model_paths import resolve_ai_models_root
from pdfexact.report import Rapport
from pdfexact.segmentation.granularite import GRANULARITES, Boite, boites, ligne_visible, regrouper_visuels_en_blocs


@dataclass(frozen=True)
class OptionsSegmentation:
    pages: list[int] | None = None
    dpi: int = 150
    text_mode: str = "spans"
    ocr_language: str = "auto"
    ai_models_root: str | None = None
    layout_provider: str | None = None
    layout_model: str | None = None
    layout_model_root: str | None = None
    layout_device: str | None = None
    text_understanding_url: str | None = None
    text_understanding_timeout: float = 3.0
    # fine: lines and every visual part; blocs: paragraphs and whole images.
    granularite: str = "blocs"
    # As in vysi (native text first, OCR only where text is missing): the text printed
    # inside the images of a page that has native text is read only on request.
    ocr_images: bool = False

    def __post_init__(self):
        if self.granularite not in GRANULARITES:
            raise ValueError(f"granularite inconnue : {self.granularite!r} (attendu : {', '.join(GRANULARITES)})")


@dataclass(frozen=True)
class ResultatSegmentation:
    document: Document
    diagnostics: list = field(default_factory=list)
    vision: list = field(default_factory=list)
    textes_images: int = 0
    durees: dict = field(default_factory=dict)
    granularite: str = "blocs"

    def boites(self) -> list[Boite]:
        """The segmentation bboxes at the chosen granularity."""
        return boites(self.document, self.granularite)


def segmenter(source_pdf: Path, options: OptionsSegmentation) -> ResultatSegmentation:
    """Segmente le PDF : un seul Document, ses éléments et leurs bboxes."""
    durees: dict[str, float] = {}
    debut = perf_counter()

    def etape(nom: str) -> None:
        nonlocal debut
        durees[nom] = perf_counter() - debut
        debut = perf_counter()

    with contexte_comprehension_texte():
        document = _extraire_scene(source_pdf, options)
        etape("extraction+layout")
        _normaliser_texte(document)
        etape("segmentation+comprehension")
        vision = annoter_zones_visuelles(document, source_pdf, None)
        etape("vision")
        textes_images = lire_texte_des_images(
            document, source_pdf, getattr(document, "polices", {}), dpi=options.dpi,
            language=options.ocr_language,
            model_root=resolve_ai_models_root(options.ai_models_root),
            pages=None if options.ocr_images else pages_sans_texte_natif(document),
        )
        etape("ocr-images")
        if options.granularite == "blocs":
            regrouper_visuels_en_blocs(document, source_pdf, dpi=options.dpi)
            etape("granularite")
        diagnostics = diagnostics_comprehension_texte()
    return ResultatSegmentation(document, diagnostics, vision, textes_images, durees, options.granularite)


def _extraire_scene(source_pdf: Path, options: OptionsSegmentation) -> Document:
    """Etape 1 : extrait une seule scène complète conservée en mémoire."""
    ocr_layout = "word-native" if options.text_mode == "rapidocr" else "blocks"
    common_root = options.ai_models_root
    layout_root = options.layout_model_root
    explicit_root = common_root if common_root is not None else layout_root
    model_root = resolve_ai_models_root(explicit_root)
    configurer_fournisseur_comprehension_texte(
        creer_fournisseur_comprehension_texte_ai(
            url=options.text_understanding_url,
            timeout=options.text_understanding_timeout,
        ),
    )
    return extraire(
        source_pdf,
        pages=options.pages,
        bibliotheque=construire(dossiers=dossiers_par_defaut()),
        dpi=options.dpi,
        strict=True,
        text_mode=options.text_mode,
        ocr_granularity="line",
        ocr_layout=ocr_layout,
        # Le layout IA est une étape obligatoire de la segmentation.
        layout_ai=True,
        layout_provider=options.layout_provider,
        layout_model=options.layout_model,
        layout_model_root=layout_root if layout_root is not None else (model_root if common_root is not None else None),
        layout_device=options.layout_device,
        ai_models_root=model_root,
        ocr_language=options.ocr_language,
        ocr_images=options.ocr_images,
        rapport=Rapport(),
        verbose=True,
    )


def pages_sans_texte_natif(document: Document) -> set[int]:
    """Pages where no native (non-OCR) text shows a visible character: OCR is needed there."""
    return {
        page.index for page in document.pages
        if not any(
            isinstance(element, (TextBox, FlowParagraph)) and getattr(element, "source_kind", None) != "ocr"
            and ligne_visible(*element.lignes)
            for element in page.elements
        )
    }


def _normaliser_texte(document: Document) -> None:
    """Etape 2 : normalise les textes dans le même Document, sans réextraire."""
    for page in document.pages:
        textes = [
            element
            for element in page.elements
            if isinstance(element, (TextBox, FlowParagraph))
        ]
        if not textes:
            continue
        textes = dedoublonner_textboxes_paragraphes(textes)
        for candidate in list(textes):
            if len(candidate.lignes) != 1 or len(
                "".join(span.texte for span in candidate.lignes[0].spans).strip()
            ) != 1:
                continue
            for target in textes:
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
                # Une lettrine reste un élément natif séparé : la ligne du
                # paragraphe commence après elle et ne doit pas la déplacer.
                if candidate.bbox.hauteur >= target.lignes[0].hauteur_ligne_emu * 2:
                    continue
                # Conserver le span du fragment avec sa police, sa taille et
                # sa couleur. Le préfixer au span du corps perdrait son style.
                target.lignes[0].spans[0:0] = [
                    deepcopy(span) for span in candidate.lignes[0].spans
                ]
                textes.remove(candidate)
                break
        page.elements = [
            element
            for element in page.elements
            if not isinstance(element, (TextBox, FlowParagraph))
        ] + textes
        segmenter_page_textes(page)
        # Un texte sans aucun caractère visible (espaces du PDF) n'est pas un élément.
        page.elements = [
            element
            for element in page.elements
            if not isinstance(element, (TextBox, FlowParagraph)) or ligne_visible(*element.lignes)
        ]


def enregistrer_catalogue(resultat: ResultatSegmentation, source_pdf: Path, destination: Path) -> None:
    """Persiste les éléments segmentés et leurs caractéristiques."""
    with pymupdf.open(source_pdf) as pdf:
        rotations = {
            index: int(getattr(pdf[index], "rotation", 0) or 0)
            for index in range(pdf.page_count)
        }
    catalogue = construire_catalogue(
        resultat.document,
        source_pdf=source_pdf,
        extraction_mode="scene-single-pass",
        page_rotations=rotations,
    )
    _ecrire_catalogue({**catalogue, "granularite": resultat.granularite}, destination)
