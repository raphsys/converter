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
