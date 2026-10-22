#!/usr/bin/env python3
"""Produit un PDF annote et un DOCX de cadres, sans contenu reconstruit."""
from __future__ import annotations

import argparse
from pathlib import Path

from pdfexact.extract.document import extraire
from pdfexact.fontlib import construire, dossiers_par_defaut
from pdfexact.render.bbox_debug import (
    annotate_pdf_bboxes,
    write_bbox_only_docx,
    write_non_text_with_bboxes_docx,
    write_non_text_only_docx,
    fill_existing_bbox_docx,
)
from pdfexact.report import Rapport


def _pages(expression: str | None) -> list[int] | None:
    if not expression:
        return None
    result: list[int] = []
    for token in expression.split(","):
        token = token.strip()
        if "-" in token:
            start, end = (int(part) for part in token.split("-", 1))
            result.extend(range(start - 1, end))
        else:
            result.append(int(token) - 1)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dessine les bboxes IR dans un PDF et dans un DOCX vierge."
    )
    parser.add_argument("source_pdf", type=Path)
    parser.add_argument("--pdf-out", type=Path, required=True)
    parser.add_argument("--docx-out", type=Path, required=True)
    parser.add_argument("--fill-bbox-docx", type=Path)
    parser.add_argument(
        "--docx-mode",
        choices=("bbox", "non-text", "combined"),
        default="bbox",
        help="bbox = cadres seuls; non-text = objets seuls; combined = objets + cadres",
    )
    parser.add_argument("--pages", help="Pages 1-basees, par exemple 1 ou 1-3,5")
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument(
        "--text-mode",
        choices=("spans", "rapidocr"),
        default="spans",
        help="spans conserve les blocs natifs; rapidocr active la detection OCR",
    )
    parser.add_argument("--layout-ai", action="store_true")
    parser.add_argument("--layout-provider", default=None)
    parser.add_argument("--layout-model", default=None)
    parser.add_argument("--layout-model-root", default=None)
    parser.add_argument("--layout-device", default=None)
    args = parser.parse_args()

    selected_pages = _pages(args.pages)
    ocr_layout = "word-native" if args.text_mode == "rapidocr" else "blocks"
    document = extraire(
        args.source_pdf,
        pages=selected_pages,
        bibliotheque=construire(dossiers=dossiers_par_defaut()),
        dpi=args.dpi,
        strict=True,
        text_mode=args.text_mode,
        ocr_granularity="line",
        ocr_layout=ocr_layout,
        layout_ai=args.layout_ai,
        layout_provider=args.layout_provider,
        layout_model=args.layout_model,
        layout_model_root=args.layout_model_root,
        layout_device=args.layout_device,
        rapport=Rapport(),
        verbose=True,
    )
    records = annotate_pdf_bboxes(args.source_pdf, args.pdf_out, document)
    if args.fill_bbox_docx:
        fill_existing_bbox_docx(args.fill_bbox_docx, document, args.docx_out)
    elif args.docx_mode == "combined":
        write_non_text_with_bboxes_docx(document, args.docx_out)
    elif args.docx_mode == "non-text":
        write_non_text_only_docx(document, args.docx_out)
    else:
        write_bbox_only_docx(document, args.docx_out)
    by_kind: dict[str, int] = {}
    for record in records:
        by_kind[record.kind] = by_kind.get(record.kind, 0) + 1
    print(f"bboxes={len(records)} " + " ".join(f"{key}={value}" for key, value in sorted(by_kind.items())))
    print(f"pdf={args.pdf_out}")
    print(f"docx={args.docx_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
