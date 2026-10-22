"""A typed OCR observation outcome must never excuse lost native paint."""
from copy import deepcopy
from importlib import import_module

import pytest

from pdfexact.analysis.provenance import Evidence
from pdfexact.geometry import BBox, PageGeometry, pt_vers_emu as u
from pdfexact.ir import Document, FontRef, Line, Page, Span, TextBox, element_source_ids
from pdfexact.render.render_plan import SourceCoverage, build_render_plan, build_scene_render_plan
from pdfexact.scene import (
    _snapshot_value, capture_source_observations, element_record_from_legacy,
    record_source_transformation, scene_from_legacy_document,
)


def helper():
    return import_module("pdfexact.analysis.ocr_correspondence")


def source_tree(text, kind, box, *, alpha=255, color="000000"):
    span = Span(text, FontRef("Arial", "Arial", False, False), 10, color,
                bbox=box, source_kind=kind, z_index=0,
                attributes={"source_alpha": alpha} if kind == "pdf-native" else {})
    line = Line(box, [span], box.hauteur, box.largeur, source_kind=kind, z_index=0)
    return TextBox(box, [line], source_kind=kind, z_index=0,
                   attributes={"engine": "rapidocr", "observation_only": True} if kind == "ocr" else {})


@pytest.fixture
def acquired():
    native = source_tree("Exact text", "pdf-native", BBox(u(10), u(10), u(110), u(20)))
    observation = source_tree("Exact text", "ocr", BBox(u(9), u(9), u(111), u(21)))
    page = Page(3, u(200), u(100), [native])
    page.ocr_correspondence_page_binding = {
        "index": 3, "source_pdf_id": None,
        "geometry": PageGeometry(200, 100, 0, None, None).snapshot(),
    }
    capture_source_observations(page, [native, observation])
    return Document([page]), native, observation


def records(page):
    result = {}
    for key, raw in page.source_inventory.items():
        record = element_record_from_legacy(deepcopy(raw), page.index)
        record.attributes["source_page_binding"] = deepcopy(page.ocr_correspondence_page_binding)
        result[key] = record
    return result


def selected(acquired):
    doc, native, observation = acquired
    page = doc.pages[0]
    inventory = records(page)
    proof, errors = helper().build_ocr_native_correspondence(
        observation, native.lignes[0], inventory,
        page_binding=page.ocr_correspondence_page_binding,
    )
    assert errors == [] and proof is not None
    event = record_source_transformation(
        page, [observation], [native], "ocr-native-selection",
        **helper().selection_event_details(proof),
    )
    native.evidence.append(Evidence("ocr-native-source-match", "pdfexact.extract.ocr", None,
                                    (("proof", deepcopy(proof)),)))
    return doc, native, observation, inventory, proof, event


def verify(data, *, proof=None, outputs=None, inventory=None, events=None, source=None):
    doc, native, observation, stored, original, event = data
    return helper().verify_ocr_native_correspondence(
        source or stored[observation.source_id], outputs if outputs is not None else [native],
        inventory if inventory is not None else stored, original if proof is None else proof,
        selection_events=events if events is not None else [event],
    )


def test_unique_padded_observation_has_typed_plan_coverage_without_alias_union(acquired):
    before = _snapshot_value(acquired[0].pages[0].source_inventory)
    data = selected(acquired)
    doc, native, observation, inventory, proof, event = data
    assert verify(data) == []
    for ident in element_source_ids(observation):
        assert verify(data, source=inventory[ident]) == []
    plan = build_render_plan(doc)
    assert plan.validate(doc) == []
    for ident in element_source_ids(observation):
        assert plan.source_coverage[ident].relationship == "observation-superseded-by-native"
        assert plan.source_coverage[ident].target_ids == (native.source_id,)
    assert not set(element_source_ids(observation)).intersection(element_source_ids(native))
    assert _snapshot_value(doc.pages[0].source_inventory) == before


@pytest.mark.parametrize("fake", [None, True, {}, {"schema": "pdfexact.ocr-native-correspondence.v1", "verified": True}])
def test_fake_or_boolean_proof_is_not_verification(acquired, fake):
    data = selected(acquired)
    assert helper().verify_ocr_native_correspondence(
        data[3][data[2].source_id], [data[1]], data[3], fake, selection_events=[data[5]],
    )


@pytest.mark.parametrize("part", ["schema", "relationship", "page", "tree", "hash", "geometry", "text", "candidates", "inverse", "metrics", "components"])
def test_proof_fields_are_recomputed_not_trusted(acquired, part):
    data = selected(acquired)
    proof = deepcopy(data[4])
    if part == "schema":
        proof["schema"] = "other"
    elif part == "relationship":
        proof["relationship"] = "paint-equivalent"
    elif part == "page":
        proof["page"]["index"] = 4
    elif part == "tree":
        proof["native_ref"]["span_ids"] = []
    elif part == "hash":
        proof["native_ref"]["node_sha256"].pop(data[1].lignes[0].spans[0].source_id)
    elif part == "geometry":
        proof["observation_geometry"][data[2].source_id]["bbox"][0] += 1
    elif part == "text":
        proof["text"]["native"] += "changed"
    elif part == "candidates":
        proof["matching"]["candidate_native_line_ids"] = []
    elif part == "inverse":
        proof["matching"]["competing_observation_ids"] = []
    elif part == "metrics":
        proof["matching"]["metrics"]["intersection"] = float("nan")
    else:
        proof["selected_component_ids"] = [data[1].source_id]
    assert verify(data, proof=proof)


@pytest.mark.parametrize("change", ["absent", "duplicated", "invented", "source", "output", "hash", "page"])
def test_actual_selection_event_is_required_and_bound(acquired, change):
    data = selected(acquired)
    event = deepcopy(data[5])
    events = [event]
    if change == "absent":
        events = []
    elif change == "duplicated":
        events.append(deepcopy(event))
    elif change == "invented":
        event["event_id"] = "invented"
    elif change == "source":
        event["source_ids"] = (data[1].source_id,)
    elif change == "output":
        event["output_ids"] = (data[2].source_id,)
    elif change == "hash":
        event["native_node_sha256"] = {}
    else:
        event["page_binding"] = {**event["page_binding"], "index": 4}
    assert verify(data, events=events)


@pytest.mark.parametrize("change", ["missing", "alias", "text", "style", "highlight", "quad", "baseline", "alpha", "z", "order", "foreignpage"])
def test_materialized_native_components_must_be_actual_and_unchanged(acquired, change):
    data = selected(acquired)
    output = deepcopy(data[1])
    line, span = output.lignes[0], output.lignes[0].spans[0]
    if change == "missing":
        output.lignes = []
    elif change == "alias":
        span.source_ids = (span.source_id,)
        span.source_id = "new-id-with-old-alias"
    elif change == "text":
        span.texte += "!"
    elif change == "style":
        span.couleur = "ff0000"
    elif change == "highlight":
        span.surlignage = "yellow"
    elif change == "quad":
        line.quad = ((0, 0), (1, 0), (1, 1), (0, 1))
    elif change == "baseline":
        line.baseline_points = ((0, 0), (1, 0))
    elif change == "alpha":
        span.attributes["source_alpha"] = 0
    elif change == "z":
        span.z_index = 1
    elif change == "order":
        line.spans = [deepcopy(span), span]
    else:
        line.source_page_index = 4
    assert verify(data, outputs=[output])


@pytest.mark.parametrize("change", ["native-as-observation", "engine", "routing", "alpha0", "alpha-unknown", "clip", "transform", "nonserializable"])
def test_acquisition_and_visibility_are_raw_not_adapter_defaults(acquired, change):
    doc, native, observation = acquired
    page = doc.pages[0]
    if change == "native-as-observation":
        for node in (observation, *observation.lignes, *observation.lignes[0].spans):
            node.source_kind = "pdf-native"
    elif change == "engine":
        observation.attributes.pop("engine")
    elif change == "routing":
        observation.attributes["ocr_routing"] = {"ambiguous": True}
    elif change == "alpha0":
        native.lignes[0].spans[0].attributes["source_alpha"] = 0
    elif change == "alpha-unknown":
        native.lignes[0].spans[0].attributes.pop("source_alpha")
    elif change == "clip":
        native.lignes[0].clip_ids = ("unresolved-clip",)
    elif change == "transform":
        native.transform = (1, 0, 0, 1, 20, 0)
    else:
        native.lignes[0].spans[0].attributes["opaque"] = object()
    page.source_inventory = {}
    capture_source_observations(page, [native, observation])
    proof, errors = helper().build_ocr_native_correspondence(
        observation, native.lignes[0], records(page), page_binding=page.ocr_correspondence_page_binding,
    )
    assert proof is None and errors


@pytest.mark.parametrize("duplicate", ["native", "observation"])
def test_all_acquired_candidates_and_inverse_uniqueness_are_checked(acquired, duplicate):
    doc, native, observation = acquired
    extra = source_tree("Exact text", "pdf-native" if duplicate == "native" else "ocr",
                        native.bbox if duplicate == "native" else observation.bbox, color="ff0000")
    capture_source_observations(doc.pages[0], [extra])
    proof, errors = helper().build_ocr_native_correspondence(
        observation, native.lignes[0], records(doc.pages[0]),
        page_binding=doc.pages[0].ocr_correspondence_page_binding,
    )
    assert proof is None and "ambiguous-correspondence" in errors


def test_native_source_cannot_use_observation_outcome_even_with_valid_foreign_proof(acquired):
    data = selected(acquired)
    assert verify(data, source=data[3][data[1].source_id])
    plan = build_render_plan(data[0])
    plan.source_coverage[data[1].source_id] = SourceCoverage(
        (data[1].source_id,), "observation-superseded-by-native", "claimed observation",
    )
    assert any(data[1].source_id in error for error in plan.validate())


def test_shared_builder_can_select_unique_line_without_producer_matching(acquired):
    doc, native, observation = acquired
    proof, errors = helper().build_ocr_native_correspondence(
        observation, None, records(doc.pages[0]), page_binding=doc.pages[0].ocr_correspondence_page_binding,
    )
    assert errors == [] and proof["native_ref"]["line_id"] == native.lignes[0].source_id


@pytest.mark.parametrize("change", ["missing-child", "missing-root", "foreignpage", "live-changed", "new-ids", "unparented"])
def test_inventory_tree_and_acquisition_signatures_cannot_be_faked(acquired, change):
    data = selected(acquired)
    inventory = deepcopy(data[3])
    native = data[1]
    if change == "missing-child":
        inventory.pop(native.lignes[0].spans[0].source_id)
    elif change == "missing-root":
        inventory.pop(native.source_id)
    elif change == "foreignpage":
        inventory[native.lignes[0].source_id].page_index = 4
    elif change == "live-changed":
        inventory[native.lignes[0].source_id].raw.spans[0].couleur = "ff0000"
    elif change == "new-ids":
        inventory[native.lignes[0].source_id].raw.source_id = "new-id"
    else:
        extra = deepcopy(native.lignes[0])
        extra.source_id = "orphan-native-line"
        inventory[extra.source_id] = element_record_from_legacy(extra, 3)
    assert verify(data, inventory=inventory)


@pytest.mark.parametrize("change", ["far", "area", "opposite-angle", "span-angle", "unknown-angle", "invalid-quad", "disjoint-quad", "invalid-span-quad"])
def test_spatial_directed_orientation_and_quad_gates(acquired, change):
    doc, native, observation = acquired
    line = native.lignes[0]
    if change == "far":
        line.bbox = BBox(u(120), u(10), u(190), u(20))
    elif change == "area":
        observation.bbox = observation.lignes[0].bbox = BBox(u(1), u(1), u(150), u(40))
    elif change == "opposite-angle":
        for node in (native, line, *line.spans):
            node.angle_deg = 180
    elif change == "span-angle":
        line.spans[0].angle_deg = 90
    elif change == "unknown-angle":
        native.orientation = line.orientation = "unknown"
    elif change == "invalid-quad":
        line.quad = ((0, 0), (0, 0), (1, 1), (2, 2))
    elif change == "invalid-span-quad":
        line.spans[0].quad = ((0, 0), (1, 1), (2, 2), (3, 3))
    else:
        line.quad = ((u(10), u(10)), (u(50), u(10)), (u(10), u(20)), (u(50), u(20)))
        observation.lignes[0].quad = ((u(70), u(10)), (u(110), u(10)), (u(70), u(20)), (u(110), u(20)))
    doc.pages[0].source_inventory = {}
    capture_source_observations(doc.pages[0], [native, observation])
    proof, errors = helper().build_ocr_native_correspondence(
        observation, None, records(doc.pages[0]), page_binding=doc.pages[0].ocr_correspondence_page_binding,
    )
    assert proof is None and errors


def test_observed_convex_quads_keep_both_original_geometries(acquired):
    doc, native, observation = acquired
    for root in (native, observation):
        b = root.lignes[0].bbox
        root.lignes[0].quad = ((b.x0, b.y0), (b.x1, b.y0), (b.x0, b.y1), (b.x1, b.y1))
    doc.pages[0].source_inventory = {}
    capture_source_observations(doc.pages[0], [native, observation])
    data = selected(acquired)
    assert verify(data) == []
    assert data[4]["observation_geometry"] != data[4]["native_geometry"]
    assert data[4]["matching"]["metrics"]["quad_iou"] >= .5


@pytest.mark.parametrize("change", ["proof", "payload", "inventory", "event", "no-binding"])
def test_provided_plan_revalidates_correspondence_instead_of_trusting_compilation(acquired, change):
    data = selected(acquired)
    plan = build_render_plan(data[0])
    assert plan.validate() == []
    if change == "proof":
        instruction = plan.instructions_for_page(3)[0]
        proof = dict(instruction.element.evidence[0].details)["proof"]
        proof["native_ref"]["node_sha256"] = {}
    elif change == "payload":
        plan.instructions_for_page(3)[0].element.lignes[0].spans[0].surlignage = "yellow"
    elif change == "inventory":
        plan.source_inventory[data[1].lignes[0].source_id].raw.quad = ((0, 0),) * 4
    elif change == "event":
        plan.source_inventory[data[2].source_id].decision_history.clear()
    else:
        for record in plan.source_inventory.values():
            record.attributes.pop("source_page_binding", None)
    assert any("ocr-native-correspondence" in error for error in plan.validate())


def test_scene_only_plan_uses_acquisition_tree_not_owner_with_added_proof(acquired):
    data = selected(acquired)
    scene = scene_from_legacy_document(data[0])
    plan = build_scene_render_plan(scene)
    assert plan.validate() == []
    assert plan.source_coverage[data[2].source_id].relationship == "observation-superseded-by-native"
    assert plan.source_inventory[data[1].source_id].raw.evidence == []


@pytest.mark.parametrize("change", ["highlight", "confidence", "page-binding"])
def test_document_changes_after_plan_are_rejected_without_rebuilding(acquired, change):
    data = selected(acquired)
    doc = data[0]
    plan = build_render_plan(doc)
    assert plan.validate(doc) == []
    if change == "highlight":
        data[1].lignes[0].spans[0].surlignage = "yellow"
    elif change == "confidence":
        data[1].lignes[0].spans[0].confidence = 0.0
    else:
        doc.pages[0].largeur_emu += u(1)
    assert plan.validate(doc)
    assert plan.validate() == []


def test_two_unique_observations_cover_all_six_nodes_without_rewriting_geometry(acquired):
    doc, native, observation = acquired
    second_native = source_tree("Second text", "pdf-native", BBox(u(10), u(50), u(110), u(60)))
    second_observation = source_tree("Second text", "ocr", BBox(u(9), u(49), u(111), u(61)))
    page = doc.pages[0]
    capture_source_observations(page, [second_native, second_observation])
    page.elements.append(second_native)
    snapshot = _snapshot_value(page.source_inventory)
    selected(acquired)
    selected((doc, second_native, second_observation))
    plan = build_render_plan(doc)
    assert plan.validate(doc) == []
    observation_ids = set(element_source_ids(observation)) | set(element_source_ids(second_observation))
    assert len(observation_ids) == 6
    assert all(plan.source_coverage[key].relationship == "observation-superseded-by-native" for key in observation_ids)
    assert not observation_ids.intersection(key for output in page.elements for key in element_source_ids(output))
    assert _snapshot_value(page.source_inventory) == snapshot


@pytest.mark.parametrize("kind", ["native", "observation"])
def test_new_acquired_candidate_invalidates_old_unique_proof(acquired, kind):
    data = selected(acquired)
    extra = source_tree("Exact text", "pdf-native" if kind == "native" else "ocr",
                        data[1].bbox if kind == "native" else data[2].bbox, alpha=0)
    capture_source_observations(data[0].pages[0], [extra])
    assert "ambiguous-correspondence" in verify(data, inventory=records(data[0].pages[0]))


def test_pure_helpers_preserve_unknown_and_zero_confidence_and_inventory(acquired):
    doc, native, observation = acquired
    native.lignes[0].spans[0].confidence = 0.0
    doc.pages[0].source_inventory = {}
    capture_source_observations(doc.pages[0], [native, observation])
    inventory = records(doc.pages[0])
    before = _snapshot_value(inventory)
    proof, errors = helper().build_ocr_native_correspondence(
        observation, None, inventory, page_binding=doc.pages[0].ocr_correspondence_page_binding,
    )
    assert errors == []
    helper().verify_ocr_native_correspondence(
        inventory[observation.source_id], [native], inventory, proof, selection_events=[],
    )
    assert _snapshot_value(inventory) == before
    assert inventory[native.lignes[0].spans[0].source_id].raw.confidence == 0.0
    assert inventory[observation.source_id].raw.confidence is None


@pytest.mark.parametrize("entry", ["direct", "scene"])
def test_acquisition_raw_cannot_hide_modified_actual_materialization(acquired, entry):
    data = selected(acquired)
    if entry == "direct":
        output = deepcopy(data[1])
        output.acquisition_raw = deepcopy(data[0].pages[0].source_inventory[data[1].source_id])
        output.lignes[0].spans[0].surlignage = "yellow"
        assert "native-source-not-preserved" in verify(data, outputs=[output])
    else:
        scene = scene_from_legacy_document(data[0])
        owner = next(record for record in scene.all_elements() if record.element_id == data[1].source_id)
        assert owner.acquisition_raw is not None
        owner.raw.lignes[0].spans[0].surlignage = "yellow"
        plan = build_scene_render_plan(scene)
        assert any("native-source-not-preserved" in error for error in plan.validate())


@pytest.mark.parametrize("gate", ["intersection", "area-ratio", "directed-angle", "quad-iou"])
@pytest.mark.parametrize("accepted", [True, False])
def test_spatial_policy_thresholds_are_fixed_not_proof_controlled(acquired, gate, accepted):
    doc, native, observation = acquired
    observation.bbox = observation.lignes[0].bbox = native.bbox
    if gate == "intersection":
        shift = 20 if accepted else 21
        native.lignes[0].bbox = BBox(u(10 + shift), u(10), u(110 + shift), u(20))
    elif gate == "area-ratio":
        observation.bbox = observation.lignes[0].bbox = BBox(u(10), u(5), u(110), u(25 if accepted else 26))
    elif gate == "directed-angle":
        for node in (native, native.lignes[0], *native.lignes[0].spans):
            node.angle_deg = 8 if accepted else 8.01
    else:
        right = u(60 if accepted else 59)
        native.lignes[0].quad = ((u(10), u(10)), (u(110), u(10)), (u(10), u(20)), (u(110), u(20)))
        observation.lignes[0].quad = ((u(10), u(10)), (right, u(10)), (u(10), u(20)), (right, u(20)))
    doc.pages[0].source_inventory = {}
    capture_source_observations(doc.pages[0], [native, observation])
    proof, errors = helper().build_ocr_native_correspondence(
        observation, None, records(doc.pages[0]), page_binding=doc.pages[0].ocr_correspondence_page_binding,
    )
    assert (proof is not None and errors == []) is accepted
