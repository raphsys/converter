"""Provenance et registre de conservation des elements."""
from __future__ import annotations

from dataclasses import dataclass, field


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




def bind_state(registry: ElementRegistry, element_id: str, state: str, reason: str | None = None) -> None:
    registry.bind_state(element_id, state, reason)




















def expliquer_filtrage(element: object, reason_code: str, **details: object) -> None:
    """Journalise un filtrage historique sans rendre la perte silencieuse."""
    history = getattr(element, "decision_history", None)
    if history is None:
        history = []
        setattr(element, "decision_history", history)
    history.append({"event": "filtered", "reason_code": reason_code, **details})


