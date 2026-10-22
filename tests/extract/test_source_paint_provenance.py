from io import BytesIO

import pymupdf
import pytest
from PIL import Image

from pdfexact.extract.images import extraire_images
from pdfexact.extract.text import extraire_texte
from pdfexact.extract.vector import extraire_vectoriel
from pdfexact.geometry import PageGeometry
from pdfexact.ir import FontAsset, RasterEl


def test_coincident_glyph_keeps_its_own_style_and_paint_occurrence(monkeypatch):
    monkeypatch.setattr("pdfexact.extract.text._corriger_espacement", lambda *args: None)
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=200, height=200)
        page.insert_text((50, 70), "Ab", fontsize=24, color=(1, 0, 0))
        page.draw_rect((40, 40, 90, 90), fill=(1, 1, 1), color=None)
        page.insert_text((50, 70), "A", fontsize=10, color=(0, 0, 0))
        fonts = {"Helvetica": FontAsset("Helvetica", "Arial", None, "ttf", False)}
        elements = extraire_texte(page, fonts, PageGeometry.depuis_page(page))
        red = [span for element in elements for line in element.lignes for span in line.spans if span.couleur == "FF0000"]
        assert red
        assert all(span.z_index == 0 for span in red)


def _wrap_transparency_group(pdf, page, opacity, level):
    resources = int(pdf.xref_get_key(page.xref, "Resources")[1].split()[0])
    form = pdf.get_new_xref()
    pdf.update_object(form, f"<</Type/XObject /Subtype/Form /BBox[0 0 200 200] /Resources {resources} 0 R /Group<</S/Transparency /I true>>>>")
    stream = page.get_contents()[0]
    pdf.update_stream(form, pdf.xref_stream(stream))
    pdf.xref_set_key(resources, f"XObject/Group{level}", f"{form} 0 R")
    state = pdf.get_new_xref()
    pdf.update_object(state, f"<</Type/ExtGState /ca {opacity} /CA {opacity}>>")
    pdf.xref_set_key(resources, f"ExtGState/Alpha{level}", f"{state} 0 R")
    pdf.update_stream(stream, f"q /Alpha{level} gs /Group{level} Do Q".encode())


@pytest.mark.parametrize("intrinsic_alpha", (255, 96))
@pytest.mark.parametrize("levels", (1, 2))
def test_form_group_opacity_and_intrinsic_image_alpha_each_apply_once(intrinsic_alpha, levels):
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=200, height=200)
        stream = BytesIO()
        Image.new("RGBA", (60, 60), (255, 255, 255, intrinsic_alpha)).save(stream, format="PNG")
        page.insert_image((40, 40, 160, 160), stream=stream.getvalue())
        for level in range(levels):
            _wrap_transparency_group(pdf, page, .5, level)
        source = page.get_pixmap(alpha=True)
        expected_alpha = source.pixel(100, 100)[3]
        media = {}
        element, = extraire_images(page, pdf, media, PageGeometry.depuis_page(page))
        image = Image.open(BytesIO(media[element.media_ref].donnees)).convert("RGBA")
        assert abs(image.getpixel((image.width // 2, image.height // 2))[3] - expected_alpha) <= 1
        assert abs(expected_alpha - intrinsic_alpha * .5 ** levels) <= 2


@pytest.mark.parametrize("rotation", (0, 90, 180, 270))
@pytest.mark.parametrize("hole", (False, True))
def test_vector_paint_respects_inherited_clip_without_page_text_capture(rotation, hole):
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=200, height=200)
        page.draw_rect((20, 20, 180, 180), fill=(1, 1, 1), color=None)
        stream = page.get_contents()[0]
        clip = b"70 70 60 60 re" + (b" 90 90 20 20 re W* n" if hole else b" W n")
        pdf.update_stream(stream, b"q " + clip + b"\n" + pdf.xref_stream(stream) + b"\nQ")
        page.insert_text((80, 100), "NATIVE", color=(1, 0, 0))
        page.set_rotation(rotation)
        geometry = PageGeometry.depuis_page(page)
        shapes = extraire_vectoriel(page, geometry)
        media = {}
        images = extraire_images(page, pdf, media, geometry)
        expected = geometry.bbox_depuis_rect_natif(pymupdf.Rect(70, 70, 130, 130))
        if not hole:
            shape, = shapes
            assert shape.bbox == expected
            assert shape.remplissage == "FFFFFF"
            assert shape.z_index == 0
            assert images == []
            return
        assert shapes == []
        element, = images
        assert isinstance(element, RasterEl)
        assert element.z_index == 0
        assert element.bbox == expected
        image = Image.open(BytesIO(media[element.media_ref].donnees)).convert("RGBA")
        center = image.getpixel((image.width // 2, image.height // 2))
        assert center[3] == (0 if hole else 255)
        assert all((r, g, b) == (255, 255, 255) for r, g, b, alpha in image.get_flattened_data() if alpha == 255)
