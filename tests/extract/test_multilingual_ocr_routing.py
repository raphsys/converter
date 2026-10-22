"""Acquisition contracts; local model quality probes are explicit opt-in smokes."""
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import RLock
from types import SimpleNamespace

import numpy as np
import pymupdf
import pytest

from pdfexact.extract import ocr_routing as routing
from pdfexact.extract.blocks import OcrLine
from pdfexact.extract.ocr import _capture_ocr_lines, _ligne_figure_isolee, _normaliser_texte_ocr
from pdfexact.extract.text import _ligne_mots_lisible
from pdfexact.geometry import BBox
from pdfexact.ir import Page, element_text


def _model(name="base", script="Latn", language="ch"):
    return routing.LocalOcrModel(name, "rec", Path("unused.onnx"), "a" * 64,
                                 "PP-OCRv6", "small", language, (script,))


@pytest.mark.parametrize("text,script", [("Русский текст", "Cyrl"), ("中文漢語", "Hani"),
                                         ("ひらがな", "Hira"), ("カタカナ", "Kana"), ("한국어", "Hang"),
                                         ("العربية", "Arab"), ("हिन्दी", "Deva"), ("ภาษาไทย", "Thai")])
def test_script_observation_is_not_a_document_language(text, script):
    assert set(routing.script_counts(text)) == {script}
    assert routing.has_non_latin_letters(text)


@pytest.mark.parametrize("text", ["俄", "中文", "漢語", "я", "Русский текст", "日本語", "한국어", "ΑΒΓ"])
def test_acquisition_filters_do_not_silently_latinize_or_drop_non_latin(text):
    assert _normaliser_texte_ocr(text) == text
    assert not _ligne_figure_isolee(OcrLine(text, .99, BBox(0, 0, 100, 100)))
    assert _ligne_mots_lisible(text)


def test_metadata_dictionary_and_classes_are_validated_not_trusted_flags():
    model = _model(script="Cyrl", language="cyrillic")
    value = "А\nБ\nВ"
    model = replace(model, dictionary={"sha256": sha256(value.encode()).hexdigest(), "count": 3})
    assert routing.validate_alphabet(model, {"character": value}, 5) == ("А", "Б", "В")
    for metadata, classes in [({}, 5), ({"character": "А\nБ\nА"}, 5),
                               ({"character": value}, 4), ({"character": "a\nb\nc"}, 5)]:
        with pytest.raises(ValueError):
            routing.validate_alphabet(model, metadata, classes)
    with pytest.raises(ValueError, match="script/alphabet"):
        routing.validate_alphabet(_model(script="Hang"), {"character": "a\nb"}, 4)
    assert routing.validate_alphabet(_model(script="Cyrl"), {"character": "А\nБ\nА"}, 5) == ("А", "Б", "А")


def test_catalog_payload_and_path_validation(tmp_path):
    directory = tmp_path / "ocr/rapidocr"
    directory.mkdir(parents=True)
    (directory / "model.onnx").write_bytes(b"local")
    entry = {"id": "test", "engine": "onnxruntime", "task": "rec", "path": "model.onnx",
             "sha256": "0" * 64, "ocr_version": "PP-OCRv6", "model_type": "small", "lang_type": "multi"}
    catalog = directory / "catalog.json"
    catalog.write_text(json.dumps({"schema": "pdfexact.ocr-models.v1", "models": [entry]}))
    with pytest.raises(ValueError, match="SHA256"):
        routing.load_catalog(tmp_path)
    entry["path"] = "../../../outside.onnx"
    catalog.write_text(json.dumps({"schema": "pdfexact.ocr-models.v1", "models": [entry]}))
    with pytest.raises(ValueError, match="escapes"):
        routing.load_catalog(tmp_path)


def test_routing_does_not_use_high_score_alone_and_retains_conflicts():
    latin = routing.candidate_evidence(_model(), "garbage", .98, tuple("garbe"))
    cyr = routing.candidate_evidence(_model("cyr", "Cyrl"), "Русский", .99, tuple("Руский"))
    selected, evidence = routing.choose_candidate([latin, cyr])
    assert selected["model_id"] == "cyr"
    assert evidence["ambiguous"] and not evidence["calibrated"]
    assert len(evidence["candidates"]) == 2
    digits = routing.candidate_evidence(_model("cyr", "Cyrl"), "123", 1., tuple("123"))
    selected, _ = routing.choose_candidate([latin, digits])
    assert selected["model_id"] == "base"


def test_bitmap_without_unicode_hints_tries_every_model_on_shared_crops():
    from rapidocr.ch_ppocr_rec import TextRecOutput
    router = routing.LocalOcrRouter.__new__(routing.LocalOcrRouter)
    base, cyr = _model(), _model("cyr", "Cyrl", "cyrillic")
    router.selected_models, router.language, router.lock = [base, cyr], "auto", RLock()
    router.failures, router.alphabets = {}, {"base": tuple("garbeEnglish"), "cyr": tuple("РускийEnglish")}
    boxes = np.array([[[0, 0], [20, 0], [20, 10], [0, 10]],
                      [[0, 20], [20, 20], [20, 30], [0, 30]]], dtype=np.float32)
    crops = [np.full((10, 20, 3), value, np.uint8) for value in (1, 2)]
    calls = []

    class Detector:
        load_img = staticmethod(lambda image: image)
        crop_text_regions = staticmethod(lambda image, selected: crops[:len(selected)])
        cls_and_rotate = staticmethod(lambda selected: (selected, None))

        def __call__(self, image, **kwargs):
            calls.append(("detection", kwargs))
            return SimpleNamespace(boxes=boxes)

    router.base = Detector()

    def recognizer(model):
        def recognize(args):
            calls.append((model.id, [id(crop) for crop in args.img]))
            text = ("garbage", "English") if model.id == "base" else ("Русский", "English")
            scores = (.50, .99) if model.id == "base" else (.99, .50)
            return TextRecOutput(args.img, text, scores)
        return recognize

    router._recognizer = recognizer
    result = router(np.zeros((40, 30, 3), np.uint8))
    assert result.txts == ("Русский", "English")
    assert len([call for call in calls if call[0] == "detection"]) == 1
    assert calls[1][1] == calls[2][1]
    assert result.routing_evidence[0]["attempted_models"] == ["base", "cyr"]
    assert all(item["shared_detection"] for item in result.routing_evidence)
    assert result.routing_evidence[0]["crop_sha256"] != result.routing_evidence[1]["crop_sha256"]
    assert result.routing_warnings[0]["reason"] == "incomplete-local-script-coverage"


def test_raw_routing_proof_is_captured_in_source_snapshot_before_filters():
    page = Page(0, 100, 100)
    details = {"ambiguous": True, "candidates": [{"text": "я"}, {"text": "R"}]}
    observations = _capture_ocr_lines(SimpleNamespace(number=0), [OcrLine("я", .9, BBox(0, 0, 50, 50))],
                                      page, "rapidocr-line", routing_evidence=[details])
    source = observations[0]
    assert source.language == "auto" and source.script == "Cyrl"
    assert source.attributes["ocr_routing"] == details
    snapshot = page.source_inventory[source.source_id]
    assert snapshot.attributes["ocr_routing"] == details
    assert source.evidence[0].confidence is None
    assert snapshot.confidence is None


def test_pdf_acquisition_entrypoint_keeps_routing_diagnostics(monkeypatch):
    from pdfexact.extract import ocr
    box = np.array([[[40, 40], [300, 40], [300, 80], [40, 80]]], dtype=np.float32)
    evidence = {"ambiguous": True, "selected_model": "cyr", "candidates": [{"text": "Русский текст"}]}
    result = SimpleNamespace(txts=("Русский текст",), scores=(.99,), boxes=box, word_results=(),
                             routing_evidence=[evidence], routing_warnings=[], routing_elapsed_seconds=.2)
    requests = []

    def recognize(image, **kwargs):
        requests.append(kwargs)
        assert kwargs["accept_box"](box[0])
        return result

    monkeypatch.setattr(ocr, "_rapidocr", lambda **kwargs: recognize)
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=600, height=400)
        observed = Page(0, 7620000, 5080000)
        outputs = ocr.extraire_rapidocr(page, {}, dpi=72, granularite="line", layout="word-native",
                                       observation_page=observed, language="auto")
    assert "Русский текст" in " ".join(element_text(item) for item in outputs)
    assert any("ocr_routing" in item.attributes for item in observed.source_inventory.values())
    assert observed.diagnostics[-1].kind == "ocr-routing-summary"
    assert requests


def test_spans_pdf_preserves_native_unicode_without_ocr(monkeypatch, tmp_path):
    from pdfexact.extract import document
    from pdfexact.layout.ai import LayoutAIPage
    source = tmp_path / "native.pdf"
    text = "Русский текст PDF"
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_font(fontname="unicode", fontfile="pdfexact/fonts/DejaVuSans.ttf")
        page.insert_text((72, 100), text, fontname="unicode", fontsize=18)
        pdf.save(source)
    monkeypatch.setattr(document, "detecter_layout_ia", lambda *args, **kwargs:
                        LayoutAIPage("fallback", "test", "none", None, ()))

    def unexpected(*args, **kwargs):
        pytest.fail("Good native spans must not invoke OCR")

    monkeypatch.setattr(document, "extraire_rapidocr", unexpected)
    monkeypatch.setattr(document, "extraire_ocr", unexpected)
    extracted = document.extraire(source, text_mode="spans", strict=True, ocr_language="auto")
    actual = " ".join(element_text(element) for element in extracted.pages[0].elements)
    assert text in actual
    assert routing.script_counts(actual) == {"Cyrl": 12, "Latn": 3}


def _synth(lines):
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new("RGB", (1200, 90 + 110 * len(lines)), "white")
    draw = ImageDraw.Draw(image)
    for index, (text, font) in enumerate(lines):
        draw.text((40, 35 + 110 * index), text, font=ImageFont.truetype(font, 46), fill="black")
    return np.asarray(image)[:, :, ::-1].copy()


_SMOKE_LINES = [
    ("Русский язык и русский текст", "pdfexact/fonts/DejaVuSans.ttf", "Cyrl"),
    ("中文汉语简体文字测试", "pdfexact/fonts/NotoSansCJKjp-Regular.ttc", "Hani"),
    ("中文漢語繁體文字測試", "pdfexact/fonts/NotoSansCJKjp-Regular.ttc", "Hani"),
    ("日本語ひらがなカタカナ", "pdfexact/fonts/NotoSansJP-Regular.otf", "Hira"),
    ("한국어 한글 문서 테스트", "pdfexact/fonts/NotoSansKR-Regular.otf", "Hang"),
]


@pytest.mark.skipif(os.environ.get("PDFEXACT_TEST_LOCAL_OCR") != "1", reason="Opt-in actual local CPU inference")
@pytest.mark.parametrize("case", list(range(5)) + ["mixed"])
def test_real_cpu_multilingual_synthetic(case):
    lines = _SMOKE_LINES if case == "mixed" else [_SMOKE_LINES[case]]
    image = _synth([(text, font) for text, font, _ in lines])
    router = routing.get_local_ocr(language="auto")
    result = router(image, return_word_box=True)
    print(json.dumps({"case": case, "seconds": result.routing_elapsed_seconds,
                      "groundtruth": [line[0] for line in lines], "observed": result.txts,
                      "models": [item["selected_model"] for item in result.routing_evidence],
                      "ambiguous": [item["ambiguous"] for item in result.routing_evidence],
                      "warnings": result.routing_warnings}, ensure_ascii=False))
    normalized = ["".join(text.split()) for text in result.txts]
    for text, font, script in lines:
        assert "".join(text.split()) in normalized
        assert script in routing.script_counts("".join(result.txts))
    assert not result.routing_warnings
    assert all(len(item["candidates"]) == len(router.selected_models) for item in result.routing_evidence)
    assert all(item["provider"] == "CPUExecutionProvider"
               for region in result.routing_evidence for item in region["candidates"])
    assert routing.get_local_ocr(language="auto") is router


@pytest.mark.skipif(os.environ.get("PDFEXACT_TEST_LOCAL_OCR") != "1", reason="Opt-in actual local CPU inference")
def test_real_cpu_pdf_bitmap_acquisition():
    from io import BytesIO
    from PIL import Image
    from pdfexact.extract.ocr import extraire_rapidocr
    from pdfexact.geometry import pt_vers_emu
    lines = [_SMOKE_LINES[0], _SMOKE_LINES[1]]
    array = _synth([(text, font) for text, font, _ in lines])
    payload = BytesIO()
    Image.fromarray(array[:, :, ::-1]).save(payload, format="PNG")
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=array.shape[1] / 2, height=array.shape[0] / 2)
        page.insert_image(page.rect, stream=payload.getvalue())
        assert not page.get_text().strip()
        observed = Page(0, pt_vers_emu(page.rect.width), pt_vers_emu(page.rect.height))
        outputs = extraire_rapidocr(page, {}, dpi=144, granularite="line", layout="word-native",
                                   observation_page=observed, language="auto")
    text = "".join(element_text(output) for output in outputs)
    assert routing.script_counts(text) == routing.script_counts("".join(line[0] for line in lines))
    for expected, font, script in lines:
        assert "".join(expected.split()) in "".join(text.split())
    summary = dict(observed.diagnostics[-1].details)
    print(json.dumps({"case": "bitmap-pdf-acquisition", "seconds": summary["elapsed_seconds"],
                      "observed": text, "scripts": routing.script_counts(text),
                      "inventory": len(observed.source_inventory)}, ensure_ascii=False))
    assert not summary["warnings"]
    assert any(item.attributes.get("ocr_routing") for item in observed.source_inventory.values())


def test_ocr_engine_uses_every_cpu_core(monkeypatch):
    from pdfexact.extract import ocr_routing

    monkeypatch.setattr(ocr_routing.os, "cpu_count", lambda: 8)
    assert ocr_routing._threads_ocr() == 8
