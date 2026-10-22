from copy import deepcopy

import pytest

from pdfexact.analysis.geometry import resolve_text_orientation
from pdfexact.analysis.text_geometry import geometry_contract_for, is_special_orientation, orientation_of
from pdfexact.geometry import BBox
from pdfexact.ir import FontRef, Line, Span, TextBox


@pytest.mark.parametrize(
    "parent, children, expected_special",
    [
        ((30.0, "horizontal"), [(-90.0, "vertical")], True),
        ((180.0, "horizontal"), [(0.0, "horizontal")], True),
        ((-135.0, "oblique-up"), [(90.0, "vertical")], True),
        ((0.0, "horizontal"), [(180.0, "rotated")], True),
        ((0.0, "horizontal"), [(-90.0, "vertical"), (0.0, "horizontal")], False),
        ((0.0, "horizontal"), [(0.0, "horizontal")], False),
    ],
)
def test_text_geometry_uses_canonical_orientation_without_losing_directed_angles(parent, children, expected_special):
    bbox = BBox(10, 10, 100, 30)
    font = FontRef("test", "Arial", False, False)
    lines = [
        Line(bbox, [Span("Observed text", font, 10, "000000")], 20, 90,
             angle_deg=angle, orientation=orientation)
        for angle, orientation in children
    ]
    element = TextBox(bbox, lines, angle_deg=parent[0], orientation=parent[1])
    before = deepcopy(element)
    resolved = resolve_text_orientation(element)

    assert orientation_of(element) == resolved["orientation"]
    assert is_special_orientation(element) is expected_special
    geometry = geometry_contract_for(element)
    assert geometry.kind == ("oriented" if expected_special else "rectangular-flow")
    assert geometry.line_bboxes == tuple(line.bbox for line in lines)
    assert resolved["angle_deg"] == (children[0][0] if parent == (0.0, "horizontal") and len(children) == 1 else parent[0])
    assert element == before
