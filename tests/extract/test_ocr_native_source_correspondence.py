"""OCR/native selection must preserve acquisition identities, not just text."""
from copy import deepcopy
from types import SimpleNamespace

import pymupdf
import pytest

from pdfexact.analysis.provenance import observation_is_preserved
from pdfexact.extract import ocr
from pdfexact.extract.fonts import collecter_polices
from pdfexact.extract.layout_map import construire_layout_map
from pdfexact.extract.text import extraire_texte
from pdfexact.geometry import PageGeometry
from pdfexact.ir import Document, Page, element_source_ids, element_text
from pdfexact.render.render_plan import build_render_plan, build_scene_render_plan
from pdfexact.scene import _snapshot_value, scene_from_legacy_document


@pytest.fixture
def acquire(monkeypatch, pdf_texte):
    def run(*, conflict=False, duplicate_observation=False, native_variant=None, routing_ambiguous=False):
        with pymupdf.open(pdf_texte) as pdf:
            page_pdf = pdf[0]
            if native_variant == "blank-only":
                width, height = page_pdf.rect.width, page_pdf.rect.height
                pdf.new_page(width=width, height=height)
                pdf.delete_page(0)
                page_pdf = pdf[0]
                page_pdf.insert_text((width / 4, height / 4), "  ", fontname="helv", fontsize=12)
            elif native_variant:
                block = next(item for item in page_pdf.get_text("dict")["blocks"] if item["type"] == 0)
                span = block["lines"][0]["spans"][0]
                origin = span["origin"]
                text = span["text"]
                if native_variant == "invisible":
                    origin = (origin[0], origin[1] + span["size"] * 4)
                    text = "Invisible source sample"
                page_pdf.insert_text(origin, text, fontname="helv", fontsize=span["size"],
                                     color=(.8, .1, .1),
                                     fill_opacity=0 if native_variant == "invisible" else .45)
            geometry = PageGeometry.depuis_page(page_pdf)
            fonts = collecter_polices(pdf)
            native = extraire_texte(page_pdf, fonts, geometry)
            native_lines = [line for element in native for line in element.lignes]
            factor = 72.0 / 150
            boxes = []
            for line in native_lines:
                bbox = line.bbox
                # Deliberately padded detector regions, not corpus coordinates.
                dx, dy = bbox.largeur * 0.04, bbox.hauteur * 0.12
                x0, y0 = (bbox.x0 - dx) / 12700 / factor, (bbox.y0 - dy) / 12700 / factor
                x1, y1 = (bbox.x1 + dx) / 12700 / factor, (bbox.y1 + dy) / 12700 / factor
                boxes.append(((x0, y0), (x1, y0), (x1, y1), (x0, y1)))
            texts = [element_text(line) for line in native_lines]
            if native_variant == "blank-only":
                texts, boxes = [], []
            if conflict:
                texts[0] = "Conflicting recognition, not the native sentence"
            if duplicate_observation:
                texts.append(texts[0])
                boxes.append(boxes[0])
            result = SimpleNamespace(txts=texts, scores=[.91] * len(texts), boxes=boxes,
                                     word_results=[], routing_warnings=[{"reason": "mock-model-unavailable"}],
                                     routing_elapsed_seconds=0.0)
            if routing_ambiguous:
                result.routing_evidence = [{"ambiguous": index == 0, "candidates": []}
                                           for index in range(len(texts))]
            engine_calls = []

            def engine(image, **kwargs):
                engine_calls.append(kwargs)
                return result

            monkeypatch.setattr(ocr, "_rapidocr", lambda **kwargs: engine)
            captured = []
            raw_inventory = {}
            original_capture = ocr._capture_ocr_lines

            def capture(*args, **kwargs):
                values = original_capture(*args, **kwargs)
                captured.extend(deepcopy(values))
                raw_inventory.update(_snapshot_value(args[2].source_inventory))
                return values

            with monkeypatch.context() as scoped:
                scoped.setattr(ocr, "_capture_ocr_lines", capture)
                page = Page(0, geometry.largeur_emu, geometry.hauteur_emu)
                outputs = ocr.extraire_rapidocr(
                    page_pdf, fonts, dpi=150, granularite="line", layout="word-native",
                    layout_map=construire_layout_map(page_pdf, geometrie=geometry),
                    geometrie=geometry, observation_page=page, language="auto",
                )
            page.elements = outputs
            document = Document([page], polices=fonts)
            document.scene = scene_from_legacy_document(document)
            assert len(engine_calls) == 1
            assert len(captured) == len(texts)
            for ident, snapshot in raw_inventory.items():
                assert _snapshot_value(page.source_inventory[ident]) == snapshot
            assert "mock-model-unavailable" in str(_snapshot_value(page.diagnostics))
            return document, native, captured
    return run


def test_padded_ocr_regions_have_explicit_mapping_for_all_six_observations(acquire):
    document, native, captured = acquire()
    raw_ids = {ident for source in captured for ident in element_source_ids(source)}
    assert len(raw_ids) == 6
    assert [element_text(item) for item in document.pages[0].elements] == [element_text(item) for item in native]
    for source in captured:
        counterpart = next(item for item in document.pages[0].elements if element_text(item) == element_text(source))
        assert ocr.overlap_ratio(source.bbox, counterpart.bbox) < 1.0

    plan = build_render_plan(document)

    assert plan.validate() == []
    assert raw_ids <= set(plan.source_coverage)
    assert all(plan.source_coverage[ident].target_ids for ident in raw_ids)


def test_native_selection_retains_native_kind_and_exact_source_children(acquire):
    document, native, captured = acquire()
    outputs = document.pages[0].elements

    assert all(item.source_kind == "pdf-native" for item in outputs)
    for source in native:
        assert observation_is_preserved(source, outputs)
        assert set(element_source_ids(source)) <= {ident for output in outputs for ident in element_source_ids(output)}
    assert all(source.source_kind == "ocr" for source in captured)
    raw_ids = {ident for source in captured for ident in element_source_ids(source)}
    assert not raw_ids.intersection(ident for output in outputs for ident in element_source_ids(output))
    for output in outputs:
        assert output.confidence is None
        for line in output.lignes:
            assert _snapshot_value(line) == _snapshot_value(document.pages[0].source_inventory[line.source_id])


def test_native_selection_records_evidence_instead_of_flat_id_union(acquire):
    document, native, captured = acquire()
    page = document.pages[0]
    raw_parents = {source.source_id for source in captured}
    events = [event for event in page.source_transformations
              if raw_parents.intersection(event["source_ids"])]

    assert events, "record the actual OCR/native selection before adapting paragraphs"
    assert any(evidence.kind == "ocr-native-source-match"
               for item in page.elements for evidence in item.evidence)
    snapshots = _snapshot_value(page.source_inventory)
    assert all(source.source_id in snapshots for source in captured)
    assert all(source.source_id in snapshots for source in native)


def test_conflicting_ocr_observation_remains_pending_with_explicit_diagnostic(acquire):
    document, native, captured = acquire(conflict=True)
    page = document.pages[0]
    conflict = captured[0]
    assert conflict.source_id in page.source_inventory
    assert [element_text(item) for item in page.elements] == [element_text(item) for item in native]
    assert not any(conflict.source_id in element_source_ids(item) for item in page.elements)
    records = {item.element_id: item for item in document.scene.all_elements()}
    assert records[conflict.source_id].render_decision is None
    assert records[conflict.source_id].verification_state.value == "detected"
    assert any(evidence.kind == "ocr-native-source-conflict"
               for evidence in [*page.diagnostics, *(proof for item in page.elements for proof in item.evidence)])


def match_proofs(page):
    return [dict(evidence.details)["proof"] for item in page.elements for evidence in item.evidence
            if evidence.kind == "ocr-native-source-match"]


def test_duplicate_ocr_observations_stay_ambiguous_without_native_id_aliases(acquire):
    document, native, captured = acquire(duplicate_observation=True)
    page = document.pages[0]
    inventory = _snapshot_value(page.source_inventory)
    duplicate_roots = {captured[0].source_id, captured[-1].source_id}

    assert all(observation_is_preserved(source, page.elements) for source in native)
    assert not duplicate_roots.intersection(proof["observation_ref"]["root_id"] for proof in match_proofs(page))
    assert any("ambiguous-correspondence" in str(evidence.details) for evidence in page.diagnostics)
    errors = build_render_plan(document).validate()
    assert all(f"uncovered-source:{ident}" in errors for ident in duplicate_roots)
    assert _snapshot_value(page.source_inventory) == inventory


def test_distinct_native_paint_variants_are_retained_not_semantic_duplicates(acquire):
    document, native, captured = acquire(native_variant="visible")
    page = document.pages[0]
    repeated = [line for output in page.elements for line in output.lignes
                if element_text(line) == element_text(captured[0])]

    assert len(repeated) == 2
    assert len({line.source_id for line in repeated}) == 2
    assert len({span.couleur for line in repeated for span in line.spans}) == 2
    assert len({span.opacity for line in repeated for span in line.spans}) == 2
    assert all(observation_is_preserved(source, page.elements) for source in native)
    assert all("duplicate_of" not in output.attributes for output in page.elements)
    assert any(span.z_index == 0 for output in page.elements for line in output.lignes for span in line.spans)
    assert any("ambiguous-correspondence" in str(evidence.details) for evidence in page.diagnostics)
    assert build_render_plan(document).validate(), "ambiguous OCR must not be certified as covered"


def test_invisible_native_paint_is_preserved_but_cannot_cover_visible_ocr(acquire):
    document, native, captured = acquire(native_variant="invisible")
    page = document.pages[0]
    invisible_lines = [line for source in native for line in source.lignes
                       if any(span.opacity == 0 for span in line.spans)]

    assert invisible_lines
    assert all(observation_is_preserved(source, page.elements) for source in native)
    assert not {line.source_id for line in invisible_lines}.intersection(
        proof["native_ref"]["line_id"] for proof in match_proofs(page))
    assert any("native-visibility-unproven" in str(evidence.details) for evidence in page.diagnostics)
    assert any("uncovered-source" in error for error in build_render_plan(document).validate())


def test_ambiguous_routing_evidence_is_not_promoted_by_exact_native_text(acquire):
    document, native, captured = acquire(routing_ambiguous=True)
    page = document.pages[0]

    assert captured[0].confidence is None
    assert all(observation_is_preserved(source, page.elements) for source in native)
    assert not any(proof["observation_ref"]["root_id"] == captured[0].source_id
                   for proof in match_proofs(page))
    assert any("ambiguous-ocr-acquisition" in str(evidence.details) for evidence in page.diagnostics)
    assert f"uncovered-source:{captured[0].source_id}" in build_render_plan(document).validate()


@pytest.mark.parametrize("tamper", ["event", "native-id", "signature", "style", "foreign-page"])
def test_produced_correspondence_still_rejects_forged_or_stale_materialization(acquire, tamper):
    document, native, captured = acquire()
    page = document.pages[0]
    inventory = _snapshot_value(page.source_inventory)
    assert build_render_plan(document).validate() == []
    proof = match_proofs(page)[0]
    if tamper == "event":
        page.source_transformations[0]["event_id"] = "forged:" + proof["selection_event_id"]
    elif tamper == "native-id":
        proof["native_ref"]["line_id"] = "missing:" + proof["native_ref"]["line_id"]
    elif tamper == "signature":
        proof["native_ref"]["node_sha256"][proof["native_ref"]["line_id"]] = "0" * 64
    elif tamper == "style":
        page.elements[0].lignes[0].spans[0].souligne = not page.elements[0].lignes[0].spans[0].souligne
    else:
        proof["page"]["index"] += 1
    document.scene = scene_from_legacy_document(document)

    assert build_render_plan(document).validate(), "forged producer evidence must not bypass the guard"
    assert _snapshot_value(page.source_inventory) == inventory


def test_canonical_scene_retains_independent_acquisition_page_binding(acquire):
    document, native, captured = acquire()
    page = document.pages[0]
    scene_page = document.scene.pages[0]

    assert scene_page.ocr_correspondence_page_binding == page.ocr_correspondence_page_binding
    assert scene_page.ocr_correspondence_page_binding is not page.ocr_correspondence_page_binding
    assert document.scene.snapshot()["pages"][0]["ocr_correspondence_page_binding"] == page.ocr_correspondence_page_binding
    for owner in page.elements:
        record = scene_page.registry.elements[owner.source_id]
        assert _snapshot_value(record.acquisition_raw) == _snapshot_value(page.source_inventory[owner.source_id])
        assert record.acquisition_raw is not page.source_inventory[owner.source_id]
        assert record.raw is not record.acquisition_raw
        assert any(evidence.kind == "ocr-native-source-match" for evidence in record.raw.evidence)
        assert not any(evidence.kind == "ocr-native-source-match" for evidence in record.acquisition_raw.evidence)
        assert "acquisition_raw" not in record.snapshot()


def test_native_blank_only_source_survives_empty_ocr_result(acquire):
    document, native, captured = acquire(native_variant="blank-only")
    page = document.pages[0]

    assert native and not captured
    assert page.elements
    assert all(observation_is_preserved(source, page.elements) for source in native)
    assert not match_proofs(page), "empty OCR must not fabricate successful correspondence"
    assert build_render_plan(document).validate() == []


@pytest.mark.parametrize("entrypoint", ["document", "scene"])
def test_acquisition_copy_on_output_cannot_hide_changed_materialized_source(acquire, entrypoint):
    document, native, captured = acquire()
    page = document.pages[0]
    inventory = _snapshot_value(page.source_inventory)
    output = page.elements[0]
    output.acquisition_raw = deepcopy(page.source_inventory[output.source_id])
    output.lignes[0].spans[0].couleur = "13579B"
    document.scene = scene_from_legacy_document(document)
    record = document.scene.pages[0].registry.elements[output.source_id]
    assert _snapshot_value(record.acquisition_raw) == inventory[output.source_id]
    assert record.raw.lignes[0].spans[0].couleur == "13579B"

    if entrypoint == "document":
        plan = build_render_plan(document)
    else:
        plan = build_scene_render_plan(document.scene)

    errors = plan.validate()
    assert any("native-source-not-preserved" in error or "unverified-source-transform" in error for error in errors)
    assert _snapshot_value(page.source_inventory) == inventory
