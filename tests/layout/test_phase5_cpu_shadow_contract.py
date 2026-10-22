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


@pytest.mark.parametrize("entrypoint", ["cli", "bbox-script"])
def test_real_conversion_entrypoint_creates_one_provider_across_pipeline_stages(
    shadow, monkeypatch, tmp_path, entrypoint,
):
    import sys
    from pdfexact import cli
    from pdfexact.geometry import BBox, pt_vers_emu as u
    from pdfexact.ir import Document, FontRef, Line, Page, Span, TextBox
    from pdfexact.scene import capture_source_observations
    from scripts import reconstruct_bbox_native as reconstruct

    created = []
    stages = []
    original_factory = factory.creer_fournisseur_comprehension_texte_ai

    def create(**kwargs):
        provider = original_factory(**kwargs)
        created.append((kwargs, provider))
        return provider

    def document():
        font = FontRef("synthetic", "Arial", False, False)
        lines = []
        for index, text in enumerate(LINES):
            bbox = BBox(u(20), u(30 + index * 11), u(220), u(40 + index * 11))
            lines.append(Line(bbox, [Span(text, font, 10, "000000", bbox=bbox)],
                              bbox.hauteur, bbox.largeur, source_id=f"line-{index}",
                              layout_frame_id="frame", layout_frame_role="text-column",
                              layout_frame_strategy="word-text", semantic_role="body"))
        block = TextBox(BBox(u(20), u(30), u(220), u(51)), lines,
                        layout_frame_id="frame", layout_frame_role="text-column",
                        layout_frame_strategy="word-text", source_id="block", semantic_role="body")
        page = Page(7, u(600), u(800), elements=[block])
        capture_source_observations(page, [block], source_kind="pdf-native")
        return Document(pages=[page])

    def extract(*_args, **_kwargs):
        assert _page() is None
        stages.append("extraction")
        return document()

    def write(*_args, **_kwargs):
        assert _page() is None
        assert _completed_event()["inference_invoked"]
        stages.append("writer")

    monkeypatch.setattr(factory, "creer_fournisseur_comprehension_texte_ai", create)
    target = cli if entrypoint == "cli" else reconstruct
    monkeypatch.setattr(target, "creer_fournisseur_comprehension_texte_ai", create)
    monkeypatch.setattr(target, "extraire", extract)
    monkeypatch.setattr(target, "construire", lambda **_kwargs: None)
    monkeypatch.setattr(target, "dossiers_par_defaut", lambda: [])
    if entrypoint == "cli":
        monkeypatch.setattr(cli, "ecrire_docx", write)
    else:
        for name in ("_enregistrer_catalogue", "_ecrire_docx_vierge", "_remplir_non_textes"):
            monkeypatch.setattr(reconstruct, name, lambda *_args, **_kwargs: None)
        monkeypatch.setattr(reconstruct, "_ecrire_bboxes_pdf", lambda *_args: [])
        monkeypatch.setattr(reconstruct, "_remplir_textes", write)
        # Normalization and plan construction execute their actual code.

    for conversion in range(2):
        output = tmp_path / f"conversion-{conversion}.docx"
        if entrypoint == "cli":
            cli.convertir(tmp_path / "synthetic.pdf", output, ai_models_root=str(shadow.root))
        else:
            monkeypatch.setattr(sys, "argv", ["reconstruct_bbox_native.py", str(tmp_path / "synthetic.pdf"),
                                "--docx-out", str(output), "--pdf-out", str(output.with_suffix(".pdf")),
                                "--ai-models-root", str(shadow.root)])
            assert reconstruct.main() == 0
        assert len(created) == len(shadow.calls) == conversion + 1
        assert created[-1][0]["model_root"] == shadow.root
    assert created[0][1] is not created[1][1]
    assert stages == ["extraction", "writer", "extraction", "writer"]


@pytest.fixture
def native_source(monkeypatch, tmp_path):
    import pymupdf
    from pdfexact.extract import native_document
    from pdfexact.geometry import BBox, pt_vers_emu as u
    from pdfexact.ir import FontRef, Line, Span, TextBox

    source = tmp_path / "native.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page(width=600, height=800)
        pdf.save(source)
    opened = []
    original_open = pymupdf.open

    def open_pdf(*args, **kwargs):
        pdf = original_open(*args, **kwargs)
        opened.append(pdf)
        return pdf

    def extract(*_args, **_kwargs):
        font = FontRef("synthetic", "Arial", False, False)
        lines = []
        for index, text in enumerate(LINES):
            bbox = BBox(u(20), u(30 + index * 11), u(220), u(40 + index * 11))
            ident = f"native-line-{index}"
            lines.append(Line(bbox, [Span(text, font, 10, "000000", bbox=bbox, source_id=ident + ":span")],
                              bbox.hauteur, bbox.largeur, source_id=ident, source_ids=(ident,),
                              layout_frame_role="text-column", layout_frame_strategy="word-text",
                              semantic_role="body"))
        return [TextBox(BBox(u(20), u(30), u(220), u(51)), lines,
                        source_id="native-block", layout_frame_role="text-column",
                        layout_frame_strategy="word-text", semantic_role="body")]

    monkeypatch.setattr(native_document.pymupdf, "open", open_pdf)
    monkeypatch.setattr(native_document, "construire", lambda **_kwargs: None)
    monkeypatch.setattr(native_document, "dossiers_par_defaut", lambda: [])
    monkeypatch.setattr(native_document, "collecter_polices", lambda *_args: {})
    monkeypatch.setattr(native_document, "extraire_texte", extract)
    return SimpleNamespace(path=source, module=native_document, extract=extract, opened=opened)


def _caller_provider(*_args):
    return comprehension.TextUnderstandingDecision("caller", "segment-page", 0.9,
                                                  line_groups=((0,), (1,)))


def _native_request():
    return comprehension.comprendre_segmentation_page(LINES, metadonnees={"page_index": 0})


@pytest.mark.parametrize("native_paragraphs", [False, True])
@pytest.mark.parametrize("route", ["local", "explicit-http", "environment-http"])
def test_native_utility_real_entrypoint_reuses_one_provider_and_restores_caller(
    shadow, native_source, monkeypatch, tmp_path, route, native_paragraphs,
):
    import sys
    from scripts import fill_bbox_docx_text as utility

    created, stages, requests = [], [], []
    original_factory = factory.creer_fournisseur_comprehension_texte_ai
    endpoint = "http://chosen-semantic.test/understand"
    if route != "local":
        monkeypatch.setenv("PDFEXACT_TEXT_UNDERSTANDING_URL",
                           "http://ignored.test" if route == "explicit-http" else endpoint)
    monkeypatch.setenv("PDFEXACT_TEXT_UNDERSTANDING_MODEL_ROOT", str(tmp_path / "ignored-model-root"))

    def create(**kwargs):
        provider = original_factory(**kwargs)
        created.append((kwargs, provider))
        return provider

    def respond(request, timeout):
        assert request.full_url == endpoint and timeout == 0.75
        requests.append(json.loads(request.data))
        return io.BytesIO(b'{"kind":"http","action":"segment-page","confidence":0.9,"line_groups":[[0],[1]]}')

    def observe(stage):
        provider = created[-1][1]
        assert comprehension._etat_analyse().provider is provider
        decision = _native_request()
        if route == "local":
            assert decision is None
            assert _completed_event()["inference_invoked"]
        else:
            assert decision.kind == "http" and decision.ai_used
        stages.append(stage)

    def extract(*args, **kwargs):
        observe("extraction")
        return native_source.extract(*args, **kwargs)

    def write(_source, document, _destination):
        assert document.pages[0].elements
        observe("writer")

    monkeypatch.setattr(factory, "creer_fournisseur_comprehension_texte_ai", create)
    monkeypatch.setattr(native_source.module, "creer_fournisseur_comprehension_texte_ai", create)
    monkeypatch.setattr(utility, "creer_fournisseur_comprehension_texte_ai", create)
    monkeypatch.setattr(factory, "urlopen", respond)
    monkeypatch.setattr(native_source.module, "extraire_texte", extract)
    writer = "fill_existing_bbox_docx_with_native_paragraphs" if native_paragraphs else "fill_existing_bbox_docx_with_text"
    other = "fill_existing_bbox_docx_with_text" if native_paragraphs else "fill_existing_bbox_docx_with_native_paragraphs"
    monkeypatch.setattr(utility, writer, write)
    monkeypatch.setattr(utility, other, lambda *_args: pytest.fail("wrong utility writer"))
    comprehension.configurer_fournisseur_comprehension_texte(_caller_provider)
    assert _native_request().kind == "caller"
    caller_state = comprehension._etat_analyse()

    for conversion in range(2):
        destination = tmp_path / f"utility-{conversion}.docx"
        args = ["fill_bbox_docx_text.py", str(native_source.path), str(tmp_path / "boxes.docx"), str(destination),
                "--ai-models-root", str(shadow.root), "--text-understanding-timeout", "0.75"]
        if native_paragraphs:
            args.extend(["--native-paragraphs", "--text-understanding-ai"])
        if route == "explicit-http":
            args.extend(["--text-understanding-url", endpoint])
        monkeypatch.setattr(sys, "argv", args)
        assert utility.main() == 0
        assert len(created) == conversion + 1
        assert len(shadow.calls) == (conversion + 1 if route == "local" else 0)
        assert created[-1][0] == {"url": endpoint if route == "explicit-http" else None,
                                  "timeout": 0.75, "model_root": shadow.root}
        assert comprehension._etat_analyse() is caller_state
        assert _native_request().kind == "caller"
        assert destination.with_suffix(".extraction.json").is_file()
    assert created[0][1] is not created[1][1]
    assert stages == ["extraction", "writer", "extraction", "writer"]
    assert len(requests) == (0 if route == "local" else 4)
    assert native_source.opened and all(pdf.is_closed for pdf in native_source.opened)


@pytest.mark.parametrize("failure", [None, "extraction", "scene"])
def test_standalone_native_extraction_restores_caller_scope_on_success_and_failure(
    shadow, native_source, monkeypatch, failure,
):
    native = native_source.module
    created = []
    original_factory = factory.creer_fournisseur_comprehension_texte_ai

    def create(**kwargs):
        provider = original_factory(**kwargs)
        created.append((kwargs, provider))
        return provider

    def extract(*args, **kwargs):
        assert comprehension._etat_analyse().provider is created[-1][1]
        assert _native_request() is None
        if failure == "extraction":
            raise RuntimeError("synthetic extraction failure")
        return native_source.extract(*args, **kwargs)

    if failure == "scene":
        def fail_scene(_document):
            assert comprehension._etat_analyse().provider is created[-1][1]
            raise RuntimeError("synthetic scene failure")

        monkeypatch.setattr(native, "scene_from_legacy_document", fail_scene)
    monkeypatch.setattr(native, "creer_fournisseur_comprehension_texte_ai", create)
    monkeypatch.setattr(native, "extraire_texte", extract)
    comprehension.configurer_fournisseur_comprehension_texte(_caller_provider)
    caller_state = comprehension._etat_analyse()
    if failure:
        with pytest.raises(RuntimeError, match=f"synthetic {failure} failure"):
            native.extraire_document_texte_natif(native_source.path, model_root=shadow.root)
    else:
        for _ in range(2):
            assert native.extraire_document_texte_natif(native_source.path, model_root=shadow.root).pages
    assert comprehension._etat_analyse() is caller_state
    assert _native_request().kind == "caller"
    assert len(created) == len(shadow.calls) == (1 if failure else 2)
    assert all(options["model_root"] == shadow.root for options, _provider in created)
    assert all(pdf.is_closed for pdf in native_source.opened)


@pytest.mark.parametrize("failure", [False, True])
def test_reused_native_extraction_keeps_exact_caller_provider_without_factory(
    shadow, native_source, monkeypatch, failure,
):
    native = native_source.module
    provider = _configure(shadow)
    caller_state = comprehension._etat_analyse()

    def extract(*args, **kwargs):
        assert comprehension._etat_analyse().provider is provider
        assert _native_request() is None
        if failure:
            raise RuntimeError("synthetic extraction failure")
        return native_source.extract(*args, **kwargs)

    monkeypatch.setattr(native, "extraire_texte", extract)
    monkeypatch.setattr(native, "creer_fournisseur_comprehension_texte_ai",
                        lambda **_kwargs: pytest.fail("reused extraction created another provider"))
    if failure:
        with pytest.raises(RuntimeError, match="synthetic extraction failure"):
            native.extraire_document_texte_natif(native_source.path, reuse_text_understanding_context=True)
    else:
        native.extraire_document_texte_natif(native_source.path, reuse_text_understanding_context=True)
    assert comprehension._etat_analyse() is caller_state
    assert _native_request() is None and _completed_event()["inference_invoked"]
    assert len(shadow.calls) == 1 and all(pdf.is_closed for pdf in native_source.opened)


@pytest.mark.parametrize("failure_stage", ["factory", "extraction", "writer"])
def test_native_utility_failure_restores_caller_provider(
    shadow, native_source, monkeypatch, tmp_path, failure_stage,
):
    import sys
    from scripts import fill_bbox_docx_text as utility

    comprehension.configurer_fournisseur_comprehension_texte(_caller_provider)
    caller_state = comprehension._etat_analyse()

    def fail(*_args, **_kwargs):
        if failure_stage != "factory":
            assert _native_request() is None
        raise RuntimeError(f"synthetic {failure_stage} failure")

    if failure_stage == "factory":
        monkeypatch.setattr(utility, "creer_fournisseur_comprehension_texte_ai", fail)
    elif failure_stage == "extraction":
        monkeypatch.setattr(native_source.module, "extraire_texte", fail)
    else:
        monkeypatch.setattr(utility, "fill_existing_bbox_docx_with_text", fail)
    monkeypatch.setattr(sys, "argv", ["fill_bbox_docx_text.py", str(native_source.path),
                        str(tmp_path / "boxes.docx"), str(tmp_path / "failure.docx"),
                        "--ai-models-root", str(shadow.root)])
    with pytest.raises(RuntimeError, match=f"synthetic {failure_stage} failure"):
        utility.main()
    assert comprehension._etat_analyse() is caller_state
    assert _native_request().kind == "caller"
    assert all(pdf.is_closed for pdf in native_source.opened)
