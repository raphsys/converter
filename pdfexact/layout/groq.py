"""Groq (OpenAI-compatible chat API): decides comprehension and reads images.

Groq decides first; the local Qwen model is the offline fallback. The key comes
from GROQ_API_KEY and is never written anywhere.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import replace
from time import monotonic, sleep
from urllib.request import Request, urlopen as _urlopen

from pdfexact.layout import text_comprehension_local as local

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODELE_TEXTE = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
MODELE_VISION = os.environ.get("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
# Free tier allows about 30 requests a minute: one spacing for text and images.
INTERVALLE_MIN_S = 2.1
_verrou = threading.Lock()
_dernier_appel = [0.0]


def cle() -> str | None:
    return os.environ.get("GROQ_API_KEY", "").strip() or None


def appeler(api_key, model, messages, *, json_mode=False, timeout=30.0, urlopen=None, min_interval=INTERVALLE_MIN_S) -> str:
    """One chat completion; returns the assistant text."""
    body = {"model": model, "messages": messages, "temperature": 0}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    request = Request(GROQ_URL, data=json.dumps(body).encode("utf-8"), method="POST",
                      headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
    with _verrou:
        attente = _dernier_appel[0] + min_interval - monotonic()
        if attente > 0:
            sleep(attente)
        _dernier_appel[0] = monotonic()
    with (urlopen or _urlopen)(request, timeout=timeout) as response:
        return json.loads(response.read())["choices"][0]["message"]["content"]


class GroqTexte:
    """Comprehension by Groq with the local conversation and strict decoder."""

    def __init__(self, api_key, *, model=None, urlopen=None, min_interval=INTERVALLE_MIN_S):
        self._api_key = api_key
        self.model = model or MODELE_TEXTE
        self._urlopen = urlopen
        self.min_interval = min_interval
        self.diagnostics = {"status": "ready", "provider": "groq", "model": self.model}

    def __call__(self, kind, lines, role, context):
        if kind not in local._ACTIONS or not lines:
            return None
        payload = local.LocalTextUnderstandingProvider._payload(kind, lines, role, context)
        try:
            content = appeler(self._api_key, self.model, local._messages(kind, payload), json_mode=True,
                              urlopen=self._urlopen, min_interval=self.min_interval)
        except Exception as exc:  # noqa: BLE001 - network or API error: no decision, recorded
            self.diagnostics = {"status": "provider-error", "provider": "groq", "reason": type(exc).__name__}
            return None
        try:
            decision = local._decoder_reponse_locale(content, kind, lines, context)
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            self.diagnostics = {"status": "invalid-response", "provider": "groq", "reason": str(exc)[:160]}
            return None
        if decision.action == "abstain" or decision.confidence < 0.5:
            self.diagnostics = {"status": "model-abstention", "provider": "groq"}
            return None
        self.diagnostics = {"status": "accepted", "provider": "groq", "model": self.model}
        return decision


class GroqPuisLocal:
    """Groq decides; the local model decides when Groq cannot; else no decision."""

    def __init__(self, groq, local_provider):
        self.groq = groq
        self.local = local_provider
        self._events = []
        self.warning_keys = getattr(local_provider, "warning_keys", set())

    @property
    def history(self):
        return [*getattr(self.local, "history", ()), *self._events]

    @property
    def diagnostics(self):
        return self.groq.diagnostics

    def __call__(self, kind, lines, role, context):
        decision = self.groq(kind, lines, role, context)
        if decision is not None:
            return replace(decision, evidence=(*decision.evidence, "groq-decision"))
        secours = self.local(kind, lines, role, context) if self.local is not None else None
        if secours is None:
            return None
        self._events.append({"status": "local-fallback", "kind": kind, "lines": len(lines),
                             "groq": self.groq.diagnostics.get("status")})
        return replace(secours, evidence=(*secours.evidence, "local-fallback"))


def creer_groq_texte():
    key = cle()
    return GroqTexte(key) if key else None
