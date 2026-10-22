#!/usr/bin/env python3
"""Extrait, comprend et segmente un PDF, puis enregistre ses caracteristiques et ses bboxes."""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path

import pymupdf

from pdfexact.bboxes import annotate_pdf_bboxes, write_bbox_docx
from pdfexact.extract.catalog import construire_catalogue, enregistrer_catalogue
from pdfexact.extract.document import extraire
from pdfexact.extract.ocr import lire_texte_des_images
from pdfexact.extract.text import dedoublonner_textboxes_paragraphes
from pdfexact.analysis.text_segmentation import segmenter_page_textes
from pdfexact.fontlib import construire, dossiers_par_defaut
from pdfexact.ir import Document, FlowParagraph, TextBox
from pdfexact.layout.text_comprehension import (
    configurer_fournisseur_comprehension_texte,
    contexte_comprehension_texte,
    diagnostics_comprehension_texte,
)
from pdfexact.layout.text_comprehension_ai import creer_fournisseur_comprehension_texte_ai
from pdfexact.layout.vision import VisionSmolVLM, annoter_zones_visuelles
from pdfexact.model_paths import resolve_ai_models_root
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extrait le PDF, enregistre ses caracteristiques et produit le PDF et le DOCX des bboxes."
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
    args = parser.parse_args()

    selected_pages = _pages(args.pages)
    with contexte_comprehension_texte():
        document = _extraire_scene(args.source_pdf, selected_pages, args)
        _normaliser_texte(document)
        vision = annoter_zones_visuelles(document, args.source_pdf, VisionSmolVLM(getattr(args, "ai_models_root", None)))
        textes_images = lire_texte_des_images(
            document, args.source_pdf, getattr(document, "polices", {}), dpi=args.dpi,
            language=getattr(args, "ocr_language", "auto"),
            model_root=resolve_ai_models_root(getattr(args, "ai_models_root", None)),
        )
        _enregistrer_catalogue(document, args.source_pdf, args.docx_out.with_suffix(".extraction.json"))
        records = annotate_pdf_bboxes(args.source_pdf, args.pdf_out, document)
        write_bbox_docx(document, args.docx_out)
        diagnostics = diagnostics_comprehension_texte()

    by_kind: dict[str, int] = {}
    for record in records:
        by_kind[record.kind] = by_kind.get(record.kind, 0) + 1
    print(f"bboxes={len(records)} " + " ".join(f"{key}={value}" for key, value in sorted(by_kind.items())))
    print(f"pdf={args.pdf_out}")
    print(f"docx={args.docx_out}")
    print(f"catalogue={args.docx_out.with_suffix('.extraction.json')}")
    # What the comprehension AI actually did: a fallback here means the
    # segmentation above came from geometric heuristics, not from the model.
    for event in diagnostics:
        print(f"comprehension_ia: status={event.get('status')} reason={event.get('reason')}")
    vus: dict[str, int] = {}
    for zone in vision:
        key = zone["type"] if zone["status"] == "compris" else "non-compris"
        vus[key] = vus.get(key, 0) + 1
    print("vision_ia: " + (" ".join(f"{key}={value}" for key, value in sorted(vus.items())) or "aucune-zone"))
    print(f"ocr_images: textes_lus={textes_images}")
    for zone in vision:
        if zone["status"] != "compris":
            print(f"vision_ia: page={zone['page'] + 1} non-compris reason={zone['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
