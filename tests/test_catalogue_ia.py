"""The catalogue records what the AI understood: roles, text in images, visual zones."""
from pdfexact.extract.catalog import construire_catalogue
from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.ir import Document, FontRef, ImageEl, Line, Page, Span, TextBox


def test_catalogue_exports_visual_zones_with_vision_and_text_read_in_images(tmp_path):
    box = BBox(u(80), u(90), u(200), u(102))
    text = TextBox(box, [Line(box, [Span("In image", FontRef("f", "Arial", False, False), 10, "000000", bbox=box)],
                              box.hauteur, box.largeur)], attributes={"text_in_image": True})
    text.presentation = {"comprehension_ia": "compris"}
    image = ImageEl(BBox(u(72), u(72), u(300), u(250)), "media-1",
                    attributes={"vision": {"status": "compris", "type": "chart", "contains_text": True, "translatable": True}})
    catalogue = construire_catalogue(Document([Page(0, u(612), u(792), [image, text])]), source_pdf=tmp_path / "x.pdf")
    page = catalogue["pages"][0]
    assert page["text_elements"][0]["text_in_image"] is True
    assert page["text_elements"][0]["presentation"]["comprehension_ia"] == "compris"
    (visual,) = page["visual_elements"]
    assert visual["kind"] == "ImageEl" and visual["vision"]["type"] == "chart" and visual["bbox"]
    assert catalogue["totals"]["visual_elements"] == 1
