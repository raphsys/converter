"""Decision universelle de representation DOCX."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from pdfexact.analysis.options import AnalysisOptions
from pdfexact.scene import ElementKind, ElementRecord
from pdfexact.analysis.text_geometry import SPECIAL_ORIENTATIONS


class RenderMode(str, Enum):
    NATIVE_FLOW = "native-flow"
    NATIVE_LIST = "native-list"
    NATIVE_TABLE = "native-table"
    POSITIONED_TEXT = "positioned-text"
    EDITABLE_FRAME = "editable-frame"
    LOCKED_NATIVE_PARAGRAPH = "locked-native-paragraph"
    ROTATED_NATIVE_TEXT = "rotated-native-text"
    CURVED_TEXT = "curved-text"
    ANCHORED_IMAGE = "anchored-image"
    ANCHORED_SHAPE = "anchored-shape"
    LOCAL_RASTER = "local-raster"
    KEEP_BOTH_AMBIGUOUS = "keep-both-ambiguous"


@dataclass(frozen=True)
class RenderDecision:
    element_id: str
    mode: RenderMode
    reason_codes: tuple[str, ...]
    confidence: float
    editable: bool
    fallback_mode: RenderMode | None = None
    constraints: tuple[str, ...] = ()
    expected_bbox: object | None = None
    expected_orientation: str | None = None
    expected_z_order: int | None = None
    expected_style: dict[str, object] = field(default_factory=dict)
    requires_verification: bool = True
    expected_angle_deg: float | None = None
    safe_reflow: bool = False


def _text_flow_is_safe(element: ElementRecord, options: AnalysisOptions) -> bool:
    return (
        element.orientation in {"horizontal", "unknown"}
        and element.attributes.get("geometry_kind", "rectangular-flow") == "rectangular-flow"
        and bool(element.attributes.get("paragraph_confirmed", False))
        # Flow in the document body cannot preserve a PDF column/frame.  A
        # paragraph may still reflow normally inside its positioned textbox;
        # only the page-level container is locked.
        and not element.attributes.get("geometry_locked", False)
        and element.semantic_confidence is not None
        and element.semantic_confidence >= options.extra.get("native_flow_min_confidence", options.native_flow_min_confidence)
        and not element.attributes.get("has_conflicting_overlap", False)
        and not element.attributes.get("preserve_line_boundaries", False)
        and not element.attributes.get("curved", False)
        and element.role not in {"caption", "credit", "label", "annotation", "diagram_text", "figure_text"}
    )


def _decision(
    element: ElementRecord,
    mode: RenderMode,
    reason_codes: tuple[str, ...],
    confidence: float,
    editable: bool,
    fallback_mode: RenderMode | None = None,
    constraints: tuple[str, ...] = (),
) -> RenderDecision:
    """Build a self-verifying decision from the source element snapshot."""
    return RenderDecision(
        element.element_id,
        mode,
        reason_codes,
        confidence,
        editable,
        fallback_mode,
        constraints,
        expected_bbox=element.bbox,
        expected_orientation=element.orientation,
        expected_z_order=element.z_order,
        expected_style=dict(element.style),
        expected_angle_deg=element.angle_deg,
        safe_reflow=mode is RenderMode.NATIVE_FLOW,
    )


def decider_mode_universel(
    element: ElementRecord,
    scene=None,
    options: AnalysisOptions | None = None,
) -> RenderDecision:
    """Choisit une representation a partir d'un contrat, jamais d'un type de PDF."""
    # Compatibilité avec l'ancien appel (element, options).
    if isinstance(scene, AnalysisOptions) and options is None:
        options, scene = scene, None
    options = options or AnalysisOptions()
    confidence = min(value if value is not None else 0.0 for value in (
        element.confidence, element.geometry_confidence, element.semantic_confidence,
    ))
    if element.kind is ElementKind.TABLE:
        return _decision(element, RenderMode.NATIVE_TABLE, ("table-record",), confidence, True)
    if element.kind is ElementKind.IMAGE:
        return _decision(element, RenderMode.ANCHORED_IMAGE, ("image-record",), confidence, False)
    if element.kind is ElementKind.SHAPE:
        return _decision(element, RenderMode.ANCHORED_SHAPE, ("shape-record",), confidence, True)
    if element.kind is ElementKind.RASTER_COMPOSITE:
        if not options.extra.get("allow_local_raster_fallback", options.allow_local_raster_fallback):
            return _decision(element, RenderMode.KEEP_BOTH_AMBIGUOUS, ("raster-fallback-forbidden",), confidence, False,
                             constraints=("materialization-forbidden",))
        return _decision(element, RenderMode.LOCAL_RASTER, ("explicit-composite",), confidence, False)
    if element.kind is ElementKind.LINK:
        return _decision(element, RenderMode.POSITIONED_TEXT, ("link-zone",), confidence, True)
    if element.kind is ElementKind.TEXT:
        if element.attributes.get("source_paint_layered"):
            return _decision(element, RenderMode.EDITABLE_FRAME, ("source-paint-layers",), confidence, True)
        if element.orientation in SPECIAL_ORIENTATIONS or bool(element.attributes.get("curved")):
            if element.orientation == "curved" or bool(element.attributes.get("curved")):
                mode = RenderMode.CURVED_TEXT
                reason = ("curved-geometry",)
            elif element.orientation in {"vertical", "vertical-lr", "vertical-rl", "vertical-rtl", "rotated"}:
                mode = RenderMode.ROTATED_NATIVE_TEXT
                reason = ("orientation-sensitive",)
            else:
                mode = RenderMode.LOCKED_NATIVE_PARAGRAPH
                reason = ("oblique-geometry",)
            fallback = RenderMode.LOCAL_RASTER if options.allow_local_raster_fallback else None
            return _decision(element, mode, reason, confidence, True, fallback)
        if options.extra.get("preserve_line_boundaries", options.preserve_line_boundaries) == "always":
            return _decision(element, RenderMode.LOCKED_NATIVE_PARAGRAPH, ("preserve-line-boundaries",), confidence, True)
        if element.role in {"caption", "credit", "label", "annotation", "diagram_text", "figure_text"}:
            return _decision(element, RenderMode.LOCKED_NATIVE_PARAGRAPH, ("geometry-sensitive-role",), confidence, True)
        if element.attributes.get("list_marker") or element.role in {"list", "list-item"}:
            return _decision(element, RenderMode.NATIVE_LIST, ("list-structure",), confidence, True)
        if element.attributes.get("geometry_kind", "rectangular-flow") != "rectangular-flow":
            return _decision(
                element,
                RenderMode.LOCKED_NATIVE_PARAGRAPH,
                ("irregular-text-geometry",),
                confidence,
                True,
            )
        if element.attributes.get("page_geometry_locked"):
            return _decision(
                element,
                RenderMode.LOCKED_NATIVE_PARAGRAPH,
                ("page-geometry-locked",),
                confidence,
                True,
            )
        if _text_flow_is_safe(element, options):
            return _decision(element, RenderMode.NATIVE_FLOW, ("safe-native-flow",), confidence, True)
        if element.attributes.get("ambiguous"):
            return _decision(element, RenderMode.KEEP_BOTH_AMBIGUOUS, ("ambiguous-source",), confidence, True)
        return _decision(element, RenderMode.POSITIONED_TEXT, ("geometry-preserved",), confidence, True)
    return _decision(element, RenderMode.KEEP_BOTH_AMBIGUOUS, ("unknown-kind",), confidence, False)






def validate_decision(decision: RenderDecision) -> list[str]:
    errors: list[str] = []
    if not decision.element_id:
        errors.append("missing-element-id")
    if not decision.reason_codes or not all(reason.strip() for reason in decision.reason_codes):
        errors.append("missing-decision-reasons")
    if not 0.0 <= decision.confidence <= 1.0:
        errors.append("invalid-confidence")
    if decision.mode is RenderMode.LOCAL_RASTER and decision.editable:
        errors.append("raster-cannot-be-fully-editable")
    if not decision.requires_verification:
        errors.append("verification-required")
    if decision.expected_bbox is None or decision.expected_orientation is None or decision.expected_z_order is None or decision.expected_angle_deg is None:
        errors.append("missing-expected-contract")
    if "materialization-forbidden" in decision.constraints:
        errors.append("materialization-forbidden")
    return errors


def verifier_decision(decision: RenderDecision, element: ElementRecord) -> list[str]:
    errors = validate_decision(decision)
    if decision.element_id != element.element_id:
        errors.append("decision-element-mismatch")
    if decision.expected_orientation and decision.expected_orientation != element.orientation:
        errors.append("decision-orientation-mismatch")
    if decision.expected_bbox is not None and decision.expected_bbox != element.bbox:
        errors.append("decision-bbox-mismatch")
    if decision.expected_z_order is not None and decision.expected_z_order != element.z_order:
        errors.append("decision-z-order-mismatch")
    if decision.expected_angle_deg is not None and decision.expected_angle_deg != element.angle_deg:
        errors.append("decision-angle-mismatch")
    return errors


def decision_is_lossless(decision: RenderDecision) -> bool:
    return decision.mode not in {RenderMode.LOCAL_RASTER, RenderMode.KEEP_BOTH_AMBIGUOUS}
