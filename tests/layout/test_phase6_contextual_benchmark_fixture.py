"""Offline benchmark preparation only: no provider, runtime, process or inference."""

from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "results/phase6_contextual_benchmark_20261011"


def _read_corpus():
    return json.loads((ARTIFACTS / "corpus.json").read_text(encoding="utf-8"))


def _canonical_sha(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _request(corpus, case):
    """Expand explicitly synthetic fixture records; never read oracle fields."""
    context = deepcopy(corpus["context_fixtures"][case["context_fixture"]])
    selected = [context["lines"][index] for index in case["selection"]]
    for index, (row, text) in enumerate(zip(selected, case["source_lines"], strict=True)):
        row["index"], row["text"] = index, text
        row["styles"] = [deepcopy(corpus["style_fixtures"][name]) for name in row["styles"]]
    context["lines"] = selected
    return {"kind": case["kind"], "lines": deepcopy(case["source_lines"]),
            "frame_role": case["frame_role"], "context": context}


def _expected_units(case):
    oracle = case["oracle"]
    if oracle["status"] == "ambiguous":
        return ()
    if oracle["field"] == "line_groups":
        group_by_index = {index: group for group, members in enumerate(oracle["expected"])
                          for index in members}
        return tuple("join" if group_by_index[index] == group_by_index[index + 1] else "break"
                     for index in range(len(case["source_lines"]) - 1))
    if oracle["field"] == "line_joins":
        return tuple(oracle["expected"])
    return (oracle["expected"],)


def _explicit_abstention():
    return {
        "status": "model-abstention", "inference_completed": True,
        "parse": {"status": "valid", "variant": "explicit-abstention-v1"},
        "parsed_response": {"kind": "unknown", "action": "abstain", "confidence": 0.0,
                            "evidence": ["document-flow-unresolved"]},
        "abstention_assessment": {"origin": "independent-review", "correct": True},
    }


def _perfect_observations(corpus):
    observations = {}
    for case in corpus["cases"]:
        observation = _explicit_abstention() if case["oracle"]["status"] == "ambiguous" else {
            "status": "decision", "units": _expected_units(case),
        }
        observation["protected"] = {
            "status": "not-applied-shadow", "final_units": _expected_units(case),
            "invariant_audit": {"assessed": True, "violations": []},
        }
        observations[case["id"]] = observation
    return observations


def _raw_scores(corpus, observations):
    """Reference metric arithmetic on already parsed choices, not a JSON parser."""
    counts = Counter(dict.fromkeys((
        "ambiguous_total", "ambiguous_model_abstentions", "ambiguous_unsafe_commitments",
        "ambiguous_unknown", "ambiguous_correct_abstentions", "unambiguous_cases", "expected_units", "predicted_units",
        "exact_cases", "correct_units",
    ), 0))
    classes = defaultdict(Counter)
    failures = Counter()
    for case in corpus["cases"]:
        observation = observations.get(case["id"], {"status": "not-attempted"})
        status = observation["status"]
        units = tuple(observation.get("units", ())) if status == "decision" else ()
        if case["oracle"]["status"] == "ambiguous":
            counts["ambiguous_total"] += 1
            if (status == "model-abstention" and observation.get("inference_completed") is True
                    and observation.get("parse") == {"status": "valid", "variant": "explicit-abstention-v1"}
                    and observation.get("parsed_response", {}).get("action") == "abstain"):
                counts["ambiguous_model_abstentions"] += 1
                assessment = observation.get("abstention_assessment", {})
                if assessment.get("origin") == "independent-review" and assessment.get("correct") is True:
                    counts["ambiguous_correct_abstentions"] += 1
            elif status == "decision":
                counts["ambiguous_unsafe_commitments"] += 1
            else:
                counts["ambiguous_unknown"] += 1
            continue
        expected = _expected_units(case)
        counts["unambiguous_cases"] += 1
        counts["expected_units"] += len(expected)
        counts["predicted_units"] += len(units)
        counts["exact_cases"] += status == "decision" and units == expected
        if status != "decision":
            failures[status] += 1
        prefix = f"{case['kind']}:{case['oracle']['field']}:"
        for index, wanted in enumerate(expected):
            actual = units[index] if index < len(units) else None
            classes[prefix + wanted]["support"] += 1
            if actual == wanted:
                counts["correct_units"] += 1
                classes[prefix + wanted]["tp"] += 1
            else:
                classes[prefix + wanted]["fn"] += 1
                if actual is not None:
                    classes[prefix + actual]["fp"] += 1
        for extra in units[len(expected):]:
            classes[prefix + extra]["fp"] += 1
    per_class = {}
    for label, values in sorted(classes.items()):
        tp, fp, fn = values["tp"], values["fp"], values["fn"]
        per_class[label] = {"tp": tp, "fp": fp, "fn": fn, "support": values["support"],
                            "precision": tp / (tp + fp) if tp + fp else None,
                            "recall": tp / (tp + fn) if tp + fn else None}
    return {**counts, "precision": counts["correct_units"] / counts["predicted_units"]
            if counts["predicted_units"] else None,
            "recall": counts["correct_units"] / counts["expected_units"],
            "failures": dict(failures), "per_class": per_class}


def _protected_scores(corpus, observations):
    counts = Counter(dict.fromkeys((
        "model_applications", "correct_model_applications", "correct_final_outcomes",
        "invariant_audits", "invariant_violations", "invariant_unknown",
    ), 0))
    statuses = Counter()
    for case in corpus["cases"]:
        protected = observations.get(case["id"], {}).get("protected", {})
        status = protected.get("status", "unknown")
        statuses[status] += 1
        if status == "applied-model":
            counts["model_applications"] += 1
            counts["correct_model_applications"] += (
                case["oracle"]["status"] == "unambiguous"
                and tuple(protected.get("applied_units", ())) == _expected_units(case)
            )
        if case["oracle"]["status"] == "unambiguous":
            counts["correct_final_outcomes"] += (
                "final_units" in protected
                and tuple(protected["final_units"]) == _expected_units(case)
            )
        audit = protected.get("invariant_audit", {})
        if audit.get("assessed") is True:
            counts["invariant_audits"] += 1
            counts["invariant_violations"] += len(audit["violations"])
        else:
            counts["invariant_unknown"] += 1
    return {**counts, "statuses": dict(statuses),
            "model_application_accuracy": counts["correct_model_applications"] / counts["model_applications"]
            if counts["model_applications"] else None,
            "invariant_gate_assessed": counts["invariant_unknown"] == 0,
            "qualified": False}


def _small_gate(corpus, observations):
    """Approved numerical prerequisite only; never enables production decisions."""
    gate = json.loads((ARTIFACTS / "approved_gate.json").read_text(encoding="utf-8"))
    raw, protected = _raw_scores(corpus, observations), _protected_scores(corpus, observations)
    page_cases = {**corpus, "cases": [case for case in corpus["cases"]
                                     if case["kind"] == "page-segmentation"]}
    page = _raw_scores(page_cases, observations)
    requirements = gate["requirements"]
    checks = {
        "frozen_corpus": hashlib.sha256((ARTIFACTS / "corpus.json").read_bytes()).hexdigest() == gate["corpus_sha256"],
        "frozen_requests": _canonical_sha([_request(corpus, case) for case in corpus["cases"]]) == gate["requests_sha256"],
        "frozen_oracles": _canonical_sha({case["id"]: case["oracle"] for case in corpus["cases"]}) == gate["oracles_sha256"],
        "exact_non_ambiguous": raw["exact_cases"] == raw["unambiguous_cases"] == requirements["exact_non_ambiguous_cases"],
        "join_break_support": page["expected_units"] == requirements["join_break_expected_units"],
        "join_break_precision": page["precision"] == requirements["join_break_precision"],
        "join_break_recall": page["recall"] == requirements["join_break_recall"],
        "correct_explicit_abstentions": raw["ambiguous_correct_abstentions"] == raw["ambiguous_total"]
            == requirements["correct_explicit_ambiguous_abstentions"],
        "hard_invariants": protected["invariant_gate_assessed"]
            and protected["invariant_violations"] == requirements["max_applied_invariant_violations"],
    }
    return {"checks": checks, "necessary_gate_passed": all(checks.values()),
            "production_qualified": False, "raw": raw, "protected": protected}


def test_initial_texts_and_independent_expected_values_are_unchanged():
    corpus = _read_corpus()
    cases = {case["id"]: case for case in corpus["cases"]}
    for reference in corpus["references"][:2]:
        path = ROOT / reference["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == reference["sha256"]
        report = json.loads(path.read_text(encoding="utf-8"))
        assert len(report["cases"]) == 15
        for initial in report["cases"]:
            case = cases[initial["id"]]
            assert case["source_lines"] == initial["source_lines"]
            assert case["kind"] == initial["request_kind"]
            assert case["oracle"]["field"] == initial["field"]
            assert case["oracle"]["expected"] == initial["expected"]
    assert len(cases) == len(corpus["cases"]) == 19


@pytest.mark.parametrize("case_id", [case["id"] for case in _read_corpus()["cases"]])
def test_context_is_aligned_explicit_synthetic_and_independent_of_oracle(case_id):
    corpus = _read_corpus()
    case = next(case for case in corpus["cases"] if case["id"] == case_id)
    before = deepcopy((corpus, case))
    request = _request(corpus, case)
    assert (corpus, case) == before
    assert request["context"]["page_index"] == 7
    assert request["context"]["coordinate_system"] == {"origin": "top-left", "units": "EMU"}
    assert [row["text"] for row in request["context"]["lines"]] == case["source_lines"]
    ids = []
    for index, row in enumerate(request["context"]["lines"]):
        assert row["index"] == index
        assert len(row["bbox"]) == 4 and all(type(value) is int for value in row["bbox"])
        assert row["bbox"][0] < row["bbox"][2] and row["bbox"][1] < row["bbox"][3]
        assert row["source_ids"] and all(value.startswith("fixture:") for value in row["source_ids"])
        assert {"font", "size_pt", "bold", "italic", "color"} <= row["styles"][0].keys()
        ids.extend(row["source_ids"])
    assert len(ids) == len(set(ids))
    without_oracle = {key: value for key, value in case.items() if key != "oracle"}
    assert _request(corpus, without_oracle) == request
    assert "expected" not in json.dumps(request) and "oracle" not in json.dumps(request)
    request["context"]["lines"][0]["bbox"][0] = -1
    assert (corpus, case) == before


def test_ambiguous_cases_reuse_text_without_inventing_missing_flow_context():
    corpus = _read_corpus()
    cases = {case["id"]: case for case in corpus["cases"]}
    ambiguous = [case for case in cases.values() if case["oracle"]["status"] == "ambiguous"]
    assert {case["language_annotation"] for case in ambiguous} == {"ru", "zh", "ja", "ko"}
    for case in ambiguous:
        assert case["source_lines"] == cases[case["derived_text_from"]]["source_lines"]
        assert case["oracle"]["expected"] is None
        context = _request(corpus, case)["context"]
        assert context["neighbors"] is None and context["obstacles"] is None
        assert all(row["semantic_role"] is None for row in context["lines"])
        assert context["context_completeness"]["selected_sources_adjacent_in_flow"] == "unknown"


def test_literal_newline_unicode_and_fingerprints_are_preserved():
    corpus = _read_corpus()
    case = next(case for case in corpus["cases"] if case["id"] == "ru-hard-break")
    assert case["source_lines"][0] == "Первая строка\n"
    assert _request(corpus, case)["context"]["lines"][0]["text"].endswith("\n")
    manifest = json.loads((ARTIFACTS / "fingerprints.json").read_text(encoding="utf-8"))
    assert hashlib.sha256((ARTIFACTS / "corpus.json").read_bytes()).hexdigest() == manifest["corpus_sha256"]
    assert _canonical_sha([_request(corpus, item) for item in corpus["cases"]]) == manifest["requests_sha256"]
    assert _canonical_sha({item["id"]: item["oracle"] for item in corpus["cases"]}) == manifest["oracles_sha256"]
    assert _canonical_sha({item["id"]: item["source_lines"] for item in corpus["cases"]}) == manifest["source_texts_sha256"]
    assert manifest["benchmark_executed"] is False


def test_correct_decisions_and_explicit_ambiguous_abstentions_are_separate_metrics():
    corpus = _read_corpus()
    observations = {case["id"]: _explicit_abstention() if case["oracle"]["status"] == "ambiguous"
                    else {"status": "decision", "units": _expected_units(case)} for case in corpus["cases"]}
    scores = _raw_scores(corpus, observations)
    assert scores["exact_cases"] == scores["unambiguous_cases"] == 15
    assert scores["correct_units"] == scores["expected_units"] == 18
    assert scores["precision"] == scores["recall"] == 1
    assert scores["ambiguous_model_abstentions"] == 4
    assert all(values["precision"] == values["recall"] == 1 for values in scores["per_class"].values())


def test_systematic_shadow_none_or_missing_runs_do_not_score_as_understanding():
    scores = _raw_scores(_read_corpus(), {})
    assert scores["exact_cases"] == 0 and scores["recall"] == 0
    assert scores["precision"] is None
    assert scores["failures"] == {"not-attempted": 15}
    assert scores["ambiguous_unknown"] == 4 and scores["ambiguous_model_abstentions"] == 0


def test_guard_rejection_does_not_remove_wrong_model_choice_from_raw_denominator():
    corpus = _read_corpus()
    observations = {"ru-heading-boundary": {"status": "decision", "units": ["join", "join"],
                                            "protected": {"status": "rejected", "reason": "heading-style-boundary"}}}
    scores = _raw_scores(corpus, observations)
    assert scores["expected_units"] == 18 and scores["predicted_units"] == 2
    assert scores["correct_units"] == 1 and scores["precision"] == 0.5
    assert scores["recall"] == 1 / 18
    assert scores["per_class"]["page-segmentation:line_groups:break"]["fn"] == 5


def test_correct_fallback_is_not_counted_as_correct_model_application():
    corpus = _read_corpus()
    observations = {case["id"]: {"status": "not-attempted", "protected": {
        "status": "not-applied-shadow", "final_units": _expected_units(case),
        "invariant_audit": {"assessed": True, "violations": []},
    }} for case in corpus["cases"]}
    raw = _raw_scores(corpus, observations)
    protected = _protected_scores(corpus, observations)
    assert raw["recall"] == 0
    assert protected["correct_final_outcomes"] == 15
    assert protected["model_applications"] == 0
    assert protected["model_application_accuracy"] is None
    assert protected["invariant_violations"] == 0
    assert protected["invariant_gate_assessed"] and not protected["qualified"]


def test_unknown_invariant_audit_is_not_zero_violations_proof():
    protected = _protected_scores(_read_corpus(), {})
    assert protected["invariant_unknown"] == 19
    assert not protected["invariant_gate_assessed"] and not protected["qualified"]


def test_actual_applied_invariant_violation_is_visible_even_with_correct_choice():
    corpus = _read_corpus()
    observations = {"ru-continuation": {"protected": {
        "status": "applied-model", "applied_units": ["join"], "final_units": ["join"],
        "invariant_audit": {"assessed": True, "violations": ["caller-source-ids-mutated"]},
    }}}
    protected = _protected_scores(corpus, observations)
    assert protected["model_applications"] == 1 and protected["model_application_accuracy"] == 1
    assert protected["invariant_violations"] == 1 and not protected["qualified"]


@pytest.mark.parametrize("status", ["invalid-response", "timeout", "runtime-error", "model-abstention"])
def test_failure_and_abstention_are_transparent_not_silently_excluded(status):
    corpus = _read_corpus()
    observations = {case["id"]: _explicit_abstention() if status == "model-abstention"
                    else {"status": status} for case in corpus["cases"]}
    scores = _raw_scores(corpus, observations)
    assert scores["recall"] == 0 and scores["precision"] is None
    assert scores["failures"] == {status: 15}
    assert scores["ambiguous_model_abstentions"] == (4 if status == "model-abstention" else 0)


def test_confident_ambiguous_commitment_cannot_be_relabelled_correct_by_guard():
    corpus = _read_corpus()
    observations = {case["id"]: {"status": "decision", "units": ["join"], "confidence": 0.99,
                                "protected": {"status": "not-applied"}}
                    for case in corpus["cases"] if case["oracle"]["status"] == "ambiguous"}
    scores = _raw_scores(corpus, observations)
    assert scores["ambiguous_unsafe_commitments"] == 4
    assert scores["ambiguous_model_abstentions"] == 0


def test_bounds_and_zero_invariant_gate_cannot_self_qualify_model():
    corpus = _read_corpus()
    bounds, qualification = corpus["bounds_for_later_parent_approval"], corpus["qualification"]
    assert bounds["max_cases"] == len(corpus["cases"])
    assert bounds["max_concurrent_workers"] == bounds["max_requests_per_case"] == 1
    assert not bounds["truncate_inputs"] and not bounds["retry"] and not bounds["prompt_tuning"]
    assert bounds["termination_then_kill_and_reap_required"]
    assert qualification["max_applied_invariant_violations"] == 0
    assert qualification["automatic_promotion"] is False
    assert qualification["raw_precision_threshold"] is qualification["raw_recall_threshold"] is None


@pytest.mark.parametrize("change", [
    {"parse": {"status": "invalid", "variant": None}},
    {"parsed_response": {"action": "segment-page", "confidence": 0.1}},
    {"inference_completed": False},
    {"parse": {"status": "guard-rejected", "variant": None}},
])
def test_abstention_label_without_actual_explicit_model_signal_does_not_get_credit(change):
    corpus = _read_corpus()
    observation = _explicit_abstention()
    observation.update(change)
    scores = _raw_scores(corpus, {"ru-ambiguous-flow": observation})
    assert scores["ambiguous_model_abstentions"] == 0
    assert scores["ambiguous_unknown"] == 4


@pytest.mark.parametrize("correct", [False, None])
def test_explicit_abstention_needs_independent_correctness_assessment(correct):
    observation = _explicit_abstention()
    observation["abstention_assessment"]["correct"] = correct
    scores = _raw_scores(_read_corpus(), {"ru-ambiguous-flow": observation})
    assert scores["ambiguous_model_abstentions"] == 1
    assert scores["ambiguous_correct_abstentions"] == 0


def test_approved_small_gate_is_necessary_not_a_production_qualification():
    corpus = _read_corpus()
    result = _small_gate(corpus, _perfect_observations(corpus))
    assert result["necessary_gate_passed"]
    assert result["production_qualified"] is False


@pytest.mark.parametrize("failure", ["wrong-page", "wrong-action", "invalid-ambiguous", "invariant", "unknown-audit"])
def test_approved_gate_fails_on_any_missed_requirement(failure):
    corpus = _read_corpus()
    observations = _perfect_observations(corpus)
    if failure == "wrong-page":
        observations["ru-continuation"]["units"] = ["break"]
    elif failure == "wrong-action":
        observations["ru-label-line"]["units"] = ["candidate-paragraph-line"]
    elif failure == "invalid-ambiguous":
        observations["ru-ambiguous-flow"]["parse"]["status"] = "invalid"
    elif failure == "invariant":
        observations["ru-continuation"]["protected"]["invariant_audit"]["violations"] = ["source-id-mutated"]
    else:
        observations["ru-continuation"]["protected"]["invariant_audit"] = {"assessed": False}
    assert not _small_gate(corpus, observations)["necessary_gate_passed"]
