"""A stroked page frame and a clipped shading never become page-sized rasters."""
import pymupdf

from pdfexact.extract.images import _graphic_paint_operations, _graphic_requires_raster
from pdfexact.fallback.rasterize import extraire_zones_shading
from pdfexact.geometry import PageGeometry, emu_vers_pt

SHADING = ("<< /ShadingType 2 /ColorSpace /DeviceRGB /Coords [0 0 612 0] /Function "
           "<< /FunctionType 2 /Domain [0 1] /C0 [0 0 1] /C1 [1 1 1] /N 1 >> >>")


def _page(contents, shading=False):
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    resources = "<< >>"
    if shading:
        xref = doc.get_new_xref()
        doc.update_object(xref, SHADING)
        resources = f"<< /Shading << /Sh0 {xref} 0 R >> >>"
    doc.xref_set_key(page.xref, "Resources", resources)
    stream = doc.get_new_xref()
    doc.update_object(stream, "<< >>")
    doc.update_stream(stream, contents.encode())
    doc.xref_set_key(page.xref, "Contents", f"{stream} 0 R")
    return doc, doc[0]


def test_a_stroked_frame_before_a_clip_does_not_widen_the_shading_zone():
    # Frame stroked over the page, then a shading clipped to a band at the bottom.
    doc, page = _page("1 w 50 27 513 747 re S q 54 33 503 41 re W n /Sh0 sh Q", shading=True)
    zones = extraire_zones_shading(doc, page, PageGeometry.depuis_page(page))
    assert len(zones) == 1
    x0, y0, x1, y1 = (round(emu_vers_pt(value)) for value in (zones[0].x0, zones[0].y0, zones[0].x1, zones[0].y1))
    assert (x0, x1) == (54, 557) and (y0, y1) == (718, 759)


def test_nested_clips_intersect():
    doc, page = _page("q 0 0 612 792 re W n q 54 33 503 41 re W n /Sh0 sh Q Q", shading=True)
    zone = extraire_zones_shading(doc, page, PageGeometry.depuis_page(page))[0]
    assert round(emu_vers_pt(zone.y1) - emu_vers_pt(zone.y0)) == 41


def test_a_stroke_clipped_by_a_rectangle_stays_vector():
    # The rectangular clip cuts half of the stroke width: the visible part is still a rectangle outline.
    _doc, page = _page("q 50 27 513 747 re W n 3 w 50 27 513 747 re S Q")
    operations = [op for op in _graphic_paint_operations(page) if op["kind"] == "stroke_path"]
    assert operations and not any(_graphic_requires_raster(op) for op in operations)


def test_a_path_clipped_by_a_non_rectangular_shape_is_still_rendered():
    _doc, page = _page("q 100 100 m 300 100 l 200 300 l h W n 0 0 1 rg 50 50 400 400 re f Q")
    operations = [op for op in _graphic_paint_operations(page) if op["kind"] == "fill_path"]
    assert operations and all(_graphic_requires_raster(op) for op in operations)
