"""Zone vision by Groq: deterministic parts tested without any network call."""
import pytest
from PIL import Image

from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.ir import ImageEl, Page, RasterEl
from pdfexact.layout import vision








@pytest.mark.parametrize(("answer", "expected"), [
    ("chart, yes", {"type": "chart", "contains_text": True, "translatable": True}),
    (" Photo; no.", {"type": "photo", "contains_text": False, "translatable": False}),
    ("It is a logo and yes there is text", {"type": "logo", "contains_text": True, "translatable": False}),
    ("text, yes", {"type": "text", "contains_text": True, "translatable": True}),
])
def test_answer_is_read_into_a_type_and_a_text_flag(answer, expected):
    assert vision._lire_reponse(answer) == expected


@pytest.mark.parametrize("answer", ["", "I am not sure", "maybe"])
def test_unreadable_answer_is_none(answer):
    assert vision._lire_reponse(answer) is None


def test_only_visual_zones_large_enough_to_be_read_are_selected():
    big = ImageEl(BBox(u(72), u(72), u(300), u(250)), "media-1")
    raster = RasterEl(BBox(u(72), u(300), u(400), u(500)), "media-2")
    tiny = ImageEl(BBox(u(10), u(10), u(20), u(20)), "media-3")
    page = Page(0, u(612), u(792), [big, raster, tiny])
    assert vision.zones_a_voir(page) == [big, raster]


def test_a_document_without_visual_zone_neither_opens_the_pdf_nor_loads_the_model():
    class Forbidden:
        def repondre(self, *args, **kwargs):
            raise AssertionError("model must not run")

    document = type("Doc", (), {"pages": [Page(0, u(612), u(792), [])]})()
    assert vision.annoter_zones_visuelles(document, "absent.pdf", Forbidden()) == []


def test_zones_to_read_are_text_seen_by_vision_or_zones_vision_could_not_understand():
    seen = ImageEl(BBox(u(72), u(72), u(300), u(250)), "a", attributes={"vision": {"status": "compris", "contains_text": True}})
    photo = ImageEl(BBox(u(72), u(300), u(300), u(450)), "b", attributes={"vision": {"status": "compris", "contains_text": False}})
    unknown = RasterEl(BBox(u(320), u(72), u(540), u(250)), "c", attributes={"vision": {"status": "non-compris"}})
    page = Page(0, u(612), u(792), [seen, photo, unknown])
    assert vision.zones_texte_image(page) == [seen.bbox, unknown.bbox]


def test_ocr_reads_only_the_selected_zones_and_marks_text_in_image(monkeypatch, tmp_path):
    import pymupdf
    from pdfexact.extract import ocr
    from pdfexact.ir import Document, FontRef, Line, Span, TextBox

    source = tmp_path / "page.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page(width=612, height=792)
        pdf.save(source)
    zone = ImageEl(BBox(u(72), u(72), u(300), u(250)), "a", attributes={"vision": {"status": "compris", "contains_text": True}})
    native_box = BBox(u(72), u(400), u(300), u(412))
    native = TextBox(native_box, [Line(native_box, [Span("Native", FontRef("f", "Arial", False, False), 10, "000000", bbox=native_box)],
                                       native_box.hauteur, native_box.largeur)])
    page = Page(0, u(612), u(792), [zone, native])
    calls = {}
    read_box = BBox(u(80), u(90), u(200), u(102))
    read = TextBox(read_box, [Line(read_box, [Span("In image", FontRef("f", "Arial", False, False), 10, "000000", bbox=read_box)],
                                   read_box.hauteur, read_box.largeur)])

    def fake(page_pdf, polices, **kwargs):
        calls.update(kwargs)
        return [read]

    monkeypatch.setattr(ocr, "extraire_rapidocr", fake)
    added = ocr.lire_texte_des_images(Document([page]), source, {}, dpi=100, language="auto", model_root=None)
    assert added == 1 and read in page.elements
    assert calls["zones_cibles"] == [zone.bbox] and calls["zones_ignorees"] == [native_box]
    assert read.attributes["text_in_image"] is True


def test_groq_vision_sends_the_zone_image_and_the_question():
    import io as stdio
    import json

    sent = {}

    def urlopen(request, timeout):
        sent.update(json.loads(request.data))
        return stdio.BytesIO(json.dumps({"choices": [{"message": {"content": "chart, yes"}}]}).encode())

    answer = vision.VisionGroq("k", model="vision-model", urlopen=urlopen, min_interval=0).repondre(Image.new("RGB", (40, 30)))
    assert answer == "chart, yes" and sent["model"] == "vision-model"
    parts = sent["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": vision.QUESTION}
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_without_groq_key_every_visual_zone_is_marked_not_understood(tmp_path):
    import pymupdf

    source = tmp_path / "p.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page(width=612, height=792)
        pdf.save(source)
    zone = ImageEl(BBox(u(72), u(72), u(300), u(250)), "media-1")
    document = type("Doc", (), {"pages": [Page(0, u(612), u(792), [zone])]})()
    assert vision.annoter_zones_visuelles(document, source, None) == [
        {"page": 0, "status": "non-compris", "reason": "no-groq-key", "model": None}]
    assert zone.attributes["vision"]["status"] == "non-compris"
