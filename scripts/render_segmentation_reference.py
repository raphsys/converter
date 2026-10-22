#!/usr/bin/env python3
"""Dessine une reference visuelle explicite, independante de l'extraction automatique."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pymupdf


COLORS = {
    "background": (0.95, 0.65, 0.10),
    "text": (1.0, 0.15, 0.65),
    "logo": (0.25, 0.95, 0.35),
    "figure": (0.05, 0.85, 1.0),
}


def render_reference(source_path: Path, reference_path: Path, destination: Path) -> None:
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    if reference["coordinate_space"] != "page-visible-canonical":
        raise ValueError("La reference doit utiliser le repere visible canonique")
    with pymupdf.open(source_path) as source, pymupdf.open() as output:
        index = reference["page_index"]
        source_page = source[index]
        width, height = reference["page_size_pt"]
        if abs(source_page.rect.width - width) > 0.01 or abs(source_page.rect.height - height) > 0.01:
            raise ValueError("Dimensions de reference incompatibles avec la page source")

        output.insert_pdf(source, from_page=index, to_page=index)
        page = output[0]
        page.remove_rotation()
        for region in reference["regions"]:
            rect = pymupdf.Rect(region["bbox_pt"])
            if rect.is_empty or not page.rect.contains(rect):
                raise ValueError(f"Bbox hors page: {region['id']}")
            color = COLORS[region["role"]]
            background = region["role"] == "background"
            page.draw_rect(rect, color=color, width=0.8 if background else 1.2,
                           dashes="[3 2] 0" if background else None, overlay=True)
            tag = pymupdf.Rect(rect.x0, max(0, rect.y0 - 11), rect.x0 + 20, rect.y0)
            page.draw_rect(tag, color=color, fill=color, width=0, overlay=True)
            page.insert_text((tag.x0 + 3, tag.y1 - 2.5), region["id"],
                             fontsize=8, fontname="hebo", color=(0, 0, 0))

        page.insert_text((36, height - 17),
                         "Codex - segmentation visuelle de reference | 01-10: objets | F1-F2: fonds",
                         fontsize=8, color=(0.15, 0.15, 0.15))
        legend = output.new_page(width=width, height=height)
        legend.insert_text((36, 45), "Segmentation visuelle de reference - Codex", fontsize=18)
        legend.insert_text((36, 70),
                           f"Page {index + 1} source: {width} x {height} pt. Bords visuels estimes par inspection.",
                           fontsize=10)
        y = 106
        for region in reference["regions"]:
            legend.insert_text((36, y), f"{region['id']}  {region['label']}", fontsize=11)
            legend.insert_text((60, y + 15),
                               f"role={region['role']} ; bbox_pt={region['bbox_pt']}",
                               fontsize=9, color=(0.35, 0.35, 0.35))
            y += 34
        legend.insert_text((36, y + 8),
                           "Reference de benchmark. Les coordonnees ne pilotent pas la reconstruction automatique.",
                           fontsize=9)
        destination.parent.mkdir(parents=True, exist_ok=True)
        output.save(destination, garbage=4, deflate=True)
        output[0].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).save(destination.with_suffix(".png"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_pdf", type=Path)
    parser.add_argument("reference_json", type=Path)
    parser.add_argument("destination_pdf", type=Path)
    args = parser.parse_args()
    render_reference(args.source_pdf, args.reference_json, args.destination_pdf)
    print(args.destination_pdf)


if __name__ == "__main__":
    main()
