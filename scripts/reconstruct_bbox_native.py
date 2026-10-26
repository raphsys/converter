#!/usr/bin/env python3
"""Lanceur du pipeline : SEGMENTATION puis IDENTIFICATION, avec leurs catalogues et PDF annotés."""
from __future__ import annotations

import argparse
from pathlib import Path
from time import perf_counter

import pymupdf

from pdfexact.bboxes import annotate_pdf_bboxes, write_bbox_docx
from pdfexact.identification import annoter_pdf_types, enregistrer_identification, identifier
from pdfexact.segmentation import OptionsSegmentation, enregistrer_catalogue, segmenter


def _toutes(expression: str | None) -> bool:
    return not expression or expression.strip().casefold() == "all"


def _nombre_pages(source_pdf: Path) -> int:
    with pymupdf.open(source_pdf) as pdf:
        return pdf.page_count


def _pages(expression: str | None, page_count: int) -> list[int] | None:
    """Pages 1-based of the command line, as 0-based indices within the document.

    "all" (or nothing) selects every page; pages beyond the document are dropped.
    """
    if _toutes(expression):
        return None
    selected: list[int] = []
    for token in expression.split(","):
        token = token.strip()
        if "-" in token:
            start, end = (int(part) for part in token.split("-", 1))
            selected.extend(range(start - 1, min(end, page_count)))
        elif int(token) <= page_count:
            selected.append(int(token) - 1)
    return list(dict.fromkeys(selected))


def _options(args) -> OptionsSegmentation:
    pages = None if _toutes(args.pages) else _pages(args.pages, _nombre_pages(args.source_pdf))
    return OptionsSegmentation(
        pages=pages,
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
        granularite=args.granularite,
        ocr_images=args.ocr_images,
    )


def _types_out(args) -> Path:
    return args.types_out or args.pdf_out.with_name(f"{args.pdf_out.stem}_types.pdf")


def _rapporter(resultat, records, args, identification=None) -> None:
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
    # One line per page and reason, not one per zone.
    non_compris: dict[tuple[int, str], int] = {}
    for zone in resultat.vision:
        if zone["status"] != "compris":
            cle = (zone["page"] + 1, zone["reason"])
            non_compris[cle] = non_compris.get(cle, 0) + 1
    for (page, raison), nombre in non_compris.items():
        print(f"vision_ia: page={page} non-compris={nombre} reason={raison}")
    if identification is not None:
        statuts: dict[str, int] = {}
        types: dict[str, int] = {}
        for element in identification.elements:
            statuts[element.statut] = statuts.get(element.statut, 0) + 1
            types[element.type] = types.get(element.type, 0) + 1
        print("identification: " + " ".join(f"{k}={v}" for k, v in sorted(statuts.items()))
              + f" | expressions={len(identification.expressions)} | sources={','.join(identification.identificateurs)}")
        print("types: " + " ".join(f"{k}={v}" for k, v in sorted(types.items(), key=lambda item: -item[1])))
        print(f"identification_catalogue={args.docx_out.with_suffix('.identification.json')}")
        print(f"types_pdf={_types_out(args)}")
    print("durees: " + " ".join(f"{nom}={valeur:.1f}s" for nom, valeur in resultat.durees.items())
          + f" total={sum(resultat.durees.values()):.1f}s")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Segmente le PDF, enregistre ses caracteristiques et produit le PDF et le DOCX des bboxes."
    )
    parser.add_argument("source_pdf", type=Path)
    parser.add_argument("--pdf-out", type=Path, required=True)
    parser.add_argument("--docx-out", type=Path, required=True)
    parser.add_argument(
        "--pages", default="all",
        help="pages a traiter : all, 3, 1-5, 1,4,7-9 ; les pages au-dela du document sont ignorees",
    )
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
        "--granularite", choices=("fine", "blocs"), default="blocs",
        help="fine : lignes et details des images ; blocs : paragraphes et images entieres",
    )
    parser.add_argument("--types-out", type=Path, default=None,
                        help="PDF annote par type (defaut : <pdf-out>_types.pdf)")
    parser.add_argument("--ocr-images", action="store_true",
                        help="lire aussi par OCR le texte des images des pages natives (lent ; defaut : seulement les pages sans texte natif)")
    parser.add_argument("--sans-ia-identification", action="store_true",
                        help="identification sans SmolVLM ni PP-FormulaNet (regles, PaddleX et OCR seulement)")
    args = parser.parse_args()

    resultat = segmenter(args.source_pdf, _options(args))
    debut = perf_counter()
    enregistrer_catalogue(resultat, args.source_pdf, args.docx_out.with_suffix(".extraction.json"))
    records = annotate_pdf_bboxes(args.source_pdf, args.pdf_out, resultat.boites())
    write_bbox_docx(resultat.document, args.docx_out, records)
    resultat.durees["sorties"] = perf_counter() - debut
    debut = perf_counter()
    ia = None if args.sans_ia_identification else "auto"
    identification = identifier(resultat, args.source_pdf, vision=ia, formulenet=ia,
                                model_root=args.ai_models_root or args.layout_model_root)
    enregistrer_identification(identification, args.source_pdf, args.docx_out.with_suffix(".identification.json"))
    annoter_pdf_types(args.source_pdf, _types_out(args), identification)
    resultat.durees["identification"] = perf_counter() - debut
    _rapporter(resultat, records, args, identification)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
