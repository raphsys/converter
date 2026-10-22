from pdfexact.analysis.decisions import RenderMode, decider_mode_universel, validate_decision
from pdfexact.analysis.geometry import axis_overlap_ratio, clip_bbox_nonempty, intersection_over_min_area, rect_intersection_area, rect_overlap_ratio
from pdfexact.analysis.options import AnalysisOptions
from pdfexact.analysis.provenance import ElementRegistry, Evidence
from pdfexact.analysis.semantic import detecter_marqueur_liste, est_continuation_de_ligne, est_frontiere_de_paragraphe, normaliser_script_et_langue, regrouper_listes
from pdfexact.geometry import BBox, pt_vers_emu
from pdfexact.scene import ElementKind, ElementRecord, SourceKind, scene_from_legacy_document


def _text(element_id: str, x: int, y: int, text: str, *, confidence: float = 0.95):
    return ElementRecord(
        element_id=element_id,
        page_index=0,
        kind=ElementKind.TEXT,
        bbox=BBox(pt_vers_emu(x), pt_vers_emu(y), pt_vers_emu(x + 160), pt_vers_emu(y + 12)),
        source_kind=SourceKind.PDF_NATIVE,
        source_ids=(element_id,),
        role="text",
        text=text,
        orientation="horizontal",
        confidence=confidence,
        role_confidence=confidence,
        geometry_confidence=confidence,
        semantic_confidence=confidence,
        attributes={"paragraph_confirmed": True},
    )








def test_semantic_grouping_is_script_aware_and_keeps_real_boundaries():
    cyrillic = _text("cyr", 10, 10, "Пример текста на русском")
    normaliser_script_et_langue(cyrillic)
    assert cyrillic.script == "cyrillic"

    first = _text("first", 10, 10, "Une phrase terminee.")
    second = _text("second", 10, 30, "Nouvelle idee")
    first.layout_frame_id = second.layout_frame_id = "same-panel"
    first.layout_frame_role = second.layout_frame_role = "text-column"
    assert est_frontiere_de_paragraphe(first, second)


def test_semantic_cross_frame_lowercase_continuation_remains_joinable():
    first = _text("first", 10, 10, "La phrase se poursuit")
    second = _text("second", 10, 24, "sans changer de paragraphe")
    first.layout_frame_id = "frame-a"
    second.layout_frame_id = "frame-b"
    assert est_continuation_de_ligne(first, second)


def test_semantic_list_group_uses_marker_and_alignment():
    marker = _text("marker", 10, 10, "•")
    body = _text("body", 175, 10, "Texte de la puce")
    assert detecter_marqueur_liste(marker) == "bullet"
    result = regrouper_listes([marker, body])
    assert len(result) == 1
    assert result[0].list_marker == "bullet"
    assert set(result[0].source_ids) == {"body", "marker"}
    assert result[0].text == body.text
    assert not getattr(body, "list_marker", None)


def test_render_decision_is_explicit_and_validated():
    element = _text("p0:text:1", 10, 10, "Paragraphe")
    decision = decider_mode_universel(element, AnalysisOptions())

    assert decision.mode is RenderMode.NATIVE_FLOW
    assert decision.editable is True
    assert validate_decision(decision) == []
    assert decision.expected_bbox == element.bbox
    assert decision.expected_orientation == element.orientation
    assert decision.expected_z_order == element.z_order




def test_orientation_sensitive_text_gets_editable_frame_and_fallback():
    element = _text("p0:text:2", 10, 10, "Credit")
    element.orientation = "vertical"
    element.attributes["paragraph_confirmed"] = False
    decision = decider_mode_universel(element, AnalysisOptions())

    assert decision.mode is RenderMode.ROTATED_NATIVE_TEXT
    assert decision.fallback_mode is RenderMode.LOCAL_RASTER


def test_provenance_is_not_a_silent_filter():
    element = _text("p0:text:3", 10, 10, "Texte")
    element.add_evidence(Evidence("overlap", "layout-ai", 0.8))
    registry = ElementRegistry()
    registry.register(element)
    registry.record(element.element_id, "duplicate-candidate", candidate_id="image-1")

    assert element.element_id in registry.elements
    assert registry.missing_terminal_states() == [element.element_id]




def test_extract_attaches_observation_scene_without_changing_legacy_ir(tmp_path):
    from copy import deepcopy

    import pymupdf

    from pdfexact.analysis.provenance import observation_is_preserved
    from pdfexact.ir import Line, Span
    from pdfexact.scene import _snapshot_value

    pdf_path = tmp_path / "scene-observation.pdf"
    source = pymupdf.open()
    page = source.new_page(width=300, height=200)
    page.insert_text((30, 50), "Observation scene", fontsize=12)
    source.save(pdf_path)
    source.close()

    from pdfexact.extract.document import extraire

    document = extraire(pdf_path, text_mode="spans", pages=[0])

    assert document.pages and document.pages[0].elements
    assert document.scene is not None
    page_ir = document.pages[0]
    records = {record.element_id: record for record in document.scene.all_elements()}
    active_ids = {element.source_id for element in page_ir.elements}
    assert set(records) == set(page_ir.source_inventory)
    assert {key for key, record in records.items() if not record.attributes["observation_only"]} == active_ids
    assert any(isinstance(raw, Line) for raw in page_ir.source_inventory.values())
    assert any(isinstance(raw, Span) for raw in page_ir.source_inventory.values())
    for source_id, raw in page_ir.source_inventory.items():
        record = records[source_id]
        assert record.attributes["source_snapshot"] == _snapshot_value(raw)
        assert observation_is_preserved(raw, [record.raw])
        if record.attributes["observation_only"]:
            assert _snapshot_value(record.raw) == _snapshot_value(raw)
        else:
            assert any(record.raw is element for element in page_ir.elements)
        assert source_id in record.source_ids
        assert document.element_registry.elements[source_id] is record
    active = list(page_ir.elements)
    snapshot = deepcopy(active)
    rebuilt = scene_from_legacy_document(document)
    assert page_ir.elements == snapshot
    assert all(left is right for left, right in zip(page_ir.elements, active))
    assert {record.element_id for record in rebuilt.all_elements()} == set(records)
    assert document.scene.snapshot()["pages"][0]["index"] == 0


def test_geometry_wrappers_cover_bbox_rect_clip_and_axis_contracts():
    box = BBox(-10, -10, 110, 50)
    clipped = clip_bbox_nonempty(box, 100, 40)

    assert clipped == BBox(0, 0, 100, 40)
    assert rect_intersection_area((0, 0, 10, 10), (5, 5, 20, 20)) == 25
    assert rect_overlap_ratio((0, 0, 10, 10), (5, 5, 20, 20)) == 0.25
    assert intersection_over_min_area(BBox(0, 0, 10, 10), BBox(5, 5, 20, 20)) == 0.25
    assert axis_overlap_ratio(BBox(0, 0, 10, 10), BBox(5, 20, 20, 30), "x") == 0.5


