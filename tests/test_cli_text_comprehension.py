import io
import json
import logging
from contextvars import Context
from types import SimpleNamespace

import pytest

from pdfexact import cli
from pdfexact.layout import text_comprehension as comprehension
from pdfexact.layout import text_comprehension_ai as http


@pytest.fixture(autouse=True)
def isolate_understanding(monkeypatch, tmp_path):
    monkeypatch.delenv("PDFEXACT_TEXT_UNDERSTANDING_URL", raising=False)
    monkeypatch.setenv("PDFEXACT_TEXT_UNDERSTANDING_MODEL_ROOT", str(tmp_path / "no-local-model"))
    monkeypatch.delenv("PDFEXACT_TEXT_ORIENTATION_URL", raising=False)
    with comprehension.contexte_comprehension_texte():
        comprehension.configurer_fournisseur_comprehension_texte(None)
        yield


@pytest.fixture
def cli_pipeline(monkeypatch, tmp_path):
    source = tmp_path / "source.pdf"
    source.touch()
    monkeypatch.setattr(cli, "construire", lambda **_kwargs: None)
    monkeypatch.setattr(cli, "dossiers_par_defaut", lambda: [])
    monkeypatch.setattr(cli, "extraire", lambda *_args, **_kwargs: SimpleNamespace(pages=[]))
    monkeypatch.setattr(cli, "ecrire_docx", lambda *_args, **_kwargs: None)
    return [str(source), str(tmp_path / "output.docx")]


def _page():
    return comprehension.comprendre_segmentation_page(["A paragraph"], metadonnees={"page_index": 0})


def _configure_caller():
    comprehension.configurer_fournisseur_comprehension_texte(
        lambda *_args: comprehension.TextUnderstandingDecision(
            "caller", "segment-page", 0.95, line_groups=((0,),)
        )
    )


def _http_response(request, timeout):
    assert json.loads(request.data)["kind"] == "page-segmentation"
    return io.BytesIO(
        b'{"kind":"http","action":"segment-page","confidence":0.95,"line_groups":[[0]]}'
    )


@pytest.mark.parametrize("endpoint_source", ["argument", "environment"])
def test_ordinary_cli_uses_endpoint_without_legacy_flag_and_restores_caller(
    monkeypatch, cli_pipeline, caplog, endpoint_source
):
    endpoint = "http://semantic.test/understand"
    args = list(cli_pipeline)
    if endpoint_source == "argument":
        args += ["--text-understanding-url", endpoint]
    else:
        monkeypatch.setenv("PDFEXACT_TEXT_UNDERSTANDING_URL", endpoint)
    _configure_caller()
    requests = []
    stages = []

    def respond(request, timeout):
        requests.append((request.full_url, timeout))
        return _http_response(request, timeout)

    def extract(*_args, **_kwargs):
        decision = _page()
        assert decision.kind == "http" and decision.ai_used is True
        stages.append("extraction")
        return SimpleNamespace(pages=[])

    def write(*_args, **_kwargs):
        assert _page().kind == "http"
        stages.append("rendering")

    monkeypatch.setattr(http, "urlopen", respond)
    monkeypatch.setattr(cli, "extraire", extract)
    monkeypatch.setattr(cli, "ecrire_docx", write)
    with caplog.at_level(logging.INFO):
        assert cli.main(args) == 0

    assert stages == ["extraction", "rendering"]
    assert requests == [(endpoint, 3.0), (endpoint, 3.0)]
    assert _page().kind == "caller"
    assert "status=configured" in caplog.text


def test_cli_missing_endpoint_announces_fallback_and_continues(
    monkeypatch, cli_pipeline, caplog
):
    _configure_caller()
    stages = []

    def extract(*_args, **_kwargs):
        assert "status=missing-provider" in caplog.text
        assert _page() is None
        decision = comprehension.comprendre_groupe_lignes(
            [
                "The mission architecture requires stable interfaces between",
                "launch systems and operational support teams so that the",
                "implementation remains consistent across all phases.",
            ],
            frame_role="text-column", frame_strategy="word-text",
        )
        assert decision.action == "merge-paragraph"
        assert decision.fallback_used is True and decision.ai_used is False
        stages.append("extraction")
        return SimpleNamespace(pages=[])

    def write(*_args, **_kwargs):
        assert _page() is None
        stages.append("rendering")

    monkeypatch.setattr(cli, "extraire", extract)
    monkeypatch.setattr(cli, "ecrire_docx", write)
    assert cli.main(cli_pipeline) == 0
    warnings = [record.message for record in caplog.records if record.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "status=missing-provider" in warnings[0] and "fallback" in warnings[0]
    assert stages == ["extraction", "rendering"]
    assert _page().kind == "caller"


@pytest.mark.parametrize("failure_stage", ["extraction", "rendering", "setup"])
def test_cli_failure_restores_caller_provider(monkeypatch, cli_pipeline, failure_stage):
    _configure_caller()
    monkeypatch.setattr(http, "urlopen", _http_response)
    failures = []

    def fail(*_args, **_kwargs):
        if failure_stage != "setup":
            assert _page().kind == "http"
        failures.append(failure_stage)
        raise RuntimeError("conversion failed")

    target = {
        "extraction": "extraire", "rendering": "ecrire_docx",
        "setup": "creer_fournisseur_comprehension_texte_ai",
    }[failure_stage]
    monkeypatch.setattr(cli, target, fail)
    assert cli.main(cli_pipeline + ["--text-understanding-url", "http://semantic.test/understand"]) == 1
    assert failures == [failure_stage]
    assert _page().kind == "caller"


@pytest.mark.parametrize("options, env, expected", [
    ({}, {}, None),
    ({"text_understanding_url": "http://text.test"}, {}, None),
    ({"text_understanding_ai": True, "text_understanding_url": "http://text.test",
      "text_understanding_timeout": 1.25}, {}, {"url": "http://text.test", "timeout": 1.25}),
    ({"text_orientation_ai": True, "text_orientation_url": "http://orientation.test",
      "text_orientation_timeout": 2.5}, {}, {"url": "http://orientation.test", "timeout": 2.5}),
    ({}, {"PDFEXACT_TEXT_UNDERSTANDING_URL": "http://text.test"}, {"url": None, "timeout": 3.0}),
    ({}, {"PDFEXACT_TEXT_ORIENTATION_URL": "http://orientation.test"}, {"url": None, "timeout": 3.0}),
])
def test_text_hookup_preserves_orientation_options(
    monkeypatch, cli_pipeline, options, env, expected
):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    provider = object()
    created = []
    configured = []

    def create(**kwargs):
        created.append(kwargs)
        return provider

    monkeypatch.setattr(cli, "creer_fournisseur_orientation_ai", create)
    monkeypatch.setattr(cli, "configurer_fournisseur_orientation", configured.append)
    cli.convertir(*cli_pipeline, **options)

    assert created == ([] if expected is None else [expected])
    assert configured == ([] if expected is None else [provider, None])


def test_direct_library_discovers_environment_only_on_initial_use(monkeypatch):
    monkeypatch.setenv("PDFEXACT_TEXT_UNDERSTANDING_URL", "http://semantic.test/understand")
    monkeypatch.setattr(http, "urlopen", _http_response)
    original_factory = http.creer_fournisseur_comprehension_texte_ai
    creations = []

    def create(**kwargs):
        creations.append(kwargs)
        return original_factory(**kwargs)

    monkeypatch.setattr(http, "creer_fournisseur_comprehension_texte_ai", create)
    fresh_context = Context()
    assert fresh_context.run(_page).kind == "http"
    assert fresh_context.run(_page).kind == "http"
    assert creations == [{}]


def test_explicit_none_keeps_direct_library_disabled_despite_environment(monkeypatch, caplog):
    monkeypatch.setenv("PDFEXACT_TEXT_UNDERSTANDING_URL", "http://semantic.test/understand")

    def unexpected_factory(**_kwargs):
        pytest.fail("an explicit None must disable environment discovery")

    monkeypatch.setattr(http, "creer_fournisseur_comprehension_texte_ai", unexpected_factory)

    def explicitly_disabled():
        comprehension.configurer_fournisseur_comprehension_texte(None)
        assert _page() is None

    Context().run(explicitly_disabled)
    assert "status=missing-provider" in caplog.text


def test_new_analysis_discovers_environment_and_restores_explicit_none(monkeypatch):
    monkeypatch.setenv("PDFEXACT_TEXT_UNDERSTANDING_URL", "http://semantic.test/understand")
    monkeypatch.setattr(http, "urlopen", _http_response)
    comprehension.configurer_fournisseur_comprehension_texte(None)
    with comprehension.contexte_comprehension_texte():
        assert _page().kind == "http"
    assert _page() is None
