import zipfile
from dataclasses import replace
from xml.etree import ElementTree

import pymupdf
import pytest

from pdfexact.geometry import BBox, PageGeometry, pt_vers_emu
from pdfexact.ir import Document, FontRef, Line, Page, Span, TextBox, TextGeometry
from pdfexact.render.bbox_debug import (
    BBoxRecord,
    _composition_path,
    _rectangle_path,
    annotate_pdf_bboxes,
    write_bbox_only_docx,
)


def _record(rectangles, scale=1):
    boxes = tuple(
        BBox(*(pt_vers_emu(value * scale) for value in rectangle))
        for rectangle in rectangles
    )
    envelope = BBox(
        min(box.x0 for box in boxes),
        min(box.y0 for box in boxes),
        max(box.x1 for box in boxes),
        max(box.y1 for box in boxes),
    )
    return BBoxRecord(0, envelope, "text", (0.9, 0.05, 0.05), boxes)


def _signed_area(polygon):
    return sum(
        a[0] * b[1] - b[0] * a[1]
        for a, b in zip(polygon, polygon[1:] + polygon[:1])
    )


def _polygons(path):
    polygons = []
    points = None
    for operation, values in path:
        if operation == "move":
            assert points is None, "Previous subpath was not closed"
            points = [values[0]]
        elif operation == "line":
            assert points is not None
            points.append(values[0])
        else:
            assert operation == "close"
            assert points is not None
            polygons.append(points)
            points = None
    assert points is None, "Final subpath was not closed"
    assert polygons
    for polygon in polygons:
        edges = list(zip(polygon, polygon[1:] + polygon[:1]))
        assert len(polygon) >= 4
        assert len(set(polygon)) == len(polygon), "Contour revisits a vertex"
        assert _signed_area(polygon) != 0
        for index, (first, second) in enumerate(edges):
            assert first != second
            assert first[0] == second[0] or first[1] == second[1], "Diagonal edge"
            for other_index, (third, fourth) in enumerate(edges):
                if other_index <= index + 1 or (index == 0 and other_index == len(edges) - 1):
                    continue
                overlap_x = min(max(first[0], second[0]), max(third[0], fourth[0])) >= max(
                    min(first[0], second[0]), min(third[0], fourth[0])
                )
                overlap_y = min(max(first[1], second[1]), max(third[1], fourth[1])) >= max(
                    min(first[1], second[1]), min(third[1], fourth[1])
                )
                assert not (overlap_x and overlap_y), "Self-intersecting contour"
    return polygons


def _contains(polygons, x, y, scale=1):
    x, y = pt_vers_emu(x * scale), pt_vers_emu(y * scale)
    inside = False
    for polygon in polygons:
        for first, second in zip(polygon, polygon[1:] + polygon[:1]):
            if (first[1] > y) != (second[1] > y):
                crossing = first[0] + (y - first[1]) * (second[0] - first[0]) / (second[1] - first[1])
                if x < crossing:
                    inside = not inside
    return inside


@pytest.mark.parametrize("scale", (1, 3))
def test_same_baseline_fragments_form_one_row(scale):
    record = _record([(40, 40, 80, 50), (84, 42, 130, 50), (40, 54, 130, 64)], scale)

    path = _composition_path(record)
    polygons = _polygons(path)

    assert len(polygons) == 1
    assert _contains(polygons, 82, 46, scale)
    assert _contains(polygons, 90, 58, scale)
    assert not _contains(polygons, 120, 41, scale)
    assert _composition_path(replace(record, line_bboxes=record.line_bboxes[::-1])) == path


@pytest.mark.parametrize(
    "rectangles, excluded",
    [
        ([(70, 20, 160, 30), (40, 34, 160, 44), (55, 48, 140, 58), (40, 62, 110, 72)], [(45, 25), (150, 53)]),
        ([(64, 20, 160, 30), (64, 34, 150, 44), (64, 48, 160, 58), (40, 62, 160, 72)], [(45, 25), (45, 39)]),
        ([(40, 20, 60, 56), (64, 20, 160, 30), (64, 34, 150, 44), (64, 48, 160, 58), (40, 62, 160, 72)], [(62, 39)]),
    ],
    ids=("variable-indents", "dropcap-exclusion", "tall-dropcap-fragment"),
)
def test_continuous_rows_have_a_simple_exterior(rectangles, excluded):
    polygons = _polygons(_composition_path(_record(rectangles)))

    assert len(polygons) == 1
    for x0, y0, x1, y1 in rectangles:
        assert _contains(polygons, (x0 + x1) / 2, (y0 + y1) / 2)
    for x, y in excluded:
        assert not _contains(polygons, x, y)


@pytest.mark.parametrize("scale", (1, 3))
@pytest.mark.parametrize(
    "rectangles, empty_point",
    [
        ([(40, 20, 160, 30), (40, 160, 160, 170)], (80, 90)),
        ([(40, 20, 80, 30), (150, 34, 200, 44)], (110, 32)),
        ([(40, 20, 80, 30), (150, 20, 200, 30), (40, 34, 80, 44), (150, 34, 200, 44)], (110, 32)),
        ([(40, 20, 80, 30), (80, 30, 120, 40)], (90, 25)),
    ],
    ids=("vertical-gap", "horizontal-discontinuity", "parallel-columns", "corner-contact"),
)
def test_disconnected_components_have_separate_closed_subpaths(rectangles, empty_point, scale):
    polygons = _polygons(_composition_path(_record(rectangles, scale)))

    assert len(polygons) == 2
    assert all(_signed_area(polygon) > 0 for polygon in polygons)
    assert not _contains(polygons, *empty_point, scale)
    for x0, y0, x1, y1 in rectangles:
        assert _contains(polygons, (x0 + x1) / 2, (y0 + y1) / 2, scale)


def test_rows_on_both_sides_of_an_exclusion_preserve_the_hole():
    rectangles = [
        (40, 20, 180, 30),
        (40, 34, 80, 44), (140, 34, 180, 44),
        (40, 48, 80, 58), (140, 48, 180, 58),
        (40, 62, 180, 72),
    ]

    polygons = _polygons(_composition_path(_record(rectangles)))

    assert len(polygons) == 2
    assert sum(_signed_area(polygon) > 0 for polygon in polygons) == 1
    assert not _contains(polygons, 110, 39)
    assert not _contains(polygons, 110, 46)
    assert _contains(polygons, 60, 46)
    assert _contains(polygons, 160, 46)


def test_overlapping_and_duplicate_fragments_have_no_internal_edges():
    rectangles = [(40, 20, 120, 32), (80, 20, 160, 32), (80, 20, 160, 32), (50, 30, 150, 44)]

    polygons = _polygons(_composition_path(_record(rectangles)))

    assert len(polygons) == 1
    assert _contains(polygons, 90, 31)
    assert not _contains(polygons, 45, 40)


def test_exclusion_touching_exterior_at_one_corner_has_simple_loops():
    record = _record([
        (10, 10, 50, 50), (50, 10, 70, 30),
        (60, 40, 80, 70), (50, 50, 60, 60),
    ])

    polygons = _polygons(_composition_path(record))

    assert len(polygons) == 2
    assert sum(_signed_area(polygon) > 0 for polygon in polygons) == 1
    assert not _contains(polygons, 55, 40)
    assert _contains(polygons, 55, 55)


@pytest.mark.parametrize("with_line", (False, True))
def test_single_rectangular_box_keeps_its_original_path(with_line):
    record = _record([(50, 30, 150, 40)])
    record = replace(record, bbox=BBox(0, 0, pt_vers_emu(200), pt_vers_emu(60)))
    if not with_line:
        record = replace(record, line_bboxes=())

    assert _composition_path(record) == _rectangle_path(record.bbox)


def test_aligned_continuous_rows_have_one_rectangular_exterior():
    record = _record([(40, 20, 160, 30), (40, 34, 160, 44), (40, 48, 160, 58)])

    polygons = _polygons(_composition_path(record))

    assert len(polygons) == 1
    assert len(polygons[0]) == 4
    assert _contains(polygons, 80, 32)


def _document(record, geometry):
    font = FontRef("Test", "Arial", False, False)
    lines = [
        Line(box, [Span("text", font, 10, "000000")], box.hauteur, box.largeur)
        for box in record.line_bboxes
    ]
    element = TextBox(
        record.bbox, lines,
        geometry=TextGeometry(kind="exclusion-flow", line_bboxes=record.line_bboxes),
    )
    return Document(pages=[Page(0, geometry.largeur_emu, geometry.hauteur_emu, [element])])


@pytest.mark.parametrize("rotation", (0, 90, 180, 270))
@pytest.mark.parametrize("crop", (False, True))
def test_pdf_preserves_separate_closed_contours(rotation, crop, tmp_path):
    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "contours.pdf"
    record = _record([(40, 30, 95, 40), (150, 120, 205, 130)])
    with pymupdf.open() as source:
        page = source.new_page(width=320, height=240)
        if crop:
            page.set_cropbox(pymupdf.Rect(20, 15, 300, 225))
        page.set_rotation(rotation)
        geometry = PageGeometry.depuis_page(page)
        cropbox = page.cropbox
        source.save(source_path)

    annotate_pdf_bboxes(source_path, output_path, _document(record, geometry))

    with pymupdf.open(output_path) as output:
        page = output[0]
        assert page.rotation == rotation
        assert page.cropbox == cropbox
        edges = []
        for drawing in page.get_drawings():
            for item in drawing["items"]:
                if item[0] == "l":
                    edges.append((item[1] * page.rotation_matrix, item[2] * page.rotation_matrix))
                else:
                    assert item[0] == "re"
                    rectangle = item[1]
                    corners = [rectangle.tl, rectangle.tr, rectangle.br, rectangle.bl]
                    edges.extend(
                        (a * page.rotation_matrix, b * page.rotation_matrix)
                        for a, b in zip(corners, corners[1:] + corners[:1])
                    )
        assert len(edges) == 8
        for first, second in edges:
            assert first.x == pytest.approx(second.x) or first.y == pytest.approx(second.y)
            assert any(
                rectangle.contains(first) and rectangle.contains(second)
                for rectangle in (pymupdf.Rect(39.99, 29.99, 95.01, 40.01), pymupdf.Rect(149.99, 119.99, 205.01, 130.01))
            ), "PDF draws a connector between independent contours"
        assert sum(abs(a.x - b.x) + abs(a.y - b.y) for a, b in edges) == pytest.approx(260)


def test_docx_shape_accepts_multiple_closed_subpaths(tmp_path):
    record = _record([(40, 30, 95, 40), (150, 120, 205, 130)])
    with pymupdf.open() as source:
        geometry = PageGeometry.depuis_page(source.new_page(width=320, height=240))
    destination = tmp_path / "contours.docx"

    write_bbox_only_docx(_document(record, geometry), destination)

    with zipfile.ZipFile(destination) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    namespace = {
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    }
    assert len(root.findall(".//a:moveTo", namespace)) == 2
    assert len(root.findall(".//a:close", namespace)) == 2
    assert len(root.findall(".//wp:anchor", namespace)) == 1
    assert not root.findall(".//w:t", namespace)
