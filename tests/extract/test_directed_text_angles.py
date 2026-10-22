import math
from types import SimpleNamespace

import pymupdf
import pytest

from pdfexact.extract.text import _angle_direction, extraire_texte
from pdfexact.geometry import PageGeometry, etat_page
from pdfexact.ir import FontAsset
from pdfexact.render.drawing import _rotation_ooxml
from pdfexact.render.word_native_rewriter import _frame_body_properties


@pytest.mark.parametrize(
    "direction, expected",
    [((0, 1), -90), ((0, -1), 90), ((-1, 0), 180)],
)
def test_directed_angle_without_page_preserves_reading_direction(direction, expected):
    assert _angle_direction(direction) == pytest.approx(expected)


@pytest.mark.parametrize("page_rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("text_angle", [0, 180, 90, -90, 30, -30, 135, -135])
def test_source_direction_survives_canonical_page_rotation_and_word_conversion(
    page_rotation, text_angle
):
    with pymupdf.open() as document:
        page = document.new_page(width=400, height=500)
        origin = pymupdf.Point(200, 250)
        page.insert_text(
            origin,
            "Directional text",
            fontsize=10,
            color=(0.2, 0.4, 0.6),
            morph=(origin, pymupdf.Matrix(text_angle)),
        )
        page.set_rotation(page_rotation)
        before = etat_page(page)
        geometry = PageGeometry.depuis_page(page)
        source = page.get_text("dict")["blocks"][0]
        source_line = source["lines"][0]
        source_span = source_line["spans"][0]
        assert source_line["dir"] == pytest.approx(
            (math.cos(math.radians(text_angle)), -math.sin(math.radians(text_angle))),
            abs=1e-5,
        )
        font = FontAsset("Helvetica", "Arial", None, "", False)
        elements = extraire_texte(page, {"Helvetica": font}, geometrie=geometry)

        assert etat_page(page) == before
        assert len(elements) == 1
        element = elements[0]
        line = element.lignes[0]
        span = line.spans[0]
        expected = (text_angle - page_rotation + 180) % 360 - 180
        if expected == -180:
            expected = 180
        assert line.angle_deg == pytest.approx(expected, abs=1e-3)
        assert element.bbox == geometry.bbox_depuis_rect_natif(pymupdf.Rect(source["bbox"]))
        assert span.bbox == geometry.bbox_depuis_rect_natif(pymupdf.Rect(source_span["bbox"]))
        assert span.texte == source_span["text"]
        assert span.police.font_id == "Helvetica"
        assert span.size_pt == 10
        assert span.couleur == f'{source_span["color"]:06X}'
        assert not span.police.gras
        assert not span.police.italique

        drawing_angle = _rotation_ooxml(SimpleNamespace(angle_deg=line.angle_deg))
        assert drawing_angle == pytest.approx(-expected * 60000, abs=100)
        body_rotation, vertical_mode = _frame_body_properties(element)
        if abs(expected) == 90:
            assert body_rotation == 0
            assert vertical_mode == ("vert270" if expected > 0 else "vert")
        else:
            assert vertical_mode == "horz"
            assert body_rotation == pytest.approx(-expected * 60000, abs=100)
