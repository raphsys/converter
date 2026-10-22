"""Phase 5 contract regressions; synthetic providers, never real inference."""

from copy import deepcopy
import json
import logging

import pytest

from pdfexact.analysis import semantic, text_segmentation
from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.ir import FontRef, ImageEl, Line, Span, TextBox
from pdfexact.layout import text_comprehension as comprehension
from pdfexact.layout import text_comprehension_ai as ai
from pdfexact.layout import text_comprehension_local as local
from pdfexact.layout.paragraph_planner import planifier_paragraphe


@pytest.fixture(autouse=True)
def isolated_analysis(monkeypatch, tmp_path):
    monkeypatch.delenv("PDFEXACT_TEXT_UNDERSTANDING_URL", raising=False)
    monkeypatch.setenv("PDFEXACT_TEXT_UNDERSTANDING_MODEL_ROOT", str(tmp_path / "absent"))
    monkeypatch.setattr(local, "_load_runtime", lambda: pytest.fail("real runtime forbidden"))
    with comprehension.contexte_comprehension_texte():
        comprehension.configurer_fournisseur_comprehension_texte(None)
        yield


def _unit(text, source_id, *, x=20, y=30, size=10, role="body", bold=False):
    bbox = BBox(u(x), u(y), u(x + 180), u(y + 10))
    source_ids = (source_id, source_id + ":span")
    font = FontRef("fixture-font", "Arial", bold, False)
    span = Span(text, font, size, "123456", bbox=bbox, source_id=source_ids[1])
    line = Line(
        bbox, [span], bbox.hauteur, bbox.largeur,
        source_id=source_id, source_ids=source_ids, semantic_role=role,
        layout_frame_id="fixture-frame", layout_frame_role="text-column",
        layout_frame_strategy="word-text",
    )
    return TextBox(
        bbox, [line], source_id=source_id, source_ids=source_ids,
        layout_frame_id="fixture-frame", layout_frame_role="text-column",
        layout_frame_strategy="word-text", semantic_role=role,
        script="latin", language="en", attributes={"script": "latin", "language": "en"},
        presentation={"page_index": 7, "segmentation_owner": "fixture-owner",
                      "source_spacing_before_emu": 0, "blank_separator_before": False},
    )


def _pair(boundary=None):
    first = _unit("The system validates incoming data", "source-first")
    second = _unit("before storing the complete results.", "source-second", y=41)
    if boundary == "style":
        second.lignes[0].spans[0].size_pt = 14
    elif boundary == "indent":
        first.lignes[0].spans[0].texte = "The first operation is complete."
        second = _unit("The next operation starts here.", "source-second", x=40, y=41)
    elif boundary == "title":
        first.semantic_role = first.lignes[0].semantic_role = "heading"
    return first, second


def _texts(units):
    return tuple("".join(span.texte for span in unit.lignes[0].spans) for unit in units)


def _bbox_values(bbox):
    return [bbox.x0, bbox.y0, bbox.x1, bbox.y1]


def _row(unit, index):
    line = unit.lignes[0]
    return {
        "index": index, "text": _texts((unit,))[0], "bbox": _bbox_values(line.bbox),
        "source_ids": list(line.source_ids), "layout_frame_id": line.layout_frame_id,
        "layout_role": line.layout_frame_role, "semantic_role": line.semantic_role,
        "orientation": line.orientation,
        "styles": [{"font": span.police.famille, "size_pt": span.size_pt,
                    "bold": span.police.gras, "italic": span.police.italique,
                    "color": span.couleur} for span in line.spans],
        "spacing_before_emu": unit.presentation.get("source_spacing_before_emu", 0),
        "blank_separator_before": unit.presentation.get("blank_separator_before", False),
    }


def _metadata(units):
    return {
        "page_index": 7, "frame_strategy": "word-text",
        "coordinate_system": {"origin": "top-left", "units": "EMU"},
        "lines": [_row(unit, index) for index, unit in enumerate(units)],
        "neighbors": [{"source_ids": ["source-neighbor"], "semantic_role": "caption",
                       "text": "Nearby source note", "bbox": [u(220), u(30), u(280), u(40)]}],
        "obstacles": [[u(220), u(50), u(280), u(70)]],
    }


def _request(kind, texts, metadata):
    if kind == "page-segmentation":
        return comprehension.comprendre_segmentation_page(texts, metadonnees=metadata)
    if kind == "line":
        return comprehension.comprendre_ligne_texte(
            texts[0], frame_role="text-column", frame_strategy="word-text", metadonnees=metadata,
        )
    function = {
        "group": comprehension.comprendre_groupe_lignes,
        "paragraph-reflow": comprehension.comprendre_reflow_paragraphe,
    }[kind]
    return function(texts, frame_role="text-column", frame_strategy="word-text", metadonnees=metadata)


def _json_decision(kind, count):
    data = {"kind": "paragraph", "confidence": 0.99, "evidence": ["model claims continuity"]}
    if kind == "page-segmentation":
        data.update(action="segment-page", line_groups=[list(range(count))])
    elif kind == "paragraph-reflow":
        data.update(action="paragraph-reflow", line_joins=["space"] * (count - 1))
    else:
        data.update(action="merge-paragraph")
    return ai._decision_depuis_json(json.loads(json.dumps(data)))


@pytest.mark.parametrize("kind", ["page-segmentation", "line", "group", "paragraph-reflow"])
def test_same_per_line_and_surrounding_context_reaches_every_provider(kind):
    units = _pair()[:1] if kind == "line" else _pair()
    metadata = _metadata(units)
    before = deepcopy((units, metadata))
    seen = []

    def provider(request_kind, lines, role, context):
        seen.append((request_kind, lines, role, deepcopy(context)))
        return None

    comprehension.configurer_fournisseur_comprehension_texte(provider)
    _request(kind, _texts(units), metadata)
    assert len(seen) == 1
    assert seen[0][0:2] == (kind, _texts(units))
    assert seen[0][3] == metadata
    assert (units, metadata) == before


@pytest.mark.parametrize("kind", ["page-segmentation", "line", "group", "paragraph-reflow"])
def test_provider_cannot_mutate_callers_context_or_source_coordinates(kind):
    units = _pair()[:1] if kind == "line" else _pair()
    metadata = _metadata(units)
    before = deepcopy((units, metadata))

    def provider(_kind, _lines, _role, context):
        context["lines"][0]["source_ids"].append("invented-by-provider")
        context["lines"][0]["bbox"][0] = -1
        context["neighbors"].clear()
        return None

    comprehension.configurer_fournisseur_comprehension_texte(provider)
    _request(kind, _texts(units), metadata)
    assert (units, metadata) == before


def test_page_projection_includes_actual_per_line_semantic_roles_and_obstacles():
    units = _pair("title")
    obstacle = BBox(u(220), u(50), u(280), u(70))
    before = deepcopy(units)
    seen = []
    comprehension.configurer_fournisseur_comprehension_texte(
        lambda _kind, _lines, _role, context: seen.append(deepcopy(context))
    )
    assert text_segmentation._groupes_ia_local(units, (obstacle,)) is None
    assert units == before
    assert seen[0]["coordinate_system"] == {"origin": "top-left", "units": "EMU"}
    assert seen[0]["obstacles"] == [_bbox_values(obstacle)]
    for index, unit in enumerate(units):
        for key, value in _row(unit, index).items():
            assert seen[0]["lines"][index][key] == value


def test_semantic_group_projects_source_lines_instead_of_only_strategy_string():
    units = _pair()
    units[0].lignes[0].spans[0].texte = "  The system validates incoming data  "
    before = deepcopy(units)
    seen = []
    comprehension.configurer_fournisseur_comprehension_texte(
        lambda kind, lines, _role, context: seen.append((kind, lines, deepcopy(context)))
    )
    semantic.est_frontiere_de_paragraphe(*units)
    assert units == before
    assert len(seen) == 1 and seen[0][0] == "group"
    assert isinstance(seen[0][2], dict), "geometry/styles/roles/source IDs are missing"
    for index, unit in enumerate(units):
        for key in ("bbox", "styles", "semantic_role", "source_ids"):
            assert seen[0][2]["lines"][index][key] == _row(unit, index)[key]
    assert seen[0][1] == _texts(units), "provider must receive verbatim source text"


def test_paragraph_planner_projects_each_line_not_parent_or_sibling_source_ids():
    units = _pair()
    block = deepcopy(units[0])
    block.lignes = [unit.lignes[0] for unit in units]
    block.bbox = BBox(block.bbox.x0, block.bbox.y0, units[-1].bbox.x1, units[-1].bbox.y1)
    block.source_ids = ("source-parent",)
    before = deepcopy(block)
    seen = []
    comprehension.configurer_fournisseur_comprehension_texte(
        lambda kind, lines, _role, context: seen.append((kind, lines, deepcopy(context)))
    )
    planifier_paragraphe(block)
    assert block == before
    assert len(seen) == 1 and seen[0][0] == "paragraph-reflow"
    assert isinstance(seen[0][2], dict), "reflow must have per-line context"
    for index, unit in enumerate(units):
        for key in ("bbox", "styles", "semantic_role", "source_ids"):
            assert seen[0][2]["lines"][index][key] == _row(unit, index)[key]


@pytest.mark.parametrize("boundary", ["style", "indent", "title"])
def test_ai_confirmed_cannot_bypass_an_existing_page_boundary(boundary):
    units = _pair(boundary)
    before = deepcopy(units)
    expected = text_segmentation._boundary(*units, u(11), (), ai_confirmed=False)
    assert expected is not None, "fixture must establish a real non-AI boundary"
    assert text_segmentation._boundary(*units, u(11), (), ai_confirmed=True) == expected
    assert units == before


@pytest.mark.parametrize("boundary", ["style", "indent", "title"])
def test_json_valid_page_merge_cannot_erase_source_boundary(boundary):
    units = _pair(boundary)
    before = deepcopy([(unit.bbox, unit.source_ids, unit.lignes) for unit in units])
    calls = []

    def provider(kind, lines, _role, _context):
        calls.append(kind)
        return _json_decision(kind, len(lines))

    comprehension.configurer_fournisseur_comprehension_texte(provider)
    groups = text_segmentation._groupes_ia_local(units)
    assert calls == ["page-segmentation"]
    assert [(unit.bbox, unit.source_ids, unit.lignes) for unit in units] == before
    assert [len(group) for group in groups] == [1, 1]


@pytest.mark.parametrize("boundary", ["style", "title"])
def test_json_valid_group_merge_cannot_bypass_style_or_title_checks(boundary):
    units = _pair(boundary)
    assert semantic.est_frontiere_de_paragraphe(*units), "baseline boundary must already exist"
    before = deepcopy(units)
    calls = []

    def provider(kind, lines, _role, _context):
        calls.append(kind)
        return _json_decision(kind, len(lines))

    comprehension.configurer_fournisseur_comprehension_texte(provider)
    assert semantic.est_frontiere_de_paragraphe(*units)
    assert units == before
    assert calls in ([], ["group"])


@pytest.mark.parametrize("boundary", ["style", "indent", "title"])
def test_reflow_join_cannot_flatten_a_per_line_hard_boundary(boundary):
    units = _pair(boundary)
    block = deepcopy(units[0])
    block.semantic_role = "body"
    block.lignes = [unit.lignes[0] for unit in units]
    block.bbox = BBox(min(unit.bbox.x0 for unit in units), units[0].bbox.y0,
                      max(unit.bbox.x1 for unit in units), units[-1].bbox.y1)
    before = deepcopy(block)
    calls = []

    def provider(kind, lines, _role, _context):
        calls.append(kind)
        return _json_decision(kind, len(lines))

    comprehension.configurer_fournisseur_comprehension_texte(provider)
    plan = planifier_paragraphe(block)
    assert calls in ([], ["paragraph-reflow"])
    assert block == before
    assert plan.action_between(0) in {"preserve_break", "paragraph_break"}


def test_distinct_ai_failures_remain_visible_after_first_warning(caplog):
    outcomes = iter((RuntimeError("CPU service failed"), None,
                     comprehension.TextUnderstandingDecision("ai", "unknown", 0.99)))
    calls = []

    def provider(kind, _lines, _role, _context):
        calls.append(kind)
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    comprehension.configurer_fournisseur_comprehension_texte(provider)
    for _ in range(3):
        assert comprehension.comprendre_segmentation_page(_texts(_pair())) is None
    assert calls == ["page-segmentation"] * 3
    for status in ("provider-error", "empty-response", "invalid-response"):
        assert f"status={status}" in caplog.text


@pytest.mark.parametrize("status,reason", [
    ("experimental-disabled", "local-quality-unqualified"),
    ("invalid-response", "invalid-boundaries:expected N-1 choices"),
    ("low-confidence", "model-confidence-not-calibrated"),
])
def test_provider_abstention_reason_is_not_replaced_by_empty_response(caplog, status, reason):
    class Provider:
        diagnostics = {"status": status, "reason": reason}

        def __call__(self, *_args):
            return None

    comprehension.configurer_fournisseur_comprehension_texte(Provider())
    assert comprehension.comprendre_segmentation_page(_texts(_pair())) is None
    assert f"status={status}" in caplog.text
    assert reason in caplog.text
    assert "status=empty-response" not in caplog.text


def test_identical_fallback_warnings_remain_deduplicated(caplog):
    comprehension.configurer_fournisseur_comprehension_texte(lambda *_args: None)
    for _ in range(4):
        assert comprehension.comprendre_segmentation_page(_texts(_pair())) is None
    warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert len(warnings) == 1


def test_wrong_high_confidence_hard_break_join_is_not_applied_or_rewritten(caplog):
    texts = ("  \u4e2d\u6587\n", "\u7d9a\u304d  ")
    before = deepcopy(texts)
    calls = []

    def provider(kind, lines, _role, _context):
        calls.append((kind, lines))
        return _json_decision(kind, len(lines))

    comprehension.configurer_fournisseur_comprehension_texte(provider)
    with caplog.at_level(logging.INFO):
        decision = comprehension.comprendre_reflow_paragraphe(texts, frame_role="text-column")
    assert calls == [("paragraph-reflow", texts)]
    assert texts == before
    assert decision.line_joins == ("preserve_break",)
    assert decision.fallback_used and not decision.ai_used
    assert "status=source-conflict" in caplog.text
    assert "status=accepted" not in caplog.text


def _block_from(units):
    block = deepcopy(units[0])
    block.semantic_role = "body"
    block.lignes = [deepcopy(line) for unit in units for line in unit.lignes]
    block.bbox = BBox(min(unit.bbox.x0 for unit in units), min(unit.bbox.y0 for unit in units),
                      max(unit.bbox.x1 for unit in units), max(unit.bbox.y1 for unit in units))
    return block


def _guard_pair(boundary):
    first, second = _pair(boundary)
    if boundary == "column":
        second = _unit("An unrelated column starts here.", "source-second", x=260, y=41)
    elif boundary == "hard-break":
        first.lignes[0].spans[0].texte += "\n"
    elif boundary == "list":
        second.lignes[0].spans[0].texte = "1. A separate operation starts here."
    elif boundary == "source-boundary":
        second.lignes[0].boundary_before = "paragraph-break"
    elif boundary == "paragraph":
        for index, unit in enumerate((first, second)):
            unit.presentation.update(paragraph_id=f"paragraph-{index}", paragraph_validated=True)
            unit.lignes[0].attributes.update(paragraph_id=f"paragraph-{index}", paragraph_validated=True)
    elif boundary == "heading-style":
        first.lignes[0].spans[0].texte = "The first operation is complete."
        second.lignes[0].spans[0].texte = "Independent Section Heading"
        second.lignes[0].spans[0].police = FontRef("heading-font", "Arial", True, False)
    return first, second


@pytest.mark.parametrize("boundary", [
    "style", "indent", "title", "column", "hard-break", "list", "source-boundary",
    "heading-style", "paragraph",
])
@pytest.mark.parametrize("producer", ["page", "semantic", "planner"])
def test_producer_keeps_real_boundaries_even_if_wrapper_accepts(monkeypatch, producer, boundary):
    units = _guard_pair(boundary)
    original = deepcopy(units)
    decision = comprehension.TextUnderstandingDecision(
        "paragraph", "segment-page" if producer == "page" else (
            "paragraph-reflow" if producer == "planner" else "merge-paragraph"),
        0.99, line_groups=((0, 1),), line_joins=("space",), ai_used=True, fallback_used=False,
    )
    if producer == "page":
        monkeypatch.setattr(text_segmentation, "comprendre_segmentation_page", lambda *a, **kw: decision)
        assert [len(group) for group in text_segmentation._groupes_ia_local(units)] == [1, 1]
        assert [(unit.bbox, unit.source_ids, unit.lignes) for unit in units] == [
            (unit.bbox, unit.source_ids, unit.lignes) for unit in original
        ]
    elif producer == "semantic":
        monkeypatch.setattr(comprehension, "comprendre_groupe_lignes", lambda *a, **kw: decision)
        assert semantic.est_frontiere_de_paragraphe(*units)
        assert units == original
    else:
        from pdfexact.layout import paragraph_planner

        block = _block_from(units)
        before = deepcopy(block)
        monkeypatch.setattr(paragraph_planner, "comprendre_reflow_paragraphe", lambda *a, **kw: decision)
        assert planifier_paragraphe(block).action_between(0) in {"preserve_break", "paragraph_break"}
        assert block == before


@pytest.mark.parametrize("emphasis", ["bold-first", "italic-first", "whole-line"])
@pytest.mark.parametrize("ai_enabled", [False, True])
def test_inline_emphasis_continues_inside_one_paragraph_without_changing_source(emphasis, ai_enabled):
    units = _pair()
    if emphasis == "whole-line":
        units[1].lignes[0].spans[0].police = FontRef("emphasis", "Arial", True, True)
    else:
        line = units[0].lignes[0]
        original = line.spans[0]
        original.texte = "The system validates incoming data with emphasis"
        line.spans.insert(0, Span(
            "Read ", FontRef("emphasis", "Arial", emphasis == "bold-first", emphasis == "italic-first"),
            original.size_pt, original.couleur, bbox=original.bbox, source_id="source-emphasis",
        ))
    before = deepcopy(units)
    if ai_enabled:
        comprehension.configurer_fournisseur_comprehension_texte(
            lambda kind, lines, _role, _context: _json_decision(kind, len(lines))
        )
    assert not semantic.est_frontiere_de_paragraphe(*units)
    assert units == before
    assert [len(group) for group in semantic.regrouper_frames(units)] == [2]
    assert [len(group) for group in semantic.regrouper_paragraphes(units)] == [2]
    assert [len(group) for group in semantic.preserver_frontieres_ambigues([units])] == [2]
    assert units == before
    groups = (text_segmentation._groupes_ia_local(units) if ai_enabled
              else text_segmentation._segment_units(units))
    assert [len(group) for group in groups] == [2]
    assert units == before
    block = _block_from(units)
    source_block = deepcopy(block)
    assert planifier_paragraphe(block).action_between(0) == "space"
    assert block == source_block


def test_planner_orders_actual_lines_and_keeps_whitespace_context_in_lockstep():
    first, last = _pair()
    last = _unit("before storing the complete results.", "source-last", y=52)
    blank = _unit(" \t\u00a0 ", "source-blank", y=41)
    empty = _unit("", "source-empty", y=45)
    block = _block_from((first, blank, empty, last))
    block.lignes.reverse()
    before = deepcopy(block)
    seen = []

    def provider(kind, texts, _role, context):
        seen.append((kind, texts, deepcopy(context)))
        return _json_decision(kind, len(texts))

    comprehension.configurer_fournisseur_comprehension_texte(provider)
    plan = planifier_paragraphe(block)
    expected = ("The system validates incoming data", " \t\u00a0 ",
                "before storing the complete results.")
    assert seen[0][0:2] == ("paragraph-reflow", expected)
    assert tuple(row["text"] for row in seen[0][2]["lines"]) == expected
    assert [row["source_ids"][0] for row in seen[0][2]["lines"]] == [
        "source-first", "source-blank", "source-last",
    ]
    assert [row["index"] for row in seen[0][2]["lines"]] == [0, 1, 2]
    assert [row["source_index"] for row in seen[0][2]["lines"]] == [3, 2, 0]
    assert plan.joins == ("preserve_break", "preserve_break")
    assert block == before


def test_semantic_multiline_transport_never_flattens_or_normalizes_source_lines():
    first, second = _pair()
    start = _unit("  The system accepts native source text  ", "source-start", y=19)
    block = _block_from((start, first))
    before = deepcopy((block, second))
    seen = []
    comprehension.configurer_fournisseur_comprehension_texte(
        lambda kind, texts, _role, context: seen.append((kind, texts, deepcopy(context)))
    )
    semantic.est_frontiere_de_paragraphe(block, second)
    expected = ("  The system accepts native source text  ", *_texts((first, second)))
    assert len(seen) == 1 and seen[0][0:2] == ("group", expected)
    assert tuple(row["text"] for row in seen[0][2]["lines"]) == expected
    assert [row["source_ids"][0] for row in seen[0][2]["lines"]] == [
        "source-start", "source-first", "source-second",
    ]
    assert (block, second) == before


@pytest.mark.parametrize("producer", ["page", "semantic", "planner"])
def test_producer_metadata_preserves_known_owner_frame_without_parent_source_ids(producer):
    units = _pair()
    for unit in units:
        unit.source_ids = ("parent-only", "unrelated-sibling")
        unit.lignes[0].layout_frame_id = None
        unit.lignes[0].layout_frame_role = None
    before = deepcopy(units)
    seen = []
    comprehension.configurer_fournisseur_comprehension_texte(
        lambda _kind, _texts, _role, context: seen.append(deepcopy(context))
    )
    if producer == "page":
        text_segmentation._groupes_ia_local(units)
    elif producer == "semantic":
        semantic.est_frontiere_de_paragraphe(*units)
    else:
        planifier_paragraphe(_block_from(units))
    assert len(seen) == 1
    for index, row in enumerate(seen[0]["lines"]):
        assert row["layout_frame_id"] == "fixture-frame"
        assert row["layout_role"] == "text-column"
        assert row["source_ids"] == list(before[index].lignes[0].source_ids)
    assert units == before


def test_source_continuity_does_not_annotate_acquired_language_script_or_confidence():
    units = _pair()
    for unit in units:
        unit.script = unit.language = "auto"
        unit.attributes = {}
        unit.lignes[0].script = unit.lignes[0].language = "auto"
        unit.lignes[0].confidence = 0
        unit.lignes[0].spans[0].confidence = None
    before = deepcopy(units)
    semantic.calculer_features_continuite(*units)
    semantic.est_frontiere_de_paragraphe(*units)
    semantic.regrouper_paragraphes(units)
    semantic.regrouper_frames(units)
    planifier_paragraphe(_block_from(units))
    assert units == before


@pytest.mark.parametrize("analysis_pass", ["paragraphs", "frames", "ambiguity"])
def test_every_semantic_pass_keeps_an_actual_intervening_obstacle(analysis_pass):
    first, second = _pair()
    obstacle = ImageEl(BBox(u(40), u(40.2), u(180), u(40.8)), "actual-source-image")
    elements = [first, obstacle, second]
    before = deepcopy(elements)
    comprehension.configurer_fournisseur_comprehension_texte(
        lambda kind, lines, _role, _context: _json_decision(kind, len(lines))
    )
    if analysis_pass == "paragraphs":
        groups = semantic.regrouper_paragraphes(elements)
    elif analysis_pass == "frames":
        groups = semantic.regrouper_frames(elements)
    else:
        groups = semantic.preserver_frontieres_ambigues([elements])
    assert all(not (first in group and second in group) for group in groups)
    assert elements == before


def test_planner_keeps_actual_surrounding_obstacle_context_without_mutating_it():
    block = _block_from(_pair())
    block.presentation["obstacles"] = [[u(40), u(40.2), u(180), u(40.8)]]
    block.presentation["neighbors"] = [{"text": "source neighbor", "source_ids": ["neighbor-id"]}]
    before = deepcopy(block)
    seen = []

    def provider(kind, texts, _role, context):
        seen.append(deepcopy(context))
        context["neighbors"].clear()
        return _json_decision(kind, len(texts))

    comprehension.configurer_fournisseur_comprehension_texte(provider)
    plan = planifier_paragraphe(block)
    assert seen[0]["obstacles"] == before.presentation["obstacles"]
    assert seen[0]["neighbors"] == before.presentation["neighbors"]
    assert plan.action_between(0) == "preserve_break"
    assert block == before


def test_deterministic_page_partition_is_never_promoted_to_ai_confirmation(monkeypatch):
    units = _pair()
    before = deepcopy(units)
    fallback = comprehension.TextUnderstandingDecision(
        "source-fallback", "segment-page", 0.0, ("source-conflict",),
        line_groups=((0, 1),), ai_used=False, fallback_used=True,
    )
    monkeypatch.setattr(text_segmentation, "comprendre_segmentation_page", lambda *a, **kw: fallback)
    segment = text_segmentation._segment_units
    flags = []

    def checked_segment(*args, **kwargs):
        flags.append(kwargs.get("ai_confirmed", False))
        return segment(*args, **kwargs)

    monkeypatch.setattr(text_segmentation, "_segment_units", checked_segment)
    assert [len(group) for group in text_segmentation._groupes_ia_local(units)] == [2]
    assert flags == [False]
    assert units == before


def test_canonical_semantic_transport_keeps_actual_text_ids_and_unknowns():
    from pdfexact.scene import ElementKind, ElementRecord, SourceKind

    native = _pair()
    records = tuple(ElementRecord(
        element_id=f"element-{index}", page_index=7, kind=ElementKind.TEXT,
        bbox=unit.bbox, source_kind=SourceKind.OCR, source_ids=unit.source_ids,
        role="body", text=_texts((unit,))[0], orientation="horizontal",
    ) for index, unit in enumerate(native))
    before = deepcopy(records)
    seen = []
    comprehension.configurer_fournisseur_comprehension_texte(
        lambda kind, texts, _role, context: seen.append((kind, texts, deepcopy(context)))
    )
    semantic.est_frontiere_de_paragraphe(*records)
    assert len(seen) == 1 and seen[0][0:2] == ("group", _texts(native))
    assert tuple(row["text"] for row in seen[0][2]["lines"]) == _texts(native)
    assert [row["source_ids"] for row in seen[0][2]["lines"]] == [
        list(unit.source_ids) for unit in native
    ]
    assert records == before
    assert all(record.confidence is None and record.language == "auto" for record in records)


@pytest.mark.parametrize("unsorted", [False, True])
def test_separator_before_a_paragraph_does_not_become_an_internal_line_boundary(unsorted):
    block = _block_from(_pair())
    if unsorted:
        block.lignes.reverse()
    block.presentation.update(blank_separator_before=True, boundary_before="blank-separator",
                              source_spacing_before_emu=u(20))
    before = deepcopy(block)
    seen = []

    def provider(kind, texts, _role, context):
        seen.append(deepcopy(context))
        return _json_decision(kind, len(texts))

    comprehension.configurer_fournisseur_comprehension_texte(provider)
    assert planifier_paragraphe(block).action_between(0) == "space"
    assert seen[0]["lines"][0]["blank_separator_before"] is True
    assert seen[0]["lines"][0]["source_ids"] == list(_pair()[0].lignes[0].source_ids)
    assert not seen[0]["lines"][1].get("blank_separator_before")
    assert not seen[0]["lines"][1].get("boundary_before")
    assert block == before


@pytest.mark.parametrize("boundary", [
    "style", "indent", "title", "column", "hard-break", "list", "source-boundary", "paragraph",
])
@pytest.mark.parametrize("analysis_pass", ["paragraphs", "frames", "ambiguity"])
def test_later_analysis_passes_never_rejoin_source_boundaries(boundary, analysis_pass):
    units = _guard_pair(boundary)
    before = deepcopy(units)
    comprehension.configurer_fournisseur_comprehension_texte(
        lambda kind, texts, _role, _context: _json_decision(kind, len(texts))
    )
    if analysis_pass == "paragraphs":
        groups = semantic.regrouper_paragraphes(units)
    elif analysis_pass == "frames":
        groups = semantic.regrouper_frames(units)
    else:
        groups = semantic.preserver_frontieres_ambigues([units])
    assert [len(group) for group in groups] == [1, 1]
    assert units == before


@pytest.mark.parametrize("reverse_roles", [False, True])
@pytest.mark.parametrize("analysis_pass", ["paragraphs", "frames", "ambiguity"])
def test_known_text_container_keeps_continuous_fragment_roles_without_rewriting_them(
    reverse_roles, analysis_pass,
):
    units = _pair()
    roles = ("figure_text", "text") if reverse_roles else ("text", "figure_text")
    for unit, role in zip(units, roles):
        unit.semantic_role = unit.lignes[0].semantic_role = role
    before = deepcopy(units)
    if analysis_pass == "paragraphs":
        groups = semantic.regrouper_paragraphes(units)
    elif analysis_pass == "frames":
        groups = semantic.regrouper_frames(units)
    else:
        groups = semantic.preserver_frontieres_ambigues([units])
    assert [len(group) for group in groups] == [2]
    assert units == before


@pytest.mark.parametrize("boundary", [
    "style", "indent", "title", "column", "hard-break", "list", "source-boundary", "paragraph",
])
@pytest.mark.parametrize("analysis_pass", ["paragraphs", "frames", "ambiguity"])
def test_known_text_container_cannot_override_actual_fragment_boundaries(boundary, analysis_pass):
    units = _guard_pair(boundary)
    if boundary != "title":
        for unit, role in zip(units, ("text", "figure_text")):
            unit.semantic_role = unit.lignes[0].semantic_role = role
    before = deepcopy(units)
    comprehension.configurer_fournisseur_comprehension_texte(
        lambda kind, texts, _role, _context: _json_decision(kind, len(texts))
    )
    if analysis_pass == "paragraphs":
        groups = semantic.regrouper_paragraphes(units)
    elif analysis_pass == "frames":
        groups = semantic.regrouper_frames(units)
    else:
        groups = semantic.preserver_frontieres_ambigues([units])
    assert [len(group) for group in groups] == [1, 1]
    assert units == before
