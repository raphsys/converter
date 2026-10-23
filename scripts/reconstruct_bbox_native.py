#!/usr/bin/env python3
"""Lanceur du pipeline : SEGMENTATION, puis catalogue, PDF annoté et DOCX des bboxes."""
from __future__ import annotations

import argparse
from pathlib import Path
from time import perf_counter

from pdfexact.bboxes import annotate_pdf_bboxes, write_bbox_docx
from pdfexact.segmentation import OptionsSegmentation, enregistrer_catalogue, segmenter


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


def _options(args) -> OptionsSegmentation:
    return OptionsSegmentation(
        pages=_pages(args.pages),
        dpi=args.dpi,
        text_mode=args.text_mode,
        ocr_language=args.ocr_language,
        ai_models_root=args.ai_models_root,
        layout_provider=args.layout_provider,
        layout_model=args.layout_model,
        layout_model_root=args.layout_model_root,
        layout_device=args.layout_device,
        text_understanding_url=args.text_understanding_url,
        text_understanding_timeout=args.text_understanding_timeout,
    )


def _rapporter(resultat, records, args) -> None:
    by_kind: dict[str, int] = {}
    for record in records:
        by_kind[record.kind] = by_kind.get(record.kind, 0) + 1
    print(f"bboxes={len(records)} " + " ".join(f"{key}={value}" for key, value in sorted(by_kind.items())))
    print(f"pdf={args.pdf_out}")
    print(f"docx={args.docx_out}")
    print(f"catalogue={args.docx_out.with_suffix('.extraction.json')}")
    # What the comprehension AI actually did: a fallback here means the
    # segmentation above came from geometric heuristics, not from the model.
    for event in resultat.diagnostics:
        print(f"comprehension_ia: status={event.get('status')} reason={event.get('reason')}")
    statuts: dict[str, int] = {}
    for page in getattr(resultat.document, "pages", ()):
        for element in page.elements:
            statut = (getattr(element, "presentation", None) or {}).get("comprehension_ia")
            if statut:
                statuts[statut] = statuts.get(statut, 0) + 1
    print("comprehension_ia: paragraphes " + (" ".join(f"{key}={value}" for key, value in sorted(statuts.items())) or "aucun"))
    vus: dict[str, int] = {}
    for zone in resultat.vision:
        key = zone["type"] if zone["status"] == "compris" else "non-compris"
        vus[key] = vus.get(key, 0) + 1
    print("vision_ia: " + (" ".join(f"{key}={value}" for key, value in sorted(vus.items())) or "aucune-zone"))
    print(f"ocr_images: textes_lus={resultat.textes_images}")
    for zone in resultat.vision:
        if zone["status"] != "compris":
            print(f"vision_ia: page={zone['page'] + 1} non-compris reason={zone['reason']}")
    print("durees: " + " ".join(f"{nom}={valeur:.1f}s" for nom, valeur in resultat.durees.items())
          + f" total={sum(resultat.durees.values()):.1f}s")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Segmente le PDF, enregistre ses caracteristiques et produit le PDF et le DOCX des bboxes."
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

    resultat = segmenter(args.source_pdf, _options(args))
    debut = perf_counter()
    enregistrer_catalogue(resultat, args.source_pdf, args.docx_out.with_suffix(".extraction.json"))
    records = annotate_pdf_bboxes(args.source_pdf, args.pdf_out, resultat.document)
    write_bbox_docx(resultat.document, args.docx_out)
    resultat.durees["sorties"] = perf_counter() - debut
    _rapporter(resultat, records, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
