#!/usr/bin/env python3
"""Produit les bboxes, les non-textes et le texte natif en une seule commande."""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path

import pymupdf

from pdfexact.extract.catalog import construire_catalogue, enregistrer_catalogue
from pdfexact.extract.document import extraire
from pdfexact.extract.text import dedoublonner_textboxes_paragraphes
from pdfexact.analysis.text_segmentation import segmenter_page_textes
from pdfexact.fontlib import construire, dossiers_par_defaut
from pdfexact.ir import Document, FlowParagraph, TextBox
from pdfexact.layout.text_comprehension import (
    configurer_fournisseur_comprehension_texte,
    contexte_comprehension_texte,
)
from pdfexact.layout.text_comprehension_ai import creer_fournisseur_comprehension_texte_ai
from pdfexact.model_paths import resolve_ai_models_root
from pdfexact.analysis.options import AnalysisOptions
from pdfexact.render.render_plan import build_document_render_plan
from pdfexact.render.native_contract import valider_contrat_word_native
from pdfexact.render.bbox_debug import (
    annotate_pdf_bboxes,
    fill_existing_bbox_docx,
    fill_existing_bbox_docx_with_native_paragraphs,
    write_bbox_only_docx,
)
from pdfexact.report import Rapport


def _pages(expression: str | None) -> list[int] | None:
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


def _extraire_scene(source_pdf: Path, pages: list[int] | None, args) -> Document:
    """Etape 1 : extrait une seule scène complète conservée en mémoire."""
    ocr_layout = "word-native" if args.text_mode == "rapidocr" else "blocks"
    common_root = getattr(args, "ai_models_root", None)
    layout_root = getattr(args, "layout_model_root", None)
    explicit_root = common_root if common_root is not None else layout_root
    model_root = resolve_ai_models_root(explicit_root)
    configurer_fournisseur_comprehension_texte(
        creer_fournisseur_comprehension_texte_ai(
            url=args.text_understanding_url,
            timeout=args.text_understanding_timeout,
            model_root=model_root if explicit_root is not None else None,
            experimental_local=getattr(args, "experimental_local_text_understanding", False) is True,
        ),
        annoncer=True,
    )
    return extraire(
        source_pdf,
        pages=pages,
        bibliotheque=construire(dossiers=dossiers_par_defaut()),
        dpi=args.dpi,
        strict=True,
        text_mode=args.text_mode,
        ocr_granularity="line",
        ocr_layout=ocr_layout,
        # Le layout IA est une etape obligatoire de l'orchestrateur. Le flag
        # historique est conserve pour compatibilite CLI, mais ne peut plus
        # desactiver l'analyse de page.
        layout_ai=True,
        layout_provider=args.layout_provider,
        layout_model=args.layout_model,
        layout_model_root=layout_root if layout_root is not None else (model_root if common_root is not None else None),
        layout_device=args.layout_device,
        ai_models_root=model_root,
        ocr_language=getattr(args, "ocr_language", "auto"),
        rapport=Rapport(),
        verbose=True,
    )


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


def _enregistrer_catalogue(document: Document, source_pdf: Path, destination: Path) -> None:
    """Etape 3 : persiste les éléments du même Document utilisé pour le rendu."""
    with pymupdf.open(source_pdf) as pdf:
        rotations = {
            index: int(getattr(pdf[index], "rotation", 0) or 0)
            for index in range(pdf.page_count)
        }
    enregistrer_catalogue(
        construire_catalogue(
            document,
            source_pdf=source_pdf,
            extraction_mode="scene-single-pass",
            page_rotations=rotations,
        ),
        destination,
    )


def _ecrire_bboxes_pdf(source_pdf: Path, destination: Path, document: Document, plan):
    """Etape 4 : dessine les bboxes du Document conservé en mémoire."""
    return annotate_pdf_bboxes(source_pdf, destination, document, render_plan=plan)


def _construire_plan_unique(document: Document):
    """Construit et verrouille le plan commun de toutes les sorties."""
    plan = build_document_render_plan(document, AnalysisOptions())
    contrat = valider_contrat_word_native(document, plan)
    if not contrat.conforme:
        details = "; ".join((*contrat.plan_errors, *contrat.missing_bbox, *contrat.unsupported_modes))
        raise RuntimeError(f"Contrat de rendu natif invalide: {details}")
    # The prepared semantic elements are the sole active representation from
    # this point on. Intermediate files remain diagnostics, not alternate IRs.
    for page in document.pages:
        prepared = plan.elements_for_page(page.index)
        if prepared is not None:
            page.elements = list(prepared)
    return plan


def _ecrire_docx_vierge(document: Document, destination: Path, plan) -> None:
    """Etape 5 : crée le DOCX vierge contenant uniquement les bboxes."""
    write_bbox_only_docx(document, destination, render_plan=plan)


def _remplir_non_textes(
    bbox_docx: Path, document: Document, destination: Path, plan
) -> None:
    """Etape 6 : ajoute les images et formes dans le DOCX bbox existant."""
    fill_existing_bbox_docx(bbox_docx, document, destination, render_plan=plan)


def _remplir_textes(
    non_text_docx: Path, document: Document,
    destination: Path, plan,
) -> None:
    """Etape 7 : ajoute les textes du même Document dans les bboxes existantes."""
    fill_existing_bbox_docx_with_native_paragraphs(
        non_text_docx,
        document,
        destination,
        render_plan=plan,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Produit le PDF des bboxes et le DOCX rempli en un seul appel."
    )
    parser.add_argument("source_pdf", type=Path)
    parser.add_argument("--pdf-out", type=Path, required=True)
    parser.add_argument("--docx-out", type=Path, required=True)
    parser.add_argument("--pages")
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--text-mode", choices=("spans", "rapidocr"), default="spans")
    parser.add_argument(
        "--ocr-language", "--ocr-lang", default="auto",
        help="langue RapidOCR : auto best-effort par region ou ru, zh, ja, ko, ru+ja",
    )
    parser.add_argument(
        "--ai-models-root", default=None,
        help="racine IA commune locale pour OCR, comprehension et layout",
    )
    parser.add_argument("--layout-ai", action="store_true")
    parser.add_argument("--layout-provider", default=None)
    parser.add_argument("--layout-model", default=None)
    parser.add_argument("--layout-model-root", default=None)
    parser.add_argument("--layout-device", default=None)
    parser.add_argument(
        "--text-understanding-ai", action="store_true",
        help="Compatibilite CLI: la comprehension textuelle est toujours invoquee.",
    )
    parser.add_argument("--text-understanding-url", default=None)
    parser.add_argument("--text-understanding-timeout", type=float, default=3.0)
    parser.add_argument(
        "--experimental-local-text-understanding", action="store_true",
        help="active explicitement la comprehension Qwen locale experimentale",
    )
    args = parser.parse_args()

    selected_pages = _pages(args.pages)
    args.pdf_out.parent.mkdir(parents=True, exist_ok=True)
    args.docx_out.parent.mkdir(parents=True, exist_ok=True)
    with contexte_comprehension_texte():
        document = _extraire_scene(args.source_pdf, selected_pages, args)
        _normaliser_texte(document)
        plan = _construire_plan_unique(document)
        _enregistrer_catalogue(
            document,
            args.source_pdf,
            args.docx_out.with_suffix(".extraction.json"),
        )
        records = _ecrire_bboxes_pdf(args.source_pdf, args.pdf_out, document, plan)
        bbox_docx = args.docx_out.with_name(args.docx_out.stem + ".bboxes.docx")
        non_text_docx = args.docx_out.with_name(args.docx_out.stem + ".non_text.docx")
        _ecrire_docx_vierge(document, bbox_docx, plan)
        _remplir_non_textes(bbox_docx, document, non_text_docx, plan)
        _remplir_textes(non_text_docx, document, args.docx_out, plan)

    by_kind: dict[str, int] = {}
    for record in records:
        by_kind[record.kind] = by_kind.get(record.kind, 0) + 1
    print(f"bboxes={len(records)} " + " ".join(f"{key}={value}" for key, value in sorted(by_kind.items())))
    modes: dict[str, int] = {}
    for planned in (item for items in plan.pages.values() for item in items):
        name = planned.decision.mode.value
        modes[name] = modes.get(name, 0) + 1
    print(
        "render_plan=universal-single "
        + " ".join(f"{key}={value}" for key, value in sorted(modes.items()))
    )
    print(f"pdf={args.pdf_out}")
    print(f"docx={args.docx_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
