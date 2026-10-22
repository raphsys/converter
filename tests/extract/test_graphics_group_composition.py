from io import BytesIO
from xml.etree import ElementTree as ET

import pymupdf
import pytest
from PIL import Image

from pdfexact.extract.images import extraire_images
from pdfexact.extract.text import extraire_texte
from pdfexact.extract.vector import extraire_vectoriel
from pdfexact.geometry import PageGeometry
from pdfexact.ir import Document, FontAsset, Page, RasterEl


def _png(color, alpha=255):
    stream = BytesIO()
    image = Image.new("RGBA", (64, 64), color)
    image.putalpha(alpha)
    image.save(stream, format="PNG")
    return stream.getvalue()


def _group(pdf, page, level, isolated=True):
    resources = int(pdf.xref_get_key(page.xref, "Resources")[1].split()[0])
    content = b"\n".join(pdf.xref_stream(xref) for xref in page.get_contents())
    form = pdf.get_new_xref()
    pdf.update_object(form, f"<</Type/XObject /Subtype/Form /BBox[0 0 200 200] /Resources {resources} 0 R /Group<</S/Transparency /CS/DeviceRGB /I {str(isolated).lower()}>>>>")
    pdf.update_stream(form, content)
    pdf.xref_set_key(resources, f"XObject/Group{level}", f"{form} 0 R")
    pdf.xref_set_key(resources, f"ExtGState/Alpha{level}", "<</Type/ExtGState /ca 0.5 /CA 0.5>>")
    stream = pdf.get_new_xref()
    pdf.update_object(stream, "<<>>")
    pdf.update_stream(stream, f"q /Alpha{level} gs /Group{level} Do Q".encode())
    page.set_contents(stream)


def _assert_source_pixel(page, element, media, point):
    source = page.get_pixmap(alpha=True).pixel(*point)
    expected = tuple(round(channel * 255 / source[3]) if source[3] else 0 for channel in source[:3]) + (source[3],)
    image = Image.open(BytesIO(media[element.media_ref].donnees)).convert("RGBA")
    x = int((point[0] * 12700 - element.bbox.x0) * image.width / element.bbox.largeur)
    y = int((point[1] * 12700 - element.bbox.y0) * image.height / element.bbox.hauteur)
    actual = image.getpixel((x, y))
    assert abs(actual[3] - expected[3]) <= 1
    if expected[3]:
        assert all(abs(a - b) <= 3 for a, b in zip(actual[:3], expected[:3]))


@pytest.mark.parametrize("overlap", (False, True))
@pytest.mark.parametrize("levels", (1, 2))
@pytest.mark.parametrize("foreground", ("blue", "white"))
@pytest.mark.parametrize("intrinsic_alpha", (255, 96))
def test_group_children_composite_before_group_opacity(overlap, levels, foreground, intrinsic_alpha):
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=200, height=200)
        page.insert_image((20, 20, 120, 120) if overlap else (20, 20, 80, 80), stream=_png("red"))
        page.insert_image((80, 80, 180, 180) if overlap else (120, 120, 180, 180), stream=_png(foreground, intrinsic_alpha))
        for level in range(levels):
            _group(pdf, page, level)
        media = {}
        elements = extraire_images(page, pdf, media, PageGeometry.depuis_page(page))
        assert len(elements) == 1
        group = elements[0]
        assert isinstance(group, RasterEl)
        assert group.paint_group_id
        assert group.paint_sequences == (0, 1)
        assert group.z_index == 0
        for point in ((40, 40), (100, 100), (150, 150)):
            _assert_source_pixel(page, group, media, point)


@pytest.mark.parametrize("background_vector", (False, True))
@pytest.mark.parametrize("foreground", ((0, 0, 1), (1, 1, 1)))
def test_group_composition_keeps_source_vector_paint(background_vector, foreground):
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=200, height=200)
        if background_vector:
            page.draw_rect((20, 20, 120, 120), color=None, fill=(1, 0, 0))
        else:
            page.insert_image((20, 20, 120, 120), stream=_png("red"))
        page.draw_rect((80, 80, 180, 180), color=None, fill=foreground)
        _group(pdf, page, 0)
        geometry = PageGeometry.depuis_page(page)
        assert extraire_vectoriel(page, geometry) == []
        media = {}
        group, = extraire_images(page, pdf, media, geometry)
        assert group.paint_sequences == (0, 1)
        _assert_source_pixel(page, group, media, (100, 100))


def test_reused_form_has_distinct_group_occurrences_and_applies_each_opacity_once():
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=200, height=200)
        page.insert_image((20, 20, 120, 120), stream=_png("red"))
        page.insert_image((80, 80, 180, 180), stream=_png("blue"))
        _group(pdf, page, 0)
        pdf.update_stream(page.get_contents()[0], b"q /Alpha0 gs /Group0 Do Q q /Alpha0 gs /Group0 Do Q")
        geometry = PageGeometry.depuis_page(page)
        media = {}
        groups = extraire_images(page, pdf, media, geometry)
        assert len(groups) == 2
        assert all(isinstance(group, RasterEl) for group in groups)
        assert len({group.paint_group_id for group in groups}) == 2
        assert [group.paint_sequences for group in groups] == [(0, 1), (2, 3)]
        assert [group.z_index for group in groups] == [0, 2]
        assert groups[0].source_xrefs == groups[1].source_xrefs
        assert extraire_vectoriel(page, geometry) == []
        images = [Image.open(BytesIO(media[group.media_ref].donnees)).convert("RGBA") for group in groups]
        combined = Image.alpha_composite(*images)
        x = int((100 * 12700 - groups[0].bbox.x0) * combined.width / groups[0].bbox.largeur)
        y = int((100 * 12700 - groups[0].bbox.y0) * combined.height / groups[0].bbox.hauteur)
        actual = combined.getpixel((x, y))
        source = page.get_pixmap(alpha=True).pixel(100, 100)
        assert actual[:3] == (0, 0, 255)
        assert abs(actual[3] - source[3]) <= 1




