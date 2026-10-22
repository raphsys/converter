"""CPU shadow conversion contracts; mocked workers and no real model runs."""

from copy import deepcopy
import io
import json
import logging
import subprocess
from types import SimpleNamespace

import pytest

from pdfexact.layout import text_comprehension as comprehension
from pdfexact.layout import text_comprehension_ai as factory
from pdfexact.layout import text_comprehension_local as local


LINES = ("The system validates incoming data", "before storing the complete results.")
CONTEXT = {
    "page_index": 7, "coordinate_system": {"origin": "top-left", "units": "EMU"},
    "lines": [
        {"index": 0, "text": LINES[0], "source_ids": ["source-first"],
         "bbox": [100, 200, 800, 300], "semantic_role": "body"},
        {"index": 1, "text": LINES[1], "source_ids": ["source-second"],
         "bbox": [100, 310, 800, 410], "semantic_role": "body"},
    ],
}


@pytest.fixture(autouse=True)
def isolated_analysis(monkeypatch):
    monkeypatch.delenv("PDFEXACT_TEXT_UNDERSTANDING_URL", raising=False)
    monkeypatch.setattr(local, "_load_runtime", lambda: pytest.fail("runtime loaded in parent"))
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("real worker forbidden"))
    monkeypatch.setattr(local, "Popen", lambda *_args, **_kwargs: pytest.fail("real worker forbidden"), raising=False)
    with comprehension.contexte_comprehension_texte():
        comprehension.configurer_fournisseur_comprehension_texte(None)
        yield


@pytest.fixture
def shadow(monkeypatch, tmp_path):
    root = tmp_path / "ai_models"
    path = root / "semantic_corrector" / "qwen2_5_0_5b_ct2_int8"
    path.mkdir(parents=True)
    (path / "model.bin").write_bytes(b"synthetic fixture, not real weights")
    state = SimpleNamespace(root=root, path=path, calls=[], result={
        "availability": "compatible", "runtime_attempt": "completed",
        "failure_stage": None, "inference_invoked": True,
        "first_token_observed": True, "generated_tokens": 24,
        "quality": "unqualified", "application": "not-applied",
        "status": "accepted", "reason": "validated-structured-decision; quality-not-certified",
        "decision": {"kind": "paragraph", "action": "segment-page", "confidence": 0.99,
                     "line_groups": [[0, 1]], "evidence": ["model claims continuity"]},
        "worker": {"finished": True, "terminated": False, "alive": False},
    })

    def execute(payload, *, timeout):
        state.calls.append((deepcopy(payload), timeout))
        return deepcopy(state.result)

    monkeypatch.setattr(local, "_executer_sonde_shadow_isolee", execute, raising=False)
    return state


def _configure(shadow):
    provider = factory.creer_fournisseur_comprehension_texte_ai(model_root=shadow.root)
    comprehension.configurer_fournisseur_comprehension_texte(provider, annoncer=True)
    return provider


def _page(lines=LINES, context=None):
    return comprehension.comprendre_segmentation_page(
        lines, metadonnees=deepcopy(CONTEXT if context is None else context),
    )


def _events():
    snapshot = getattr(comprehension, "diagnostics_comprehension_texte", None)
    assert callable(snapshot), "read-only analysis diagnostic snapshot API is missing"
    events = snapshot()
    assert isinstance(events, tuple)
    json.dumps(events, allow_nan=False)
    return events


def _completed_event():
    events = [event for event in _events() if event.get("runtime_attempt") == "completed"]
    assert events, "generation completion must not be confused with installed/disabled"
    return events[-1]


def _worker_payload(tmp_path):
    path = tmp_path / "synthetic-worker-bundle"
    path.mkdir()
    (path / "model.bin").write_bytes(b"synthetic fixture, not real weights")
    return {
        "schema": "pdfexact.text_understanding.v1", "kind": "page-segmentation",
        "model_path": str(path), "frame_role": "page", "metadata": deepcopy(CONTEXT),
        "lines": [{"i": index, "text": text} for index, text in enumerate(LINES)],
        "max_input_tokens": 3072, "max_output_tokens": 128,
    }




























@pytest.mark.parametrize("endpoint_source", ["explicit", "environment"])
def test_http_priority_suppresses_local_shadow(shadow, monkeypatch, endpoint_source):
    endpoint = "http://semantic.test/understand"
    if endpoint_source == "environment":
        monkeypatch.setenv("PDFEXACT_TEXT_UNDERSTANDING_URL", endpoint)
    monkeypatch.setattr(factory, "urlopen", lambda *_args, **_kwargs: io.BytesIO(
        b'{"action":"segment-page","confidence":0.9,"line_groups":[[0],[1]]}'
    ))
    provider = factory.creer_fournisseur_comprehension_texte_ai(
        model_root=shadow.root, url=endpoint if endpoint_source == "explicit" else None,
    )
    comprehension.configurer_fournisseur_comprehension_texte(provider)
    assert _page().ai_used
    assert shadow.calls == []
















def _caller_provider(*_args):
    return comprehension.TextUnderstandingDecision("caller", "segment-page", 0.9,
                                                  line_groups=((0,), (1,)))


def _native_request():
    return comprehension.comprendre_segmentation_page(LINES, metadonnees={"page_index": 0})








