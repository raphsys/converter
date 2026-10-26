"""A typed OCR observation outcome must never excuse lost native paint."""
from copy import deepcopy
from importlib import import_module

import pytest

from pdfexact.analysis.provenance import Evidence
from pdfexact.geometry import BBox, PageGeometry, pt_vers_emu as u
from pdfexact.ir import Document, FontRef, Line, Page, Span, TextBox
from pdfexact.scene import (
    capture_source_observations, element_record_from_legacy,
    record_source_transformation,
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




def test_shared_builder_can_select_unique_line_without_producer_matching(acquired):
    doc, native, observation = acquired
    proof, errors = helper().build_ocr_native_correspondence(
        observation, None, records(doc.pages[0]), page_binding=doc.pages[0].ocr_correspondence_page_binding,
    )
    assert errors == [] and proof["native_ref"]["line_id"] == native.lignes[0].source_id




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


def test_each_source_node_is_snapshotted_once_per_proof(acquired, monkeypatch):
    # A math page holds hundreds of fragments: re-hashing every tree for every row exploded.
    module = helper()
    vus = []
    original = module._snapshot

    def compte(value):
        if isinstance(value, (TextBox, Line, Span)):  # the costly trees (geometry fields are tiny)
            vus.append(id(value))
        return original(value)

    monkeypatch.setattr(module, "_snapshot", compte)
    doc, native, observation = acquired
    page = doc.pages[0]
    proof, errors = module.build_ocr_native_correspondence(
        observation, native.lignes[0], records(page), page_binding=page.ocr_correspondence_page_binding)
    assert errors == [] and proof is not None
    assert len(vus) == len(set(vus))


def test_a_page_loop_snapshots_its_immutable_inventory_only_once(acquired, monkeypatch):
    module = helper()
    vus = []
    original = module._snapshot

    def compte(value):
        if isinstance(value, (TextBox, Line, Span)):
            vus.append(id(value))
        return original(value)

    monkeypatch.setattr(module, "_snapshot", compte)
    doc, native, observation = acquired
    page = doc.pages[0]
    inventaire = records(page)
    with module.memoire_empreintes():
        for _ in range(3):
            proof, errors = module.build_ocr_native_correspondence(
                observation, native.lignes[0], inventaire, page_binding=page.ocr_correspondence_page_binding)
            assert errors == [] and proof is not None
    assert len(vus) == len(set(vus))
