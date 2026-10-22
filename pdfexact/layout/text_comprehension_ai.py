"""HTTP takes precedence over an available offline CPU understanding bundle."""

from __future__ import annotations

import json
import os
from http.client import HTTPException
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from pdfexact.layout.text_comprehension import (
    TextUnderstandingContext,
    TextUnderstandingDecision,
    TextUnderstandingProvider,
    _raison_action_invalide,
    _raison_decision_invalide,
    _signaler_diagnostic,
)


def creer_fournisseur_comprehension_texte_ai(
    *,
    url: str | None = None,
    timeout: float = 3.0,
    model_root=None,
    local_timeout: float = 30.0,
) -> TextUnderstandingProvider | None:
    endpoint = (url or "").strip() or os.environ.get("PDFEXACT_TEXT_UNDERSTANDING_URL", "").strip()
    if not endpoint:
        # Comprehension is mandatory: the local model's decisions are applied.
        from pdfexact.layout import text_comprehension_local as local

        return local.creer_fournisseur_comprehension_texte_local(model_root=model_root, timeout=local_timeout)

    def refuse(status, kind, lines, reason, context):
        provider.diagnostics = {"status": status, "reason": reason}
        if provider.diagnostics not in provider.history:
            provider.history.append(dict(provider.diagnostics))
        _signaler_diagnostic(status, kind, lines, reason, contexte=context)
        return None

    def provider(
        kind: str,
        lignes: tuple[str, ...],
        frame_role: str | None,
        frame_strategy: TextUnderstandingContext,
    ) -> TextUnderstandingDecision | None:
        payload = {
            "schema": "pdfexact.text_understanding.v1",
            "kind": kind,
            "lines": [{"i": index, "text": texte} for index, texte in enumerate(lignes)],
            "frame_role": frame_role,
            "frame_strategy": frame_strategy,
            "metadata": frame_strategy if isinstance(frame_strategy, (dict, list)) else None,
            "actions": [
                "segment-page",
                "candidate-paragraph-line",
                "merge-paragraph",
                "preserve-line",
                "preserve-lines",
                "paragraph-reflow",
                "abstain",
            ],
            "line_join_values": [
                "space",
                "no_space",
                "hyphen_join",
                "preserve_break",
                "paragraph_break",
            ],
        }
        try:
            data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            request = Request(
                endpoint,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=timeout) as response:
                raw_response = response.read()
        except (OSError, URLError, TimeoutError, HTTPException, ValueError, TypeError) as exc:
            return refuse(
                "provider-error", kind, lignes, f"endpoint={endpoint}: {type(exc).__name__}: {exc}",
                frame_strategy,
            )
        try:
            decision = _decision_depuis_json(_charger_json_strict(raw_response.decode("utf-8")))
        except (ValueError, UnicodeError) as exc:
            return refuse(
                "invalid-response", kind, lignes, f"endpoint={endpoint}: {type(exc).__name__}: {exc}",
                frame_strategy,
            )
        if decision.action == "abstain":
            return refuse("model-abstention", kind, lignes, "; ".join(decision.evidence), frame_strategy)
        if decision.confidence < 0.50:
            return refuse(
                "low-confidence", kind, lignes,
                f"endpoint={endpoint}: confidence={decision.confidence:.3f} below 0.50",
                frame_strategy,
            )
        reason = _raison_action_invalide(decision, kind, len(lignes))
        if reason is not None:
            return refuse(
                "invalid-response", kind, lignes, f"endpoint={endpoint}: {reason}",
                frame_strategy,
            )
        provider.diagnostics = {}
        return decision

    provider.diagnostics = {}
    provider.history = []
    return provider






def _unique_keys(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate-json-key:{key}")
        result[key] = value
    return result


def _charger_json_strict(raw):
    def invalid_constant(value):
        raise ValueError(f"invalid-json-constant:{value}")

    return json.loads(raw, object_pairs_hook=_unique_keys, parse_constant=invalid_constant)


def _decision_depuis_json(data: Any) -> TextUnderstandingDecision:
    if not isinstance(data, dict):
        raise ValueError("response must be a JSON object")
    if data.get("action") == "abstain":
        if set(data) != {"kind", "action", "confidence", "evidence"} or data["kind"] != "unknown":
            raise ValueError("explicit-abstention requires exactly kind/action/confidence/evidence and kind=unknown")
        confidence, evidence = data["confidence"], data["evidence"]
        if (type(confidence) not in (int, float) or not 0 <= confidence <= 1
                or not isinstance(evidence, list) or not 1 <= len(evidence) <= 8
                or not all(isinstance(reason, str) and reason.strip() and len(reason) <= 256 for reason in evidence)):
            raise ValueError("invalid-explicit-abstention-confidence/evidence")
        return TextUnderstandingDecision("unknown", "abstain", float(confidence), tuple(evidence))
    if set(data) - {"kind", "action", "confidence", "evidence", "line_joins", "joins", "line_groups", "groups"}:
        raise ValueError("response contains unsupported fields or rewritten text")
    joins_source = data.get("line_joins", data.get("joins", []))
    if not isinstance(joins_source, list):
        raise ValueError("line_joins must be a JSON array")
    joins = tuple(joins_source)
    action = data.get("action") or ("paragraph-reflow" if joins else "")
    confidence_source = data.get("confidence", 0.0)
    if isinstance(confidence_source, bool):
        raise ValueError("confidence must be numeric, not boolean")
    try:
        confidence = float(confidence_source)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("confidence must be numeric") from exc
    evidence_source = data.get("evidence", [])
    if not isinstance(evidence_source, list) or not all(isinstance(item, str) for item in evidence_source):
        raise ValueError("evidence must be a JSON array of strings")
    groups_source = data.get("line_groups", data.get("groups", []))
    if not isinstance(groups_source, list) or not all(
        isinstance(group, list) and group and all(type(index) is int for index in group)
        for group in groups_source
    ):
        raise ValueError("line_groups must contain nonempty JSON arrays of integer indices")
    decision = TextUnderstandingDecision(
        kind=data.get("kind") or "ai",
        action=action,
        confidence=confidence,
        evidence=tuple(evidence_source) + ("ai-text-understanding",),
        line_joins=joins,
        ai_used=True,
        fallback_used=False,
        line_groups=tuple(tuple(group) for group in groups_source),
    )
    reason = _raison_decision_invalide(decision)
    if reason is not None:
        raise ValueError(reason)
    return decision
