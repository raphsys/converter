"""Groq decides comprehension; the local model is the fallback."""
import io
import json

from pdfexact.layout import groq
from pdfexact.layout.text_comprehension import TextUnderstandingDecision

LINES = ("Appendix A. Field Data Collection Forms", "Appendix B. HWM Location Maps")
CONTEXT = {"lines": [{"index": index, "text": text} for index, text in enumerate(LINES)]}


def answer(boundaries):
    content = json.dumps({"kind": "paragraph", "action": "segment-page", "confidence": 0.9,
                          "evidence": ["two entries"], "boundaries": boundaries})
    return io.BytesIO(json.dumps({"choices": [{"message": {"content": content}}]}).encode())


def test_groq_request_is_authenticated_deterministic_json_and_strictly_decoded():
    sent = {}

    def urlopen(request, timeout):
        sent.update(url=request.full_url, headers=dict(request.header_items()), body=json.loads(request.data))
        return answer(["break"])

    client = groq.GroqTexte("secret-key", model="test-model", urlopen=urlopen, min_interval=0)
    assert client("page-segmentation", LINES, "list", CONTEXT).line_groups == ((0,), (1,))
    assert sent["url"] == groq.GROQ_URL and sent["headers"]["Authorization"] == "Bearer secret-key"
    assert sent["body"]["model"] == "test-model" and sent["body"]["temperature"] == 0
    assert sent["body"]["response_format"] == {"type": "json_object"}
    assert "secret-key" not in json.dumps(client.diagnostics)


def test_invalid_groq_answer_is_no_decision():
    client = groq.GroqTexte("k", urlopen=lambda request, timeout: answer(["join", "join"]), min_interval=0)
    assert client("page-segmentation", LINES, None, CONTEXT) is None
    assert client.diagnostics["status"] == "invalid-response"


def decision(groups):
    return TextUnderstandingDecision("paragraph", "segment-page", 0.9, ("model",), line_groups=groups)


class Groq:
    def __init__(self, result):
        self.result, self.diagnostics = result, {"status": "accepted" if result else "provider-error"}

    def __call__(self, *args):
        return self.result


def test_groq_decides_and_the_local_model_is_not_asked():
    asked = []
    provider = groq.GroqPuisLocal(Groq(decision(((0,), (1,)))), lambda *args: asked.append(args))
    result = provider("page-segmentation", LINES, None, CONTEXT)
    assert result.line_groups == ((0,), (1,)) and "groq-decision" in result.evidence and asked == []


def test_local_model_decides_when_groq_cannot():
    provider = groq.GroqPuisLocal(Groq(None), lambda *args: decision(((0, 1),)))
    result = provider("page-segmentation", LINES, None, CONTEXT)
    assert result.line_groups == ((0, 1),) and "local-fallback" in result.evidence
    assert provider.history[-1]["status"] == "local-fallback"


def test_no_decision_when_neither_model_decides():
    assert groq.GroqPuisLocal(Groq(None), lambda *args: None)("page-segmentation", LINES, None, CONTEXT) is None


def test_no_key_means_no_groq(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert groq.creer_groq_texte() is None
