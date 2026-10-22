#!/usr/bin/env python3
"""Ajoute le texte natif du PDF aux bboxes existantes, en paragraphes Word."""
from __future__ import annotations

import argparse
from pathlib import Path

from pdfexact.extract.native_document import (
    extraire_document_texte_natif,
    pages_depuis_expression,
)
from pdfexact.render.bbox_debug import (
    fill_existing_bbox_docx_with_native_paragraphs,
    fill_existing_bbox_docx_with_text,
)
from pdfexact.layout.text_comprehension import (
    configurer_fournisseur_comprehension_texte,
    contexte_comprehension_texte,
)
from pdfexact.layout.text_comprehension_ai import creer_fournisseur_comprehension_texte_ai
from pdfexact.model_paths import resolve_ai_models_root


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_pdf", type=Path)
    parser.add_argument("bbox_docx", type=Path)
    parser.add_argument("destination_docx", type=Path)
    parser.add_argument("--pages", default=None)
    parser.add_argument("--native-paragraphs", action="store_true")
    parser.add_argument("--text-understanding-ai", action="store_true")
    parser.add_argument("--text-understanding-url", default=None)
    parser.add_argument("--text-understanding-timeout", type=float, default=3.0)
    parser.add_argument("--ai-models-root", type=Path, default=None)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="fichier JSON de l'extraction; par défaut: destination.docx -> .extraction.json",
    )
    args = parser.parse_args()

    selected = pages_depuis_expression(args.pages)
    catalog_path = args.catalog or args.destination_docx.with_suffix(".extraction.json")
    with contexte_comprehension_texte():
        configurer_fournisseur_comprehension_texte(
            creer_fournisseur_comprehension_texte_ai(
                url=args.text_understanding_url,
                timeout=args.text_understanding_timeout,
                model_root=resolve_ai_models_root(args.ai_models_root) if args.ai_models_root is not None else None,
            ),
            annoncer=True,
        )
        text_document = extraire_document_texte_natif(
            args.source_pdf,
            pages=selected,
            catalog_path=catalog_path,
            text_understanding_ai=args.text_understanding_ai,
            text_understanding_url=args.text_understanding_url,
            text_understanding_timeout=args.text_understanding_timeout,
            reuse_text_understanding_context=True,
        )
        if args.native_paragraphs:
            fill_existing_bbox_docx_with_native_paragraphs(
                args.bbox_docx, text_document, args.destination_docx
            )
        else:
            fill_existing_bbox_docx_with_text(args.bbox_docx, text_document, args.destination_docx)
    print(f"text_boxes={sum(len(page.elements) for page in text_document.pages)}")
    print(f"catalog={catalog_path}")
    print(args.destination_docx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
