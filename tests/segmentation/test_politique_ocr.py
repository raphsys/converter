"""OCR policy taken from vysi: native text first, OCR only where the page has none."""
from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.ir import Document, FontRef, ImageEl, Line, Page, Span, TextBox
from pdfexact.segmentation.pipeline import OptionsSegmentation, pages_sans_texte_natif

ARIAL = FontRef("f", "Arial", False, False)


def _texte(contenu, **attributs):
    box = BBox(u(72), u(100), u(300), u(112))
    element = TextBox(box, [Line(box, [Span(contenu, ARIAL, 10, "000000")], box.hauteur, box.largeur)])
    for nom, valeur in attributs.items():
        setattr(element, nom, valeur)
    return element


def test_only_pages_without_native_text_need_ocr():
    image = ImageEl(BBox(u(0), u(0), u(612), u(792)), "scan")
    document = Document([
        Page(0, u(612), u(792), [image, _texte("Native text")]),
        Page(1, u(612), u(792), [image]),
        Page(2, u(612), u(792), [image, _texte("read by OCR", source_kind="ocr")]),
        Page(3, u(612), u(792), [_texte("   ")]),
    ])
    assert pages_sans_texte_natif(document) == {1, 2, 3}


def test_text_in_images_of_native_pages_is_not_read_by_default():
    assert OptionsSegmentation().ocr_images is False
