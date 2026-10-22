from pathlib import Path
from types import SimpleNamespace

import pytest

from pdfexact import cli
from pdfexact.model_paths import resolve_ai_models_root


@pytest.mark.parametrize("flag", ["--ocr-language", "--ocr-lang"])
def test_cli_common_root_and_explicit_language_reach_both_providers(monkeypatch, tmp_path, flag):
    source = tmp_path / "source.pdf"
    source.touch()
    common, layout = tmp_path / "models", tmp_path / "layout"
    calls = {}
    monkeypatch.setattr(cli, "construire", lambda **kwargs: None)
    monkeypatch.setattr(cli, "dossiers_par_defaut", lambda: [])
    monkeypatch.setattr(cli, "ecrire_docx", lambda *args, **kwargs: None)

    def provider(**kwargs):
        calls["provider"] = kwargs

    def extract(*args, **kwargs):
        calls["extract"] = kwargs
        return SimpleNamespace(pages=[])

    monkeypatch.setattr(cli, "creer_fournisseur_comprehension_texte_ai", provider)
    monkeypatch.setattr(cli, "extraire", extract)
    assert cli.main([str(source), str(tmp_path / "out.docx"), "--ai-models-root", str(common),
                     "--layout-model-root", str(layout), flag, "ru+ja", "--text-mode", "spans"]) == 0
    assert Path(calls["provider"]["model_root"]) == common
    assert Path(calls["extract"]["ai_models_root"]) == common
    assert calls["extract"]["layout_model_root"] == str(layout)
    assert calls["extract"]["ocr_language"] == "ru+ja"
    assert calls["extract"]["text_mode"] == "spans"
    assert calls["extract"]["ocr_layer"] is False
    assert calls["provider"]["experimental_local"] is False


def test_common_root_environment_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("VYSI_AI_MODELS_ROOT", str(tmp_path / "vysi"))
    monkeypatch.setenv("PDFEXACT_AI_MODELS_ROOT", str(tmp_path / "converter"))
    assert resolve_ai_models_root() == tmp_path / "converter"
    assert resolve_ai_models_root(tmp_path / "explicit") == tmp_path / "explicit"


def test_no_explicit_root_preserves_understanding_specific_environment(monkeypatch, tmp_path):
    source = tmp_path / "source.pdf"
    source.touch()
    roots = []
    monkeypatch.setattr(cli, "construire", lambda **kwargs: None)
    monkeypatch.setattr(cli, "dossiers_par_defaut", lambda: [])
    monkeypatch.setattr(cli, "extraire", lambda *args, **kwargs: SimpleNamespace(pages=[]))
    monkeypatch.setattr(cli, "ecrire_docx", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "creer_fournisseur_comprehension_texte_ai",
                        lambda **kwargs: roots.append(kwargs["model_root"]))
    assert cli.main([str(source), str(tmp_path / "out.docx")]) == 0
    assert roots == [None]


@pytest.mark.parametrize("opt_in", [False, True])
def test_local_understanding_needs_its_own_explicit_flag(monkeypatch, tmp_path, opt_in):
    source = tmp_path / "source.pdf"
    source.touch()
    calls = []
    monkeypatch.setattr(cli, "construire", lambda **kwargs: None)
    monkeypatch.setattr(cli, "dossiers_par_defaut", lambda: [])
    monkeypatch.setattr(cli, "extraire", lambda *args, **kwargs: SimpleNamespace(pages=[]))
    monkeypatch.setattr(cli, "ecrire_docx", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "creer_fournisseur_comprehension_texte_ai", lambda **kwargs: calls.append(kwargs))
    args = [str(source), str(tmp_path / "out.docx"), "--ai-models-root", str(tmp_path),
            "--text-understanding-url", "http://semantic.test/understand"]
    if opt_in:
        args.append("--experimental-local-text-understanding")
    assert cli.main(args) == 0
    assert calls[0]["experimental_local"] is opt_in
    assert calls[0]["url"] == "http://semantic.test/understand"
    assert calls[0]["timeout"] == 3.0


def test_common_root_does_not_activate_actual_local_factory(monkeypatch, tmp_path, capsys, caplog):
    import logging
    from pdfexact.layout import text_comprehension, text_comprehension_local
    source = tmp_path / "source.pdf"
    source.touch()
    (tmp_path / "model.bin").touch()
    monkeypatch.delenv("PDFEXACT_TEXT_UNDERSTANDING_URL", raising=False)
    monkeypatch.setattr(cli, "construire", lambda **kwargs: None)
    monkeypatch.setattr(cli, "dossiers_par_defaut", lambda: [])
    monkeypatch.setattr(cli, "extraire", lambda *args, **kwargs: SimpleNamespace(pages=[]))
    monkeypatch.setattr(cli, "ecrire_docx", lambda *args, **kwargs: None)

    def unexpected(*args, **kwargs):
        pytest.fail("A common OCR root must not initialize the experimental LLM")

    def unexpected_runtime(*args, **kwargs):
        pytest.fail("An empty IR must not import a local runtime or start a shadow worker")

    providers = []
    real_factory = cli.creer_fournisseur_comprehension_texte_ai

    def create(**kwargs):
        assert kwargs["model_root"] == tmp_path
        assert kwargs["experimental_local"] is False
        provider = real_factory(**kwargs)
        assert isinstance(provider, text_comprehension_local.LocalCPUShadowProvider)
        assert provider.diagnostics["status"] == "shadow-pending"
        assert provider.diagnostics["inference_invoked"] is False
        providers.append(provider)
        return provider

    monkeypatch.setattr(text_comprehension_local, "creer_fournisseur_comprehension_texte_local", unexpected)
    monkeypatch.setattr(text_comprehension_local, "_load_runtime", unexpected_runtime)
    monkeypatch.setattr(text_comprehension_local, "_executer_sonde_shadow_isolee", unexpected_runtime)
    monkeypatch.setattr(text_comprehension_local.subprocess, "Popen", unexpected_runtime)
    monkeypatch.setattr(cli, "creer_fournisseur_comprehension_texte_ai", create)
    with text_comprehension.contexte_comprehension_texte():
        caller = lambda *_args: None
        text_comprehension.configurer_fournisseur_comprehension_texte(caller)
        caller_state = text_comprehension._etat_analyse()
        with caplog.at_level(logging.INFO, logger="pdfexact.layout.text_comprehension"):
            assert cli.main([str(source), str(tmp_path / "out.docx"), "--ai-models-root", str(tmp_path), "--verbose"]) == 0
        assert text_comprehension._etat_analyse() is caller_state
        assert caller_state.provider is caller
    assert len(providers) == 1
    diagnostic = providers[0].diagnostics
    assert diagnostic["status"] == "shadow-not-attempted"
    assert diagnostic["reason"] == "no-eligible-source-input"
    assert diagnostic["runtime_attempt"] == "not-attempted"
    for field in ("inference_invoked", "first_token_observed", "load_started", "load_completed", "inference_completed"):
        assert diagnostic[field] is False
    assert diagnostic["generated_tokens"] == 0
    assert diagnostic["quality"] == "unqualified" and diagnostic["application"] == "not-applied"
    assert providers[0].history == [diagnostic]
    assert "shadow-pending" in capsys.readouterr().err
    assert "status=configured" in caplog.text
    assert "status=shadow-not-attempted" in caplog.text
    assert "no-eligible-source-input" in caplog.text
    assert "status=accepted" not in caplog.text
