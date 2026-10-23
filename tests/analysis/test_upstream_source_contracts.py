"""Focused B2/B3 acquisition and canonical adapter regressions."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from pdfexact.geometry import BBox
from pdfexact import ir
from pdfexact.scene import SourceKind, VerificationState, capture_source_observations, element_record_from_legacy, scene_from_legacy_document
from pdfexact.extract.document import (
    _appliquer_filtre_page, _dedoublonner_textes_positionnes,
    _filtrer_textes_intersectant_zones,
)


def text_box(text="AB", *, z=0, color="123456"):
    font = ir.FontRef("actual-font", "Actual Family", True, False, script="Latn", language="fr")
    spans = [ir.Span(char, font, 11, color, bbox=BBox(index * 40, 10, index * 40 + 30, 30),
                     z_index=z, source_kind="pdf-native") for index, char in enumerate(text)]
    line = ir.Line(BBox(0, 10, len(text) * 40, 30), spans, 20, len(text) * 40,
                   quad=((0, 10), (80, 10), (80, 30), (0, 30)), angle_deg=-25,
                   baseline_points=((0, 25), (80, 5)), z_index=z, source_kind="pdf-native")
    return ir.TextBox(line.bbox, [line], z_index=z, source_kind="pdf-native", language="fr", script="Latn")


def test_clone_keeps_dynamic_metadata_without_aliasing():
    source = text_box()
    source.dynamic_metadata = {"native": [0]}
    clone = ir.clone_element_with_metadata(source, bbox=BBox(0, 0, 50, 30))
    clone.dynamic_metadata["native"].append(1)
    clone.lignes[0].spans[0].texte = "changed"
    assert source.dynamic_metadata == {"native": [0]}
    assert ir.element_text(source) == "AB"
    assert clone.bbox == BBox(0, 0, 50, 30)


def test_span_filter_retains_raw_inventory_and_all_geometry_metadata():
    source = text_box()
    source.alpha = 0.0
    source.lignes[0].custom = {"font-evidence": ["native"]}
    page = ir.Page(4, 200, 200, [source])
    capture_source_observations(page, page.elements)
    removed_span_id = source.lignes[0].spans[1].source_id
    old_ids = set(page.source_inventory)
    _appliquer_filtre_page(page, _filtrer_textes_intersectant_zones, [BBox(39, 0, 90, 40)], reason="protected-zone")
    filtered = page.elements[0]
    line = filtered.lignes[0]
    assert ir.element_text(filtered) == "A"
    assert filtered.source_id != source.source_id
    assert filtered.alpha == 0.0 and filtered.z_index == 0
    assert line.angle_deg == -25 and line.z_index == 0
    assert line.quad == source.lignes[0].quad
    assert line.baseline_points == source.lignes[0].baseline_points
    assert line.custom == source.lignes[0].custom
    assert old_ids <= set(page.source_inventory)
    assert ir.element_text(page.source_inventory[source.source_id]) == "AB"
    assert removed_span_id not in ir.element_source_ids(filtered)
    assert removed_span_id in filtered.attributes["removed_source_ids"]
    assert source in page.discarded_elements
    scene = scene_from_legacy_document(ir.Document(pages=[page]))
    removed = scene.registry.elements[removed_span_id]
    assert removed.verification_state is VerificationState.DETECTED
    assert removed.render_decision is None


def test_duplicate_loser_kept_with_verified_winner_and_raw_snapshot():
    winner, loser = text_box(), text_box()
    page = ir.Page(0, 200, 200, [winner, loser])
    _dedoublonner_textes_positionnes(page)
    assert len(page.elements) == 1
    assert page.discarded_elements == [loser]
    assert winner.source_id != loser.source_id
    assert loser.attributes["duplicate_of"] == winner.source_id
    assert loser.attributes["duplicate_verified"] is True
    assert loser.source_id in ir.element_source_ids(winner)
    assert "duplicate_of" not in page.source_inventory[loser.source_id].attributes


@pytest.mark.parametrize("variant", ["color", "font", "alpha", "z", "ocr", "clip"])
def test_native_paint_variants_and_ocr_are_not_equivalent_duplicates(variant):
    first, second = text_box(), text_box()
    if variant == "color":
        second.lignes[0].spans[0].couleur = "FFFFFF"
    elif variant == "font":
        second.lignes[0].spans[0].police = ir.FontRef("other", "Other", True, False)
    elif variant == "alpha":
        second.lignes[0].spans[0].opacity = 0.5
    elif variant == "z":
        second.lignes[0].spans[0].z_index = 1
    elif variant == "ocr":
        second.source_kind = "ocr"
    else:
        second.clip_ids = ("mask",)
    page = ir.Page(0, 200, 200, [first, second])
    _dedoublonner_textes_positionnes(page)
    assert page.elements == [first, second]
    assert page.discarded_elements == []


def test_ambiguous_short_fragment_not_silently_removed():
    whole, fragment = text_box("AB"), text_box("Z")
    whole.layout_frame_id = fragment.layout_frame_id = "same-frame"
    page = ir.Page(0, 200, 200, [whole, fragment])
    _dedoublonner_textes_positionnes(page)
    assert page.elements == [whole, fragment]


def test_factory_preserves_zeroes_full_runs_metrics_clips_history_and_ids():
    box = text_box()
    box.opacity = 0.0
    box.clip_ids = ("native-clip",)
    box.parent_group_id = "native-group"
    box.compositing = {"blend": "multiply"}
    box.decision_history.append({"event": "acquired", "z": 0})
    page = ir.Page(0, 200, 200, [box])
    capture_source_observations(page, page.elements)
    doc = ir.Document(pages=[page], polices={"actual-font": ir.FontAsset("actual-font", "Actual Family", None, "ttf", False,
                                                                         metriques={"ascent": 800})})
    scene = scene_from_legacy_document(doc)
    record = scene.registry.elements[box.source_id]
    again = element_record_from_legacy(box, 0, document=doc)
    assert again.element_id == record.element_id == box.source_id
    assert record.z_order == 0 and record.opacity == 0.0
    assert record.angle_deg == -25 and record.quad == box.lignes[0].quad
    assert record.font_metrics["actual-font"]["metrics"] == {"ascent": 800}
    assert record.style["runs"][0]["police"]["famille"] == "Actual Family"
    assert record.clip_ids == ("native-clip",) and record.parent_group_id == "native-group"
    assert record.compositing == {"blend": "multiply"}
    assert record.confidence is None and record.semantic_confidence is None
    assert len(record.spans) == 2
    assert json.loads(json.dumps(scene.snapshot()))["pages"][0]["elements"][0]["decision_history"] == box.decision_history


def test_render_mode_export_is_the_owned_enum():
    from pdfexact.scene import RenderMode
    from pdfexact.analysis.decisions import RenderMode as OwnedRenderMode

    assert RenderMode is OwnedRenderMode


def test_bboxless_span_is_registered_without_fabricated_geometry():
    box = text_box("A")
    box.lignes[0].spans[0].bbox = None
    doc = ir.Document(pages=[ir.Page(0, 200, 200, [box])])
    scene = scene_from_legacy_document(doc)
    span_id = box.lignes[0].spans[0].source_id
    assert scene.registry.elements[span_id].bbox is None
    assert scene.registry.elements[span_id].attributes["observation_only"] is True
    assert span_id in doc.pages[0].source_inventory


def test_raw_ocr_unmatched_observation_retained_without_invented_font_or_confidence():
    from pdfexact.extract.blocks import OcrLine
    from pdfexact.extract.ocr import _capture_ocr_lines, _finaliser_source_ocr

    page = ir.Page(0, 200, 200)
    pdf_page = SimpleNamespace(number=0)
    sources = [OcrLine("Raw", 0.37, BBox(0, 0, 30, 20)), OcrLine("Rejected", -1, BBox(40, 0, 80, 20))]
    observations = _capture_ocr_lines(pdf_page, sources, page, "actual-engine")
    output = text_box("Raw")
    output.source_kind = "ocr"
    _finaliser_source_ocr(pdf_page, [output], observations, page)
    rejected = page.source_inventory[observations[1].source_id]
    assert ir.element_text(rejected) == "Rejected"
    assert rejected.confidence is None
    assert rejected.lignes[0].spans[0].police.famille == ""
    assert rejected.source_id not in ir.element_source_ids(output)
    assert page.source_inventory[observations[0].source_id].confidence == 0.37


def test_raster_link_captures_components_reason_and_actual_producer_evidence():
    from pdfexact.extract.document import _lier_composants_raster

    shape = ir.ShapeEl(BBox(0, 0, 20, 20), [[("line", ((0, 0), (20, 20)))]], "112233", None, 0, alpha=0.0, z_index=0)
    page = ir.Page(0, 200, 200)
    raster = ir.RasterEl(BBox(0, 0, 20, 20), "actual-raster")
    _lier_composants_raster(page, raster, [shape], "complex-vector-cluster", dpi=144)
    assert raster.source_component_ids == (shape.source_id,)
    assert raster.fallback_reason == "complex-vector-cluster"
    proof = dict(raster.evidence[0].details)
    assert proof["dpi"] == 144 and proof["output_id"] == raster.source_id
    assert proof["source_ids"] == (shape.source_id,)
    assert proof["pixel_equivalence_verified"] is False
    assert raster.evidence[0].confidence is None
    assert page.source_inventory[shape.source_id].alpha == 0.0
    assert shape in page.discarded_elements


def test_acquisition_inventory_before_rejected_tables_outside_vectors_and_raster(monkeypatch):
    import pymupdf
    from pdfexact.extract import document as extractor
    from pdfexact.report import Rapport

    pdf = pymupdf.open()
    pdf_page = pdf.new_page(width=200, height=200)
    geometry = extractor.PageGeometry.depuis_page(pdf_page)
    page = ir.Page(0, geometry.largeur_emu, geometry.hauteur_emu)
    doc = ir.Document(pages=[page])
    rejected_table = ir.TableEl(BBox(0, 0, 40, 40), [], [40], ir.FontRef("f", "real", False, False), 10)
    outside = ir.ShapeEl(BBox(-50, -50, -10, -10), [], "000000", None, 0)
    component = ir.ShapeEl(BBox(50, 50, 70, 70), [], "000000", None, 0)
    monkeypatch.setattr(extractor, "analyser_page", lambda *a, **k: SimpleNamespace(native_line_bboxes=lambda: []))
    monkeypatch.setattr(extractor, "detecter_layout_ia", lambda *a, **k: SimpleNamespace(warnings=[], status="disabled", zones=[]))
    monkeypatch.setattr(extractor, "page_a_des_degrades", lambda *a: False)
    monkeypatch.setattr(extractor, "extraire_tableaux", lambda *a, **k: [rejected_table])
    monkeypatch.setattr(extractor, "extraire_tableaux_listing", lambda *a, **k: [])
    monkeypatch.setattr(extractor, "_tableau_ressemble_graphe", lambda *a: False)
    monkeypatch.setattr(extractor, "_tableau_ressemble_bandeau_entete", lambda *a: True)
    monkeypatch.setattr(extractor, "extraire_vectoriel", lambda *a, **k: [outside, component])
    monkeypatch.setattr(extractor, "regrouper", lambda shapes: [[shape] for shape in shapes])
    monkeypatch.setattr(extractor, "doit_rasteriser", lambda *a: True)
    monkeypatch.setattr(extractor, "_zone_visuelle_garde_texte_original", lambda *a: False)
    monkeypatch.setattr(extractor, "rasteriser_region", lambda _page, bbox, *_a, **_k: ir.RasterEl(bbox, "raster"))
    monkeypatch.setattr(extractor, "extraire_zones_shading", lambda *a: [])
    monkeypatch.setattr(extractor, "extraire_images_rasterisees", lambda *a, **k: [])
    monkeypatch.setattr(extractor, "extraire_images_inline_rasterisees", lambda *a, **k: [])

    class StopAfterAcquisition(Exception):
        pass

    def stop(**kwargs):
        raise StopAfterAcquisition

    monkeypatch.setattr(extractor, "comprendre_page", stop)
    with pytest.raises(StopAfterAcquisition):
        extractor._remplir_page(page, pdf_page, pdf, doc, {}, 150, 100, Rapport(), "rapidocr", "line", "word-native",
                                False, None, None, None, None, False)
    assert {rejected_table.source_id, outside.source_id, component.source_id} <= set(page.source_inventory)
    assert rejected_table in page.discarded_elements and outside in page.discarded_elements
    event = next(event for event in page.source_transformations if event["reason_code"] == "outside-visible-page")
    assert event["outside_page"]["intersection_area"] == 0
    raster = next(item for item in page.elements if isinstance(item, ir.RasterEl))
    assert raster.source_component_ids == (component.source_id,)
    assert raster.fallback_reason == "complex-vector-cluster"
    pdf.close()


def test_native_extraction_acquires_span_quad_baseline_glyphs_zero_z_and_opacity(monkeypatch):
    import pymupdf
    from pdfexact.extract.text import extraire_texte
    from pdfexact.geometry import PageGeometry

    monkeypatch.setattr("pdfexact.extract.text._corriger_espacement", lambda *args: None)
    with pymupdf.open() as pdf:
        pdf_page = pdf.new_page(width=200, height=200)
        pdf_page.insert_text((50, 70), "Ab", fontsize=12, fill_opacity=0.0)
        fonts = {"Helvetica": ir.FontAsset("Helvetica", "Helvetica", None, "ttf", False)}
        box, = extraire_texte(pdf_page, fonts, PageGeometry.depuis_page(pdf_page))
        line = box.lignes[0]
        span = line.spans[0]
        assert span.source_kind == "pdf-native" and span.source_id
        assert box.source_id and line.source_id
        assert span.z_index == span.z_order == 0 and span.opacity == 0.0
        assert len(span.quad) == len(line.quad) == 4
        assert len(span.baseline) == len(span.baseline_points) == 2
        assert span.glyph_ids and len(span.glyph_ids) == len(span.texte)
        assert span.to_unicode_status == "decoded-unicode"
        assert span.confidence is None


def test_unknown_confidence_chooses_conservative_mode_without_fabricating_one():
    from pdfexact.analysis.decisions import decider_mode_universel

    record = element_record_from_legacy(text_box(), 0)
    decision = decider_mode_universel(record)
    assert record.confidence is None and record.semantic_confidence is None
    assert decision.mode.value != "native-flow"
    assert decision.confidence == 0.0


def test_required_span_public_aliases_accept_defaults_and_preserve_zero():
    font = ir.FontRef("f", "actual", False, False)
    span = ir.Span("x", font, 10, "000000", baseline=((0, 0), (1, 0)), z_order=0)
    assert span.baseline_points == ((0, 0), (1, 0))
    assert span.z_index == 0


def test_legacy_local_line_aliases_are_acquisition_scoped_before_scene_registration():
    first = text_box("A")
    second = text_box("B")
    first.lignes[0].source_id = second.lignes[0].source_id = "line:0"
    pages = [ir.Page(index, 200, 200, deepcopy([first, second])) for index in (0, 1)]
    scene = scene_from_legacy_document(ir.Document(pages=pages))
    line_ids = [box.lignes[0].source_id for page in pages for box in page.elements]
    assert len(line_ids) == len(set(line_ids)) == 4
    assert all(scene.registry.elements[source_id].attributes["source_metadata"]["attributes"]["legacy_local_source_id"] == "line:0"
               for source_id in line_ids)


def test_factory_derives_only_observed_language_script_and_keeps_parent_orientation():
    box = text_box("A")
    box.language = box.script = "auto"
    span = box.lignes[0].spans[0]
    span.language, span.script = "ar", "Arab"
    span.police = ir.FontRef("actual", "actual", False, False)
    box.angle_deg, box.orientation = 90.0, "vertical"
    box.lignes[0].angle_deg, box.lignes[0].orientation = 0.0, "horizontal"
    record = element_record_from_legacy(box, 0)
    assert (record.language, record.script) == ("ar", "Arab")
    assert (record.angle_deg, record.orientation) == (90.0, "vertical")


@pytest.mark.parametrize("angle", [90.0, 180.0])
def test_factory_parent_geometry_survives_default_child_and_snapshots_are_distinct(angle):
    box = text_box("A")
    box.angle_deg, box.orientation = angle, "vertical"
    line = box.lignes[0]
    line.angle_deg, line.orientation, line.quad, line.baseline_points = 0.0, "horizontal", (), ()
    record = element_record_from_legacy(box, 0)
    assert (record.angle_deg, record.orientation) == (angle, "vertical")
    assert record.attributes["parent_orientation_geometry"] == {"angle_deg": angle, "orientation": "vertical"}
    assert record.attributes["line_geometries"][0]["angle_deg"] == 0.0
    assert record.attributes["geometry_conflicts"] == ()


def test_factory_contradictory_observed_geometry_is_evidence_not_silent_overwrite():
    box = text_box("A")
    box.angle_deg, box.orientation = 90.0, "vertical"
    line = box.lignes[0]
    line.angle_deg, line.orientation = -25.0, "oblique-up"
    record = element_record_from_legacy(box, 0)
    assert record.angle_deg == 90.0 and record.orientation == "vertical"
    conflict, = record.attributes["geometry_conflicts"]
    assert conflict["parent"]["angle_deg"] == 90.0 and conflict["line"]["angle_deg"] == -25.0
    assert any(proof.kind == "geometry-conflict" and proof.confidence is None for proof in record.evidence)


def test_factory_inherits_only_known_consistent_acquisition_kind():
    box = text_box("A")
    box.source_kind = box.lignes[0].source_kind = None
    box.lignes[0].spans[0].source_kind = "ocr"
    assert element_record_from_legacy(box, 0).source_kind is SourceKind.OCR
    mixed = text_box("AB")
    mixed.source_kind = mixed.lignes[0].source_kind = None
    mixed.lignes[0].spans[0].source_kind = "ocr"
    record = element_record_from_legacy(mixed, 0)
    assert record.source_kind is SourceKind.INFERRED
    assert record.attributes["source_kind_conflict"] is True
    assert any(proof.kind == "source-kind-conflict" for proof in record.evidence)
