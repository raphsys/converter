"""Without an endpoint, comprehension uses the local model and applies its decisions."""
from pdfexact.layout import text_comprehension_ai as ai
from pdfexact.layout import text_comprehension_local as local


def test_default_provider_is_the_applied_local_model(monkeypatch):
    monkeypatch.delenv("PDFEXACT_TEXT_UNDERSTANDING_URL", raising=False)
    sentinel = object()
    calls = {}

    def applied(**kwargs):
        calls.update(kwargs)
        return sentinel

    monkeypatch.setattr(local, "creer_fournisseur_comprehension_texte_local", applied)
    assert ai.creer_fournisseur_comprehension_texte_ai(model_root="models") is sentinel
    assert calls["model_root"] == "models"


def test_local_generator_uses_every_cpu_core(monkeypatch):
    monkeypatch.setattr(local.os, "cpu_count", lambda: 8)
    assert local._cpu_threads() == 8
    monkeypatch.setattr(local.os, "cpu_count", lambda: None)
    assert local._cpu_threads() >= 1


def test_groq_key_makes_groq_decide_with_the_local_model_as_fallback(monkeypatch):
    from pdfexact.layout import groq as groq_module

    monkeypatch.delenv("PDFEXACT_TEXT_UNDERSTANDING_URL", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    sentinel = object()
    monkeypatch.setattr(local, "creer_fournisseur_comprehension_texte_local", lambda **kwargs: sentinel)
    provider = ai.creer_fournisseur_comprehension_texte_ai()
    assert isinstance(provider, groq_module.GroqPuisLocal) and provider.local is sentinel


def test_tests_never_see_a_real_groq_key():
    import os

    assert "GROQ_API_KEY" not in os.environ
