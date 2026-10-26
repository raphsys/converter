"""OCR restricted to target zones renders only around them, and places what it reads on the page."""
from types import SimpleNamespace

import numpy as np
import pymupdf
from PIL import Image

from pdfexact.extract import ocr
from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.ir import Page, element_text


def _faux_ocr(monkeypatch, boite_px):
    vus = []
    box = np.array([boite_px], dtype=np.float32)

    def recognize(image, **kwargs):
        vus.append(image)
        acceptees = [b for b in box if kwargs["accept_box"](b)]
        return SimpleNamespace(txts=("Texte image",) * len(acceptees), scores=(.99,) * len(acceptees),
                               boxes=np.asarray(acceptees), word_results=(), routing_evidence=[],
                               routing_warnings=[], routing_elapsed_seconds=0.0)

    monkeypatch.setattr(ocr, "_rapidocr", lambda **kwargs: recognize)
    return vus


def _lire(zones):
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=600, height=400)
        return ocr.extraire_rapidocr(page, {}, dpi=72, granularite="line", layout="word-native",
                                     zones_cibles=zones, observation_page=Page(0, u(600), u(400)))


def test_only_the_target_zones_are_rendered_and_read_text_lands_on_the_page(monkeypatch):
    marge = ocr.MARGE_ZONES_OCR_PT
    # Text 10..60 px right and 10..30 px down from the corner of the rendered crop (72 dpi: 1 px = 1 pt).
    vus = _faux_ocr(monkeypatch, [[10, 10], [60, 10], [60, 30], [10, 30]])
    sorties = _lire([BBox(u(300), u(200), u(400), u(250))])
    image = vus[0]
    assert isinstance(image, Image.Image)  # in memory, no temporary PNG
    assert image.size == (100 + 2 * marge, 50 + 2 * marge)
    ligne = sorties[0]
    assert "Texte image" in element_text(ligne)
    assert ligne.bbox.x0 == u(300 - marge + 10) and ligne.bbox.y0 == u(200 - marge + 10)


def test_the_render_stays_inside_the_page(monkeypatch):
    vus = _faux_ocr(monkeypatch, [[0, 0], [5, 0], [5, 5], [0, 5]])
    _lire([BBox(u(590), u(0), u(600), u(10))])
    assert vus[0].size == (10 + ocr.MARGE_ZONES_OCR_PT, 10 + ocr.MARGE_ZONES_OCR_PT)


def test_without_target_zones_the_whole_page_is_read(monkeypatch):
    vus = _faux_ocr(monkeypatch, [[40, 40], [300, 40], [300, 80], [40, 80]])
    _lire(None)
    assert vus[0].size == (600, 400)


def test_zones_outside_the_page_fall_back_to_the_whole_page(monkeypatch):
    vus = _faux_ocr(monkeypatch, [[0, 0], [5, 0], [5, 5], [0, 5]])
    assert _lire([BBox(u(700), u(500), u(720), u(510))]) == []
    assert vus[0].size == (600, 400)


def test_on_a_rotated_page_the_target_zone_itself_is_rendered(monkeypatch):
    # PyMuPDF clips in displayed (rotated) coordinates.
    vus = _faux_ocr(monkeypatch, [[0, 0], [5, 0], [5, 5], [0, 5]])
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=612, height=792)
        page.set_rotation(90)
        ocr.extraire_rapidocr(page, {}, dpi=72, granularite="line", layout="word-native",
                              zones_cibles=[BBox(u(300), u(200), u(500), u(250))], observation_page=Page(0, u(792), u(612)))
    marge = ocr.MARGE_ZONES_OCR_PT
    assert vus[0].size == (200 + 2 * marge, 50 + 2 * marge)
