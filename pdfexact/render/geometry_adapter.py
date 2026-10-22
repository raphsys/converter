"""Prepare Word text geometry without changing the source coordinate system."""
from dataclasses import dataclass
from statistics import median

from pdfexact.geometry import BBox, emu_vers_pt, pt_vers_emu, pt_vers_twips, quantifier_bbox
from pdfexact.analysis.text_geometry import block_alignment, geometry_kind


def twips(value):
    return pt_vers_twips(emu_vers_pt(value))


@dataclass(frozen=True)
class TextGeometrySpec:
    bbox: BBox
    alignment: str
    kind: str
    line_height: int
    line_step: int
    frame_height: int
    frame_rule: str
    native_height: int
    native_line_height: int
    tabs: tuple[int, ...]
    list_left: int
    list_level: int
    leader_tabs: tuple[tuple[int, str], ...] = ()


def _uniform_source_step(lines):
    if len(lines) < 2:
        return None
    baselines = [getattr(line, "baseline_points", ()) for line in lines]
    if all(baselines):
        if any(len({point[1] for point in points}) != 1 for points in baselines):
            return None
        positions = [points[0][1] for points in baselines]
    else:
        positions = [line.bbox.y0 for line in lines]
    steps = [twips(current - previous) for previous, current in zip(positions, positions[1:])]
    return steps[0] if steps and min(steps) > 0 and len(set(steps)) == 1 else None


def prepare_text_geometry(element, lines, composition, occupied_bboxes=()):
    bbox = quantifier_bbox(element.bbox)
    role = getattr(element, "semantic_role", None) or getattr(element, "layout_frame_role", None)
    if role is None:
        role = next((getattr(line, "semantic_role", None) for line in lines if getattr(line, "semantic_role", None)), None)
    compact = role in {"caption", "credit", "label", "annotation", "diagram_text", "figure_text"}
    deltas = [b.bbox.y0 - a.bbox.y0 for a, b in zip(lines, lines[1:]) if b.bbox.y0 > a.bbox.y0]
    heights = [line.bbox.hauteur for line in lines if line.bbox.hauteur > 0]
    step = max(pt_vers_emu(1), int(median(deltas))) if deltas else max(
        pt_vers_emu(1), int(median(heights)) if heights else 0,
        getattr(element, "interligne_emu", 0), pt_vers_emu(max(getattr(element, "size_pt", 10.0) * 1.12, 1.0)),
    )
    height = step if compact else max(
        getattr(element, "interligne_emu", 0),
        *(line.hauteur_ligne_emu for line in lines),
        pt_vers_emu(max(getattr(element, "size_pt", 10.0) * 1.12, 1.0)),
    )
    frame_height = max(bbox.hauteur, step * max(len(lines) - 1, 0)) if compact and lines else max(bbox.hauteur, height * max(len(lines), 1) + pt_vers_emu(2), 1)
    metrics = max((max(line.bbox.hauteur, line.hauteur_ligne_emu, 1) for line in lines), default=1)
    native_step = max(median(deltas) if deltas else 0, metrics, 1)
    embedded_breaks = sum(span.texte.count(char) for line in lines for span in line.spans for char in "\r\n  ")
    rendered_lines = max(len(lines) + embedded_breaks, 1)
    line_count = max(rendered_lines, composition.estimated_line_count, 1)
    source_height = max(twips(bbox.hauteur), 1)
    if deltas and line_count == len(lines) and geometry_kind(element) != "oriented":
        # Leading is a property of the source text: the typical baseline pitch.
        # Ink height divided by the row count is always smaller than the pitch
        # (N rows hold only N-1 pitches), which visibly squeezed the rows.
        native_line = max(twips(native_step), twips(metrics), 1)
        native_height = max(source_height, twips(metrics) + native_line * (line_count - 1), 1)
    else:
        native_line = max(min(max(twips(native_step), 1), max(source_height // line_count, 1)), max(twips(metrics), 1))
        native_height = max(source_height, native_line * line_count, 1)
    source_step = _uniform_source_step(lines)
    exact_rows = (
        composition.preserve_lines and composition.estimated_line_count <= len(lines)
        and geometry_kind(element) != "oriented"
        and not any(char in span.texte for line in lines for span in line.spans for char in "\r\n\u2028\u2029")
    )
    if exact_rows and source_step is not None:
        # Ink height excludes the final leading: N rows contain N-1 steps.
        native_line = source_step
        ink_height = max(twips(line.bbox.hauteur) for line in lines)
        native_height = max(source_height, ink_height + source_step * (len(lines) - 1), 1)
    limits = [other.y0 - pt_vers_emu(0.5) for other in occupied_bboxes if other.y0 >= bbox.y1 and min(bbox.x1, other.x1) > max(bbox.x0, other.x0)]
    if native_height > source_height and limits:
        native_height = min(native_height, max(source_height, twips(min(limits) - bbox.y0)))
    tabs = tuple(sorted({twips(line.bbox.x0 - bbox.x0) for line in lines if line.bbox.x0 > bbox.x0 + pt_vers_emu(0.5)})) if geometry_kind(element) != "rectangular-flow" or composition.preserve_lines else ()
    marker = getattr(element, "list_marker_bbox", None)
    body_x = min((line.bbox.x0 for line in lines), default=bbox.x0)
    if marker is not None and body_x > bbox.x0:
        tabs = tuple(sorted({*tabs, max(twips(body_x - bbox.x0), 1)}))
    list_left = twips(max(pt_vers_emu(6), body_x - marker.x0)) if marker else 0
    from pdfexact.analysis.line_structure import split_leader

    leader_tabs = tuple(sorted({
        (max(twips(line.bbox.x1 - bbox.x0), 1), parts[2])
        for line in lines
        if (parts := split_leader("".join(span.texte for span in line.spans))) is not None
    }))
    return TextGeometrySpec(
        bbox, block_alignment(element), geometry_kind(element), max(twips(height), 1), max(twips(step), 1),
        max(twips(frame_height), 1), "exact" if compact and lines else "atLeast",
        native_height, native_line, tabs, list_left, max(0, min(8, int(getattr(element, "list_level", 0) or 0))),
        leader_tabs,
    ), compact
