import io
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from pdfexact.layout import text_comprehension as comprehension
from pdfexact.layout import text_comprehension_ai as http
from pdfexact.segmentation import OptionsSegmentation
from pdfexact.segmentation import pipeline as segmentation
from scripts import reconstruct_bbox_native as reconstruct


@pytest.fixture(autouse=True)
def isolate_provider(monkeypatch, tmp_path):
    monkeypatch.delenv("PDFEXACT_TEXT_UNDERSTANDING_URL", raising=False)
    comprehension.configurer_fournisseur_comprehension_texte(None)
    yield
    comprehension.configurer_fournisseur_comprehension_texte(None)


def _warnings(caplog):
    return [record.message for record in caplog.records if record.levelno >= logging.WARNING]


def _page():
    return comprehension.comprendre_segmentation_page(
        ["First line", "Second line"], metadonnees={"page_index": 3}
    )


@pytest.mark.parametrize("endpoint_source", ["argument", "environment", "missing"])
def test_script_initializes_understanding_without_opt_in(
    monkeypatch, caplog, endpoint_source
):
    endpoint = "http://semantic.test/understand"
    if endpoint_source == "environment":
        monkeypatch.setenv("PDFEXACT_TEXT_UNDERSTANDING_URL", endpoint)
    options = OptionsSegmentation(
        pages=[0], text_understanding_url=endpoint if endpoint_source == "argument" else None,
        text_understanding_timeout=0.75,
    )
    requests = []

    def respond(request, timeout):
        requests.append((request.full_url, timeout))
        return io.BytesIO(json.dumps({
            "action": "segment-page", "confidence": 0.95, "line_groups": [[0], [1]],
        }).encode())

    def extract(*_args, **kwargs):
        assert kwargs["layout_ai"] is True
        decision = _page()
        if endpoint_source == "missing":
            assert decision is None
        else:
            assert decision.ai_used is True
        return "scene"

    # A preceding analysis must not leak its provider into an unconfigured run.
    comprehension.configurer_fournisseur_comprehension_texte(
        lambda *_args: pytest.fail("stale provider was called")
    )
    monkeypatch.setattr(http, "urlopen", respond)
    monkeypatch.setattr(segmentation, "extraire", extract)
    monkeypatch.setattr(segmentation, "construire", lambda **_kwargs: None)
    monkeypatch.setattr(segmentation, "dossiers_par_defaut", lambda: [])

    assert segmentation._extraire_scene(Path("unused.pdf"), options) == "scene"
    if endpoint_source == "missing":
        assert len(_warnings(caplog)) == 1
        assert "status=missing-provider" in _warnings(caplog)[0]
    else:
        assert requests == [(endpoint, 0.75)]
        assert _warnings(caplog) == []


def test_missing_provider_warns_once_and_resets_for_next_analysis(caplog):
    for _ in range(4):
        assert _page() is None
        decision = comprehension.comprendre_ligne_texte("A label", frame_role="heading")
        assert decision.fallback_used is True
    assert len(_warnings(caplog)) == 1
    message = _warnings(caplog)[0]
    assert "status=missing-provider" in message
    assert "PDFEXACT_TEXT_UNDERSTANDING_URL" in message
    assert "geometric" in message.lower()
    assert "fallback" in message.lower()

    comprehension.configurer_fournisseur_comprehension_texte(None)
    assert _page() is None
    assert len(_warnings(caplog)) == 2


@pytest.mark.parametrize("fail_during_normalization", [False, True])
def test_segmentation_provider_spans_its_stages_and_restores_caller(
    monkeypatch, tmp_path, fail_during_normalization
):
    comprehension.configurer_fournisseur_comprehension_texte(
        lambda *_args: comprehension.TextUnderstandingDecision(
            "caller", "segment-page", 0.9, line_groups=((0,), (1,))
        )
    )
    stages = []

    def check_provider(stage):
        assert _page().ai_used is True
        assert _page().kind == "http"
        stages.append(stage)

    def extract(*_args, **_kwargs):
        check_provider("extraction")
        return SimpleNamespace(pages=[])

    def normalize(_document):
        check_provider("normalization")
        if fail_during_normalization:
            raise RuntimeError("normalization failed")

    def fill(*_args):
        stages.append("rendering")

    monkeypatch.setattr(sys, "argv", [
        "reconstruct_bbox_native.py", "unused.pdf",
        "--pdf-out", str(tmp_path / "bboxes.pdf"),
        "--docx-out", str(tmp_path / "output.docx"),
        "--text-understanding-url", "http://semantic.test/understand",
    ])
    monkeypatch.setattr(http, "urlopen", lambda *_args, **_kwargs: io.BytesIO(
        b'{"kind":"http","action":"segment-page","confidence":0.9,"groups":[[0],[1]]}'
    ))
    monkeypatch.setattr(segmentation, "extraire", extract)
    monkeypatch.setattr(segmentation, "construire", lambda **_kwargs: None)
    monkeypatch.setattr(segmentation, "dossiers_par_defaut", lambda: [])
    monkeypatch.setattr(segmentation, "_normaliser_texte", normalize)
    monkeypatch.setattr(reconstruct, "enregistrer_catalogue", lambda *_args: None)
    monkeypatch.setattr(reconstruct, "annotate_pdf_bboxes", lambda *_args: [])
    monkeypatch.setattr(reconstruct, "write_bbox_docx", fill)

    if fail_during_normalization:
        with pytest.raises(RuntimeError, match="normalization failed"):
            reconstruct.main()
        assert stages == ["extraction", "normalization"]
    else:
        assert reconstruct.main() == 0
        assert stages == ["extraction", "normalization", "rendering"]
    assert _page().kind == "caller"


def test_missing_provider_is_announced_even_without_text(caplog):
    comprehension.configurer_fournisseur_comprehension_texte(None, annoncer=True)
    assert "status=missing-provider" in _warnings(caplog)[0]


def test_explicit_custom_provider_remains_usable_with_configured_environment(monkeypatch):
    monkeypatch.setenv("PDFEXACT_TEXT_UNDERSTANDING_URL", "http://unused.test/understand")
    comprehension.configurer_fournisseur_comprehension_texte(
        lambda *_args: comprehension.TextUnderstandingDecision(
            "custom", "segment-page", 0.5, line_groups=((0,), (1,))
        )
    )
    decision = _page()
    assert decision.kind == "custom" and decision.ai_used is True


def test_provider_exception_warns_with_context_and_preserves_fallback(caplog):
    def broken(*_args):
        raise RuntimeError("semantic backend offline")

    comprehension.configurer_fournisseur_comprehension_texte(broken)
    assert _page() is None
    decision = comprehension.comprendre_reflow_paragraphe(
        ["Text continues", "on this line"], frame_role="text-column"
    )
    assert decision.line_joins == ("space",)
    assert decision.ai_used is False
    assert decision.fallback_used is True
    assert len(_warnings(caplog)) == 1
    message = _warnings(caplog)[0]
    assert "status=provider-error" in message
    assert "RuntimeError" in message and "semantic backend offline" in message
    assert "page-segmentation" in message and "page_index=3" in message


@pytest.mark.parametrize("response, status", [
    (None, "empty-response"),
    ({"confidence": 0.9}, "invalid-response"),
    (comprehension.TextUnderstandingDecision("ai", "unknown", 0.9), "invalid-response"),
    (comprehension.TextUnderstandingDecision("ai", "segment-page", float("nan")), "invalid-response"),
    (comprehension.TextUnderstandingDecision("ai", "segment-page", float("inf")), "invalid-response"),
    (comprehension.TextUnderstandingDecision("ai", "segment-page", 1.1), "invalid-response"),
    (comprehension.TextUnderstandingDecision("ai", "segment-page", "bad"), "invalid-response"),
    (comprehension.TextUnderstandingDecision("ai", "segment-page", 0.49), "low-confidence"),
    (comprehension.TextUnderstandingDecision("ai", "segment-page", 0.9), "invalid-response"),
])
def test_custom_provider_rejection_is_diagnosed_without_crash(caplog, response, status):
    comprehension.configurer_fournisseur_comprehension_texte(lambda *_args: response)
    assert _page() is None
    assert _page() is None
    assert len(_warnings(caplog)) == 1
    assert f"status={status}" in _warnings(caplog)[0]


@pytest.mark.parametrize("joins", [(), ("wrong",), ("space", "space")])
def test_invalid_reflow_transitions_report_fallback(caplog, joins):
    comprehension.configurer_fournisseur_comprehension_texte(
        lambda *_args: comprehension.TextUnderstandingDecision(
            "ai", "paragraph-reflow", 0.95, line_joins=joins
        )
    )
    decision = comprehension.comprendre_reflow_paragraphe(
        ["The text continues", "on another line"], frame_role="text-column"
    )
    assert decision.line_joins == ("space",)
    assert decision.fallback_used is True
    assert "status=invalid-response" in _warnings(caplog)[0]


@pytest.mark.parametrize("metadata", [
    [{"index": 0, "bbox": [10, 20, 90, 40], "styles": [{"font": "Arial", "size_pt": 10}]}],
    {
        "page_index": 3, "coordinate_space": "emu",
        "lines": [{"index": 0, "bbox": [10, 20, 90, 40], "styles": [{"bold": True}]}],
        "layout": [{"role": "text-column", "bbox": [0, 0, 100, 200]}],
        "obstacles": [{"kind": "image", "bbox": [100, 50, 200, 100]}],
    },
])
def test_http_payload_carries_rich_metadata_and_reports_acceptance(monkeypatch, caplog, metadata):
    def respond(request, timeout):
        payload = json.loads(request.data)
        assert payload["schema"] == "pdfexact.text_understanding.v1"
        assert payload["kind"] == "page-segmentation"
        assert payload["metadata"] == metadata
        assert payload["frame_strategy"] == metadata  # Existing HTTP contract remains readable.
        assert payload["lines"] == [{"i": 0, "text": "A paragraph"}]
        return io.BytesIO(b'{"action":"segment-page","confidence":0.9,"line_groups":[[0]]}')

    monkeypatch.setattr(http, "urlopen", respond)
    comprehension.configurer_fournisseur_comprehension_texte(
        http.creer_fournisseur_comprehension_texte_ai(url="http://semantic.test/understand")
    )
    with caplog.at_level(logging.INFO):
        decision = comprehension.comprendre_segmentation_page(["A paragraph"], metadonnees=metadata)
    assert decision.ai_used is True and decision.fallback_used is False
    assert "ai-decision-accepted" in decision.evidence
    assert "status=accepted" in caplog.text
    assert _warnings(caplog) == []


@pytest.mark.parametrize("body", [
    b"not JSON", b"[]", b'{"action":"unknown","confidence":0.9}',
    b'{"action":"segment-page","confidence":"invalid","line_groups":[[0]]}',
    b'{"action":"segment-page","confidence":0.9,"line_groups":[["0"]]}',
    b'{"action":"segment-page","confidence":0.9,"line_groups":[[true]]}',
    b'{"action":"segment-page","confidence":0.9,"line_groups":[[0],"bad"]}',
    b'{"action":"segment-page","confidence":true,"line_groups":[[0]]}',
    b'{"action":"segment-page","confidence":NaN,"line_groups":[[0]]}',
    b'{"action":"segment-page","confidence":0.9}',
    b'{"action":"merge-paragraph","confidence":0.9}',
    b'\xff',
])
def test_http_invalid_response_has_endpoint_and_reason(monkeypatch, caplog, body):
    monkeypatch.setattr(http, "urlopen", lambda *_args, **_kwargs: io.BytesIO(body))
    provider = http.creer_fournisseur_comprehension_texte_ai(url="http://semantic.test/understand")
    assert provider("page-segmentation", ("Text",), "page", None) is None
    assert len(_warnings(caplog)) == 1
    message = _warnings(caplog)[0]
    assert "status=invalid-response" in message
    assert "http://semantic.test/understand" in message
    assert "page-segmentation" in message and "fallback" in message.lower()


def test_http_low_confidence_has_endpoint_context(monkeypatch, caplog):
    monkeypatch.setattr(http, "urlopen", lambda *_args, **_kwargs: io.BytesIO(
        b'{"action":"segment-page","confidence":0.2,"line_groups":[[0],[1]]}'
    ))
    comprehension.configurer_fournisseur_comprehension_texte(
        http.creer_fournisseur_comprehension_texte_ai(url="http://semantic.test/understand")
    )
    assert _page() is None
    assert len(_warnings(caplog)) == 1
    assert "status=low-confidence" in _warnings(caplog)[0]
    assert "http://semantic.test/understand" in _warnings(caplog)[0]


@pytest.mark.parametrize("metadata", [
    {"bad": object()}, {"bad": float("nan")},
])
def test_http_unserializable_metadata_reports_fallback(caplog, metadata):
    provider = http.creer_fournisseur_comprehension_texte_ai(url="http://semantic.test/understand")
    assert provider("page-segmentation", ("Text",), "page", metadata) is None
    assert "status=provider-error" in _warnings(caplog)[0]
    assert "http://semantic.test/understand" in _warnings(caplog)[0]


@pytest.mark.parametrize("error", [
    URLError("connection refused"), TimeoutError("timed out"),
    HTTPError("http://semantic.test/understand", 503, "unavailable", {}, None),
])
def test_http_transport_errors_keep_endpoint_and_exception(monkeypatch, caplog, error):
    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(http, "urlopen", fail)
    comprehension.configurer_fournisseur_comprehension_texte(
        http.creer_fournisseur_comprehension_texte_ai(url="http://semantic.test/understand")
    )
    assert _page() is None
    assert _page() is None
    assert len(_warnings(caplog)) == 1
    message = _warnings(caplog)[0]
    assert "status=provider-error" in message
    assert type(error).__name__ in message
    assert "http://semantic.test/understand" in message


def test_analysis_scope_restores_custom_provider_after_exception():
    custom = lambda *_args: comprehension.TextUnderstandingDecision(
        "custom", "segment-page", 0.9, line_groups=((0,), (1,))
    )
    comprehension.configurer_fournisseur_comprehension_texte(custom)
    with pytest.raises(RuntimeError, match="extraction failed"):
        with comprehension.contexte_comprehension_texte():
            assert _page() is None
            raise RuntimeError("extraction failed")
    assert _page().kind == "custom"


@pytest.mark.parametrize("rows", [
    ["Research division", "Operations group", "Customer support"],
    ["101 Accounts division", "204 Field support", "309 Research center"],
    ["Personnel 120,000.50", "Equipment 42,000.25", "Travel 7,000.00"],
    ["operating costs: 12,500.50", "capital investment: 5,000.25"],
    ["maintenance 100", "training 250", "equipment 300"],
    ["Annual maintenance and safety inspections  1300",
     "Annual equipment and software renewals  2450"],
    ["Revenue = $12,500.50", "Expenses = $8,000.25", "Balance = $4,500.25"],
])
def test_reflow_preserves_general_structured_rows_in_one_paragraph(rows):
    decision = comprehension.comprendre_reflow_paragraphe(
        rows, frame_role="text-column", frame_strategy="word-text"
    )
    assert decision.action == "paragraph-reflow"
    assert decision.line_joins == ("preserve_break",) * (len(rows) - 1)
    assert "structured-row-breaks" in decision.evidence
    assert decision.fallback_used is True and decision.ai_used is False


@pytest.mark.parametrize("rows, expected", [
    (["Research division", "Operations group"], ("space",)),
    (["The project continues", "through several stages", "before final delivery."], ("space", "space")),
    (["The first phase is complete.", "The second phase starts today.", "The final review follows."],
     ("space", "space")),
    (["The team works", "In local offices", "And around the world."], ("space", "space")),
    (["The project continues.", "Across several locations", "Before final delivery"], ("space", "space")),
    (["Research and development", "across shared facilities", "Operations support"], ("space", "space")),
    (["The program first started in 2024", "We expect its completion in 2025"], ("space",)),
    (["The first of these longer prose lines explains how the project continues",
      "Across several regions while preserving all the operational interfaces we need",
      "During the next release and the subsequent stages of the entire program"], ("space", "space")),
    (["Research continues with inter-", "national coordination across regions", "and remains consistent."],
     ("hyphen_join", "space")),
])
def test_reflow_keeps_soft_prose_and_lowercase_continuations(rows, expected):
    decision = comprehension.comprendre_reflow_paragraphe(rows, frame_role="text-column")
    assert decision.line_joins == expected
    assert "structured-row-breaks" not in decision.evidence


@pytest.mark.parametrize("punctuation", [",", ":", ";", "-", "/", "(", "["])
def test_reflow_continuation_punctuation_prevents_structured_row_detection(punctuation):
    decision = comprehension.comprendre_reflow_paragraphe(
        [f"Research across regions{punctuation}", "Operations support", "Customer services"],
        frame_role="text-column",
    )
    assert decision.line_joins == ("space", "space")


def test_reflow_valid_ai_joins_override_structured_row_fallback():
    comprehension.configurer_fournisseur_comprehension_texte(
        lambda *_args: comprehension.TextUnderstandingDecision(
            "paragraph", "paragraph-reflow", 0.9, line_joins=("space", "space")
        )
    )
    decision = comprehension.comprendre_reflow_paragraphe(
        ["Research division", "Operations group", "Customer support"], frame_role="text-column"
    )
    assert decision.line_joins == ("space", "space")
    assert decision.ai_used is True and decision.fallback_used is False


@pytest.mark.parametrize("failure", ["missing", "exception", "invalid", "low-confidence"])
def test_reflow_structured_row_fallback_survives_provider_failures(failure):
    def provider(*_args):
        if failure == "exception":
            raise RuntimeError("backend unavailable")
        return comprehension.TextUnderstandingDecision(
            "paragraph", "paragraph-reflow", 0.2 if failure == "low-confidence" else 0.9,
            line_joins=("invalid",) if failure == "invalid" else ("space", "space"),
        )

    if failure != "missing":
        comprehension.configurer_fournisseur_comprehension_texte(provider)
    decision = comprehension.comprendre_reflow_paragraphe(
        ["Personnel 120000", "Equipment 42000", "Travel 7000"], frame_role="text-column"
    )
    assert decision.line_joins == ("preserve_break", "preserve_break")
    assert decision.fallback_used is True


