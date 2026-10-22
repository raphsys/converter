"""Operations geometriques communes a toute la chaine.

Toutes les boites sont en EMU et utilisent l'origine en haut a gauche. Ce
module ne supprime jamais une geometrie : il mesure et normalise.
"""
from __future__ import annotations

from math import atan2, degrees, hypot
from typing import Iterable

from pdfexact.geometry import BBox, se_chevauchent, union


Point = tuple[int, int]
Rect = tuple[float, float, float, float]


def bbox_area(bbox: BBox) -> int:
    return max(0, bbox.largeur) * max(0, bbox.hauteur)


def rect_area(rect: Rect) -> float:
    x0, y0, x1, y1 = rect
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def rect_intersection_area(left: Rect, right: Rect) -> float:
    return max(0.0, min(left[2], right[2]) - max(left[0], right[0])) * max(
        0.0, min(left[3], right[3]) - max(left[1], right[1])
    )


def rect_overlap_ratio(inner: Rect, outer: Rect) -> float:
    area = rect_area(inner)
    return rect_intersection_area(inner, outer) / area if area else 0.0


def rect_union(left: Rect, right: Rect) -> Rect:
    return (
        min(left[0], right[0]),
        min(left[1], right[1]),
        max(left[2], right[2]),
        max(left[3], right[3]),
    )


def axis_overlap_ratio(left: BBox, right: BBox, axis: str) -> float:
    if axis == "x":
        length = max(0, min(left.x1, right.x1) - max(left.x0, right.x0))
        denominator = max(min(left.largeur, right.largeur), 1)
    elif axis == "y":
        length = max(0, min(left.y1, right.y1) - max(left.y0, right.y0))
        denominator = max(min(left.hauteur, right.hauteur), 1)
    else:
        raise ValueError("axis doit valoir x ou y")
    return length / denominator


def clip_bbox_nonempty(bbox: BBox, page_width: int, page_height: int) -> BBox:
    x0 = max(0, min(bbox.x0, max(page_width - 1, 0)))
    y0 = max(0, min(bbox.y0, max(page_height - 1, 0)))
    x1 = max(x0 + 1, min(bbox.x1, page_width))
    y1 = max(y0 + 1, min(bbox.y1, page_height))
    return BBox(x0, y0, x1, y1)


def intersection_area(left: BBox, right: BBox) -> int:
    if not se_chevauchent(left, right):
        return 0
    return max(0, min(left.x1, right.x1) - max(left.x0, right.x0)) * max(
        0, min(left.y1, right.y1) - max(left.y0, right.y0)
    )


def overlap_ratio(inner: BBox, outer: BBox) -> float:
    area = bbox_area(inner)
    return intersection_area(inner, outer) / area if area else 0.0


def iou(left: BBox, right: BBox) -> float:
    intersection = intersection_area(left, right)
    total = bbox_area(left) + bbox_area(right) - intersection
    return intersection / total if total else 0.0


def intersection_over_min_area(left: BBox, right: BBox) -> float:
    """Recouvrement symétrique utilisé pour comparer deux objets concurrents."""
    denominator = max(min(bbox_area(left), bbox_area(right)), 1)
    return intersection_area(left, right) / denominator


def center(bbox: BBox) -> Point:
    return ((bbox.x0 + bbox.x1) // 2, (bbox.y0 + bbox.y1) // 2)


def center_in(bbox: BBox, zone: BBox) -> bool:
    x, y = center(bbox)
    return zone.x0 <= x <= zone.x1 and zone.y0 <= y <= zone.y1


def clip_bbox(bbox: BBox, page_width: int, page_height: int) -> BBox:
    return BBox(
        max(0, min(page_width, bbox.x0)),
        max(0, min(page_height, bbox.y0)),
        max(0, min(page_width, bbox.x1)),
        max(0, min(page_height, bbox.y1)),
    )


def union_many(boxes: Iterable[BBox]) -> BBox | None:
    result: BBox | None = None
    for bbox in boxes:
        result = bbox if result is None else union(result, bbox)
    return result


def gap(left: BBox, right: BBox) -> tuple[int, int]:
    """Distance horizontale/verticale entre deux boites, 0 si elles se recouvrent."""
    dx = max(0, max(left.x0, right.x0) - min(left.x1, right.x1))
    dy = max(0, max(left.y0, right.y0) - min(left.y1, right.y1))
    return dx, dy


def baseline_angle(points: Iterable[Point]) -> float | None:
    values = tuple(points)
    if len(values) < 2:
        return None
    start, end = values[0], values[-1]
    if start == end:
        return None
    return degrees(atan2(end[1] - start[1], end[0] - start[0]))


def polyline_length(points: Iterable[Point]) -> float:
    values = tuple(points)
    return sum(hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(values, values[1:]))


def quad_bbox(points: Iterable[Point]) -> BBox | None:
    values = tuple(points)
    if not values:
        return None
    return BBox(
        min(point[0] for point in values),
        min(point[1] for point in values),
        max(point[0] for point in values),
        max(point[1] for point in values),
    )


def orientation_from_angle(angle: float | None, tolerance: float = 8.0) -> str:
    if angle is None:
        return "unknown"
    normal = ((angle + 180.0) % 360.0) - 180.0
    if abs(normal) <= tolerance or abs(abs(normal) - 180.0) <= tolerance:
        return "horizontal"
    if abs(abs(normal) - 90.0) <= tolerance:
        return "vertical"
    return "oblique-up" if normal < 0 else "oblique-down"


def projection_x(geometry: BBox | Iterable[Point]) -> tuple[float, float] | None:
    if isinstance(geometry, BBox):
        return geometry.x0, geometry.x1
    values = tuple(point[0] for point in geometry)
    return (min(values), max(values)) if values else None


def projection_y(geometry: BBox | Iterable[Point]) -> tuple[float, float] | None:
    if isinstance(geometry, BBox):
        return geometry.y0, geometry.y1
    values = tuple(point[1] for point in geometry)
    return (min(values), max(values)) if values else None


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _polygon_area(points):
    if len(points) < 3:
        return 0.0
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))) / 2.0


def _ordered_quad(points):
    points = tuple(points)
    if len(points) != 4:
        raise ValueError("un quadrilatere doit porter quatre points")
    x, y = sum(p[0] for p in points) / 4, sum(p[1] for p in points) / 4
    return sorted(points, key=lambda point: atan2(point[1] - y, point[0] - x))


def quad_iou(left: Iterable[Point], right: Iterable[Point]) -> float:
    """Convex quadrilateral IoU, including PyMuPDF's UL/UR/LL/LR order."""
    left, right = _ordered_quad(left), _ordered_quad(right)
    left_area, right_area = _polygon_area(left), _polygon_area(right)
    if not left_area or not right_area:
        return 0.0
    # Sutherland-Hodgman clipping, with counterclockwise convex clip edges.
    polygon = left
    for a, b in zip(right, right[1:] + right[:1]):
        previous = polygon
        polygon = []
        if not previous:
            break
        start = previous[-1]
        for end in previous:
            start_side, end_side = _cross(a, b, start), _cross(a, b, end)
            if (start_side >= 0) != (end_side >= 0):
                ratio = start_side / (start_side - end_side)
                polygon.append((start[0] + ratio * (end[0] - start[0]),
                                start[1] + ratio * (end[1] - start[1])))
            if end_side >= 0:
                polygon.append(end)
            start = end
    intersection = _polygon_area(polygon)
    return intersection / (left_area + right_area - intersection)


def _point_segment_distance(point, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    norm = dx * dx + dy * dy
    ratio = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / norm)) if norm else 0.0
    return hypot(point[0] - start[0] - ratio * dx, point[1] - start[1] - ratio * dy)


def baseline_distance(left: Iterable[Point], right: Iterable[Point]) -> float | None:
    """Shortest distance between complete baseline polylines; absent is unknown."""
    left, right = tuple(left), tuple(right)
    if not left or not right:
        return None
    left_segments = tuple(zip(left, left[1:])) or ((left[0], left[0]),)
    right_segments = tuple(zip(right, right[1:])) or ((right[0], right[0]),)
    result = float("inf")
    for a, b in left_segments:
        for c, d in right_segments:
            distances = (_point_segment_distance(a, c, d), _point_segment_distance(b, c, d),
                         _point_segment_distance(c, a, b), _point_segment_distance(d, a, b))
            if _cross(a, b, c) * _cross(a, b, d) < 0 and _cross(c, d, a) * _cross(c, d, b) < 0:
                return 0.0
            result = min(result, *distances)
    return result


def baseline_curvature(points: Iterable[Point]) -> float | None:
    """Length excess over the endpoint chord, without an implicit threshold."""
    points = tuple(points)
    if len(points) < 2:
        return None
    length = polyline_length(points)
    return 1.0 - hypot(points[-1][0] - points[0][0], points[-1][1] - points[0][1]) / length if length else 0.0


def path_is_curved(path) -> bool:
    return any(command in {"cubic", "quad"} for command, _points in path)


def resolve_text_orientation(element) -> dict[str, object]:
    """Keep explicit parent geometry; report contradictory child observations."""
    parent_angle = getattr(element, "angle_deg", 0.0)
    parent_orientation = getattr(element, "orientation", "unknown")
    lines = list(getattr(element, "lignes", ()) or ())
    parent_explicit = bool(parent_angle) or parent_orientation not in {"horizontal", "unknown", "auto", None}
    angle, orientation = parent_angle, parent_orientation
    conflicts = []
    if len(lines) == 1:
        line = lines[0]
        line_angle = getattr(line, "angle_deg", 0.0)
        line_orientation = getattr(line, "orientation", "unknown")
        if not parent_explicit:
            angle, orientation = line_angle, line_orientation
        observed = bool(line_angle or line_orientation not in {"horizontal", "unknown", "auto", None}
                        or getattr(line, "quad", ()) or getattr(line, "baseline_points", ()))
        if parent_explicit and observed and (parent_angle != line_angle or parent_orientation != line_orientation):
            conflicts.append({"parent": {"angle_deg": parent_angle, "orientation": parent_orientation},
                              "line": {"angle_deg": line_angle, "orientation": line_orientation},
                              "line_source_id": getattr(line, "source_id", None)})
    return {"angle_deg": angle, "orientation": orientation, "conflicts": tuple(conflicts),
            "parent": {"angle_deg": parent_angle, "orientation": parent_orientation}}
