"""Modeles stables pour l'analyse de mise en page."""
from __future__ import annotations

from dataclasses import dataclass, field

from pdfexact.geometry import BBox


@dataclass(frozen=True)
class LayoutBlock:
    kind: str
    bbox: BBox
    source: str
    text: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class LayoutRegion:
    kind: str
    bbox: BBox
    confidence: float
    editable: bool
    strategy: str
    children: tuple["LayoutRegion", ...] = ()
    style_hints: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ProtectedZone:
    kind: str
    bbox: BBox
    source: str
    protect_ocr: bool = True
    protect_layout: bool = True


@dataclass(frozen=True)
class LayoutPage:
    page_index: int
    width: int
    height: int
    rotation: int
    text_blocks: tuple[LayoutBlock, ...] = ()
    image_blocks: tuple[LayoutBlock, ...] = ()
    drawing_blocks: tuple[LayoutBlock, ...] = ()
    table_candidates: tuple[LayoutBlock, ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)

    def native_line_bboxes(self) -> list[BBox]:
        lignes: list[BBox] = []
        for block in self.text_blocks:
            lignes.extend(block.metadata.get("line_bboxes", ()))
        return lignes

    def resume(self) -> str:
        return (
            "layout-page: "
            f"text={len(self.text_blocks)}, "
            f"images={len(self.image_blocks)}, "
            f"drawings={len(self.drawing_blocks)}, "
            f"tables={len(self.table_candidates)}"
        )
