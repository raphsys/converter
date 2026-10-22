from pdfexact.extract.image_composition import (
    _PlacementInfo,
    _can_join,
    _components,
    _is_composition,
)
from types import SimpleNamespace

from pdfexact.geometry import BBox
from pdfexact.ir import ImageEl


def _image(index, box, source_size):
    element = ImageEl(
        bbox=BBox(*(int(value * 12700) for value in box)),
        media_ref=f"image{index}",
        source_xref=index,
    )
    return _PlacementInfo(index, element, source_size)


def test_adjacent_equal_slices_form_one_component_but_not_page_background():
    first = _image(1, (100, 100, 200, 133), (200, 68))
    second = _image(2, (100, 132, 200, 166), (200, 68))
    background = _image(3, (0, 0, 500, 400), (1500, 900))

    assert _can_join(first, second)
    assert not _can_join(first, background)
    groups = _components([first, second, background])
    assert any({info.index for info in group} == {1, 2} for group in groups)


def test_attached_thin_strip_joins_matching_image_only():
    strip = _image(1, (100, 100, 200, 103), (200, 7))
    image = _image(2, (100, 102, 200, 200), (209, 204))
    assert _can_join(strip, image)


def test_composition_rejects_page_sized_group():
    first = _image(1, (0, 0, 500, 30), (1500, 90))
    second = _image(2, (0, 29, 500, 400), (1500, 1100))
    geometry = SimpleNamespace(largeur_emu=500 * 12700, hauteur_emu=400 * 12700)
    assert not _is_composition([first, second], geometry)
