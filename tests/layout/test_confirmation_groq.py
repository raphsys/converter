"""Groq confirms local comprehension decisions with the same strict contract."""
import io
import json

import pytest

from pdfexact.layout import confirmation_groq as groq
from pdfexact.layout import text_comprehension_local as local
from pdfexact.layout.text_comprehension import TextUnderstandingDecision

LINES = ("Appendix A. Field Data Collection Forms", "Appendix B. HWM Location Maps")
CONTEXT = {"lines": [{"index": index, "text": text} for index, text in enumerate(LINES)]}


def answer(boundaries):
    content = json.dumps({"kind": "paragraph", "action": "segment-page", "confidence": 0.9,
                          "evidence": ["two entries"], "boundaries": boundaries})
    return io.BytesIO(json.dumps({"choices": [{"message": {"content": content}}]}).encode())


def test_prompt_and_chat_messages_carry_the_same_contract():
    payload = local.LocalTextUnderstandingProvider._payload("page-segmentation", LINES, "list", {"lines": []})
    messages = local._messages("page-segmentation", payload)
    assert messages[0]["role"] == "system" and messages[-1]["role"] == "user"
    rebuilt = "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages) + "<|im_start|>assistant\n"
    assert local._prompt("page-segmentation", payload) == rebuilt


def test_groq_request_is_an_authenticated_deterministic_json_chat_and_is_decoded_strictly():
    sent = {}

    def urlopen(request, timeout):
        sent.update(url=request.full_url, headers=dict(request.header_items()), body=json.loads(request.data))
        return answer(["break"])

    confirm = groq.ConfirmationGroq("secret-key", model="test-model", urlopen=urlopen, min_interval=0)
    decision = confirm("page-segmentation", LINES, "list", CONTEXT)
    assert decision.line_groups == ((0,), (1,))
    assert sent["url"] == groq.GROQ_URL
    assert sent["headers"]["Authorization"] == "Bearer secret-key"
    assert sent["body"]["model"] == "test-model" and sent["body"]["temperature"] == 0
    assert sent["body"]["response_format"] == {"type": "json_object"}
    assert "secret-key" not in json.dumps(confirm.diagnostics)


def test_invalid_groq_answer_is_no_decision():
    confirm = groq.ConfirmationGroq("k", urlopen=lambda request, timeout: answer(["join", "join"]), min_interval=0)
    assert confirm("page-segmentation", LINES, None, CONTEXT) is None
    assert confirm.diagnostics["status"] == "invalid-response"


def decision(groups):
    return TextUnderstandingDecision("paragraph", "segment-page", 0.9, ("local",), line_groups=groups)


@pytest.mark.parametrize(("local_groups", "groq_groups", "mark"), [
    (((0,), (1,)), ((0,), (1,)), "groq-confirmed"),
    (((0, 1),), ((0,), (1,)), "groq-disagreed"),
])
def test_local_decision_is_kept_and_marked_confirmed_or_disagreed(local_groups, groq_groups, mark):
    wrapped = groq.FournisseurConfirme(lambda *args: decision(local_groups), lambda *args: decision(groq_groups))
    result = wrapped("page-segmentation", LINES, None, {})
    assert result.line_groups == local_groups and mark in result.evidence
    assert wrapped.history[-1]["status"] == mark


def test_groq_decides_when_the_local_model_does_not():
    wrapped = groq.FournisseurConfirme(lambda *args: None, lambda *args: decision(((0,), (1,))))
    result = wrapped("page-segmentation", LINES, None, {})
    assert result.line_groups == ((0,), (1,)) and "groq-decision" in result.evidence


def test_no_key_means_no_confirmation(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert groq.creer_confirmation_groq() is None
