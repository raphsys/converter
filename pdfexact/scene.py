"""Scene IR canonique entre extraction, comprehension, rendu et audit."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Iterable

from pdfexact.analysis.geometry import quad_bbox, resolve_text_orientation
from pdfexact.analysis.provenance import ElementRegistry, Evidence
from pdfexact.geometry import BBox


class SourceKind(str, Enum):
    PDF_NATIVE = "pdf-native"
    OCR = "ocr"
    IMAGE = "image"
    VECTOR = "vector"
    LAYOUT_AI = "layout-ai"
    INFERRED = "inferred"


class ElementKind(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    SHAPE = "shape"
    TABLE = "table"
    LINK = "link"
    RASTER_COMPOSITE = "raster-composite"


class VerificationState(str, Enum):
    DETECTED = "detected"
    EXTRACTED = "extracted"
    CLASSIFIED = "classified"
    GROUPED = "grouped"
    PLANNED = "planned"
    RENDERED = "rendered"
    VERIFIED = "verified"
    WARNING = "warning"
    FAILED = "failed"
    NON_REPRESENTABLE = "non-representable"


@dataclass
class ElementRecord:
    element_id: str
    page_index: int
    kind: ElementKind
    bbox: BBox | None
    source_kind: SourceKind
    source_ids: tuple[str, ...] = ()
    role: str = "unknown"
    text: str = ""
    quad: tuple[tuple[int, int], ...] = ()
    polygon: tuple[tuple[int, int], ...] = ()
    baseline: tuple[tuple[int, int], ...] = ()
    angle_deg: float = 0.0
    orientation: str = "unknown"
    z_order: int = 0
    opacity: float = 1.0
    clip_ids: tuple[str, ...] = ()
    language: str = "auto"
    script: str = "auto"
    confidence: float | None = None
    role_confidence: float | None = None
    geometry_confidence: float | None = None
    semantic_confidence: float | None = None
    extraction_confidence: float | None = None
    render_decision: object | None = None
    style: dict[str, Any] = field(default_factory=dict)
    path: tuple[tuple[str, tuple[tuple[int, int], ...]], ...] = ()
    attributes: dict[str, Any] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)
    duplicate_candidates: list[dict[str, Any]] = field(default_factory=list)
    decision_history: list[dict[str, Any]] = field(default_factory=list)
    verification_state: VerificationState = VerificationState.DETECTED
    visual_contract: object | None = None
    raw: object | None = None
    spans: tuple[object, ...] = ()
    font_metrics: dict[str, object] = field(default_factory=dict)
    orientation_points: tuple[tuple[int, int], ...] = ()
    clip_bbox: BBox | None = None
    compositing: dict[str, object] = field(default_factory=dict)
    parent_group_id: str | None = None
    acquisition_raw: object | None = None

    def __post_init__(self) -> None:
        if not self.element_id:
            raise ValueError("element_id obligatoire")
        for name in ("confidence", "role_confidence", "geometry_confidence", "semantic_confidence", "extraction_confidence"):
            value = getattr(self, name)
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} doit etre compris entre 0 et 1")
        if not 0.0 <= self.opacity <= 1.0:
            raise ValueError("opacity doit etre compris entre 0 et 1")
        if self.quad and quad_bbox(self.quad) is None:
            raise ValueError("quad invalide")

    @property
    def is_text(self) -> bool:
        return self.kind is ElementKind.TEXT

    @property
    def is_visual(self) -> bool:
        return self.kind in {
            ElementKind.IMAGE,
            ElementKind.SHAPE,
            ElementKind.RASTER_COMPOSITE,
        }

    def add_evidence(self, evidence: Evidence) -> None:
        self.evidence.append(evidence)

    def snapshot(self) -> dict[str, Any]:
        """Vue stable et sérialisable pour les diagnostics et golden tests."""
        return {item.name: _snapshot_value(getattr(self, item.name)) for item in fields(self)
                if item.name not in {"raw", "acquisition_raw"}}


@dataclass
class PageScene:
    index: int
    width_emu: int
    height_emu: int
    elements: list[ElementRecord] = field(default_factory=list)
    coordinate_space: str = "page-visible-canonical"
    orientation: str = "portrait"
    format_name: str | None = None
    rotation_pdf: int = 0
    registry: ElementRegistry = field(default_factory=ElementRegistry, repr=False)
    source_pdf_id: str | None = None
    options_snapshot: dict[str, object] = field(default_factory=dict)
    ocr_correspondence_page_binding: dict[str, object] | None = None

    def __post_init__(self) -> None:
        for element in self.elements:
            self._register(element)

    def _register(self, element: ElementRecord) -> None:
        if element.page_index != self.index:
            raise ValueError("element page_index incompatible avec PageScene")
        self.registry.register(element)
        element._registry = self.registry
        state = element.verification_state
        if state not in {VerificationState.DETECTED, "detected"}:
            self.registry.record(element.element_id, str(getattr(state, "value", state)))

    def add(self, element: ElementRecord) -> None:
        if element.page_index != self.index:
            raise ValueError("element page_index incompatible avec PageScene")
        self._register(element)
        self.elements.append(element)
        document = getattr(self, "_document", None)
        if document is not None:
            document._register_page(self)

    def ordered_elements(self) -> list[ElementRecord]:
        return sorted(self.elements, key=lambda item: (item.z_order, item.attributes.get("source_acquisition_index", 0)))


@dataclass
class SceneDocument:
    pages: list[PageScene] = field(default_factory=list)
    registry: ElementRegistry = field(default_factory=ElementRegistry)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for page in self.pages:
            self._register_page(page)

    def _register_page(self, page: PageScene) -> None:
        page._document = self
        for element in page.elements:
            self.registry.register(element)
            element._registries = (page.registry, self.registry)
            state = element.verification_state
            if state not in {VerificationState.DETECTED, "detected"}:
                self.registry.record(element.element_id, str(getattr(state, "value", state)))

    def add_page(self, page: PageScene) -> None:
        self.pages.append(page)
        self._register_page(page)

    def all_elements(self) -> Iterable[ElementRecord]:
        for page in self.pages:
            yield from page.elements

    def snapshot(self) -> dict[str, Any]:
        return {
            "pages": [
                {
                    "index": page.index,
                    "width_emu": page.width_emu,
                    "height_emu": page.height_emu,
                    "coordinate_space": page.coordinate_space,
                    "orientation": page.orientation,
                    "format_name": page.format_name,
                    "rotation_pdf": page.rotation_pdf,
                    "elements": [element.snapshot() for element in page.elements],
                    "source_pdf_id": page.source_pdf_id,
                    "options_snapshot": _snapshot_value(page.options_snapshot),
                    "ocr_correspondence_page_binding": _snapshot_value(page.ocr_correspondence_page_binding),
                }
                for page in self.pages
            ],
            "metadata": _snapshot_value(self.metadata),
            "registry_events": _snapshot_value(self.registry.events),
        }


def _kind_for_legacy(element: object) -> ElementKind:
    name = type(element).__name__
    return {
        "FlowParagraph": ElementKind.TEXT,
        "TextBox": ElementKind.TEXT,
        "ImageEl": ElementKind.IMAGE,
        "ShapeEl": ElementKind.SHAPE,
        "RasterEl": ElementKind.RASTER_COMPOSITE,
        "TableEl": ElementKind.TABLE,
        "LinkZone": ElementKind.LINK,
    }.get(name, ElementKind.TEXT)


def _legacy_text(element: object) -> str:
    from pdfexact.ir import element_text

    return element_text(element)


def _snapshot_value(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BBox):
        return [value.x0, value.y0, value.x1, value.y1]
    if is_dataclass(value):
        names = {item.name for item in fields(value)}
        names.update(name for name in vars(value) if not name.startswith("_"))
        return {name: _snapshot_value(getattr(value, name)) for name in sorted(names)}
    if isinstance(value, dict):
        return {str(key): _snapshot_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_snapshot_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_snapshot_value(item) for item in value), key=repr)
    if isinstance(value, bytes):
        return {"sha256": sha256(value).hexdigest(), "length": len(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _children(element):
    for name in ("lignes", "spans", "rows", "cells"):
        yield from getattr(element, name, ()) or ()
    marker = getattr(element, "list_marker_source", None)
    if marker is not None:
        yield marker


def ensure_source_identity(element, page_index, *, source_kind=None, source_pdf_id="", source_token=None):
    """Assign acquisition identity once, independent of later output ordering."""
    if isinstance(element, ElementRecord):
        return element.element_id
    element.source_page_index = page_index
    existing_kind = getattr(element, "source_kind", None)
    observed_kinds = {getattr(getattr(child, "source_kind", None), "value", getattr(child, "source_kind", None))
                      for child in _descendants(element)}
    observed_kinds.difference_update({None, "inferred", "unknown", ""})
    inherited_kind = next(iter(observed_kinds)) if len(observed_kinds) == 1 else None
    kind = getattr(existing_kind or source_kind, "value", existing_kind or source_kind) or inherited_kind or "inferred"
    if not existing_kind:
        setattr(element, "source_kind", kind)
    source_id = getattr(element, "source_id", None)
    if (type(element).__name__ == "Line" and source_token is not None and isinstance(source_id, str)
            and source_id.startswith("line:") and source_id[5:].isdigit()):
        element.attributes["legacy_local_source_id"] = source_id
        element.source_id = None
        source_id = None
    if not source_id:
        signature = {
            "document": source_pdf_id, "page": page_index, "kind": kind,
            "type": type(element).__name__, "token": source_token,
            "geometry": _snapshot_value({name: getattr(element, name, None) for name in (
                "bbox", "quad", "baseline_points", "z_index", "placement_id", "source_xref", "chemins",
            )}),
            "text": _legacy_text(element),
            "style": _snapshot_value({name: getattr(element, name, None) for name in (
                "police", "size_pt", "couleur", "remplissage", "contour", "alpha", "opacity",
            )}),
            "child_paint": [_snapshot_value({name: getattr(child, name, None) for name in (
                "bbox", "texte", "police", "size_pt", "couleur", "alpha", "opacity", "z_index", "quad", "baseline_points",
            )}) for child in _descendants(element)],
        }
        digest = sha256(json.dumps(signature, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:24]
        source_id = f"p{page_index}:{kind}:{type(element).__name__}:{digest}"
        setattr(element, "source_id", source_id)
    aliases = {}
    for index, child in enumerate(_children(element)):
        old_id = getattr(child, "source_id", None)
        ensure_source_identity(child, page_index, source_kind=kind, source_pdf_id=source_pdf_id,
                               source_token=f"{source_id}:{type(child).__name__}:{index}")
        if old_id and old_id != child.source_id:
            aliases[old_id] = child.source_id
    if aliases:
        for name in ("source_ids", "source_line_ids"):
            if hasattr(element, name):
                setattr(element, name, tuple(aliases.get(value, value) for value in getattr(element, name)))
    from pdfexact.ir import element_source_ids

    source_ids = element_source_ids(element)
    setattr(element, "source_ids", source_ids)
    return str(source_id)


def capture_source_observations(page, elements, *, source_kind=None):
    """Keep immutable acquisition copies before grouping, clipping or filtering."""
    if not hasattr(page, "source_inventory"):
        page.source_inventory = {}
    for index, element in enumerate(elements):
        source_id = ensure_source_identity(element, page.index, source_kind=source_kind,
                                           source_pdf_id=getattr(page, "source_pdf_id", None) or "",
                                           source_token=f"acquisition:{len(page.source_inventory)}:{index}")
        nodes = list(dict((id(child), child) for child in (element, *_descendants(element))).values())
        for offset, child in enumerate(nodes):
            if not hasattr(child, "source_acquisition_index"):
                child.source_acquisition_index = len(page.source_inventory) + offset
        for child in nodes:
            child_id = str(getattr(child, "source_id"))
            if child_id not in page.source_inventory:
                page.source_inventory[child_id] = deepcopy(child)
        # The inventory remains raw; subsequent outcomes live in a separate log.
        assert source_id in page.source_inventory


def _descendants(element):
    seen = set()
    for child in _children(element):
        if id(child) in seen:
            continue
        seen.add(id(child))
        yield child
        yield from _descendants(child)


def record_source_transformation(page, sources, outputs, reason_code, **details):
    """Record replacement evidence without declaring an unresolved source lost."""
    if not reason_code:
        raise ValueError("reason_code obligatoire")
    sources, outputs = list(sources), list(outputs)
    capture_source_observations(page, sources)
    for output in outputs:
        ensure_source_identity(output, page.index, source_pdf_id=page.source_pdf_id or "")
    entry = {"event": "transformed", "reason_code": reason_code,
             "source_ids": tuple(getattr(item, "source_id") for item in sources),
             "output_ids": tuple(getattr(item, "source_id") for item in outputs), **details}
    page.source_transformations.append(entry)
    for source in sources:
        if not any(source is item for item in page.elements) and not any(source is item for item in page.discarded_elements):
            page.discarded_elements.append(source)
    return entry


def element_record_from_legacy(element, page_index, *, document=None):
    """The single lossless scene/plan adapter; unknown confidences stay unknown."""
    if isinstance(element, ElementRecord):
        return element
    from pdfexact.ir import element_source_ids

    element_id = ensure_source_identity(element, page_index, source_pdf_id=getattr(document, "source_pdf_id", None) or "")
    children = list(_descendants(element))
    lines = list(getattr(element, "lignes", ()) or ())
    spans = list(getattr(element, "spans", ()) or ())
    if not spans:
        spans = [child for child in children if type(child).__name__ == "Span"]
    kind_value = getattr(element, "source_kind", None)
    kind_value = getattr(kind_value, "value", kind_value) or "inferred"
    source_kind = SourceKind(kind_value)
    presentation = deepcopy(getattr(element, "presentation", {}) or {})
    attributes = deepcopy(getattr(element, "attributes", {}) or {})
    attributes.update({name: deepcopy(getattr(element, name)) for name in (
        "layout_frame_id", "layout_frame_role", "layout_frame_strategy", "layout_frame_bbox",
        "group_id", "grouping_evidence", "paint_group_id", "source_component_ids", "source_placements",
        "source_xrefs", "paint_sequences", "transform", "alpha_preserved", "fallback_reason", "purpose",
        "reading_direction", "boundary_before", "boundary_after", "boundary_before_confidence", "boundary_after_confidence",
        "duplicate_of", "duplicate_verified", "replaces", "transformation", "removed_source_ids", "list_marker_source",
        "outside_page", "replacement_id", "source_line_ids", "grid_evidence", "semantic_table", "associated_text",
        "source_acquisition_index",
    ) if hasattr(element, name)})
    attributes.update({
        "presentation": presentation,
        "paragraph_confirmed": bool(presentation.get("paragraph_validated")),
        "preserve_line_boundaries": bool(presentation.get("preserve_line_boundaries", False)),
        "geometry_kind": getattr(getattr(element, "geometry", None), "kind", "rectangular-flow"),
        "geometry_locked": bool(getattr(element, "layout_frame_id", None) or getattr(element, "layout_frame_bbox", None)),
        "list_marker": getattr(element, "list_marker", None),
        "curved": bool(getattr(element, "curved", False)),
        "line_geometries": [{**_snapshot_value(line), "bbox": _snapshot_value(line.bbox)} for line in lines],
        "source_metadata": _snapshot_value(element),
    })
    runs = [_snapshot_value(span) for span in spans]
    style = deepcopy(getattr(element, "style", {}) or {})
    style.update({name: deepcopy(getattr(element, name)) for name in (
        "alignement", "vertical_alignement", "remplissage", "contour", "epaisseur_emu", "pointilles",
        "retrait_gauche_emu", "retrait_droite_emu", "retrait_premiere_ligne_emu", "espace_avant_emu", "espace_apres_emu", "interligne_emu",
    ) if hasattr(element, name)})
    first_span = spans[0] if spans else element
    font = getattr(first_span, "police", None)
    style.update({name: value for name, value in {
        "font_id": getattr(font, "font_id", None), "font_family": getattr(font, "famille", None),
        "size_pt": getattr(first_span, "size_pt", None), "color": getattr(first_span, "couleur", None),
        "bold": getattr(font, "gras", None), "italic": getattr(font, "italique", None),
        "runs": runs, "presentation": presentation,
    }.items() if value is not None})
    metrics = deepcopy(getattr(element, "font_metrics", {}) or {})
    for span in spans:
        span_font = getattr(span, "police", None)
        font_id = getattr(span_font, "font_id", None)
        asset = getattr(document, "polices", {}).get(font_id) if document is not None else None
        if font_id:
            metrics[font_id] = {
                "metrics": deepcopy(getattr(asset, "metriques", None) or getattr(span, "font_metrics", {})),
                "font_confidence": getattr(asset, "font_confidence", None),
                "metrics_confidence": getattr(asset, "metrics_confidence", None),
                "substitution_source": getattr(asset, "substitution_source", None),
            }
    paint = [getattr(item, "z_index", None) for item in (element, *children)]
    paint = [value for value in paint if value is not None]
    baseline = tuple(getattr(element, "baseline_points", ()) or getattr(element, "baseline", ()) or ())
    quad = tuple(getattr(element, "quad", ()) or ())
    if len(lines) == 1:
        baseline = baseline or tuple(getattr(lines[0], "baseline_points", ()) or ())
        quad = quad or tuple(getattr(lines[0], "quad", ()) or ())
    text_metadata = {}
    for name in ("language", "script"):
        value = getattr(element, name, "auto")
        if value in {None, "auto", "unknown", ""}:
            observed = {getattr(item, name, "auto") for item in (*lines, *spans, *(getattr(span, "police", None) for span in spans))}
            observed.difference_update({None, "auto", "unknown", ""})
            value = observed.pop() if len(observed) == 1 else "auto"
        text_metadata[name] = value
    orientation_geometry = resolve_text_orientation(element)
    angle, orientation = orientation_geometry["angle_deg"], orientation_geometry["orientation"]
    attributes["parent_orientation_geometry"] = orientation_geometry["parent"]
    attributes["geometry_conflicts"] = orientation_geometry["conflicts"]
    source_kinds = tuple(dict.fromkeys(getattr(getattr(item, "source_kind", None), "value", getattr(item, "source_kind", None))
                                     for item in (element, *children)))
    attributes["source_kind_observations"] = tuple(value for value in source_kinds if value)
    attributes["source_kind_conflict"] = len(set(source_kinds) - {None, "inferred", "unknown", ""}) > 1
    paths = tuple(command for path in getattr(element, "chemins", ()) for command in path)
    opacity = getattr(element, "alpha", None)
    if opacity is None:
        opacity = getattr(element, "opacity", 1.0)
    state = getattr(element, "verification_state", VerificationState.DETECTED)
    state = VerificationState(getattr(state, "value", state))
    record = ElementRecord(
        element_id=element_id, page_index=page_index, kind=_kind_for_legacy(element), bbox=element.bbox,
        source_kind=source_kind, source_ids=element_source_ids(element),
        role=getattr(element, "semantic_role", None) or getattr(element, "layout_frame_role", None) or "unknown",
        text=_legacy_text(element), quad=quad, polygon=tuple(getattr(element, "polygon", ()) or ()),
        baseline=baseline, orientation_points=tuple(getattr(element, "orientation_points", ()) or baseline),
        angle_deg=angle, orientation=orientation, language=text_metadata["language"], script=text_metadata["script"],
        z_order=getattr(element, "z_index", None) if getattr(element, "z_index", None) is not None else min(paint) if paint else 0,
        opacity=opacity,
        clip_ids=tuple(getattr(element, "clip_ids", ()) or ()), clip_bbox=getattr(element, "clip_bbox", None),
        confidence=getattr(element, "confidence", None), role_confidence=getattr(element, "role_confidence", None),
        geometry_confidence=getattr(element, "geometry_confidence", None),
        semantic_confidence=getattr(element, "semantic_confidence", None), extraction_confidence=getattr(element, "extraction_confidence", None),
        render_decision=getattr(element, "render_decision", None), style=style, path=tuple(getattr(element, "path", ()) or paths),
        spans=tuple(deepcopy(spans)), font_metrics=metrics, attributes=attributes,
        compositing=deepcopy(getattr(element, "compositing", {}) or {}),
        parent_group_id=getattr(element, "parent_group_id", None),
        evidence=deepcopy(getattr(element, "evidence", ()) or []),
        duplicate_candidates=deepcopy(getattr(element, "duplicate_candidates", ()) or []),
        decision_history=deepcopy(getattr(element, "decision_history", ()) or []), verification_state=state, raw=element,
    )
    record.visual_contract = {name: deepcopy(getattr(record, name)) for name in (
        "bbox", "quad", "polygon", "path", "baseline", "orientation_points", "z_order", "orientation",
        "angle_deg", "opacity", "clip_ids", "clip_bbox", "compositing", "parent_group_id", "style", "font_metrics", "source_ids",
    )}
    if record.bbox is None:
        record.attributes["geometry_missing"] = True
    if orientation_geometry["conflicts"]:
        record.evidence.append(Evidence("geometry-conflict", "pdfexact.analysis.geometry.resolve_text_orientation", None,
                                        (("observations", orientation_geometry["conflicts"]),)))
    if attributes["source_kind_conflict"]:
        record.evidence.append(Evidence("source-kind-conflict", "pdfexact.scene.element_record_from_legacy", None,
                                        (("observations", attributes["source_kind_observations"]),)))
    return record


def scene_from_legacy_document(document: object) -> SceneDocument:
    """Register acquisition metadata without taking a rendering decision."""
    result = SceneDocument(metadata={"source_pdf_id": getattr(document, "source_pdf_id", None),
                                     "options_snapshot": deepcopy(getattr(document, "options_snapshot", {}))})
    for page in getattr(document, "pages", ()):
        scene_page = PageScene(
            page.index,
            page.largeur_emu,
            page.hauteur_emu,
            coordinate_space=getattr(page, "coordinate_space", "page-visible-canonical"),
            orientation=getattr(page, "orientation", "portrait"),
            format_name=getattr(page, "format_name", None),
            rotation_pdf=int(getattr(page, "rotation_pdf", 0) or 0),
            source_pdf_id=getattr(page, "source_pdf_id", None),
            options_snapshot=deepcopy(getattr(page, "options_snapshot", {})),
            ocr_correspondence_page_binding=deepcopy(getattr(page, "ocr_correspondence_page_binding", None)),
        )
        discarded = list(getattr(page, "discarded_elements", ()) or ())
        capture_source_observations(page, [*page.elements, *discarded])
        active_ids = {item.source_id for item in page.elements}
        candidates = [*page.elements, *discarded, *getattr(page, "source_inventory", {}).values()]
        used_ids = set()
        for legacy in candidates:
            element = element_record_from_legacy(legacy, page.index, document=document)
            if element.element_id in used_ids:
                continue
            used_ids.add(element.element_id)
            element.attributes["observation_only"] = element.element_id not in active_ids
            element.attributes["discarded_by_historical_pipeline"] = any(legacy is item for item in discarded)
            original = page.source_inventory.get(element.element_id)
            if original is not None:
                element.attributes["source_snapshot"] = _snapshot_value(original)
                element.acquisition_raw = deepcopy(original)
            for transformation in getattr(page, "source_transformations", ()):
                if element.element_id in transformation["source_ids"]:
                    element.decision_history.append(deepcopy(transformation))
                    for key in ("duplicate_of", "duplicate_verified", "outside_page", "replacement_id"):
                        if key in transformation:
                            element.attributes[key] = deepcopy(transformation[key])
            scene_page.add(element)
        page.element_registry = scene_page.registry
        result.add_page(scene_page)
    document.element_registry = result.registry
    return result
















def __getattr__(name):
    if name == "RenderMode":
        from pdfexact.analysis.decisions import RenderMode

        return RenderMode
    raise AttributeError(name)






