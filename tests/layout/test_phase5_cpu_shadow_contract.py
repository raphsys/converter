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


def test_configuration_alone_is_not_a_cpu_inference_attempt(shadow):
    _configure(shadow)
    assert shadow.calls == []
    assert all(not event.get("inference_invoked", False) for event in _events())


def test_available_default_runs_shadow_once_without_applying_valid_json(shadow):
    provider = _configure(shadow)
    assert provider is not None
    assert _page() is None
    assert len(shadow.calls) == 1, "installed-but-disabled is not a real attempt"
    event = _completed_event()
    assert event["availability"] == "compatible"
    assert event["inference_invoked"] and event["first_token_observed"]
    assert event["generated_tokens"] == 24
    assert event["quality"] == "unqualified"
    assert event["application"] == "not-applied"
    assert event["weights_provenance"] == "local-user-bundle-unverified"


def test_one_eligible_request_budget_spans_page_group_and_reflow(shadow):
    _configure(shadow)
    assert _page() is None
    group = comprehension.comprendre_groupe_lignes(LINES, frame_role="text-column")
    reflow = comprehension.comprendre_reflow_paragraphe(LINES, frame_role="text-column")
    assert group.fallback_used and not group.ai_used
    assert reflow.fallback_used and not reflow.ai_used
    assert len(shadow.calls) == 1


@pytest.mark.parametrize("attempt", ["completed", "load-failed", "timeout"])
def test_repeated_analysis_begins_keep_same_conversion_provider_budget(shadow, attempt):
    if attempt != "completed":
        shadow.result.update(
            runtime_attempt=attempt, failure_stage="model-load",
            inference_invoked=False, first_token_observed=False, generated_tokens=0,
            status="shadow-abstained", reason="model-load-error" if attempt == "load-failed" else "global-deadline",
            worker={"finished": True, "terminated": attempt == "timeout", "alive": False},
        )
    provider = factory.creer_fournisseur_comprehension_texte_ai(model_root=shadow.root)
    for stage in ("extraction", "normalization", "planning", "writer"):
        with comprehension.contexte_comprehension_texte():
            comprehension.configurer_fournisseur_comprehension_texte(provider)
            assert _page() is None
            assert _page() is None
            assert len(shadow.calls) == 1, f"internal stage {stage} must not create a second CPU load"
            assert any(event.get("runtime_attempt") == attempt for event in _events())


def test_new_conversion_provider_gets_its_own_single_attempt_budget(shadow):
    providers = []
    for _ in range(2):
        with comprehension.contexte_comprehension_texte():
            provider = factory.creer_fournisseur_comprehension_texte_ai(model_root=shadow.root)
            providers.append(provider)
            comprehension.configurer_fournisseur_comprehension_texte(provider)
            assert _page() is None
            assert _page() is None
    assert providers[0] is not providers[1]
    assert len(shadow.calls) == 2


def test_final_diagnostics_preserve_actual_attempt_across_internal_analysis_resets(shadow):
    provider = _configure(shadow)
    assert _page() is None
    assert len(shadow.calls) == 1
    first_attempt = deepcopy(_completed_event())
    for stage in ("normalization", "planning", "writer"):
        comprehension.configurer_fournisseur_comprehension_texte(provider)
        assert any(event == first_attempt for event in _events()), stage
        assert _page() is None
    final_events = _events()
    assert any(event == first_attempt for event in final_events)
    assert len(shadow.calls) == 1
    assert not any(event.get("reason") == "no-eligible-source-input" for event in final_events)
    assert _completed_event()["inference_invoked"]
    assert _completed_event()["generated_tokens"] == 24


def test_empty_later_analysis_does_not_erase_or_mislabel_completed_conversion_attempt(shadow, caplog):
    provider = _configure(shadow)
    assert _page() is None
    assert len(shadow.calls) == 1
    first_attempt = deepcopy(_completed_event())
    with comprehension.contexte_comprehension_texte():
        comprehension.configurer_fournisseur_comprehension_texte(provider)
        assert any(event == first_attempt for event in _events())
    assert any(event == first_attempt for event in _events())
    assert "no-eligible-source-input" not in caplog.text
    assert len(shadow.calls) == 1


@pytest.mark.parametrize("excess", ["lines", "characters", "metadata"])
def test_ineligible_budget_input_warns_then_next_eligible_request_runs(shadow, caplog, excess):
    _configure(shadow)
    lines = ("source line",) * 65 if excess == "lines" else LINES
    if excess == "characters":
        lines = ("x" * 16001,)
    context = {"page_index": 7, "source_note": "x" * 25000} if excess == "metadata" else CONTEXT
    assert _page(lines, context) is None
    assert shadow.calls == [], "source limits must not spawn a worker or consume the eligible attempt"
    assert "input-limit" in caplog.text
    assert _page() is None
    assert len(shadow.calls) == 1


def test_shadow_request_preserves_source_context_and_has_finite_bounds(shadow):
    _configure(shadow)
    before = deepcopy(CONTEXT)
    assert _page() is None
    assert len(shadow.calls) == 1
    payload, timeout = shadow.calls[0]
    assert payload["kind"] == "page-segmentation"
    assert payload["model_path"] == str(shadow.path)
    assert payload["lines"] == [{"i": index, "text": text} for index, text in enumerate(LINES)]
    assert payload["metadata"] == CONTEXT
    assert CONTEXT == before
    assert 0 < timeout <= 30
    assert 0 < payload["max_input_tokens"] <= 3072
    assert 0 < payload["max_output_tokens"] <= 384


@pytest.mark.parametrize("availability,attempt,stage,invoked,token,reason", [
    ("unavailable", "not-attempted", "runtime-import", False, False, "missing-runtime"),
    ("incompatible", "not-attempted", "bundle-inspection", False, False, "incompatible-tokenizer"),
    ("compatible", "not-attempted", "resource-check", False, False, "insufficient-memory"),
    ("compatible", "load-failed", "model-load", False, False, "model-load-error"),
    ("compatible", "failed-before-first-token", "before-first-token", True, False, "runtime-failed-before-first-token"),
    ("compatible", "timeout", "model-load", False, False, "global-deadline"),
    ("compatible", "timeout", "generation", True, True, "global-deadline"),
    ("compatible", "completed", "response-validation", True, True, "malformed-json"),
])
def test_attempt_phase_and_abstention_are_truthful_and_diagnostic(
    shadow, caplog, availability, attempt, stage, invoked, token, reason,
):
    shadow.result.update(
        availability=availability, runtime_attempt=attempt, failure_stage=stage,
        inference_invoked=invoked, first_token_observed=token,
        generated_tokens=1 if token else 0, status="shadow-abstained", reason=reason,
        worker={"finished": True, "terminated": attempt == "timeout", "alive": False},
    )
    _configure(shadow)
    assert _page() is None
    assert len(shadow.calls) == 1
    events = [event for event in _events() if event.get("reason") == reason]
    assert events
    event = events[-1]
    for key in ("availability", "runtime_attempt", "failure_stage", "inference_invoked",
                "first_token_observed", "generated_tokens"):
        assert event[key] == shadow.result[key]
    assert event["quality"] == "unqualified" and event["application"] == "not-applied"
    assert reason in caplog.text
    assert not event["worker"]["alive"]


def test_missing_bundle_warns_without_fabricating_inference(shadow, caplog):
    shadow.path.joinpath("model.bin").unlink()
    with caplog.at_level(logging.INFO):
        _configure(shadow)
        assert _page() is None
    assert shadow.calls == []
    assert "missing-bundle" in caplog.text
    events = _events()
    assert any(event.get("availability") == "absent" for event in events)
    assert all(not event.get("inference_invoked", False) for event in events)


def test_worker_claim_cannot_promote_unqualified_quality_or_application(shadow):
    shadow.result.update(quality="qualified", application="applied")
    _configure(shadow)
    assert _page() is None
    assert len(shadow.calls) == 1
    assert _completed_event()["quality"] == "unqualified"
    assert _completed_event()["application"] == "not-applied"


def test_diagnostic_snapshot_cannot_mutate_later_analysis_state(shadow):
    _configure(shadow)
    assert _page() is None
    snapshot = _events()
    assert snapshot
    before = deepcopy(snapshot)
    snapshot[-1]["application"] = "invented-application"
    assert _events() == before


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


def test_current_unqualified_path_never_claims_applied_ai(shadow):
    _configure(shadow)
    decision = comprehension.comprendre_reflow_paragraphe(LINES, frame_role="text-column")
    assert decision.line_joins == ("space",)
    assert decision.fallback_used and not decision.ai_used


def test_conversion_without_eligible_text_reports_no_inference(shadow, caplog):
    with comprehension.contexte_comprehension_texte():
        _configure(shadow)
    assert shadow.calls == []
    assert "no-eligible-source-input" in caplog.text


def test_explicit_experimental_route_is_distinct_but_source_guard_still_wins(shadow, monkeypatch):
    calls = []

    def experimental(kind, lines, _role, _context):
        calls.append((kind, lines))
        return comprehension.TextUnderstandingDecision(
            "paragraph", "paragraph-reflow", 0.99, line_joins=("space",),
        )

    monkeypatch.setattr(local, "creer_fournisseur_comprehension_texte_local", lambda **_kwargs: experimental)
    provider = factory.creer_fournisseur_comprehension_texte_ai(
        model_root=shadow.root, experimental_local=True,
    )
    comprehension.configurer_fournisseur_comprehension_texte(provider)
    texts = ("An explicit source break\n", "the following source line")
    decision = comprehension.comprendre_reflow_paragraphe(texts, frame_role="text-column")
    assert calls == [("paragraph-reflow", texts)]
    assert shadow.calls == []
    assert decision.line_joins == ("preserve_break",)
    assert decision.fallback_used and not decision.ai_used


@pytest.mark.parametrize("stubborn", [False, True])
def test_global_timeout_terminates_and_reaps_owned_worker_without_token_callback(monkeypatch, tmp_path, stubborn):
    processes = []

    class Process:
        def __init__(self, *_args, **_kwargs):
            self.alive = True
            self.terminated = self.killed = self.reaped = False
            self.returncode = None
            processes.append(self)

        def communicate(self, input=None, timeout=None):
            if self.alive:
                assert timeout is not None and timeout >= 0
                raise subprocess.TimeoutExpired("mock-worker", timeout)
            self.reaped = True
            return b"", b""

        def poll(self):
            return None if self.alive else self.returncode

        def terminate(self):
            self.terminated = True
            if not stubborn:
                self.alive, self.returncode = False, -15

        def kill(self):
            self.killed = True
            self.alive, self.returncode = False, -9

        def wait(self, timeout=None):
            if self.alive:
                raise subprocess.TimeoutExpired("mock-worker", timeout)
            self.reaped = True
            return self.returncode

    monkeypatch.setattr(subprocess, "Popen", Process)
    execute = getattr(local, "_executer_sonde_shadow_isolee", None)
    assert callable(execute), "owned isolated executor is missing; token callback is insufficient"
    result = execute(_worker_payload(tmp_path), timeout=0.1)
    assert len(processes) == 1
    process = processes[0]
    assert process.terminated and process.reaped and not process.alive
    assert process.killed is stubborn
    assert result["runtime_attempt"] == "timeout"
    assert result["quality"] == "unqualified" and result["application"] == "not-applied"
    assert not result["worker"]["alive"]


def test_process_start_time_is_included_in_global_deadline(monkeypatch, tmp_path):
    clock = SimpleNamespace(now=0.0)
    waits = []

    class Process:
        returncode = 0

        def __init__(self, *_args, **_kwargs):
            clock.now = 0.3

        def communicate(self, input=None, timeout=None):
            waits.append(timeout)
            return json.dumps({
                "availability": "compatible", "runtime_attempt": "completed",
                "inference_invoked": True, "first_token_observed": True,
                "generated_tokens": 1, "quality": "unqualified", "application": "not-applied",
            }).encode(), b""

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(local, "monotonic", lambda: clock.now)
    monkeypatch.setattr(subprocess, "Popen", Process)
    execute = getattr(local, "_executer_sonde_shadow_isolee", None)
    assert callable(execute), "owned isolated executor is missing"
    result = execute(_worker_payload(tmp_path), timeout=0.5)
    assert waits and 0 < waits[0] <= 0.200001
    assert result["runtime_attempt"] == "completed"






def _caller_provider(*_args):
    return comprehension.TextUnderstandingDecision("caller", "segment-page", 0.9,
                                                  line_groups=((0,), (1,)))


def _native_request():
    return comprehension.comprendre_segmentation_page(LINES, metadonnees={"page_index": 0})








