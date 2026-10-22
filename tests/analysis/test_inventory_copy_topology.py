"""Inventory snapshots copy a registered graph once per immutable phase."""
import copy
from collections import Counter
import json

import pytest

from pdfexact.analysis.provenance import ElementRegistry
from pdfexact.geometry import BBox
from pdfexact.ir import Document, FontRef, Line, Page, Span, TextBox, element_source_ids
from pdfexact.layout.text_comprehension import configurer_fournisseur_comprehension_texte, contexte_comprehension_texte
from pdfexact.render import render_plan
from pdfexact.scene import (
    ElementKind, ElementRecord, PageScene, SceneDocument, SourceKind, _snapshot_value,
    capture_source_observations, scene_from_legacy_document,
)


def source(index=0):
    ident = f"source-{index}"
    bbox = BBox(100, 100 + index * 200, 2000, 200 + index * 200)
    span = Span("source text", FontRef("font", "Arial", False, False), 12, "000000",
                bbox=bbox, source_id=ident + ":span", source_kind="pdf-native", z_index=0)
    span.opacity = 0
    line = Line(bbox, [span], 100, bbox.largeur, source_id=ident + ":line",
                source_kind="pdf-native", z_index=0)
    return TextBox(bbox, [line], source_id=ident, source_kind="pdf-native", z_index=0)


def registered_scene():
    shared = {"zero": 0, "unknown": None, "nested": [1, 2]}
    records = []
    for index in range(3):
        raw = source(index)
        record = ElementRecord(raw.source_id, 0, ElementKind.TEXT, raw.bbox, SourceKind.PDF_NATIVE,
                               source_ids=element_source_ids(raw), raw=raw, acquisition_raw=copy.deepcopy(raw))
        record.public_dynamic = shared
        record.public_callable = source
        records.append(record)
    return SceneDocument([PageScene(0, 3000, 3000, records)])


@pytest.fixture(autouse=True)
def no_model_provider():
    with contexte_comprehension_texte():
        configurer_fournisseur_comprehension_texte(None)
        yield


@pytest.mark.parametrize("phase", ["previous", "rebuilt"])
def test_registered_collection_copies_each_record_once(monkeypatch, phase):
    scene = registered_scene()
    original = {record.element_id: record for record in scene.all_elements()}
    document = Document(scene=scene if phase == "previous" else None)
    monkeypatch.setattr(render_plan, "scene_from_legacy_document",
                        lambda document: SceneDocument() if phase == "previous" else scene)
    counts = Counter()
    reconstruct = copy._reconstruct

    def counted(value, *args, **kwargs):
        if isinstance(value, (ElementRecord, ElementRegistry)):
            counts[type(value).__name__] += 1
        return reconstruct(value, *args, **kwargs)

    monkeypatch.setattr(copy, "_reconstruct", counted)
    inventory = render_plan._inventory_for_document(document)
    print(json.dumps({"phase": phase, "copies": dict(counts)}, sort_keys=True))
    assert counts == {"ElementRecord": 3, "ElementRegistry": 2}
    assert set(inventory) == set(original)
    for ident, record in inventory.items():
        assert _snapshot_value(record) == _snapshot_value(original[ident])
        assert record is not original[ident]
        assert record.raw is not original[ident].raw
        assert record.acquisition_raw is not original[ident].acquisition_raw
        assert record.raw is not record.acquisition_raw
        assert record.public_callable is source
        assert record.public_dynamic is not original[ident].public_dynamic
        assert record._registries[1].elements[ident] is record
        assert all(record._registries[1].elements[key] is inventory[key] for key in inventory)
    assert inventory["source-0"].public_dynamic is inventory["source-1"].public_dynamic


def test_registry_wins_and_snapshot_remains_independent(monkeypatch):
    scene = registered_scene()
    winner = copy.deepcopy(scene.pages[0].elements[0])
    winner.attributes["owner"] = "registry"
    winner.raw.attributes["owner"] = "registry"
    registry = ElementRegistry(elements={winner.element_id: winner})
    document = Document(scene=scene, element_registry=registry)
    monkeypatch.setattr(render_plan, "scene_from_legacy_document", lambda document: SceneDocument())
    before = _snapshot_value(winner)
    inventory = render_plan._inventory_for_document(document)
    snapshot = inventory[winner.element_id]
    assert _snapshot_value(snapshot) == before
    winner.raw.attributes["owner"] = "later"
    winner.public_dynamic["nested"].append(3)
    assert _snapshot_value(snapshot) == before
    assert snapshot.raw is not snapshot.acquisition_raw


def test_capture_boundary_and_each_call_take_fresh_snapshots(monkeypatch):
    import pdfexact.scene as scene_module

    scene = registered_scene()
    record = scene.pages[0].elements[0]
    document = Document([Page(0, 3000, 3000)], scene=scene)
    calls = []

    def capture(page, elements):
        calls.append(1)
        record.raw.attributes["phase"] = len(calls)

    monkeypatch.setattr(scene_module, "capture_source_observations", capture)
    monkeypatch.setattr(render_plan, "scene_from_legacy_document", lambda document: scene)
    first = render_plan._inventory_for_document(document)
    second = render_plan._inventory_for_document(document)
    assert first[record.element_id].raw.attributes["phase"] == 1
    assert second[record.element_id].raw.attributes["phase"] == 2
    assert "phase" not in first[record.element_id].acquisition_raw.attributes
    assert first[record.element_id].raw is not second[record.element_id].raw
    assert record.raw.attributes["phase"] == 2


def test_real_source_mutation_after_plan_is_still_refused():
    raw = source()
    document = Document([Page(0, 3000, 3000, [raw])])
    capture_source_observations(document.pages[0], [raw])
    document.scene = scene_from_legacy_document(document)
    acquired = _snapshot_value(document.pages[0].source_inventory)
    plan = render_plan.build_document_render_plan(document)
    assert plan.validate(document) == []
    raw.lignes[0].spans[0].texte = "changed after plan"
    assert "source-mutated-after-plan:source-0:span" in plan.validate(document)
    fresh = render_plan.build_document_render_plan(document)
    assert "source-mutated-after-plan:source-0:span" in fresh.validate(document)
    assert _snapshot_value(document.pages[0].source_inventory) == acquired
