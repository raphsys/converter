"""Provenance et registre de conservation des elements."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


def observation_children(element):
    """Walk render-bearing children once, including attached list markers."""
    # Native text instructions emit attached runs before the body's runs.
    marker = getattr(element, "list_marker_source", None)
    if marker is not None:
        yield marker
    # Paragraph flat runs mirror the rows; even copied caches are not paint.
    names = ("lignes", "rows", "cells") if getattr(element, "lignes", None) else ("lignes", "spans", "rows", "cells")
    for name in names:
        for child in getattr(element, name, ()) or ():
            yield child


def observation_nodes(element):
    yield element
    for child in observation_children(element):
        yield from observation_nodes(child)


def observation_signature(element):
    """Exact visible source data, deliberately independent of acquisition IDs."""
    from pdfexact.scene import _snapshot_value

    names = (
        "texte", "text", "bbox", "police", "size_pt", "couleur", "souligne", "barre",
        "lien", "lien_uri", "invisible", "capitales", "exposant", "indice",
        "espacement_twips", "baseline_points", "quad", "polygon", "path", "chemins",
        "angle_deg", "orientation", "z_index", "alpha", "opacity", "clip_bbox", "clip_ids",
        "compositing", "transform", "media_ref", "remplissage", "contour", "epaisseur_emu",
        "pointilles", "uri", "page_cible", "col_span", "v_merge", "hauteur_ligne_emu",
        "largeur_cible_emu", "alignement",
        "surlignage", "glyph_ids", "to_unicode_status", "font_metrics", "language", "script",
        "reading_direction", "curved", "baseline", "z_order", "source_kind", "source_page_index",
        "confidence",
    )
    signature = {name: _snapshot_value(getattr(element, name)) for name in names if hasattr(element, name)}
    from pdfexact.ir import FlowParagraph, Line, Span, TextBox

    if isinstance(element, (TextBox, FlowParagraph, Line, Span)):
        signature["attributes"] = _snapshot_value({
            key: value for key, value in element.attributes.items()
            if key not in {"duplicate_of", "duplicate_verified"}
        })
    return signature


def _observation_id(element):
    return getattr(element, "source_id", None) or getattr(element, "element_id", None)


def _exact_component(source, target, *, equivalent=False):
    if (type(source) is not type(target)
            or (not equivalent and _observation_id(source) != _observation_id(target))
            or observation_signature(source) != observation_signature(target)
            or not _source_history_preserved(source, target)):
        return False
    left, right = list(observation_children(source)), list(observation_children(target))
    return len(left) == len(right) and all(
        _exact_component(a, b, equivalent=equivalent) for a, b in zip(left, right)
    )


def _source_history_preserved(source, target):
    for name in ("evidence", "decision_history", "grouping_evidence", "duplicate_candidates"):
        remaining = list(getattr(target, name, ()))
        for item in getattr(source, name, ()):
            if item not in remaining:
                return False
            remaining.remove(item)
    return True


def verify_preserved_text_components(source, outputs, *, equivalent=False):
    """Bind actual ordered components, never parent aliases or proof metadata."""
    expected = [node for child in observation_children(source) for node in observation_nodes(child)]
    actual = [node for output in outputs for node in observation_nodes(output)]
    if equivalent:
        return [] if any(_exact_component(source, node, equivalent=True) for node in actual) else ["changed-components"]
    ids = [_observation_id(node) for node in expected]
    if any(ident is None for ident in ids) or len(set(ids)) != len(ids):
        return ["unidentified-or-duplicate-source-component"]
    matches = [node for node in actual if _observation_id(node) in ids]
    if [_observation_id(node) for node in matches] != ids:
        return ["missing-duplicate-or-reordered-component"]
    return [] if all(_exact_component(a, b) for a, b in zip(expected, matches)) else ["changed-component"]


_COMPONENT_GEOMETRY = ("quad", "polygon", "baseline_points", "baseline")
_FUSION_CONTRACT = (
    "angle_deg", "orientation", "z_index", "z_order", "alpha", "opacity", "clip_bbox", "clip_ids",
    "compositing", "transform", "curved", "source_kind", "language", "script", "reading_direction",
    "layout_frame_role", "layout_frame_strategy", "semantic_role", "list_group_id", "list_marker",
    "list_level", "list_marker_bbox", "parent_group_id", "vertical_alignement",
    "extraction_confidence", "role_confidence", "geometry_confidence", "semantic_confidence",
    "paragraph_confidence", "group_id", "source_page_index",
)
_PAINT_CONTRACT = (
    "angle_deg", "orientation", "z_index", "z_order", "alpha", "opacity", "clip_bbox",
    "clip_ids", "compositing", "transform", "curved",
)


def _geometry_in_components(source, name):
    value = getattr(source, name, ())
    return not value or any(
        value == getattr(node, name, None)
        for child in observation_children(source) for node in observation_nodes(child)
    )


def text_fusion_errors(elements):
    """Conservative lossless contract for proposed paragraph aggregates."""
    from dataclasses import fields
    from pdfexact.ir import FlowParagraph, Line, Span, TextBox
    from pdfexact.scene import _snapshot_value

    errors = []
    if not elements:
        return ["empty-text-group"]
    for element in elements:
        if type(element) not in (TextBox, FlowParagraph) or not element.lignes:
            errors.append("missing-exact-text-rows")
            continue
        if any(type(line) is not Line or not line.spans or any(type(span) is not Span for span in line.spans)
               for line in element.lignes):
            errors.append("invalid-text-component-type")
        for name in _COMPONENT_GEOMETRY:
            if not _geometry_in_components(element, name):
                errors.append(f"unrecoverable-{name}")
        if getattr(element, "list_marker_source", None) is not None:
            errors.append("attached-list-marker")
    actual_ids = [_observation_id(node) for element in elements for node in observation_nodes(element)
                  if _observation_id(node) is not None]
    if len(set(actual_ids)) != len(actual_ids) or len({id(item) for item in elements}) != len(elements):
        errors.append("duplicate-text-component")
    first = elements[0]
    if any(getattr(item, "confidence", None) != getattr(first, "confidence", None) for item in elements[1:]):
        if any(source_confidence_evidence(item) is None for item in elements):
            errors.append("unidentified-confidence-source")
    for name in _FUSION_CONTRACT:
        if any(_snapshot_value(getattr(item, name, None)) != _snapshot_value(getattr(first, name, None))
               for item in elements[1:]):
            errors.append(f"incompatible-{name}")
    # Parent style may supply fallback paint even when rows also have styles.
    styles = ("police", "size_pt", "couleur", "souligne", "barre", "capitales", "surlignage", "espacement_twips")
    for name in styles:
        if any(getattr(item, name, None) != getattr(first, name, None) for item in elements[1:]):
            errors.append(f"incompatible-{name}")
    for name in ("attributes", "presentation"):
        combined = {}
        for item in elements:
            for key, value in getattr(item, name, {}).items():
                value = _snapshot_value(value)
                if key in combined and combined[key] != value:
                    errors.append(f"incompatible-{name}:{key}")
                combined[key] = value
    dynamic = {name for item in elements if type(item) in (TextBox, FlowParagraph)
               for name in vars(item) if name not in {entry.name for entry in fields(item)}}
    for name in dynamic - {"source_acquisition_index", "grouping_evidence", *_COMPONENT_GEOMETRY}:
        if any(_snapshot_value(getattr(item, name, None)) != _snapshot_value(getattr(first, name, None))
               for item in elements[1:]):
            errors.append(f"incompatible-{name}")
    return list(dict.fromkeys(errors))


def _aggregate_contract_preserved(source, target):
    def paint_matches(name):
        left, right = getattr(source, name, None), getattr(target, name, None)
        if left == right:
            return True
        if name == "z_index":
            def child_paint(element):
                values = [node.z_index for child in observation_children(element) for node in observation_nodes(child)
                          if getattr(node, "z_index", None) is not None]
                return min(values) if values else None
            return left in (None, child_paint(source)) and right == child_paint(target)
        return False

    if (any(not paint_matches(name) for name in _PAINT_CONTRACT)
            or not _source_history_preserved(source, target)):
        return False
    left, right = observation_signature(source), observation_signature(target)
    for name, value in left.items():
        if name in {"bbox", "texte", "text", "z_index"}:
            continue
        if name == "confidence" and value != right.get(name):
            expected = source_confidence_evidence(source)
            if right.get(name) is not None or expected is None:
                return False
            measured = [entry for entry in getattr(target, "evidence", ())
                        if isinstance(entry, Evidence) and entry.kind == expected.kind
                        and entry.source == expected.source and entry.details == expected.details]
            if not measured or any(entry != expected for entry in measured):
                return False
            continue
        if name in _COMPONENT_GEOMETRY and value != right.get(name):
            if not _geometry_in_components(source, name) or not _geometry_in_components(target, name):
                return False
        elif name == "attributes":
            if any(key not in right.get(name, {}) or right[name][key] != item for key, item in value.items()):
                return False
        elif value != right.get(name):
            return False
    return True


def observation_is_preserved(source, outputs, *, equivalent=False):
    """Prove retained source geometry/style/text, not just a claimed source ID."""
    from pdfexact.ir import FlowParagraph, Line, TextBox, element_source_ids

    nodes = [node for output in outputs for node in observation_nodes(output)]
    if isinstance(source, (TextBox, FlowParagraph)) and list(observation_children(source)):
        parents = [node for node in nodes if isinstance(node, (TextBox, FlowParagraph))
                   and (equivalent or _observation_id(source) in element_source_ids(node))]
        direct = [node for node in parents if _observation_id(node) == _observation_id(source)]
        parents = direct or parents
        return (bool(parents) and all(_aggregate_contract_preserved(source, node) for node in parents)
                and not verify_preserved_text_components(source, outputs, equivalent=equivalent))
    if list(observation_children(source)):
        # Other containers keep their existing geometry obligations; only text
        # aggregates may change representation while preserving exact children.
        matches = [node for node in nodes if equivalent or _observation_id(source) == _observation_id(node)]
        return (equivalent or not isinstance(source, Line) or len(matches) == 1) and any(
            _exact_component(source, node, equivalent=equivalent) for node in matches
        )
    matches = [node for node in nodes if equivalent or _observation_id(source) == _observation_id(node)]
    return (equivalent or len(matches) == 1) and any(_exact_component(source, node, equivalent=equivalent) for node in matches)


def source_paint_index(element: object) -> int | None:
    """Resolve paint provenance without treating sequence zero as missing."""
    values = [
        value
        for line in getattr(element, "lignes", ())
        for value in (getattr(line, "z_index", None), *(getattr(span, "z_index", None) for span in line.spans))
        if value is not None
    ]
    # Painted components are authoritative. A container value is an aggregate
    # that survives splits and views, so it may describe siblings painted
    # earlier; it only answers when no component carries a sequence.
    if values:
        return min(values)
    return getattr(element, "z_index", None)


@dataclass(frozen=True)
class Evidence:
    kind: str
    source: str
    confidence: float | None = None
    details: tuple[tuple[str, object], ...] = ()


def source_confidence_evidence(element) -> Evidence | None:
    """Bind aggregate metadata to its real source and ordered components."""
    source_id = _observation_id(element)
    component_ids = tuple(_observation_id(node) for child in observation_children(element)
                          for node in observation_nodes(child))
    if (source_id is None or not component_ids or any(ident is None for ident in component_ids)
            or len(set(component_ids)) != len(component_ids)):
        return None
    return Evidence(
        "source-confidence", source_id, getattr(element, "confidence", None),
        (("source_type", type(element).__name__), ("component_ids", component_ids)),
    )


@dataclass(frozen=True)
class DuplicateCandidate:
    element_id: str
    candidate_id: str
    score: float
    reason: str


@dataclass
class ElementRegistry:
    """Registre de cycle de vie : aucun element ne disparait sans explication."""

    elements: dict[str, object] = field(default_factory=dict)
    events: list[dict[str, object]] = field(default_factory=list)

    def register(self, element: object) -> str:
        element_id = str(getattr(element, "element_id"))
        if element_id in self.elements and self.elements[element_id] is not element:
            raise ValueError(f"element_id duplique: {element_id}")
        self.elements[element_id] = element
        self.events.append({"event": "registered", "element_id": element_id})
        return element_id

    def record(self, element_id: str, event: str, **details: object) -> None:
        if element_id not in self.elements:
            raise KeyError(f"element inconnu: {element_id}")
        self.events.append({"event": event, "element_id": element_id, **details})

    def bind_state(self, element_id: str, state: str, reason: str | None = None) -> None:
        element = self.elements[element_id]
        current = getattr(element, "verification_state", None)
        enum_type = type(current)
        value = enum_type(state) if hasattr(enum_type, "__members__") else state
        setattr(element, "verification_state", value)
        self.record(element_id, state, **({"reason": reason} if reason else {}))

    def missing_terminal_states(self) -> list[str]:
        terminal = {"rendered", "verified", "warning", "failed", "non-representable"}
        seen = {
            event["element_id"]
            for event in self.events
            if event.get("event") in terminal
        }
        return sorted(set(self.elements) - seen)


def add_evidence(element: object, evidence: Evidence) -> None:
    evidences = getattr(element, "evidence", None)
    if evidences is None:
        evidences = []
        setattr(element, "evidence", evidences)
    evidences.append(evidence)


def bind_state(registry: ElementRegistry, element_id: str, state: str, reason: str | None = None) -> None:
    registry.bind_state(element_id, state, reason)


def registre_elements(scene) -> ElementRegistry:
    registry = scene.registry
    for element in scene.all_elements():
        if element.element_id not in registry.elements:
            registry.register(element)
    return registry


def record_decision(element: object, decision: object, reason: str) -> None:
    history = getattr(element, "decision_history", None)
    if history is None:
        history = []
        setattr(element, "decision_history", history)
    history.append({"decision": decision, "reason": reason})
    if hasattr(element, "render_decision"):
        setattr(element, "render_decision", decision)


def mark_state(element: object, state: str, reason: str | None = None) -> None:
    setattr(element, "verification_state", state)
    if reason:
        history = getattr(element, "decision_history", None)
        if history is None:
            history = []
            setattr(element, "decision_history", history)
        history.append({"state": state, "reason": reason})


def stable_source_id(page_index: int, source_kind: str, source_index: int, token: str = "") -> str:
    suffix = f":{token}" if token else ""
    return f"p{page_index}:{source_kind}:{source_index}{suffix}"


def merge_evidence(*groups: Iterable[Evidence]) -> tuple[Evidence, ...]:
    import json
    from pdfexact.scene import _snapshot_value

    result: list[Evidence] = []
    seen: set[tuple[str, str, str]] = set()
    for group in groups:
        for item in group:
            key = (item.kind, item.source, json.dumps(_snapshot_value(item.details), sort_keys=True))
            if key not in seen:
                result.append(item)
                seen.add(key)
    return tuple(result)


def creer_source_id(page_index: int, source_kind: str, source_index: int, token: str = "") -> str:
    """Construit un identifiant stable pour une source d'extraction."""
    return stable_source_id(page_index, source_kind, source_index, token)


def lier_source_ocr_native(
    element: object,
    *,
    native_id: str | None = None,
    ocr_id: str | None = None,
    confidence: float = 0.0,
) -> None:
    """Enregistre une correspondance OCR/native sans supprimer l'une des sources."""
    ids = list(getattr(element, "source_ids", ()) or ())
    for source_id in (native_id, ocr_id):
        if source_id and source_id not in ids:
            ids.append(source_id)
    if hasattr(element, "source_ids"):
        setattr(element, "source_ids", tuple(ids))
    add_evidence(
        element,
        Evidence(
            "ocr-native-link",
            "provenance",
            max(0.0, min(1.0, confidence)),
            tuple(
                (key, value)
                for key, value in (("native_id", native_id), ("ocr_id", ocr_id))
                if value
            ),
        ),
    )


def calculer_candidats_doublon(
    element: object,
    candidates: Iterable[object],
    *,
    score_fn=None,
    minimum: float = 0.80,
) -> list[DuplicateCandidate]:
    """Calcule des doublons possibles et les retourne sans filtrer l'élément."""
    results: list[DuplicateCandidate] = []
    source_id = str(getattr(element, "element_id"))
    for candidate in candidates:
        candidate_id = str(getattr(candidate, "element_id"))
        if candidate_id == source_id:
            continue
        score = float(score_fn(element, candidate) if score_fn else 0.0)
        if score >= minimum:
            results.append(DuplicateCandidate(source_id, candidate_id, score, "similar-source"))
    return sorted(results, key=lambda item: (-item.score, item.candidate_id))


def marquer_doublon_sans_supprimer(element: object, candidate: DuplicateCandidate) -> None:
    entries = getattr(element, "duplicate_candidates")
    entries.append({
        "element_id": candidate.candidate_id,
        "score": candidate.score,
        "reason": candidate.reason,
    })
    add_evidence(element, Evidence("duplicate-candidate", "provenance", candidate.score))


def expliquer_filtrage(element: object, reason_code: str, **details: object) -> None:
    """Journalise un filtrage historique sans rendre la perte silencieuse."""
    history = getattr(element, "decision_history", None)
    if history is None:
        history = []
        setattr(element, "decision_history", history)
    history.append({"event": "filtered", "reason_code": reason_code, **details})


def expliquer_fallback(element: object, reason_code: str, **details: object) -> None:
    history = getattr(element, "decision_history", None)
    if history is None:
        history = []
        setattr(element, "decision_history", history)
    history.append({"event": "fallback", "reason_code": reason_code, **details})
