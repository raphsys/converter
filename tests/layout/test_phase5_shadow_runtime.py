"""Strict decoding and synthetic runtime observations, without model execution."""

from copy import deepcopy
import io
import json
from types import SimpleNamespace

import pytest

from pdfexact.layout import text_comprehension as comprehension
from pdfexact.layout import text_comprehension_ai as ai
from pdfexact.layout import text_comprehension_local as local


ABSTENTION = {"kind": "unknown", "action": "abstain", "confidence": 0.0,
              "evidence": ["Source context does not establish a boundary."]}


@pytest.mark.parametrize("kind", ["line", "group", "page-segmentation", "paragraph-reflow"])
def test_explicit_abstention_is_distinct_and_preserves_raw_evidence(kind):
    original = deepcopy(ABSTENTION)
    decision = local._decoder_reponse_locale(json.dumps(original), kind, ("first", "second"), None)
    assert decision.kind == "unknown" and decision.action == "abstain"
    assert decision.evidence == tuple(original["evidence"])
    assert not decision.ai_used and decision.fallback_used
    assert original == ABSTENTION


@pytest.mark.parametrize("change", [
    {"kind": "paragraph"}, {"line_groups": []}, {"line_joins": []}, {"text": "rewritten"},
    {"confidence": True}, {"confidence": "0"}, {"confidence": float("inf")},
    {"confidence": -0.1}, {"confidence": 1.1}, {"evidence": []}, {"evidence": [""]},
    {"evidence": [" "]}, {"evidence": ["x" * 257]}, {"evidence": ["reason"] * 9},
])
def test_abstention_requires_exact_fields_finite_number_and_bounded_nonempty_reasons(change):
    with pytest.raises(ValueError):
        ai._decision_depuis_json({**ABSTENTION, **change})


@pytest.mark.parametrize("raw", [
    '{"kind":"unknown","action":"abstain","confidence":0,"evidence":["reason"],"action":"abstain"}',
    '{"kind":"unknown","action":"abstain","confidence":NaN,"evidence":["reason"]}',
    '```json\n{"kind":"unknown","action":"abstain","confidence":0,"evidence":["reason"]}\n```',
    '{"kind":"unknown","action":"abstain","confidence":0,"evidence":["reason"]',
    '{} {}',
])
def test_strict_json_has_no_duplicate_keys_fences_or_repair(raw):
    with pytest.raises(ValueError):
        ai._decision_depuis_json(ai._charger_json_strict(raw))


@pytest.mark.parametrize("raw,status", [
    (json.dumps(ABSTENTION), "model-abstention"),
    ('{"action":"preserve-line","confidence":0.8,"confidence":0.99}', "invalid-response"),
])
def test_http_uses_strict_decoder_and_honest_abstention(monkeypatch, caplog, raw, status):
    def response(request, **_kwargs):
        assert "abstain" in json.loads(request.data)["actions"]
        return io.BytesIO(raw.encode())

    monkeypatch.setattr(ai, "urlopen", response)
    with comprehension.contexte_comprehension_texte():
        provider = ai.creer_fournisseur_comprehension_texte_ai(url="http://synthetic.test")
        comprehension.configurer_fournisseur_comprehension_texte(provider)
        result = comprehension.comprendre_ligne_texte("source prose", frame_role="text-column")
        assert not result.ai_used and result.fallback_used
        assert provider.diagnostics["status"] == status
    assert f"status={status}" in caplog.text
    assert "status=empty-response" not in caplog.text


@pytest.mark.parametrize("kind", ["group", "paragraph-reflow", "page-segmentation"])
def test_blank_lines_and_sparse_source_indices_remain_aligned(kind):
    lines = ("  \u4e2d\u6587\n", " \t ", "suite  ")
    original = {"page_index": 7, "lines": [
        {"index": index, "text": text, "source_ids": [f"source-{index}"],
         "blank_separator_before": index == 19}
        for index, text in zip((7, 11, 19), lines)
    ]}
    before = deepcopy(original)
    context = comprehension.contexte_lignes_texte(original["lines"], metadonnees=original)
    assert [row["index"] for row in context["lines"]] == [0, 1, 2]
    assert [row["source_index"] for row in context["lines"]] == [7, 11, 19]
    seen = []
    with comprehension.contexte_comprehension_texte():
        comprehension.configurer_fournisseur_comprehension_texte(
            lambda request_kind, texts, _role, metadata: seen.append((request_kind, texts, metadata)))
        if kind == "page-segmentation":
            comprehension.comprendre_segmentation_page(lines, metadonnees=context)
        else:
            wrapper = (comprehension.comprendre_groupe_lignes if kind == "group"
                       else comprehension.comprendre_reflow_paragraphe)
            wrapper(lines, frame_role="text-column", metadonnees=context)
    assert seen == [(kind, lines, context)]
    seen[0][2]["lines"][0]["source_ids"].append("mutated")
    assert original == before and context["lines"][0]["source_ids"] == ["source-7"]


@pytest.fixture
def synthetic_runtime(monkeypatch, tmp_path):
    state = SimpleNamespace(raw=json.dumps(ABSTENTION), loads=0, calls=0, failure=None, token=True)
    tokenizer = SimpleNamespace(
        encode=lambda *_args, **_kwargs: SimpleNamespace(tokens=["input"] * 3),
        token_to_id=lambda _token: 0, decode=lambda *_args, **_kwargs: state.raw,
    )

    class Generator:
        def __init__(self, *_args, **_kwargs):
            state.loads += 1
            if state.failure == "load":
                raise RuntimeError("synthetic load failure")

        def generate_batch(self, *_args, **kwargs):
            state.calls += 1
            if state.failure == "before-first-token":
                raise RuntimeError("synthetic runtime failure")
            if state.token:
                kwargs["callback"](SimpleNamespace(token="output"))
            return [SimpleNamespace(sequences=[["output"]])]

    monkeypatch.setattr(local, "_load_runtime", lambda: SimpleNamespace(Generator=Generator))
    monkeypatch.setattr(local, "_inspect_bundle", lambda *_args: tokenizer)
    monkeypatch.setattr(local, "_memory_preflight", lambda _path: {"synthetic": True})
    payload = {"model_path": str(tmp_path), "kind": "group", "frame_role": "text-column",
               "lines": [{"i": 0, "text": "A complete source sentence"},
                         {"i": 1, "text": "continues without a break."}],
               "metadata": None, "max_input_tokens": 10, "max_output_tokens": 32}
    return state, payload












def test_projection_uses_known_owner_frame_but_never_owner_or_sibling_ids():
    font = SimpleNamespace(famille="SourceFont", gras=False, italique=False, font_bytes=b"not JSON")
    span = SimpleNamespace(texte="  Exact Unicode \u4e2d\u6587  ", police=font, size_pt=10, couleur="123456")
    line = SimpleNamespace(spans=[span], source_ids=("line-only",), layout_frame_id=None,
                           layout_frame_role=None, semantic_role=None, bbox=None)
    owner = SimpleNamespace(lignes=[line], source_ids=("parent", "sibling"),
                            layout_frame_id="known-frame", layout_frame_role="text-column",
                            semantic_role="body", presentation={"page_index": 7})
    context = comprehension.contexte_lignes_texte(owner)
    row = context["lines"][0]
    assert row["source_ids"] == ["line-only"]
    assert row["layout_frame_id"] == "known-frame" and row["semantic_role"] == "body"
    assert row["bbox"] is None and row["orientation"] is None
    assert row["text"] == span.texte and context["page_index"] == 7
    assert "font_bytes" not in json.dumps(context)


def test_inline_bold_or_italic_word_does_not_create_a_paragraph_boundary():
    bbox_a = SimpleNamespace(x0=100, y0=200, x1=800, y1=300)
    bbox_b = SimpleNamespace(x0=100, y0=310, x1=800, y1=410)

    def span(text, bold=False, italic=False):
        return SimpleNamespace(texte=text, size_pt=10, couleur="000000", police=SimpleNamespace(
            famille="Arial", gras=bold, italique=italic))

    first = SimpleNamespace(spans=[span("The system "), span("carefully", bold=True),
                                  span(" validates the "), span("complete", italic=True), span(" input")], bbox=bbox_a)
    second = SimpleNamespace(spans=[span("before storing the results.")], bbox=bbox_b)
    context = comprehension.contexte_lignes_texte([first, second])
    lines = tuple(row["text"] for row in context["lines"])
    decision = comprehension.TextUnderstandingDecision("paragraph", "paragraph-reflow", 0.99, line_joins=("space",))
    assert comprehension.source_decision_conflict(decision, "paragraph-reflow", lines, context=context) is None
    assert not context["lines"][0]["dominant_style"]["bold"]


def test_canonical_record_projects_text_style_and_context_without_raw_records():
    from pdfexact.geometry import BBox
    from pdfexact.scene import ElementKind, ElementRecord, SourceKind

    record = ElementRecord("record", 7, ElementKind.TEXT, BBox(100, 200, 800, 300), SourceKind.PDF_NATIVE,
                           source_ids=("source-record",), text="  Exact \u4e2d\u6587\n", role="body",
                           angle_deg=12.0, orientation="oblique-up",
                           style={"font_family": "SourceFont", "size_pt": 10, "bold": True,
                                  "font_bytes": b"excluded", "runs": [{"raw": b"excluded"}]},
                           attributes={"layout_frame_id": "known-frame", "boundary_before": "paragraph-break",
                                       "source_metadata": {"huge-record": b"excluded"},
                                       "neighbors": [{"text": "real neighbor"}]})
    before = deepcopy(record)
    context = comprehension.contexte_lignes_texte(record)
    row = context["lines"][0]
    assert row["text"] == record.text and row["semantic_role"] == "body"
    assert row["bbox"] == [100, 200, 800, 300] and row["angle_deg"] == 12.0
    assert row["layout_frame_id"] == "known-frame" and row["boundary_before"] == "paragraph-break"
    assert context["neighbors"] == [{"text": "real neighbor"}]
    serialized = json.dumps(context, allow_nan=False)
    assert "font_bytes" not in serialized and "huge-record" not in serialized and "runs" not in serialized
    assert record == before


def test_page_conflict_fallback_is_distinct_from_model_acceptance_and_abstention(caplog):
    lines = ("Known Heading", "A following body sentence continues.")
    context = {"lines": [{"text": lines[0], "semantic_role": "heading"},
                         {"text": lines[1], "semantic_role": "body"}]}
    with comprehension.contexte_comprehension_texte():
        comprehension.configurer_fournisseur_comprehension_texte(lambda *_args:
            comprehension.TextUnderstandingDecision("paragraph", "segment-page", 0.99, line_groups=((0, 1),)))
        result = comprehension.comprendre_segmentation_page(lines, metadonnees=context)
        assert result.line_groups == ((0,), (1,))
        assert result.fallback_used and not result.ai_used
        assert "source-conflict" in result.evidence
        assert "status=accepted" not in caplog.text
        comprehension.configurer_fournisseur_comprehension_texte(lambda *_args: None)
        assert comprehension.comprendre_segmentation_page(lines, metadonnees=context) is None


@pytest.mark.parametrize("owner_page,line_page,explicit,expected", [
    (7, None, {}, 7), (None, 9, {}, 9), (0, None, {}, 0),
    (None, None, {}, None), (7, 9, {"page_index": 11}, 11),
])
def test_projection_preserves_only_known_source_page_indices(owner_page, line_page, explicit, expected):
    line = SimpleNamespace(spans=[], text="Exact source text", source_page_index=line_page)
    owner = SimpleNamespace(lignes=[line], source_page_index=owner_page)
    context = comprehension.contexte_lignes_texte(owner, metadonnees=explicit)
    assert context["page_index"] == expected
    assert context["lines"][0]["text"] == "Exact source text"
