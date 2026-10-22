import math
from types import SimpleNamespace

import pymupdf
import pytest

from pdfexact.extract.text import _angle_direction, extraire_texte
from pdfexact.geometry import PageGeometry, etat_page
from pdfexact.ir import FontAsset


@pytest.mark.parametrize(
    "direction, expected",
    [((0, 1), -90), ((0, -1), 90), ((-1, 0), 180)],
)
def test_directed_angle_without_page_preserves_reading_direction(direction, expected):
    assert _angle_direction(direction) == pytest.approx(expected)


