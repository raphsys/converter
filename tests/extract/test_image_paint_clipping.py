from io import BytesIO

import pymupdf
import pytest
from PIL import Image

from pdfexact.extract.images import extraire_images
from pdfexact.extract.image_composition import composer_placements_visuels
from pdfexact.geometry import PageGeometry
from pdfexact.ir import ImageEl, MediaItem, RasterEl


def _white_image():
    stream = BytesIO()
    Image.new("RGB", (60, 60), "white").save(stream, format="PNG")
    return stream.getvalue()


@pytest.mark.parametrize("rotation", (0, 90, 180, 270))
@pytest.mark.parametrize("cropped", (False, True))
@pytest.mark.parametrize("clip", ("hole", "triangle"))
def test_image_placement_replays_actual_clip_not_just_its_envelope(rotation, cropped, clip):
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=200, height=200)
        page.insert_image((40, 40, 160, 160), stream=_white_image())
        stream = page.get_contents()[0]
        path = (
            b"40 40 120 120 re 80 80 40 40 re W* n"
            if clip == "hole" else b"40 40 m 160 40 l 40 160 l h W n"
        )
        pdf.update_stream(stream, b"q " + path + b"\n" + pdf.xref_stream(stream) + b"\nQ")
        # This later native text must never be baked into the image placement.
        page.insert_text((65, 105), "Editable", color=(1, 0, 0))
        if cropped:
            page.set_cropbox(pymupdf.Rect(10, 10, 190, 190))
        page.set_rotation(rotation)
        geometry = PageGeometry.depuis_page(page)
        before = (page.rotation, tuple(page.cropbox))
        media = {}
        images = extraire_images(page, pdf, media, geometry)
        assert (page.rotation, tuple(page.cropbox)) == before
        assert len(images) == 1
        element = images[0]
        assert element.z_index == 0
        assert element.clip_bbox == element.bbox
        assert element.bbox == geometry.bbox_depuis_rect_natif(pymupdf.Rect(page.get_image_info()[0]["bbox"]))
        result = Image.open(BytesIO(media[element.media_ref].donnees)).convert("RGBA")
        pixels = list(result.get_flattened_data())
        assert any(alpha == 0 for _r, _g, _b, alpha in pixels)
        assert any(alpha == 255 for _r, _g, _b, alpha in pixels)
        assert all((r, g, b) == (255, 255, 255) for r, g, b, alpha in pixels if alpha == 255)
        if clip == "hole":
            assert result.getpixel((result.width // 2, result.height // 2))[3] == 0


def test_nested_clips_intersect_placement_bounds_without_erasing_white():
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=200, height=200)
        page.insert_image((40, 40, 160, 160), stream=_white_image())
        stream = page.get_contents()[0]
        pdf.update_stream(stream, b"q 40 40 120 120 re W n q 60 40 80 120 re W n\n" + pdf.xref_stream(stream) + b"\nQ Q")
        geometry = PageGeometry.depuis_page(page)
        media = {}
        image, = extraire_images(page, pdf, media, geometry)
        assert image.bbox == geometry.bbox_depuis_rect_natif(pymupdf.Rect(60, 40, 140, 160))
        result = Image.open(BytesIO(media[image.media_ref].donnees)).convert("RGBA")
        assert result.getpixel((result.width // 2, result.height // 2)) == (255, 255, 255, 255)


def test_image_paint_opacity_preserves_source_white_pixels():
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=200, height=200)
        page.insert_image((40, 40, 160, 160), stream=_white_image())
        resources = int(pdf.xref_get_key(page.xref, "Resources")[1].split()[0])
        state = pdf.get_new_xref()
        pdf.update_object(state, "<</Type/ExtGState /ca 0.4 /CA 0.4>>")
        pdf.xref_set_key(resources, "ExtGState", f"<</LayerAlpha {state} 0 R>>")
        stream = page.get_contents()[0]
        pdf.update_stream(stream, b"q /LayerAlpha gs\n" + pdf.xref_stream(stream) + b"\nQ")
        media = {}
        image, = extraire_images(page, pdf, media, PageGeometry.depuis_page(page))
        result = Image.open(BytesIO(media[image.media_ref].donnees)).convert("RGBA")
        r, g, b, alpha = result.getpixel((result.width // 2, result.height // 2))
        assert (r, g, b) == (255, 255, 255)
        assert abs(alpha - 102) <= 1


@pytest.mark.parametrize("sequences", ((0, 1), (0, 2)))
def test_image_slices_never_capture_text_or_cross_intervening_paint(sequences, monkeypatch):
    def no_page_capture(*args, **kwargs):
        pytest.fail("Source-known image composition must not capture page text")

    monkeypatch.setattr("pdfexact.fallback.rasterize.rasteriser_region", no_page_capture)
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=300, height=300)
        geometry = PageGeometry.depuis_page(page)
        data = BytesIO()
        Image.new("RGBA", (80, 30), (255, 255, 255, 96)).save(data, format="PNG")
        media = {"slice": MediaItem("slice", data.getvalue(), "png")}
        images = [
            ImageEl(geometry.bbox_depuis_rect_natif(pymupdf.Rect(40, 40 + 30 * index, 120, 70 + 30 * index)), "slice", z_index=sequence)
            for index, sequence in enumerate(sequences)
        ]
        output = composer_placements_visuels(page, images, media, geometry)
        if sequences == (0, 2):
            assert output == images
        else:
            composite, = output
            assert isinstance(composite, RasterEl)
            assert composite.z_index == 0
            result = Image.open(BytesIO(media[composite.media_ref].donnees)).convert("RGBA")
            assert result.getpixel((result.width // 2, result.height // 4)) == (255, 255, 255, 96)
