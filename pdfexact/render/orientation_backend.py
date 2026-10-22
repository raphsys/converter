"""Normalized orientation instructions prepared before XML consumption."""
from dataclasses import dataclass

from pdfexact.analysis.text_geometry import orientation_of, is_special_orientation


@dataclass(frozen=True)
class OrientationSpec:
    name: str
    angle_deg: float
    body_rotation: int
    body_vertical: str
    vml_rotation: int
    vertical: bool
    special: bool
    warp: str


def prepare_orientation(element, lines) -> OrientationSpec:
    name = orientation_of(element)
    angle = float(getattr(element, "angle_deg", 0.0) or 0.0)
    if not angle:
        angle = next((float(line.angle_deg) for line in lines if abs(float(line.angle_deg or 0.0)) > 0.1), 0.0)
    vertical = name in {"vertical", "vertical-lr", "vertical-rl", "vertical-rtl"}
    body_vertical = ("vert270" if angle >= 0 else "vert") if vertical else "horz"
    curved = bool(getattr(element, "curved", False)) or name == "curved" or any(getattr(line, "curved", False) for line in lines)
    points = list(getattr(element, "baseline_points", ()) or ())
    if not points:
        points = [point for line in lines for point in (getattr(line, "baseline_points", ()) or ())]
    warp = ("textArchDown" if len(points) >= 2 and points[-1][1] < points[0][1] else "textArchUp") if curved else ""
    return OrientationSpec(
        name, angle, 0 if vertical or abs(angle) <= 7 else round(-angle * 60000), body_vertical,
        (-90 if angle >= 0 else 90) if vertical else round(-angle),
        vertical, is_special_orientation(element), warp,
    )
