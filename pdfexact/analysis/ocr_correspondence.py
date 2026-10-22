"""Pure acquisition-bound OCR observation correspondence, not paint equivalence."""
from __future__ import annotations

from copy import copy, deepcopy
from dataclasses import fields, is_dataclass
from enum import Enum
from hashlib import sha256
import json
from math import atan2, isfinite

from pdfexact.analysis.geometry import intersection_area, quad_iou, resolve_text_orientation
from pdfexact.geometry import BBox, pt_vers_emu
from pdfexact.ir import Line, Span, TextBox

SCHEMA = "pdfexact.ocr-native-correspondence.v1"
RELATIONSHIP = "observation-superseded-by-native"
MATCHING_POLICY = "unique-line-spatial-v1"
TEXT_POLICY = "unicode-whitespace-fold-v1"
_GEOMETRY_FIELDS = (
    "bbox", "quad", "polygon", "baseline_points", "angle_deg", "orientation",
    "orientation_points", "transform", "clip_bbox", "clip_ids", "compositing",
    "opacity", "alpha", "z_index", "parent_group_id", "paint_group_id",
)


class _Invalid(ValueError):
    pass


def _raw(record):
    raw = getattr(record, "raw", None)
    return raw if raw is not None else record


def _id(node):
    return getattr(node, "source_id", None)


def _kind(node):
    value = getattr(node, "source_kind", None)
    return getattr(value, "value", value)


def _serializable(value, stack=None):
    """Reject the scene snapshot helper's lossy unknown-object fallback."""
    if value is None or isinstance(value, (str, bool, int, bytes, Enum)):
        return
    if isinstance(value, float):
        if not isfinite(value):
            raise _Invalid("nonserializable-source-snapshot")
        return
    stack = set() if stack is None else stack
    if id(value) in stack:
        raise _Invalid("nonserializable-source-snapshot")
    stack.add(id(value))
    try:
        if is_dataclass(value):
            names = {item.name for item in fields(value)}
            names.update(name for name in vars(value) if not name.startswith("_"))
            for name in names:
                _serializable(getattr(value, name), stack)
        elif isinstance(value, dict):
            if not all(isinstance(key, str) for key in value):
                raise _Invalid("nonserializable-source-snapshot")
            for item in value.values():
                _serializable(item, stack)
        elif isinstance(value, (tuple, list, set, frozenset)):
            for item in value:
                _serializable(item, stack)
        else:
            raise _Invalid("nonserializable-source-snapshot")
    finally:
        stack.remove(id(value))


def _snapshot(value):
    from pdfexact.scene import _snapshot_value

    _serializable(value)
    return _snapshot_value(value)


def _digest(value):
    encoded = json.dumps(_snapshot(value), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("utf-8")
    return sha256(encoded).hexdigest()




def _page_index(record):
    raw = _raw(record)
    index = getattr(raw, "source_page_index", None)
    if type(index) is not int or getattr(record, "page_index", index) != index:
        raise _Invalid("page-mismatch")
    return index


def _validate_binding(binding):
    if not isinstance(binding, dict) or set(binding) != {"index", "source_pdf_id", "geometry"}:
        raise _Invalid("page-mismatch")
    geometry = binding["geometry"]
    if (type(binding["index"]) is not int or not isinstance(geometry, dict)
            or binding["source_pdf_id"] is not None and not isinstance(binding["source_pdf_id"], str)
            or geometry.get("coordinate_space") != "page-visible-canonical"):
        raise _Invalid("page-mismatch")
    _serializable(binding)
    for key in ("width_pt", "height_pt"):
        value = geometry.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise _Invalid("page-mismatch")




def _tree(root, line, inventory, binding, kind):
    if not isinstance(root, TextBox) or not isinstance(line, Line):
        raise _Invalid("invalid-source-tree")
    if sum(_id(item) == _id(line) for item in root.lignes) != 1 or not line.spans:
        raise _Invalid("invalid-source-tree")
    nodes = [root, line, *line.spans]
    ids = [_id(node) for node in nodes]
    if any(not isinstance(key, str) or not key for key in ids) or len(set(ids)) != len(ids):
        raise _Invalid("invalid-source-tree")
    for node in nodes:
        key = _id(node)
        if key not in inventory:
            raise _Invalid("unknown-source")
        stored = inventory[key]
        if (_id(_raw(stored)) != key or _page_index(stored) != binding["index"]
                or _page_index(node) != binding["index"]):
            raise _Invalid("page-mismatch")
        if _kind(node) != kind or _kind(_raw(stored)) != kind:
            raise _Invalid("invalid-source-tree")
        if not hasattr(node, "source_acquisition_index"):
            raise _Invalid("missing-acquisition-provenance")
        if _digest(node) != _digest(_raw(stored)):
            raise _Invalid("source-snapshot-mismatch")
    if not all(isinstance(span, Span) for span in line.spans):
        raise _Invalid("invalid-source-tree")
    return {
        "root_id": ids[0], "line_id": ids[1], "span_ids": ids[2:], "node_ids": ids,
        "node_sha256": {key: _digest(node) for key, node in zip(ids, nodes)},
    }


def _population(inventory, binding, kind):
    result = []
    line_roots = {}
    for key, record in inventory.items():
        root = _raw(record)
        if not isinstance(root, TextBox) or _kind(root) != kind:
            continue
        if _page_index(record) != binding["index"]:
            continue
        if key != _id(root):
            raise _Invalid("invalid-source-tree")
        if kind == "ocr" and root.attributes.get("observation_only") is not True:
            continue
        for line in root.lignes:
            reference = _tree(root, line, inventory, binding, kind)
            previous = line_roots.setdefault(_id(line), key)
            if previous != key:
                raise _Invalid("invalid-source-tree")
            result.append((root, line, reference))
    for record in inventory.values():
        node = _raw(record)
        if isinstance(node, Line) and _kind(node) == kind and _page_index(record) == binding["index"]:
            if _id(node) not in line_roots:
                raise _Invalid("invalid-source-tree")
    return result


def _geometry(root, line):
    return {_id(node): {name: _snapshot(getattr(node, name)) for name in _GEOMETRY_FIELDS if hasattr(node, name)}
            for node in (root, line, *line.spans)}


def _text(line):
    return "".join(span.texte for span in line.spans)


def _fold(text):
    return " ".join(text.split())


def _supported_geometry(root, line):
    for node in (root, line, *line.spans):
        if (getattr(node, "clip_bbox", None) is not None or getattr(node, "clip_ids", ())
                or getattr(node, "compositing", {}) or getattr(node, "transform", None)
                or getattr(node, "curved", False)):
            raise _Invalid("unresolved-source-geometry")
        quad = getattr(node, "quad", ())
        if quad and not _valid_quad(tuple(quad)):
            raise _Invalid("invalid-source-quad")
    proxy = copy(root)
    proxy.lignes = [line]
    resolved = resolve_text_orientation(proxy)
    angle = resolved["angle_deg"]
    if (resolved["conflicts"] or resolved["orientation"] in {None, "unknown", "auto", ""}
            or isinstance(angle, bool) or not isinstance(angle, (int, float)) or not isfinite(angle)):
        raise _Invalid("unresolved-source-orientation")
    for span in line.spans:
        span_angle = getattr(span, "angle_deg", None)
        if (not isinstance(span_angle, (int, float)) or not isfinite(span_angle)
                or abs((span_angle - angle + 180) % 360 - 180) > 8):
            raise _Invalid("unresolved-source-orientation")
    return resolved


def _valid_quad(quad):
    if len(quad) != 4 or len(set(quad)) != 4:
        return False
    if any(len(point) != 2 or any(isinstance(n, bool) or not isinstance(n, (int, float)) or not isfinite(n)
                                for n in point) for point in quad):
        return False
    cx, cy = sum(p[0] for p in quad) / 4, sum(p[1] for p in quad) / 4
    ordered = sorted(quad, key=lambda p: atan2(p[1] - cy, p[0] - cx))
    crosses = [(b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
               for a, b, c in zip(ordered, ordered[1:] + ordered[:1], ordered[2:] + ordered[:2])]
    return all(c > 0 for c in crosses) or all(c < 0 for c in crosses)


def _metrics(observation, native, binding):
    left_root, left, _ = observation
    right_root, right, _ = native
    a, b = left.bbox, right.bbox
    width = pt_vers_emu(binding["geometry"]["width_pt"])
    height = pt_vers_emu(binding["geometry"]["height_pt"])
    for box in (a, b):
        if (not isinstance(box, BBox) or not 0 <= box.x0 < box.x1 <= width
                or not 0 <= box.y0 < box.y1 <= height):
            raise _Invalid("invalid-canonical-geometry")
    # Unknown geometry on a plausible same-text candidate cannot establish uniqueness.
    left_orientation = _supported_geometry(left_root, left)
    right_orientation = _supported_geometry(right_root, right)
    angle_a, angle_b = left_orientation["angle_deg"], right_orientation["angle_deg"]
    difference = abs((angle_a - angle_b + 180) % 360 - 180)
    intersection = intersection_area(a, b)
    area_a, area_b = a.largeur * a.hauteur, b.largeur * b.hauteur
    center_a = (a.x0 + a.x1, a.y0 + a.y1)
    center_b = (b.x0 + b.x1, b.y0 + b.y1)
    center_a_in_b = 2 * b.x0 <= center_a[0] <= 2 * b.x1 and 2 * b.y0 <= center_a[1] <= 2 * b.y1
    center_b_in_a = 2 * a.x0 <= center_b[0] <= 2 * a.x1 and 2 * a.y0 <= center_b[1] <= 2 * a.y1
    qa, qb = tuple(left.quad), tuple(right.quad)
    if any(quad and not _valid_quad(quad) for quad in (qa, qb)):
        raise _Invalid("invalid-source-quad")
    iou = quad_iou(qa, qb) if qa and qb else None
    metrics = {
        "intersection": intersection, "observation_area": area_a, "native_area": area_b,
        "observation_center_in_native": center_a_in_b, "native_center_in_observation": center_b_in_a,
        "intersection_over_min_area": intersection / min(area_a, area_b),
        "max_over_min_area": max(area_a, area_b) / min(area_a, area_b),
        "observation_angle": angle_a, "native_angle": angle_b, "angle_difference": difference,
        "quad_iou": iou, "resolver_conflicts": [],
    }
    matches = (center_a_in_b and center_b_in_a and intersection * 5 >= min(area_a, area_b) * 4
               and max(area_a, area_b) <= min(area_a, area_b) * 2 and difference <= 8
               and (iou is None or iou >= 0.5))
    return metrics, matches


def _observation_acquired(root, line):
    if (_kind(root) != "ocr" or root.attributes.get("observation_only") is not True
            or len(root.lignes) != 1 or not isinstance(root.attributes.get("engine"), str)
            or not root.attributes["engine"].strip()):
        raise _Invalid("source-not-ocr-observation")
    for node in (root, line, *line.spans):
        routing = node.attributes.get("ocr_routing", {})
        if not isinstance(routing, dict) or routing.get("ambiguous"):
            raise _Invalid("ambiguous-ocr-acquisition")


def _native_visible(root, line):
    for node in (root, line, *line.spans):
        if getattr(node, "invisible", False):
            raise _Invalid("native-visibility-unproven")
        for name in ("opacity", "alpha"):
            value = getattr(node, name, None)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not isfinite(value) or value <= 0):
                raise _Invalid("native-visibility-unproven")
    for span in line.spans:
        alpha = span.attributes.get("source_alpha")
        if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not isfinite(alpha) or not 0 < alpha <= 255:
            raise _Invalid("native-visibility-unproven")


def _build(observation_root, native_line, inventory, binding):
    _validate_binding(binding)
    observation_id, native_id = _id(_raw(observation_root)), _id(_raw(native_line))
    observations = _population(inventory, binding, "ocr")
    natives = _population(inventory, binding, "pdf-native")
    selected_observations = [entry for entry in observations if _id(entry[0]) == observation_id]
    if len(selected_observations) != 1:
        raise _Invalid("source-not-ocr-observation")
    observation = selected_observations[0]
    if _digest(_raw(observation_root)) != _digest(observation[0]):
        raise _Invalid("source-snapshot-mismatch")
    _observation_acquired(*observation[:2])
    raw_observation = _text(observation[1])
    comparison = _fold(raw_observation)
    if not comparison:
        raise _Invalid("recognition-conflict")
    candidates = []
    for candidate in natives:
        if _fold(_text(candidate[1])) == comparison:
            _, matches = _metrics(observation, candidate, binding)
            if matches:
                candidates.append(_id(candidate[1]))
    if native_line is None and len(candidates) == 1:
        native_id = candidates[0]
    selected_natives = [entry for entry in natives if _id(entry[1]) == native_id]
    if len(candidates) != 1:
        raise _Invalid("ambiguous-correspondence" if candidates else "spatial-correspondence-unproven")
    if len(selected_natives) != 1:
        raise _Invalid("invalid-source-tree")
    native = selected_natives[0]
    if native_line is not None and _digest(_raw(native_line)) != _digest(native[1]):
        raise _Invalid("source-snapshot-mismatch")
    raw_native = _text(native[1])
    if comparison != _fold(raw_native):
        raise _Invalid("recognition-conflict")
    competing = []
    for candidate in observations:
        if _fold(_text(candidate[1])) == comparison:
            _, matches = _metrics(candidate, native, binding)
            if matches:
                competing.append(_id(candidate[0]))
    if candidates != [native_id] or competing != [observation_id]:
        raise _Invalid("ambiguous-correspondence")
    _native_visible(*native[:2])
    metrics, matches = _metrics(observation, native, binding)
    if not matches:
        raise _Invalid("spatial-correspondence-unproven")
    proof = {
        "schema": SCHEMA, "relationship": RELATIONSHIP, "page": deepcopy(binding),
        "observation_ref": observation[2], "native_ref": native[2],
        "observation_geometry": _geometry(*observation[:2]), "native_geometry": _geometry(*native[:2]),
        "text": {"policy": TEXT_POLICY, "observation": raw_observation, "native": raw_native, "comparison": comparison},
        "matching": {"policy": MATCHING_POLICY, "candidate_native_line_ids": candidates,
                     "competing_observation_ids": competing, "metrics": metrics},
        "selected_component_ids": [_id(native[1]), *(_id(span) for span in native[1].spans)],
    }
    identity = {key: proof[key] for key in ("page", "observation_ref", "native_ref")}
    identity["policy"] = MATCHING_POLICY
    proof["selection_event_id"] = "ocr-native-selection:" + _digest(identity)
    return proof


def build_ocr_native_correspondence(observation_root, native_line, inventory, *, page_binding):
    """Return acquisition proof plus errors; never record an event or choose output."""
    try:
        return _build(observation_root, native_line, inventory, page_binding), []
    except _Invalid as error:
        return None, [str(error)]
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return None, ["invalid-correspondence-source"]


def selection_event_details(proof):
    """Details for the existing real selection hook, not a replacement event log."""
    return {
        "event_id": proof["selection_event_id"], "relationship": RELATIONSHIP, "proof_schema": SCHEMA,
        "page_binding": deepcopy(proof["page"]),
        "observation_component_ids": list(proof["observation_ref"]["node_ids"]),
        "selected_native_component_ids": list(proof["selected_component_ids"]),
        "observation_node_sha256": deepcopy(proof["observation_ref"]["node_sha256"]),
        "native_node_sha256": deepcopy(proof["native_ref"]["node_sha256"]),
        "matching_policy": MATCHING_POLICY,
    }


