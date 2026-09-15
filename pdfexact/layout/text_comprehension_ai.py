"""Provider IA optionnel pour la comprehension intra-bloc."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from pdfexact.layout.text_comprehension import TextUnderstandingDecision, TextUnderstandingProvider


def creer_fournisseur_comprehension_texte_ai(
    *,
    url: str | None = None,
    timeout: float = 3.0,
) -> TextUnderstandingProvider | None:
    endpoint = (url or os.environ.get("PDFEXACT_TEXT_UNDERSTANDING_URL") or "").strip()
    if not endpoint:
        return None

    def provider(
        kind: str,
        lignes: tuple[str, ...],
        frame_role: str | None,
        frame_strategy: str | None,
    ) -> TextUnderstandingDecision | None:
        payload = {
            "schema": "pdfexact.text_understanding.v1",
            "kind": kind,
            "lines": [{"i": index, "text": texte} for index, texte in enumerate(lignes)],
            "frame_role": frame_role,
            "frame_strategy": frame_strategy,
            "actions": [
                "candidate-paragraph-line",
                "merge-paragraph",
                "preserve-line",
                "preserve-lines",
            ],
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            endpoint,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                reponse = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, TimeoutError, json.JSONDecodeError):
            return None
        return _decision_depuis_json(reponse)

    return provider


def _decision_depuis_json(data: Any) -> TextUnderstandingDecision | None:
    if not isinstance(data, dict):
        return None
    action = str(data.get("action") or "")
    if action not in {
        "candidate-paragraph-line",
        "merge-paragraph",
        "preserve-line",
        "preserve-lines",
    }:
        return None
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        return None
    evidence_source = data.get("evidence", ())
    evidence = tuple(str(item) for item in evidence_source) if isinstance(evidence_source, list) else ()
    return TextUnderstandingDecision(
        kind=str(data.get("kind") or "ai"),
        action=action,
        confidence=confidence,
        evidence=evidence + ("ai-text-understanding",),
    )
