"""Dessine les bboxes de layout sur un PDF pour auditer la detection."""
from __future__ import annotations

import argparse
from pathlib import Path

import pymupdf

from pdfexact.geometry import BBox, PageGeometry, emu_vers_pt
from pdfexact.layout import (
    analyser_page,
    classer_regions,
    comprendre_page,
    detecter_layout_ia,
    planifier_regions,
    zones_layout_du_plan,
    zones_ocr_du_plan,
    zones_protegees_du_plan,
)


LEVELS = (
    "raw-blocks",
    "native-lines",
    "classified",
    "understanding",
    "plan",
    "protected",
    "ai",
    "all",
)

COLORS = {
    "TEXT": (0.0, 0.75, 0.0),
    "LINE": (0.45, 0.85, 0.15),
    "IMAGE": (1.0, 0.0, 0.0),
    "DRAWING": (1.0, 0.55, 0.0),
    "TABLE": (0.55, 0.0, 1.0),
    "CLASS": (0.0, 0.35, 1.0),
    "UNDERSTAND": (0.0, 0.75, 0.85),
    "PLAN": (0.95, 0.0, 0.65),
    "OCR": (1.0, 0.0, 0.0),
    "LAYOUT": (0.0, 0.0, 1.0),
    "AI": (0.0, 0.55, 0.95),
}


def main() -> int:
    args = _parser().parse_args()
    source = Path(args.source)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)

    niveaux = _levels(args.level)
    pages = _pages(args.pages)
    doc = pymupdf.open(source)

    for page_index, page in enumerate(doc):
        if pages is not None and page_index not in pages:
            continue
        geometrie = PageGeometry.depuis_page(page)
        analyse = analyser_page(page, geometrie=geometrie)
        layout_ai = None

        if "ai" in niveaux:
            layout_ai = detecter_layout_ia(
                page,
                analyse,
                provider=args.layout_provider,
                model=args.layout_model,
                model_root=args.layout_model_root,
                device=args.layout_device,
            )

        regions = classer_regions(analyse)
        comprehension = comprendre_page(
            largeur_emu=analyse.width,
            hauteur_emu=analyse.height,
            images=[],
            tableaux=[],
            formes=[],
            zones_rasterisees=[],
            lignes_natives=analyse.native_line_bboxes(),
            zones_ia=layout_ai.zones if layout_ai else None,
        )
        plan = planifier_regions(comprehension.elements)

        if "raw-blocks" in niveaux:
            _draw_raw_blocks(page, analyse)
        if "native-lines" in niveaux:
            for index, bbox in enumerate(analyse.native_line_bboxes(), 1):
                _draw(page, bbox, f"LINE#{index}", "LINE", width=0.45, fontsize=4)
        if "classified" in niveaux:
            for index, region in enumerate(regions, 1):
                _draw(page, region.bbox, f"CLASS#{index} {region.kind}", "CLASS", width=0.8)
        if "understanding" in niveaux:
            for index, element in enumerate(comprehension.elements, 1):
                label = f"UNDER#{index} {element.role}/{element.strategy}"
                _draw(page, element.bbox, label, "UNDERSTAND", width=0.8)
        if "plan" in niveaux:
            for index, item in enumerate(plan, 1):
                label = f"PLAN#{index} {item.kind}/{item.strategy}"
                _draw(page, item.bbox, label, "PLAN", width=0.8)
        if "protected" in niveaux:
            for index, zone in enumerate(zones_protegees_du_plan(plan), 1):
                kind = "OCR" if zone.protect_ocr else "LAYOUT"
                label = f"PROTECT#{index} {zone.kind} ocr={int(zone.protect_ocr)} layout={int(zone.protect_layout)}"
                _draw(page, zone.bbox, label, kind, width=1.0)
            for index, bbox in enumerate(zones_ocr_du_plan(plan), 1):
                _draw(page, bbox, f"OCR-ZONE#{index}", "OCR", width=1.4, fontsize=5)
            for index, bbox in enumerate(zones_layout_du_plan(plan), 1):
                _draw(page, bbox, f"LAYOUT-ZONE#{index}", "LAYOUT", width=1.0, fontsize=5)
        if "ai" in niveaux and layout_ai is not None:
            _draw_status(page, layout_ai.status, len(layout_ai.zones), layout_ai.warnings)
            for index, zone in enumerate(layout_ai.zones, 1):
                score = "?" if zone.confidence is None else f"{zone.confidence:.2f}"
                label = f"AI#{index} {zone.label}/{zone.role} {score}"
                _draw(page, zone.bbox, label, "AI", width=1.2)

    doc.save(destination)
    doc.close()
    print(destination)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="PDF source")
    parser.add_argument("output", help="PDF annote en sortie")
    parser.add_argument(
        "--level",
        action="append",
        choices=LEVELS,
        default=[],
        help="niveau a dessiner, repetable. Defaut: raw-blocks",
    )
    parser.add_argument("--pages", help="pages 1-based, ex: 1,2,5-8")
    parser.add_argument("--layout-provider", default=None)
    parser.add_argument("--layout-model", default=None)
    parser.add_argument("--layout-model-root", default=None)
    parser.add_argument("--layout-device", default=None)
    return parser


def _levels(values: list[str]) -> set[str]:
    niveaux = set(values or ["raw-blocks"])
    if "all" in niveaux:
        return set(LEVELS) - {"all"}
    return niveaux


def _pages(expression: str | None) -> set[int] | None:
    if not expression:
        return None
    pages: set[int] = set()
    for morceau in expression.split(","):
        morceau = morceau.strip()
        if not morceau:
            continue
        if "-" in morceau:
            debut, fin = [int(part) for part in morceau.split("-", 1)]
            pages.update(range(debut - 1, fin))
        else:
            pages.add(int(morceau) - 1)
    return pages


def _draw_raw_blocks(page, analyse) -> None:
    items = []
    items += [("TEXT", block.bbox, block.kind) for block in analyse.text_blocks]
    items += [("IMAGE", block.bbox, block.kind) for block in analyse.image_blocks]
    items += [("DRAWING", block.bbox, block.kind) for block in analyse.drawing_blocks]
    items += [("TABLE", block.bbox, block.kind) for block in analyse.table_candidates]
    for index, (kind, bbox, name) in enumerate(items, 1):
        _draw(page, bbox, f"{kind}#{index} {name}", kind)


def _draw(page, bbox: BBox, label: str, color_key: str, *, width: float = 0.8, fontsize: float = 5) -> None:
    rect = _rect(bbox)
    color = COLORS[color_key]
    page.draw_rect(rect, color=color, width=width)
    y = rect.y0 - 2 if rect.y0 > 8 else rect.y0 + fontsize + 1
    page.insert_text((rect.x0, y), label, fontsize=fontsize, color=color)


def _draw_status(page, status: str, zones: int, warnings: tuple[str, ...]) -> None:
    texte = f"LAYOUT_AI status={status} zones={zones}"
    if warnings:
        texte += " warnings=" + ",".join(warnings)
    page.insert_text((8, 10), texte, fontsize=6, color=COLORS["AI"])


def _rect(bbox: BBox) -> pymupdf.Rect:
    return pymupdf.Rect(
        emu_vers_pt(bbox.x0),
        emu_vers_pt(bbox.y0),
        emu_vers_pt(bbox.x1),
        emu_vers_pt(bbox.y1),
    )


if __name__ == "__main__":
    raise SystemExit(main())
