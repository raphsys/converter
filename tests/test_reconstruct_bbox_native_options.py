"""User script option propagation without model initialization or rendering."""
import io
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from pdfexact.layout import text_comprehension as comprehension
from pdfexact.layout import text_comprehension_ai as http
from pdfexact.segmentation import OptionsSegmentation
from pdfexact.segmentation import pipeline as segmentation
from scripts import reconstruct_bbox_native as reconstruct


@pytest.fixture
def pipeline(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setenv("PDFEXACT_AI_MODELS_ROOT", str(tmp_path / "env-models"))
    monkeypatch.delenv("VYSI_AI_MODELS_ROOT", raising=False)
    monkeypatch.delenv("PDFEXACT_TEXT_UNDERSTANDING_URL", raising=False)
    monkeypatch.setattr(segmentation, "construire", lambda **kwargs: None)
    monkeypatch.setattr(segmentation, "dossiers_par_defaut", lambda: [])

    def provider(**kwargs):
        calls["factory"] = kwargs
        return None

    def extract(source, **kwargs):
        calls["extract"] = kwargs
        return SimpleNamespace(pages=[])

    monkeypatch.setattr(segmentation, "creer_fournisseur_comprehension_texte_ai", provider)
    monkeypatch.setattr(segmentation, "extraire", extract)
    monkeypatch.setattr(segmentation, "_normaliser_texte", lambda document: None)
    monkeypatch.setattr(reconstruct, "enregistrer_catalogue", lambda *args: None)
    monkeypatch.setattr(reconstruct, "annotate_pdf_bboxes", lambda *args: [])
    monkeypatch.setattr(reconstruct, "write_bbox_docx", lambda *args: [])
    calls["argv"] = ["reconstruct_bbox_native.py", "unused.pdf", "--pdf-out", str(tmp_path / "bbox.pdf"),
                     "--docx-out", str(tmp_path / "out.docx")]
    with comprehension.contexte_comprehension_texte():
        yield calls


@pytest.mark.parametrize("flags,language,ocr_root,layout_root", [
    ([], "auto", "env-models", None),
    (["--ocr-language", "ru+ja", "--ai-models-root", "common"], "ru+ja", "common", "common"),
    (["--ocr-lang", "ru+ja", "--ai-models-root", "common"], "ru+ja", "common", "common"),
    (["--layout-model-root", "legacy"], "auto", "legacy", "legacy"),
    (["--ai-models-root", "common", "--layout-model-root", "legacy"], "auto", "common", "legacy"),
    (["--text-understanding-ai"], "auto", "env-models", None),
    (["--text-mode", "rapidocr", "--ocr-language", "ru+ja"], "ru+ja", "env-models", None),
])
def test_user_main_propagates_language_roots_and_separate_opt_in(
    monkeypatch, tmp_path, pipeline, flags, language, ocr_root, layout_root
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", pipeline["argv"] + flags)
    assert reconstruct.main() == 0
    extraction, factory = pipeline["extract"], pipeline["factory"]
    assert extraction["ocr_language"] == language
    assert extraction["ai_models_root"] == tmp_path / ocr_root
    assert (Path(extraction["layout_model_root"]).resolve()
            if extraction["layout_model_root"] is not None else None) == (
                tmp_path / layout_root if layout_root else None)
    assert factory["url"] is None and factory["timeout"] == 3.0
    assert extraction["strict"] is True and extraction["layout_ai"] is True
    mode = "rapidocr" if "rapidocr" in flags else "spans"
    assert extraction["text_mode"] == mode
    assert extraction["ocr_layout"] == ("word-native" if mode == "rapidocr" else "blocks")


def test_segmentation_options_default_to_automatic_ocr_language(pipeline):
    segmentation._extraire_scene(Path("unused.pdf"), OptionsSegmentation(pages=[0], text_understanding_timeout=.75))
    assert pipeline["extract"]["ocr_language"] == "auto"
    assert pipeline["factory"]["timeout"] == .75


@pytest.mark.parametrize("explicit_url", [False, True])
def test_http_priority_survives_models_root(
    monkeypatch, tmp_path, pipeline, explicit_url
):
    requests = []
    monkeypatch.setenv("PDFEXACT_TEXT_UNDERSTANDING_URL", "http://environment.test/understand")
    monkeypatch.setattr(segmentation, "creer_fournisseur_comprehension_texte_ai",
                        http.creer_fournisseur_comprehension_texte_ai)

    def respond(request, timeout):
        requests.append((request.full_url, timeout))
        return io.BytesIO(b'{"action":"segment-page","confidence":0.95,"line_groups":[[0]]}')

    def extract(*args, **kwargs):
        decision = comprehension.comprendre_segmentation_page(["Native PDF line"], metadonnees={"page_index": 0})
        assert decision.ai_used and not decision.fallback_used
        return SimpleNamespace(pages=[])

    monkeypatch.setattr(http, "urlopen", respond)
    monkeypatch.setattr(segmentation, "extraire", extract)
    flags = ["--ai-models-root", str(tmp_path), "--text-understanding-timeout", "0.75"]
    if explicit_url:
        flags += ["--text-understanding-url", "http://explicit.test/understand"]
    monkeypatch.setattr(sys, "argv", pipeline["argv"] + flags)
    assert reconstruct.main() == 0
    expected = "http://explicit.test/understand" if explicit_url else "http://environment.test/understand"
    assert requests == [(expected, .75)]


def test_user_help_exposes_the_options_without_loading_models():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-B", str(root / "scripts/reconstruct_bbox_native.py"), "--help"],
                            cwd=root, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    for flag in ("--ocr-language", "--ai-models-root"):
        assert flag in result.stdout




@pytest.mark.parametrize("expression,expected", [
    (None, None), ("", None), ("all", None), ("ALL", None), (" all ", None),
    ("1-5", [0, 1, 2, 3, 4]),
    ("1-40", list(range(25))),
    ("20-30", [19, 20, 21, 22, 23, 24]),
    ("3,30", [2]),
    ("26-30", []),
    ("1-3,2", [0, 1, 2]),
])
def test_pages_accept_all_and_are_limited_to_the_document(expression, expected):
    assert reconstruct._pages(expression, 25) == expected


def test_pages_beyond_the_document_reach_segmentation_without_error(monkeypatch, tmp_path, pipeline):
    monkeypatch.setattr(reconstruct, "_nombre_pages", lambda source: 3)
    monkeypatch.setattr(sys, "argv", pipeline["argv"] + ["--pages", "2-10"])
    assert reconstruct.main() == 0
    assert pipeline["extract"]["pages"] == [1, 2]
