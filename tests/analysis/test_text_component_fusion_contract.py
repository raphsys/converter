"""Component conservation at semantic fusion, without OCR or model execution."""
from copy import deepcopy
from dataclasses import replace

import pytest

from pdfexact.analysis.provenance import Evidence, observation_is_preserved, observation_signature, observation_nodes
from pdfexact.geometry import BBox, PageGeometry, pt_vers_emu as u
from pdfexact.ir import Document, FlowParagraph, FontRef, Line, Page, Span, TextBox
from pdfexact.layout.text_comprehension import (
    configurer_fournisseur_comprehension_texte,
    contexte_comprehension_texte,
)
from pdfexact.render.render_plan import build_document_render_plan, build_render_plan
from pdfexact.render.reflow import fusionner_flow_paragraphes, regrouper_continuations_par_frame
from pdfexact.scene import capture_source_observations, element_record_from_legacy, record_source_transformation


@pytest.fixture(autouse=True)
def isolated_deterministic_analysis():
    with contexte_comprehension_texte():
        configurer_fournisseur_comprehension_texte(None)
        yield


def text_box(text, source_id, y, *, quad=False, opacity=1.0):
    bbox = BBox(u(10), u(y), u(170), u(y + 12))
    points = (
        (bbox.x0, bbox.y0), (bbox.x1, bbox.y0),
        (bbox.x1, bbox.y1), (bbox.x0, bbox.y1),
    ) if quad else ()
    span = Span(
        text, FontRef("Arial", "Arial", False, False), 12, "123456",
        bbox=bbox, source_id=source_id + ":span", source_kind="pdf-native",
        quad=points, z_index=0,
    )
    line = Line(
        bbox, [span], u(12), bbox.largeur, source_id=source_id + ":line",
        source_kind="pdf-native", quad=points, z_index=0,
    )
    return TextBox(
        bbox, [line], source_id=source_id, source_kind="pdf-native",
        semantic_role="body", quad=points, opacity=opacity, z_index=0,
    )


def document(*elements):
    doc = Document([Page(3, u(300), u(200), list(elements))])
    capture_source_observations(doc.pages[0], doc.pages[0].elements)
    return doc


def two_boxes(**kwargs):
    return document(
        text_box("first part", "first", 10, **kwargs),
        text_box("next part", "second", 24, **kwargs),
    )


def inventory_signatures(doc):
    return {key: observation_signature(raw) for key, raw in doc.pages[0].source_inventory.items()}


def merged_payload(plan):
    instructions = plan.instructions_for_page(3)
    assert len(instructions) == 1
    return instructions[0].element


def test_control_merge_preserves_native_children_inventory_and_caller():
    doc = two_boxes()
    before = deepcopy(doc)
    plan = build_document_render_plan(doc)

    assert plan.validate(doc) == []
    assert doc == before
    assert inventory_signatures(doc) == inventory_signatures(before)
    assert set(plan.source_coverage) == set(plan.source_inventory)
    payload = merged_payload(plan)
    assert [line.source_id for line in payload.lignes] == ["first:line", "second:line"]
    assert all(item.decision.editable for item in plan.for_page(3))


def test_component_quads_allow_verified_aggregate_without_changing_children():
    doc = two_boxes(quad=True)
    before = deepcopy(doc)
    plan = build_document_render_plan(doc)
    payload = merged_payload(plan)

    assert [line for line in payload.lignes] == [root.lignes[0] for root in before.pages[0].elements]
    assert all(
        observation_is_preserved(root.lignes[0], [payload])
        for root in before.pages[0].elements
    )
    assert doc == before
    assert inventory_signatures(doc) == inventory_signatures(before)
    assert plan.validate(doc) == []


def test_root_quad_not_recoverable_from_actual_children_prevents_fusion():
    roots = [text_box("first part", "first", 10, quad=True),
             text_box("next part", "second", 24, quad=True)]
    roots[0].quad = tuple((x + u(5), y) for x, y in roots[0].quad)
    doc = document(*roots)
    before = deepcopy(doc)
    plan = build_document_render_plan(doc)

    assert len(plan.for_page(3)) == 2
    assert plan.validate(doc) == []
    assert doc == before


@pytest.mark.parametrize("opacity", [0.0, 0.4])
def test_shared_opacity_survives_fusion_instead_of_dataclass_default(opacity):
    doc = two_boxes(opacity=opacity)
    before = deepcopy(doc)
    plan = build_document_render_plan(doc)
    payload = merged_payload(plan)

    assert payload.opacity == opacity
    assert plan.validate(doc) == []
    assert doc == before
    assert inventory_signatures(doc) == inventory_signatures(before)


@pytest.mark.parametrize("frame", [None, "same-frame"])
@pytest.mark.parametrize(("field", "left", "right"), [
    ("opacity", 0.4, 0.7),
    ("z_index", 0, 1),
    ("clip_ids", ("clip-a",), ("clip-b",)),
    ("compositing", {"blend_mode": "normal"}, {"blend_mode": "multiply"}),
    ("transform", (1, 0, 0, 1, 0, 0), (1, 0, 0, 1, 10, 0)),
])
def test_incompatible_root_paint_prevents_fusion_across_all_reflow_passes(frame, field, left, right):
    roots = [text_box("first part", "first", 10), text_box("next part", "second", 24)]
    for root, value in zip(roots, (left, right)):
        setattr(root, field, value)
        root.layout_frame_id = frame
    doc = document(*roots)
    before = deepcopy(doc)
    plan = build_document_render_plan(doc)

    assert len(plan.for_page(3)) == 2
    assert [getattr(instruction.element, field) for instruction in plan.instructions_for_page(3)] == [left, right]
    assert all(item.decision.editable for item in plan.for_page(3))
    assert plan.validate(doc) == []
    assert doc == before
    assert inventory_signatures(doc) == inventory_signatures(before)


@pytest.mark.parametrize(("field", "original", "changed"), [
    ("opacity", 1.0, 0.4),
    ("z_index", 0, 2),
    ("clip_ids", (), ("unexpected-clip",)),
    ("compositing", {}, {"blend_mode": "multiply"}),
    ("transform", (1, 0, 0, 1, 0, 0), (1, 0, 0, 1, 10, 0)),
])
def test_materialization_with_changed_root_paint_is_rejected(field, original, changed):
    source = text_box("first part", "first", 10)
    setattr(source, field, original)
    doc = document(source)
    plan = build_render_plan(doc)
    assert plan.validate(doc) == []
    setattr(merged_payload(plan), field, changed)

    assert "unverified-source-transform:first" in plan.validate(doc)


@pytest.mark.parametrize("missing", ["line", "span", "line-with-flat-span-remaining"])
def test_source_aliases_cannot_cover_a_missing_real_child(missing):
    doc = two_boxes()
    plan = build_document_render_plan(doc)
    assert plan.validate(doc) == []
    payload = merged_payload(plan)
    if missing in {"line", "line-with-flat-span-remaining"}:
        payload.lignes.pop()
    else:
        payload.lignes[-1].spans.clear()
    if missing != "line-with-flat-span-remaining":
        payload.spans = [span for line in payload.lignes for span in line.spans]

    assert "second:span" in plan.source_coverage
    assert "unverified-source-transform:second:line" in plan.validate(doc)
    if missing != "line-with-flat-span-remaining":
        assert "unverified-source-transform:second:span" in plan.validate(doc)
    assert "unverified-source-transform:second" in plan.validate(doc)


def test_parent_quad_cannot_substitute_for_changed_real_line_quad():
    doc = document(text_box("first part", "first", 10, quad=True))
    plan = build_render_plan(doc)
    assert plan.validate(doc) == []
    payload = merged_payload(plan)
    line = payload.lignes[0]
    line.quad = tuple((x + u(5), y) for x, y in line.quad)

    assert "unverified-source-transform:first:line" in plan.validate(doc)
    assert "unverified-source-transform:first" in plan.validate(doc)


@pytest.mark.parametrize("claim", [True, "source-components-preserved", {"verified": True, "schema": "text-component-partition-v1"}])
def test_unmeasured_component_proof_cannot_authorize_changed_paint(claim):
    doc = two_boxes()
    plan = build_document_render_plan(doc)
    assert plan.validate(doc) == []
    payload = merged_payload(plan)
    payload.opacity = 0.4
    payload.attributes["text_component_partition"] = claim
    payload.attributes["source_components"] = deepcopy(doc.pages[0].elements)
    payload.evidence.append(Evidence(
        "preserved-components", "claimed-producer", 1.0,
        (("proof", claim), ("reason", "source-components-preserved")),
    ))

    assert "unverified-source-transform:first" in plan.validate(doc)
    assert "unverified-source-transform:second" in plan.validate(doc)


def test_identical_text_new_identities_are_not_verified_lineage():
    doc = two_boxes()
    raw_ids = set(doc.pages[0].source_inventory)
    doc.pages[0].elements = [
        text_box("first part", "derived:first", 10),
        text_box("next part", "derived:second", 24),
    ]
    before = deepcopy(doc)
    plan = build_render_plan(doc)

    assert [span.texte for instruction in plan.instructions_for_page(3)
            for line in instruction.element.lignes for span in line.spans] == ["first part", "next part"]
    assert {error.removeprefix("uncovered-source:") for error in plan.validate(doc)
            if error.startswith("uncovered-source:")} == raw_ids
    assert raw_ids.isdisjoint(plan.source_coverage)
    assert doc == before
    assert inventory_signatures(doc) == inventory_signatures(before)


@pytest.mark.parametrize("observable", [
    "highlight", "glyph-order", "unicode-status", "font-metrics", "source-alpha",
    "source-font", "source-origin", "source-size", "language", "script", "font",
])
def test_real_span_observables_cannot_change_with_same_identity(observable):
    root = text_box("first part", "first", 10)
    span = root.lignes[0].spans[0]
    span.glyph_ids = (41, 42)
    span.to_unicode_status = "decoded-unicode"
    span.font_metrics = {"ascender": .8, "descender": -.2}
    span.attributes.update(source_alpha=255, source_font_name="Arial", source_origin=(10., 20.), source_size_pt=12.)
    doc = document(root)
    plan = build_render_plan(doc)
    assert plan.validate(doc) == []
    changed = merged_payload(plan).lignes[0].spans[0]
    if observable == "highlight":
        changed.surlignage = "yellow"
    elif observable == "glyph-order":
        changed.glyph_ids = (42, 41)
    elif observable == "unicode-status":
        changed.to_unicode_status = "unicode-missing"
    elif observable == "font-metrics":
        changed.font_metrics["ascender"] = 1.2
    elif observable == "source-alpha":
        changed.attributes["source_alpha"] = 0
    elif observable == "source-font":
        changed.attributes["source_font_name"] = "Another native font"
    elif observable == "source-origin":
        changed.attributes["source_origin"] = (11., 20.)
    elif observable == "source-size":
        changed.attributes["source_size_pt"] = 13.
    elif observable == "language":
        changed.language = "ru"
    elif observable == "script":
        changed.script = "Cyrillic"
    else:
        changed.police = replace(changed.police, gras=True)
    errors = plan.validate(doc)
    assert "unverified-source-transform:first:span" in errors
    assert "unverified-source-transform:first:line" in errors
    assert "unverified-source-transform:first" in errors


@pytest.mark.parametrize("mutation", ["line-order", "span-order", "duplicate-line", "line-type"])
def test_exact_actual_component_types_multiplicity_and_order_are_required(mutation):
    root = text_box("first part", "first", 10)
    second = text_box("next part", "second", 24)
    root.lignes.append(second.lignes[0])
    root.lignes[0].spans.append(replace(root.lignes[0].spans[0], texte=" extra", source_id="extra:span"))
    root.bbox = BBox(root.bbox.x0, root.bbox.y0, root.bbox.x1, second.bbox.y1)
    doc = document(root)
    plan = build_render_plan(doc)
    assert plan.validate(doc) == []
    payload = merged_payload(plan)
    if mutation == "line-order":
        payload.lignes.reverse()
    elif mutation == "span-order":
        payload.lignes[0].spans.reverse()
    elif mutation == "duplicate-line":
        payload.lignes.append(deepcopy(payload.lignes[0]))
    else:
        row = payload.lignes[0]
        fake = TextBox(row.bbox, [], source_id=row.source_id, source_ids=row.source_ids,
                       z_index=row.z_index, source_kind=row.source_kind)
        fake.spans = row.spans
        payload.lignes[0] = fake
    assert "unverified-source-transform:first" in plan.validate(doc)


def test_owner_annotations_do_not_authorize_modified_child_metadata():
    doc = two_boxes()
    plan = build_document_render_plan(doc)
    payload = merged_payload(plan)
    payload.attributes["analysis_note"] = "additive owner annotation"
    payload.lignes[1].spans[0].attributes["source_alpha"] = 0
    assert "unverified-source-transform:second" in plan.validate(doc)


def test_direct_incompatible_fusion_fails_without_losing_input():
    roots = [text_box("first part", "first", 10, opacity=0), text_box("next part", "second", 24)]
    before = deepcopy(roots)
    with pytest.raises(ValueError, match="incompatible-text-fusion"):
        fusionner_flow_paragraphes(roots)
    assert roots == before


@pytest.mark.parametrize("field", ["source_kind", "layout_frame_role", "layout_frame_strategy", "list_group_id"])
def test_context_incompatibility_is_rechecked_in_frame_reflow(field, monkeypatch):
    roots = [text_box("first part", "first", 10), text_box("next part", "second", 24)]
    for root in roots:
        root.layout_frame_id = "common-frame"
    left, right = ("pdf-native", "ocr") if field == "source_kind" else ("context-a", "context-b")
    setattr(roots[0], field, left)
    setattr(roots[1], field, right)
    monkeypatch.setattr("pdfexact.render.reflow.regrouper_frames", lambda *args: [roots])
    before = deepcopy(roots)
    assert regrouper_continuations_par_frame(roots) == roots
    assert roots == before


@pytest.mark.parametrize("cache_copies", [False, True])
def test_ocr_selection_then_fusion_has_one_actual_component_not_flat_cache(cache_copies):
    from pdfexact.analysis.ocr_correspondence import (
        build_ocr_native_correspondence, selection_event_details,
        verify_ocr_native_correspondence,
    )
    native = text_box("first part", "first", 10)
    other = text_box("next part", "second", 24)
    observation = text_box("first part", "observation", 10)
    for node in observation_nodes(observation):
        node.source_kind = "ocr"
    observation.attributes = {"engine": "rapidocr", "observation_only": True}
    native.lignes[0].spans[0].attributes["source_alpha"] = 255
    doc = Document([Page(3, u(300), u(200), [native, other])])
    page = doc.pages[0]
    page.ocr_correspondence_page_binding = {
        "index": 3, "source_pdf_id": None,
        "geometry": PageGeometry(300, 200, 0, None, None).snapshot(),
    }
    capture_source_observations(page, [native, other, observation])
    inventory = {}
    for key, raw in page.source_inventory.items():
        record = element_record_from_legacy(deepcopy(raw), page.index)
        record.attributes["source_page_binding"] = deepcopy(page.ocr_correspondence_page_binding)
        inventory[key] = record
    proof, errors = build_ocr_native_correspondence(
        observation, native.lignes[0], inventory,
        page_binding=page.ocr_correspondence_page_binding,
    )
    assert errors == [] and proof is not None
    event = record_source_transformation(page, [observation], [native], "ocr-native-selection",
                                         **selection_event_details(proof))
    native.evidence.append(Evidence("ocr-native-source-match", "pdfexact.extract.ocr", None,
                                   (("proof", deepcopy(proof)),)))
    fused = fusionner_flow_paragraphes(deepcopy([native, other]))
    if cache_copies:
        fused.spans = deepcopy(fused.spans)
    assert sum(node.source_id == native.lignes[0].spans[0].source_id
               for node in observation_nodes(fused)) == 1
    assert verify_ocr_native_correspondence(
        inventory[observation.source_id], [fused], inventory, proof, selection_events=[event],
    ) == []
    page.elements = [fused]
    plan = build_render_plan(doc)
    assert plan.validate(doc) == []
    assert plan.source_coverage[observation.source_id].relationship == "observation-superseded-by-native"
    # Keeping only the cache cannot replace a removed actual native row.
    fused.lignes.pop(0)
    assert verify_ocr_native_correspondence(
        inventory[observation.source_id], [fused], inventory, proof, selection_events=[event],
    )


@pytest.mark.parametrize("observable", ["text-order", "baseline-alias", "z-alias", "chars"])
def test_additional_actual_span_data_is_bound(observable):
    root = text_box("ab", "first", 10)
    root.lignes[0].spans[0].attributes["chars"] = [{"c": "a"}, {"c": "b"}]
    doc = document(root)
    plan = build_render_plan(doc)
    span = merged_payload(plan).lignes[0].spans[0]
    if observable == "text-order":
        span.texte = "ba"
    elif observable == "baseline-alias":
        span.baseline = ((0, 0), (100, 0))
    elif observable == "z-alias":
        span.z_order = 10
    else:
        span.attributes["chars"].reverse()
    assert "unverified-source-transform:first:span" in plan.validate(doc)


def test_common_parent_contracts_and_all_metadata_survive_direct_fusion():
    roots = [text_box("first part", "first", 10), text_box("next part", "second", 24)]
    for index, root in enumerate(roots):
        root.opacity = 0
        root.clip_ids = ("clip",)
        root.compositing = {"blend_mode": "normal", "alpha": 0}
        root.transform = (1, 0, 0, 1, 0, 0)
        root.source_kind = "pdf-native"
        root.language = "en"
        root.confidence = 0
        root.attributes[f"owner-{index}"] = {"confidence": 0, "unknown": None}
        root.presentation[f"note-{index}"] = index
        root.evidence = [Evidence("source", "extract", index / 2, (("paint", 0),))]
        root.decision_history = [{"event": "source", "index": index}]
    before = deepcopy(roots)
    fused = fusionner_flow_paragraphes(roots)
    for name in ("opacity", "clip_ids", "compositing", "transform", "source_kind", "language", "confidence"):
        assert getattr(fused, name) == getattr(roots[0], name)
    assert fused.attributes == {**roots[0].attributes, **roots[1].attributes}
    assert all(fused.presentation[f"note-{i}"] == i for i in range(2))
    assert fused.evidence[:2] == roots[0].evidence + roots[1].evidence
    assert [(entry.kind, entry.source, entry.confidence) for entry in fused.evidence[2:]] == [
        ("source-confidence", root.source_id, root.confidence) for root in roots
    ]
    assert fused.decision_history == roots[0].decision_history + roots[1].decision_history
    assert fused.lignes == [root.lignes[0] for root in roots]
    assert roots == before


@pytest.mark.parametrize("container", ["attributes", "presentation"])
def test_conflicting_parent_metadata_refuses_direct_fusion(container):
    roots = [text_box("first part", "first", 10), text_box("next part", "second", 24)]
    for index, root in enumerate(roots):
        getattr(root, container)["source-owner"] = index
    with pytest.raises(ValueError, match="incompatible-text-fusion"):
        fusionner_flow_paragraphes(roots)


@pytest.mark.parametrize("pass_name", ["paragraph", "column", "frame"])
def test_incompatible_proposed_groups_are_partitioned_even_when_forced(pass_name, monkeypatch):
    import pdfexact.render.reflow as reflow

    roots = [text_box("first part", "first", 10, opacity=0),
             text_box("next part", "second", 24, opacity=.4)]
    if pass_name == "paragraph":
        monkeypatch.setattr(reflow, "regrouper_paragraphes", lambda *args: [roots])
        monkeypatch.setattr(reflow, "preserver_frontieres_ambigues", lambda groups, *args: groups)
        result = reflow.prepare_page_elements(roots)
    elif pass_name == "column":
        monkeypatch.setattr(reflow, "detecter_colonnes_textuelles", lambda *args: [roots])
        monkeypatch.setattr(reflow, "regrouper_paragraphes", lambda *args: [roots])
        result = reflow.regrouper_continuations_par_colonne(roots)
    else:
        monkeypatch.setattr(reflow, "regrouper_frames", lambda *args: [roots])
        result = reflow.regrouper_continuations_par_frame(roots)
    assert result == roots


@pytest.mark.parametrize("texts", [(" \t", "visible"), (" \t", "  ")])
def test_first_blank_block_never_drops_later_components(texts):
    roots = [text_box(text, ident, y) for text, ident, y in zip(texts, ("first", "second"), (10, 24))]
    doc = document(*roots)
    before = deepcopy(doc)
    fused = fusionner_flow_paragraphes(deepcopy(roots))
    assert [line.source_id for line in fused.lignes] == ["first:line", "second:line"]
    assert [span.texte for line in fused.lignes for span in line.spans] == list(texts)
    assert all(observation_is_preserved(root, [fused]) for root in roots)
    plan = build_document_render_plan(doc)
    assert plan.validate(doc) == []
    assert set(plan.source_coverage) == set(plan.source_inventory)
    assert doc == before


def test_synthetic_flow_lines_cannot_authorize_acquisition_fusion():
    source = text_box("next part", "second", 24)
    span = source.lignes[0].spans[0]
    flat = FlowParagraph(source.bbox, "first part", span.police, 12, "123456", source_id="flat")
    with pytest.raises(ValueError, match="incompatible-text-fusion:missing-exact-text-rows"):
        fusionner_flow_paragraphes([flat, source])


@pytest.mark.parametrize("field", ["transform", "alpha", "clip_bbox", "z_order"])
def test_new_parent_paint_contract_cannot_be_added_after_compilation(field):
    doc = document(text_box("first part", "first", 10))
    plan = build_render_plan(doc)
    setattr(merged_payload(plan), field, BBox(0, 0, 1, 1) if field == "clip_bbox" else (0 if field != "transform" else (1, 0, 0, 1, 1, 0)))
    assert "unverified-source-transform:first" in plan.validate(doc)


def test_direct_fusion_cannot_drop_different_dynamic_parent_metadata():
    roots = [text_box("first part", "first", 10), text_box("next part", "second", 24)]
    roots[0].source_annotation = {"paint": 0}
    roots[1].source_annotation = {"paint": 1}
    with pytest.raises(ValueError, match="incompatible-text-fusion"):
        fusionner_flow_paragraphes(roots)


@pytest.mark.parametrize("field", ["evidence", "decision_history"])
def test_acquired_parent_history_and_evidence_cannot_be_dropped(field):
    root = text_box("first part", "first", 10)
    root.evidence = [Evidence("source", "extract", 0, (("paint", 0),))]
    root.decision_history = [{"event": "acquired", "confidence": 0}]
    doc = document(root)
    plan = build_render_plan(doc)
    assert plan.validate(doc) == []
    setattr(merged_payload(plan), field, [])
    assert "unverified-source-transform:first" in plan.validate(doc)


def test_flat_flow_uses_real_acquired_spans_without_claiming_a_source_line():
    from pdfexact.render.reflow import _lines

    span = text_box("flat text", "flat", 10).lignes[0].spans[0]
    span.surlignage = "yellow"
    flat = FlowParagraph(span.bbox, span.texte, span.police, span.size_pt, span.couleur, spans=[span])
    doc = document(flat)
    rows = _lines(flat)
    assert rows[0].source_id is None
    assert rows[0].spans[0] is span
    assert not any(isinstance(node, Line) for node in observation_nodes(flat))
    before = deepcopy(doc.pages[0].source_inventory)
    plan = build_render_plan(doc)
    assert plan.validate(doc) == []
    assert doc.pages[0].source_inventory == before


def test_fused_components_keep_order_between_separate_acquired_roots():
    doc = two_boxes()
    plan = build_document_render_plan(doc)
    merged_payload(plan).lignes.reverse()
    assert any("component-order" in error for error in plan.validate(doc))


def test_overlapping_frame_proposals_cannot_drop_the_last_source(monkeypatch):
    roots = [text_box("first part", "first", 10), text_box("next part", "second", 24),
             text_box("last part", "third", 38)]
    monkeypatch.setattr("pdfexact.render.reflow.regrouper_frames", lambda *args: [roots[:2], roots[1:]])
    outputs = regrouper_continuations_par_frame(roots)
    assert [span.texte for output in outputs for line in output.lignes for span in line.spans] == [
        "first part", "next part", "last part",
    ]


def list_document(acquisition):
    marker = text_box("*", "marker", 10)
    marker_box = BBox(u(1), u(10), u(5), u(22))
    for node in observation_nodes(marker):
        node.bbox = marker_box
    marker.lignes[0].largeur_cible_emu = marker_box.largeur
    marker.lignes[0].spans.append(replace(marker.lignes[0].spans[0], texte=" ", source_id="marker:space"))
    body = text_box("Body text", "body", 10)
    body.lignes.append(text_box("next line", "continuation", 24).lignes[0])
    body.bbox = replace(body.bbox, y1=body.lignes[-1].bbox.y1)
    body.presentation["paragraph_validated"] = True
    if acquisition == "attached":
        body.list_marker_source = marker
        body.list_marker = "bullet"
        return document(body)
    return document(*([marker, body] if acquisition == "marker-first" else [body, marker]))


@pytest.mark.parametrize("acquisition", ["marker-first", "body-first", "attached"])
def test_attached_components_follow_rendered_structure_not_inventory_insertion(acquisition):
    doc = list_document(acquisition)
    before = deepcopy(doc)
    plan = build_document_render_plan(doc)
    instruction, = plan.instructions_for_page(3)
    rendered = [run.span.source_id for run in instruction.text.native_runs if run.span is not None]
    traversed = [node.source_id for node in observation_nodes(instruction.element) if type(node) is Span]
    assert rendered == traversed == ["marker:span", "marker:space", "body:span", "continuation:span"]
    assert plan.validate(doc) == []
    assert doc == before


@pytest.mark.parametrize("mutation", [
    "body-order", "missing", "duplicate", "paint", "span-order", "identity", "wrong-page", "unbound",
])
def test_attached_components_keep_body_order_and_strict_source_obligations(mutation):
    doc = list_document("marker-first")
    plan = build_document_render_plan(doc)
    inventory = deepcopy(doc.pages[0].source_inventory)
    payload = merged_payload(plan)
    marker = payload.list_marker_source
    if mutation == "body-order":
        payload.lignes.reverse()
    elif mutation == "missing":
        payload.list_marker_source = None
    elif mutation == "duplicate":
        marker.lignes.append(deepcopy(marker.lignes[0]))
    elif mutation == "paint":
        marker.lignes[0].spans[0].couleur = "FFFFFF"
    elif mutation == "span-order":
        marker.lignes[0].spans.reverse()
    elif mutation == "identity":
        marker.source_id = "invented-marker"
    elif mutation == "wrong-page":
        marker.source_page_index = 4
    else:
        plan.for_page(3)[0].element.raw.list_marker_source = None
    assert plan.validate(doc)
    assert doc.pages[0].source_inventory == inventory


def test_derived_container_snapshots_do_not_duplicate_acquired_line_order(monkeypatch):
    from pdfexact.analysis.text_segmentation import segmenter_page_textes

    root = text_box("first part", "first", 10)
    root.lignes.append(text_box("next part", "second", 24).lignes[0])
    root.bbox = replace(root.bbox, y1=root.lignes[-1].bbox.y1)
    doc = document(root)
    acquired = deepcopy(doc.pages[0].source_inventory)
    monkeypatch.setattr("pdfexact.analysis.text_segmentation.comprendre_segmentation_page", lambda *args, **kwargs: None)
    segmenter_page_textes(doc.pages[0])
    plan = build_render_plan(doc)
    assert len(plan.source_inventory) > len(acquired)
    assert all(doc.pages[0].source_inventory[ident] == raw for ident, raw in acquired.items())
    assert plan.validate(doc) == []
    payload = merged_payload(plan)
    payload.lignes.reverse()
    assert any("component-order" in error for error in plan.validate(doc))


def test_paint_fragments_keep_dynamic_metadata_without_repairing_mutations():
    from pdfexact.ir import ShapeEl

    root = text_box("first part", "first", 10)
    later = text_box("next part", "second", 24).lignes[0]
    later.z_index = 2
    later.spans[0] = replace(later.spans[0], z_index=2, z_order=2)
    root.lignes.append(later)
    root.bbox = replace(root.bbox, y1=later.bbox.y1)
    root.transform = (1, 0, 0, 1, 0, 0)
    root.lignes[0].source_note = {"confidence": 0, "unknown": None}
    cover = ShapeEl(BBox(u(30), u(8), u(200), u(60)), [], "FFFFFF", None, 0, z_index=1)
    doc = document(root, cover)
    acquired = deepcopy(doc.pages[0].source_inventory)
    plan = build_render_plan(doc)
    outputs = [instruction.element for instruction in plan.instructions_for_page(3)
               if isinstance(instruction.element, (TextBox, FlowParagraph))]
    assert len(outputs) == 2
    assert all(output.transform == root.transform for output in outputs)
    assert outputs[0].lignes[0].source_note == root.lignes[0].source_note
    assert all(node.source_page_index == 3 for output in outputs for node in observation_nodes(output))
    assert plan.validate(doc) == []
    outputs[1].lignes[0].source_page_index = 4
    assert "unverified-source-transform:second:line" in plan.validate(doc)
    assert doc.pages[0].source_inventory == acquired


def confidence_document(values, *, source_kind="pdf-native"):
    roots = [text_box("first part", "first", 10), text_box("next part", "second", 24)]
    for root, parent_confidence, child_confidence in zip(roots, values, (.91, .97)):
        root.confidence = parent_confidence
        for node in observation_nodes(root):
            node.source_kind = source_kind
        root.lignes[0].confidence = child_confidence
        root.lignes[0].spans[0].confidence = child_confidence
    return document(*roots)


@pytest.mark.parametrize("source_kind", ["pdf-native", "ocr"])
@pytest.mark.parametrize("values", [(None, None), (.91, .97), (0., .97), (None, 0.), (0., 0.), (.91, .91)])
def test_source_confidence_metadata_allows_fusion_without_losing_values(values, source_kind):
    from pdfexact.analysis.provenance import text_fusion_errors

    doc = confidence_document(values, source_kind=source_kind)
    before = deepcopy(doc)
    assert text_fusion_errors(doc.pages[0].elements) == []
    plan = build_document_render_plan(doc)
    payload = merged_payload(plan)
    assert payload.confidence == (values[0] if values[0] == values[1] else None)
    assert payload.lignes == [root.lignes[0] for root in before.pages[0].elements]
    assert plan.validate(doc) == []
    assert doc == before
    if values[0] != values[1]:
        for root in before.pages[0].elements:
            claims = [entry for entry in payload.evidence if entry.kind == "source-confidence"
                      and entry.source == root.source_id]
            assert claims and all(entry.confidence == root.confidence for entry in claims)
            assert observation_is_preserved(root, [payload])


@pytest.mark.parametrize("level", ["line", "span"])
@pytest.mark.parametrize(("original", "changed"), [(.91, .97), (.91, None), (0., None), (None, 0.)])
def test_line_span_confidence_changes_or_loss_are_rejected(level, original, changed):
    root = text_box("first part", "first", 10)
    source = root.lignes[0] if level == "line" else root.lignes[0].spans[0]
    source.confidence = original
    doc = document(root)
    inventory = deepcopy(doc.pages[0].source_inventory)
    plan = build_render_plan(doc)
    assert plan.validate(doc) == []
    payload = merged_payload(plan)
    target = payload.lignes[0] if level == "line" else payload.lignes[0].spans[0]
    target.confidence = changed
    target.evidence.append(Evidence("source-confidence", source.source_id, original))
    errors = plan.validate(doc)
    assert f"unverified-source-transform:first:{level}" in errors
    assert "unverified-source-transform:first:line" in errors
    assert "unverified-source-transform:first" in errors
    assert doc.pages[0].source_inventory == inventory


@pytest.mark.parametrize("mutation", ["missing", "value", "source", "binding", "claim-only", "summary"])
def test_aggregate_confidence_requires_measured_source_evidence(mutation):
    doc = confidence_document((.91, .97))
    inventory = deepcopy(doc.pages[0].source_inventory)
    plan = build_document_render_plan(doc)
    payload = merged_payload(plan)
    assert plan.validate(doc) == []
    position = next(index for index, entry in enumerate(payload.evidence)
                    if entry.kind == "source-confidence" and entry.source == "second")
    original = payload.evidence[position]
    if mutation in {"missing", "claim-only"}:
        payload.evidence.pop(position)
        if mutation == "claim-only":
            payload.attributes["source_confidence"] = {"second": .97, "verified": True}
    elif mutation == "value":
        payload.evidence[position] = replace(original, confidence=.12)
    elif mutation == "source":
        payload.evidence[position] = replace(original, source="foreign-source")
    elif mutation == "binding":
        payload.evidence[position] = replace(original, details=())
    else:
        payload.confidence = .91
    assert "unverified-source-transform:second" in plan.validate(doc)
    assert doc.pages[0].source_inventory == inventory


def test_confidence_provenance_survives_equal_then_mixed_fusions():
    doc = confidence_document((.91, .91))
    third = text_box("last part", "third", 38)
    third.confidence = .97
    fourth = text_box("final part", "fourth", 52)
    fourth.confidence = .97
    doc.pages[0].elements.extend([third, fourth])
    capture_source_observations(doc.pages[0], [third, fourth])
    inventory = deepcopy(doc.pages[0].source_inventory)
    first, second, third, fourth = deepcopy(doc.pages[0].elements)
    equal = fusionner_flow_paragraphes([first, second])
    assert equal.confidence == .91
    other = fusionner_flow_paragraphes([third, fourth])
    fused = fusionner_flow_paragraphes([equal, other])
    assert fused.confidence is None
    assert all(observation_is_preserved(root, [fused]) for root in doc.pages[0].elements)
    doc.pages[0].elements = [fused]
    assert build_render_plan(doc).validate(doc) == []
    assert doc.pages[0].source_inventory == inventory
