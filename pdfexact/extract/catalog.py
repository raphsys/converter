"""Persistance complète de l'extraction texte PDF.

Le catalogue conserve l'IR utile au rendu et à l'audit sans sérialiser les octets
binaires des polices. Toutes les coordonnées sont présentes en EMU (repère Word)
et en points PDF, et chaque ligne/span conserve la bbox du conteneur qui le porte.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pdfexact.geometry import BBox, emu_vers_pt
from pdfexact.ir import Document, FlowParagraph, Span, TextBox


def _bbox(value: BBox | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "emu": {"x0": value.x0, "y0": value.y0, "x1": value.x1, "y1": value.y1,
                "width": value.largeur, "height": value.hauteur},
        "pt": {"x0": emu_vers_pt(value.x0), "y0": emu_vers_pt(value.y0),
               "x1": emu_vers_pt(value.x1), "y1": emu_vers_pt(value.y1),
               "width": emu_vers_pt(value.largeur), "height": emu_vers_pt(value.hauteur)},
    }


def _points(points) -> list[list[int]]:
    return [[int(x), int(y)] for x, y in (points or ())]


def _text_geometry(element) -> dict[str, Any]:
    geometry = getattr(element, "geometry", None)
    if geometry is None:
        return {}
    return {
        "kind": geometry.kind,
        "line_bboxes": [_bbox(value) for value in geometry.line_bboxes],
        "line_quads": [_points(value) for value in geometry.line_quads],
        "baselines": [_points(value) for value in geometry.baselines],
        "exclusion_bboxes": [_bbox(value) for value in geometry.exclusion_bboxes],
    }


def _font_ref(span: Span) -> dict[str, Any]:
    return {
        "font_id": span.police.font_id,
        "family": span.police.famille,
        "bold": span.police.gras,
        "italic": span.police.italique,
    }


def _span(span: Span, *, span_id: str, line_bbox: BBox, element_bbox: BBox) -> dict[str, Any]:
    return {
        "id": span_id,
        "text": span.texte,
        "bbox": _bbox(span.bbox),
        "line_bbox": _bbox(line_bbox),
        "element_bbox": _bbox(element_bbox),
        "font": _font_ref(span),
        "size_pt": span.size_pt,
        "color": span.couleur,
        "character_spacing_twips": span.espacement_twips,
        "link": span.lien,
        "invisible": span.invisible,
        "underline": span.souligne,
        "strike": span.barre,
        "small_caps": span.capitales,
        "superscript": span.exposant,
        "subscript": span.indice,
        "highlight": span.surlignage,
        "quad": _points(span.quad),
        "source_id": span.source_id,
        "angle_deg": span.angle_deg,
        "orientation": span.orientation,
        "baseline_points": _points(span.baseline_points),
        "semantic_role": span.semantic_role,
        "curved": span.curved,
    }


def _line(line, *, line_id: str, element_bbox: BBox) -> dict[str, Any]:
    return {
        "id": line_id,
        "text": "".join(span.texte for span in line.spans),
        "bbox": _bbox(line.bbox),
        "container_bbox": _bbox(element_bbox),
        "height_emu": line.hauteur_ligne_emu,
        "target_width_emu": line.largeur_cible_emu,
        "alignment": line.alignement,
        "layout_frame_id": line.layout_frame_id,
        "layout_frame_role": line.layout_frame_role,
        "layout_frame_strategy": line.layout_frame_strategy,
        "layout_frame_bbox": _bbox(line.layout_frame_bbox),
        "source_id": line.source_id,
        "angle_deg": line.angle_deg,
        "orientation": line.orientation,
        "baseline_points": _points(line.baseline_points),
        "semantic_role": line.semantic_role,
        "z_index": line.z_index,
        "curved": line.curved,
        "quad": _points(line.quad),
        "spans": [
            _span(span, span_id=f"{line_id}-run-{index + 1}", line_bbox=line.bbox, element_bbox=element_bbox)
            for index, span in enumerate(line.spans)
        ],
    }


def _text_element(element, *, element_id: str, page_index: int, index: int) -> dict[str, Any]:
    lignes = list(getattr(element, "lignes", ()) or ())
    if isinstance(element, FlowParagraph):
        text = element.texte
    else:
        text = "\n".join("".join(span.texte for span in line.spans) for line in lignes)
    return {
        "id": element_id,
        "page_index": page_index,
        "element_index": index,
        "kind": type(element).__name__,
        "text": text,
        "bbox": _bbox(element.bbox),
        "layout_frame_id": getattr(element, "layout_frame_id", None),
        "layout_frame_role": getattr(element, "layout_frame_role", None),
        "layout_frame_strategy": getattr(element, "layout_frame_strategy", None),
        "layout_frame_bbox": _bbox(getattr(element, "layout_frame_bbox", None)),
        "source_id": getattr(element, "source_id", None),
        "source_ids": list(getattr(element, "source_ids", ()) or ()),
        "angle_deg": getattr(element, "angle_deg", 0.0),
        "orientation": getattr(element, "orientation", "horizontal"),
        "baseline_points": _points(getattr(element, "baseline_points", ())),
        "semantic_role": getattr(element, "semantic_role", None),
        "z_index": getattr(element, "z_index", None),
        "curved": getattr(element, "curved", False),
        "list_marker": getattr(element, "list_marker", None),
        "list_level": getattr(element, "list_level", 0),
        "list_group_id": getattr(element, "list_group_id", None),
        "list_marker_bbox": _bbox(getattr(element, "list_marker_bbox", None)),
        "geometry": _text_geometry(element),
        "presentation": dict(getattr(element, "presentation", {}) or {}),
        "lines": [
            _line(line, line_id=f"{element_id}-line-{line_index + 1}", element_bbox=element.bbox)
            for line_index, line in enumerate(lignes)
        ],
    }


def _font_asset(asset) -> dict[str, Any]:
    path = str(asset.chemin) if asset.chemin else None
    file_info: dict[str, Any] | None = None
    if path:
        try:
            file_path = Path(path)
            data = file_path.read_bytes()
            file_info = {"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        except OSError:
            file_info = {"path": path, "size": None, "sha256": None}
    return {
        "font_id": asset.font_id,
        "family": asset.famille,
        "embedded_in_pdf": asset.embarquee,
        "embedded_data_present": asset.donnees is not None,
        "embedded_data_size": len(asset.donnees) if asset.donnees is not None else 0,
        "extension": asset.extension,
        "recognized": asset.reconnue,
        "resolution_mode": asset.mode_resolution,
        "resolution_confidence": asset.confiance_resolution,
        "resolution_alias": asset.alias_resolution,
        "metrics": dict(asset.metriques),
        "resolved_file": file_info,
    }


def construire_catalogue(
    document: Document,
    *,
    source_pdf: str | Path,
    extraction_mode: str = "pdf-native",
    page_rotations: dict[int, int] | None = None,
) -> dict[str, Any]:
    """Construit un document JSON complet et stable à partir de l'IR extraite."""
    pages: list[dict[str, Any]] = []
    for page in document.pages:
        elements: list[dict[str, Any]] = []
        for index, element in enumerate(page.elements):
            if not isinstance(element, (TextBox, FlowParagraph)):
                continue
            element_id = str(getattr(element, "source_id", None) or f"p{page.index + 1}-text-{index + 1}")
            elements.append(_text_element(element, element_id=element_id, page_index=page.index, index=index))
        pages.append({
            "index": page.index,
            "page_number": page.index + 1,
            "width_emu": page.largeur_emu,
            "height_emu": page.hauteur_emu,
            "width_pt": emu_vers_pt(page.largeur_emu),
            "height_pt": emu_vers_pt(page.hauteur_emu),
            "rotation_deg": int((page_rotations or {}).get(page.index, 0)),
            "text_elements": elements,
        })
    return {
        "schema": "pdfexact.text-extraction.v1",
        "source_pdf": str(Path(source_pdf).resolve()),
        "extraction_mode": extraction_mode,
        "coordinate_system": {
            "origin": "top-left",
            "units_primary": "EMU",
            "units_secondary": "PDF points",
            "emu_per_point": 12700,
        },
        "pages": pages,
        "fonts": {key: _font_asset(asset) for key, asset in sorted(document.polices.items())},
        "totals": {
            "pages": len(pages),
            "text_elements": sum(len(page["text_elements"]) for page in pages),
            "lines": sum(len(element["lines"]) for page in pages for element in page["text_elements"]),
            "runs": sum(len(line["spans"]) for page in pages for element in page["text_elements"] for line in element["lines"]),
        },
    }


def enregistrer_catalogue(catalogue: dict[str, Any], destination) -> None:
    """Ecrit le catalogue de façon atomique, lisible et UTF-8."""
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(catalogue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
