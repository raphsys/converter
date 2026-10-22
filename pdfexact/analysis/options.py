"""Options explicites partagees par toute la chaine d'analyse.

Une option modifie une politique documentee. Elle ne peut jamais desactiver la
tracabilite ou rendre la perte d'un element silencieuse.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AnalysisOptions:
    """Politique universelle d'observation, de reconstruction et de controle."""

    use_native_pdf_text: bool = True
    ocr_provider: str = "rapidocr"
    ocr_granularity: str = "line"
    use_layout_ai: bool = True
    layout_provider: str | None = None
    language: str = "auto"
    script: str = "auto"
    detect_orientation: bool = True
    detect_curved_text: bool = True
    detect_z_order: bool = True
    preserve_reading_order: bool = True
    preserve_line_boundaries: str = "auto"
    allow_local_raster_fallback: bool = True
    # Nom du plan d'architecture. L'ancien nom reste accepté pour ne pas casser
    # les appels existants pendant la migration.
    allow_raster_fallback: bool | None = None
    target_reader: str = "word"
    visual_priority: float = 0.8
    editability_priority: float = 0.8
    native_flow_min_confidence: float = 0.86
    semantic_group_min_confidence: float = 0.72
    semantic_vertical_gap_factor: float = 1.8
    semantic_sentence_gap_factor: float = 0.55
    semantic_cross_frame_gap_factor: float = 1.75
    semantic_overlap_gap_factor: float = 0.35
    semantic_column_overlap_min: float = 0.35
    semantic_list_y_factor: float = 1.6
    semantic_list_x_gap_emu: int = 381000
    geometry_tolerance_emu: int = 12700
    max_repair_passes: int = 2
    extra: dict[str, object] = field(default_factory=dict)
    ocr_language: str = "auto"
    ai_models_root: str | None = None

    def __post_init__(self) -> None:
        for name in ("visual_priority", "editability_priority"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} doit etre compris entre 0 et 1")
        if self.preserve_line_boundaries not in {"auto", "always", "never"}:
            raise ValueError("preserve_line_boundaries doit valoir auto, always ou never")
        if self.max_repair_passes < 0:
            raise ValueError("max_repair_passes ne peut pas etre negatif")
        for name in (
            "native_flow_min_confidence",
            "semantic_group_min_confidence",
            "semantic_vertical_gap_factor",
            "semantic_sentence_gap_factor",
            "semantic_cross_frame_gap_factor",
            "semantic_overlap_gap_factor",
            "semantic_column_overlap_min",
            "semantic_list_y_factor",
        ):
            if float(getattr(self, name)) < 0:
                raise ValueError(f"{name} ne peut pas etre negatif")
        if self.allow_raster_fallback is not None:
            object.__setattr__(
                self,
                "allow_local_raster_fallback",
                bool(self.allow_raster_fallback),
            )


@dataclass(frozen=True)
class PackageOptions:
    """Options d'emballage OOXML sans decision semantique."""

    embed_fonts: bool = True
    include_scene_manifest: bool = True
    validate_xml: bool = True


@dataclass(frozen=True)
class AuditOptions:
    """Niveau de verification de sortie."""

    level: str = "element"
    dpi: int = 150
    fail_on_missing_element: bool = True
    fail_on_unverified_element: bool = False

    def __post_init__(self) -> None:
        if self.level not in {"basic", "zone", "element"}:
            raise ValueError("level doit valoir basic, zone ou element")
        if self.dpi <= 0:
            raise ValueError("dpi doit etre positif")
