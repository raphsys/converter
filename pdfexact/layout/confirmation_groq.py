"""Groq confirmation of comprehension decisions (OpenAI-compatible chat API).

Groq receives the same conversation and is decoded by the same strict decoder
as the local model. The local decision is kept and marked confirmed or
disagreed; when the local model gives no decision, Groq's decision applies.
The API key is read from GROQ_API_KEY and never written anywhere.
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
MODELE_DEFAUT = "llama-3.3-70b-versatile"
# Free tier allows about 30 requests a minute: keep a margin between calls.
INTERVALLE_MIN_S = 2.1


class ConfirmationGroq:
    def __init__(self, api_key, *, model=None, timeout=20.0, min_interval=INTERVALLE_MIN_S, urlopen=None):
        self._api_key = api_key
        self.model = model or os.environ.get("GROQ_MODEL", MODELE_DEFAUT)
        self.timeout = float(timeout)
        self.min_interval = float(min_interval)
        self._urlopen = urlopen or _urlopen
        self._dernier = 0.0
        self._lock = threading.Lock()
        self.diagnostics = {"status": "ready", "provider": "groq", "model": self.model}

    def __call__(self, kind, lines, role, context):
        if kind not in local._ACTIONS or not lines:
            return None
        payload = local.LocalTextUnderstandingProvider._payload(kind, lines, role, context)
        body = json.dumps({"model": self.model, "messages": local._messages(kind, payload), "temperature": 0,
                           "response_format": {"type": "json_object"}}).encode("utf-8")
        request = Request(GROQ_URL, data=body, method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {self._api_key}"})
        try:
            with self._lock:
                attente = self._dernier + self.min_interval - monotonic()
                if attente > 0:
                    sleep(attente)
                self._dernier = monotonic()
            with self._urlopen(request, timeout=self.timeout) as response:
                content = json.loads(response.read())["choices"][0]["message"]["content"]
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


def _meme_decision(left, right) -> bool:
    return (left.action, tuple(left.line_groups), tuple(left.line_joins)) == (
        right.action, tuple(right.line_groups), tuple(right.line_joins))


class FournisseurConfirme:
    """Local decision confirmed by Groq; Groq decides when the local model cannot."""

    def __init__(self, local_provider, confirmation):
        self.local = local_provider
        self.confirmation = confirmation
        self._events = []
        self.warning_keys = getattr(local_provider, "warning_keys", set())

    @property
    def history(self):
        return [*getattr(self.local, "history", ()), *self._events]

    @property
    def diagnostics(self):
        return getattr(self.local, "diagnostics", None) or getattr(self.confirmation, "diagnostics", {})

    def __call__(self, kind, lines, role, context):
        decision = self.local(kind, lines, role, context) if self.local is not None else None
        other = self.confirmation(kind, lines, role, context)
        if decision is None:
            if other is None:
                return None
            self._events.append({"status": "groq-decision", "kind": kind, "lines": len(lines)})
            return replace(other, evidence=(*other.evidence, "groq-decision"))
        if other is None:
            self._events.append({"status": "groq-unconfirmed", "kind": kind, "lines": len(lines)})
            return replace(decision, evidence=(*decision.evidence, "groq-unconfirmed"))
        mark = "groq-confirmed" if _meme_decision(decision, other) else "groq-disagreed"
        event = {"status": mark, "kind": kind, "lines": len(lines)}
        if mark == "groq-disagreed":
            event.update(local=[list(group) for group in decision.line_groups] or list(decision.line_joins),
                         groq=[list(group) for group in other.line_groups] or list(other.line_joins))
        self._events.append(event)
        return replace(decision, evidence=(*decision.evidence, mark))


def creer_confirmation_groq():
    key = os.environ.get("GROQ_API_KEY", "").strip()
    return ConfirmationGroq(key) if key else None
