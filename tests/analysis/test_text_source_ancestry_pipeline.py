"""Typed source ancestors survive segmentation and mixed text containers."""
from copy import deepcopy

import pytest

from pdfexact.analysis import text_segmentation as segmentation
from pdfexact.analysis.decisions import RenderDecision, RenderMode
from pdfexact.analysis.options import AnalysisOptions
from pdfexact.analysis.provenance import verify_preserved_text_components
from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.ir import Document, FontRef, Line, Page, ShapeEl, Span, TextBox, element_source_ids
from pdfexact.layout.text_comprehension import (
    configurer_fournisseur_comprehension_texte,
    contexte_comprehension_texte,
)
from pdfexact.render import render_plan
from pdfexact.scene import (
    ElementKind, _snapshot_value, capture_source_observations,
    element_record_from_legacy, scene_from_legacy_document,
)


@pytest.fixture(autouse=True)
def deterministic_groups(monkeypatch):
    with contexte_comprehension_texte():
        configurer_fournisseur_comprehension_texte(None)
        monkeypatch.setattr(segmentation, "_groupes_ia",
                            lambda units, *args: [[unit] for unit in units])
        monkeypatch.setattr(segmentation, "_join_source_fragments",
                            lambda groups, *args: groups)
        yield


def source_box(texts=("same words", " ", "same words"), ident="acquired"):
    lines = []
    for index, text in enumerate(texts):
        bbox = BBox(u(10), u(10 + index * 18), u(180), u(22 + index * 18))
        span = Span(text, FontRef("font", "Arial", False, False), 12, "123456",
                    bbox=bbox, source_id=f"{ident}-span-{index}",
                    source_kind="pdf-native", z_index=0)
        span.opacity = 0.0
        span.public_metadata = {"zero": 0, "unknown": None}
        line = Line(bbox, [span], bbox.hauteur, bbox.largeur,
                    source_id=f"{ident}-line-{index}", source_kind="pdf-native", z_index=0)
        line.public_metadata = {"zero": 0, "unknown": None}
        lines.append(line)
    return TextBox(BBox(lines[0].bbox.x0, lines[0].bbox.y0,
                        lines[-1].bbox.x1, lines[-1].bbox.y1), lines,
                   source_id=ident, source_kind="pdf-native", z_index=0)


def frame_view(root, lines, ident):
    view = deepcopy(root)
    view.source_id = ident
    view.lignes = deepcopy(lines)
    view.bbox = BBox(min(x.bbox.x0 for x in lines), min(x.bbox.y0 for x in lines),
                     max(x.bbox.x1 for x in lines), max(x.bbox.y1 for x in lines))
    view.source_ids = (root.source_id, *(i for line in lines for i in element_source_ids(line)))
    return view


def view_document(texts=("same words", " ", "same words")):
    root = source_box(texts)
    page = Page(0, u(300), u(240), [root])
    capture_source_observations(page, [root])
    page.elements = [frame_view(root, [line], f"view-{index}")
                     for index, line in enumerate(root.lignes)]
    document = Document([page])
    document.scene = scene_from_legacy_document(document)
    return root, document


@pytest.mark.parametrize("texts", [
    ("same words", " ", "same words"),
    ("same words", "same words", "same words"),
])
def test_split_views_keep_partial_and_complete_parent_coverage(texts):
    root, document = view_document(texts)
    page = document.pages[0]
    acquired = _snapshot_value(page.source_inventory)
    segmentation.segmenter_page_textes(page)
    for element in page.elements:
        assert root.source_id in element.source_ids
        selected = {i for line in element.lignes for i in element_source_ids(line)}
        siblings = {i for line in root.lignes for i in element_source_ids(line)} - selected
        assert siblings.isdisjoint(element.source_ids)
        if element.presentation.get("paragraph_validated"):
            index = root.lignes.index(element.lignes[0])
            assert element.source_ids[0] == f"view-{index}"
    plan = render_plan.build_document_render_plan(document)
    assert plan.validate(document) == []
    assert len(plan.source_coverage[root.source_id].target_ids) == len(texts)
    assert _snapshot_value(page.source_inventory) == acquired


@pytest.mark.parametrize("store", ["both", "registry", "inventory"])
def test_multiple_verified_ancestors_append_without_sibling_components(store):
    root = source_box(("same words", "same words", "same words"))
    page = Page(0, u(300), u(240), [root])
    capture_source_observations(page, [root])
    middle = frame_view(root, root.lignes[:2], "middle-container")
    page.elements = [middle]
    document = Document([page])
    document.scene = scene_from_legacy_document(document)
    view = frame_view(middle, middle.lignes, "selected-view")
    view.source_ids += (root.source_id, root.lignes[2].source_id, root.lignes[2].spans[0].source_id)
    page.elements = [view]
    if store == "registry":
        page.source_inventory = {}
    elif store == "inventory":
        page.element_registry = None
    before = _snapshot_value((root, middle, view, page.source_inventory))
    segmentation.segmenter_page_textes(page)
    for element in page.elements:
        assert element.source_ids[0] == "selected-view"
        assert "middle-container" in element.source_ids
        assert root.source_id in element.source_ids
        selected = {i for line in element.lignes for i in element_source_ids(line)}
        siblings = {i for line in root.lignes for i in element_source_ids(line)} - selected
        assert siblings.isdisjoint(element.source_ids)
    assert _snapshot_value((root, middle, view, page.source_inventory)) == before


@pytest.mark.parametrize("defect", [
    "lexical-collision", "wrong-parent-page", "wrong-line-page", "wrong-kind",
    "wrong-container-type", "wrong-direct-id", "changed-confidence", "changed-opacity",
    "changed-history", "changed-quad", "fake-proof", "missing-component",
])
def test_claimed_parent_requires_actual_typed_same_page_component(defect):
    root, document = view_document(("same words", "same words"))
    page = document.pages[0]
    view = deepcopy(page.elements[0])
    candidate = deepcopy(root)
    candidate.source_id = "claimed-parent"
    view.source_ids = (candidate.source_id, *element_source_ids(root.lignes[1]))
    if defect == "lexical-collision":
        candidate.lignes = [deepcopy(root.lignes[1])]
    elif defect == "wrong-parent-page":
        candidate.source_page_index = 1
    elif defect == "wrong-line-page":
        candidate.lignes[0].source_page_index = 1
    elif defect == "wrong-container-type":
        candidate = deepcopy(root.lignes[0])
        candidate.source_id = "claimed-parent"
    elif defect == "wrong-direct-id":
        candidate.lignes[0].source_id = "other-line"
        candidate.lignes[0].source_ids += (view.lignes[0].source_id,)
    elif defect == "changed-confidence":
        candidate.lignes[0].confidence = 0.0
    elif defect == "changed-opacity":
        candidate.lignes[0].spans[0].opacity = None
    elif defect == "changed-history":
        candidate.lignes[0].decision_history.append({"reason": "acquired-history"})
    elif defect == "changed-quad":
        candidate.lignes[0].quad = ((1, 1), (2, 1), (2, 2), (1, 2))
    elif defect in {"fake-proof", "missing-component"}:
        candidate.lignes = []
        view.attributes["verified_parent"] = {"id": candidate.source_id, "verified": True}
    record = element_record_from_legacy(candidate, 1 if defect == "wrong-parent-page" else 0)
    if defect == "wrong-line-page":
        candidate.lignes[0].source_page_index = 1
    if defect == "wrong-kind":
        record.kind = ElementKind.SHAPE
    page.element_registry.elements[candidate.source_id] = record
    page.source_inventory[candidate.source_id] = deepcopy(candidate)
    page.elements = [view]
    segmentation.segmenter_page_textes(page)
    assert len(page.elements) == 1
    output = page.elements[0]
    assert candidate.source_id not in output.source_ids
    assert set(element_source_ids(root.lignes[1])).isdisjoint(output.source_ids)


def compile_modes(monkeypatch, modes, boxes=None, visuals=(), texts=("first text", "second text", "last text"),
                  line_ys=None, line_paints=None, element_order=None):
    root = source_box(texts)
    if line_ys is not None:
        for line, y in zip(root.lignes, line_ys):
            line.bbox = BBox(line.bbox.x0, u(y), line.bbox.x1, u(y + 12))
            line.spans[0].bbox = line.bbox
        root.bbox = BBox(min(x.bbox.x0 for x in root.lignes), min(x.bbox.y0 for x in root.lignes),
                         max(x.bbox.x1 for x in root.lignes), max(x.bbox.y1 for x in root.lignes))
    if line_paints is not None:
        root.z_index = None
        for line, paint in zip(root.lignes, line_paints):
            line.z_index = paint
            line.spans[0].z_index = line.spans[0].z_order = paint
    page = Page(0, u(300), u(240), [root])
    capture_source_observations(page, [root])
    children = [frame_view(root, [line], f"fragment-{index}")
                for index, line in enumerate(root.lignes)]
    if boxes:
        for item, bbox in zip(children, boxes):
            item.bbox = bbox
    if element_order is not None:
        children = [children[index] for index in element_order]
    records = [element_record_from_legacy(item, 0) for item in [*children, *visuals]]

    def decide(record, *, options):
        mode = modes[int(record.element_id.rsplit("-", 1)[1])] if record.kind is ElementKind.TEXT else RenderMode.ANCHORED_SHAPE
        reasons = ("page-geometry-locked",) if mode is RenderMode.LOCKED_NATIVE_PARAGRAPH else ()
        return RenderDecision(record.element_id, mode, reasons, 1.0, True)

    monkeypatch.setattr(render_plan, "decider_mode_universel", decide)
    planned, schedule = render_plan._compile_page(page, records, AnalysisOptions())
    return root, planned, schedule


@pytest.mark.parametrize("locked", [0, 1, 2])
def test_flow_and_dml_text_share_original_body_order(monkeypatch, locked):
    modes = [RenderMode.NATIVE_FLOW] * 3
    modes[locked] = RenderMode.LOCKED_NATIVE_PARAGRAPH
    root, planned, schedule = compile_modes(monkeypatch, modes)
    assert {x.container for x in schedule} == {"flow", "dml-frame"}
    assert verify_preserved_text_components(root, [x.element for x in schedule]) == []
    assert [x.element.lignes[0].source_id for x in schedule] == [x.source_id for x in root.lignes]
    assert [x.anchor.z for x in schedule] == [100, 100, 100]


def test_positioned_blank_and_locked_text_do_not_jump_over_flow(monkeypatch):
    modes = [RenderMode.NATIVE_FLOW, RenderMode.POSITIONED_TEXT, RenderMode.LOCKED_NATIVE_PARAGRAPH]
    root, _, schedule = compile_modes(monkeypatch, modes, texts=("first text", " ", "last text"))
    assert [x.container for x in schedule] == ["flow", "positioned", "dml-frame"]
    assert verify_preserved_text_components(root, [x.element for x in schedule]) == []


@pytest.mark.parametrize("locked", [0, 1, 2])
def test_equal_geometry_retains_structured_input_order(monkeypatch, locked):
    modes = [RenderMode.NATIVE_FLOW] * 3
    modes[locked] = RenderMode.LOCKED_NATIVE_PARAGRAPH
    bbox = BBox(u(10), u(10), u(180), u(80))
    root, _, schedule = compile_modes(monkeypatch, modes, boxes=[bbox] * 3)
    assert verify_preserved_text_components(root, [x.element for x in schedule]) == []


@pytest.mark.parametrize("locked", [0, 1, 2])
def test_acquired_component_order_precedes_nonmonotone_coordinates(monkeypatch, locked):
    modes = [RenderMode.NATIVE_FLOW] * 3
    modes[locked] = RenderMode.LOCKED_NATIVE_PARAGRAPH
    root, _, schedule = compile_modes(monkeypatch, modes, line_ys=(200, 100, 150))
    assert verify_preserved_text_components(root, [x.element for x in schedule]) == []
    assert [x.element.lignes[0].source_id for x in schedule] == [x.source_id for x in root.lignes]


@pytest.mark.parametrize("context", ["page-registry", "record-registry"])
def test_canonical_order_uses_actual_registry_when_page_inventory_unavailable(monkeypatch, context):
    compile_page = render_plan._compile_page

    def with_registry(page, records, *args):
        document = Document([page])
        document.scene = scene_from_legacy_document(document)
        page.source_inventory = {}
        if context == "record-registry":
            for record in records:
                record._registry = page.element_registry
            page.element_registry = None
        return compile_page(page, records, *args)

    monkeypatch.setattr(render_plan, "_compile_page", with_registry)
    root, _, schedule = compile_modes(
        monkeypatch, [RenderMode.NATIVE_FLOW, RenderMode.LOCKED_NATIVE_PARAGRAPH, RenderMode.NATIVE_FLOW],
        line_ys=(200, 100, 150))
    assert verify_preserved_text_components(root, [x.element for x in schedule]) == []


def test_conflicting_canonical_source_and_anchor_paint_orders_are_refused(monkeypatch):
    with pytest.raises(ValueError, match="conflicting-source-component-and-paint-order"):
        compile_modes(monkeypatch, [RenderMode.LOCKED_NATIVE_PARAGRAPH] * 3,
                      line_paints=(2, 1, 0))


@pytest.mark.parametrize("element_order", [(2, 1, 0), (1, 2, 0)])
def test_shared_paint_sequence_defers_to_acquired_row_order(monkeypatch, element_order):
    # Les vues issues d'une même opération de peinture partagent (z, paint_order) :
    # seul l'ordre des rangées acquises peut les départager.
    root, _, schedule = compile_modes(monkeypatch, [RenderMode.LOCKED_NATIVE_PARAGRAPH] * 3,
                                      line_paints=(1, 1, 1), element_order=element_order)
    assert [x.anchor.z for x in schedule] == [110, 110, 110]
    assert verify_preserved_text_components(root, [x.element for x in schedule]) == []
    assert [x.element.lignes[0].source_id for x in schedule] == [x.source_id for x in root.lignes]


def test_consistent_source_and_paint_orders_ignore_nonmonotone_geometry(monkeypatch):
    root, _, schedule = compile_modes(monkeypatch, [RenderMode.LOCKED_NATIVE_PARAGRAPH] * 3,
                                      line_ys=(200, 100, 150), line_paints=(0, 1, 2))
    assert verify_preserved_text_components(root, [x.element for x in schedule]) == []
    assert [x.anchor.z for x in schedule] == [100, 110, 120]


def test_unrelated_source_containers_retain_old_mode_specific_order(monkeypatch):
    roots = [source_box(("same words",), f"independent-{index}") for index in range(3)]
    page = Page(0, u(300), u(240), roots)
    capture_source_observations(page, roots)
    modes = [RenderMode.NATIVE_FLOW, RenderMode.POSITIONED_TEXT, RenderMode.LOCKED_NATIVE_PARAGRAPH]
    def decide(record, *, options):
        mode = modes[int(record.element_id.rsplit("-", 1)[1])]
        reasons = ("page-geometry-locked",) if mode is RenderMode.LOCKED_NATIVE_PARAGRAPH else ()
        return RenderDecision(record.element_id, mode, reasons, 1.0, True)
    monkeypatch.setattr(render_plan, "decider_mode_universel", decide)
    _, schedule = render_plan._compile_page(
        page, [element_record_from_legacy(root, 0) for root in roots], AnalysisOptions())
    assert [x.container for x in schedule] == ["dml-frame", "flow", "positioned"]
    assert all(verify_preserved_text_components(root, [x.element for x in schedule]) == [] for root in roots)


def test_mixed_container_merge_preserves_anchor_paint_and_flow_sequences(monkeypatch):
    background = ShapeEl(BBox(u(220), u(5), u(250), u(25)), [], "FFFFFF", None, 0)
    foreground = deepcopy(background)
    background.source_id, background.z_index = "background", 0
    foreground.source_id, foreground.z_index = "foreground", 2
    root, _, schedule = compile_modes(
        monkeypatch, [RenderMode.NATIVE_FLOW, RenderMode.LOCKED_NATIVE_PARAGRAPH, RenderMode.NATIVE_FLOW],
        visuals=(foreground, background),
    )
    text = [x for x in schedule if x.kind is ElementKind.TEXT]
    assert verify_preserved_text_components(root, [x.element for x in text]) == []
    anchors = [x for x in schedule if x.container != "flow"]
    assert [(x.anchor.z, *x.paint_order) for x in anchors] == sorted((x.anchor.z, *x.paint_order) for x in anchors)
    assert [x.element.source_id for x in anchors if x.kind is ElementKind.SHAPE] == ["background", "foreground"]


@pytest.mark.parametrize("mutation", ["missing", "changed", "reversed", "wrong-page", "duplicated"])
def test_strict_components_still_reject_corrupt_rendered_body(monkeypatch, mutation):
    root, _, schedule = compile_modes(
        monkeypatch, [RenderMode.NATIVE_FLOW, RenderMode.NATIVE_FLOW, RenderMode.LOCKED_NATIVE_PARAGRAPH])
    outputs = [deepcopy(x.element) for x in schedule]
    # This assertion also makes the producer-order defect a real RED first.
    assert verify_preserved_text_components(root, outputs) == []
    if mutation == "missing":
        outputs.pop()
    elif mutation == "changed":
        outputs[0].lignes[0].spans[0].confidence = 0.0
    elif mutation == "wrong-page":
        outputs[0].lignes[0].source_page_index = 1
    elif mutation == "duplicated":
        outputs.append(deepcopy(outputs[0]))
    else:
        outputs.reverse()
    assert verify_preserved_text_components(root, outputs)


def test_partial_ancestry_cannot_cover_absent_sibling_rows():
    root, document = view_document(("first text", "second text", "last text"))
    page = document.pages[0]
    page.elements.pop()
    segmentation.segmenter_page_textes(page)
    assert all(root.source_id in item.source_ids for item in page.elements)
    assert all(root.lignes[-1].source_id not in item.source_ids for item in page.elements)
    plan = render_plan.build_document_render_plan(document)
    assert "unverified-source-transform:acquired" in plan.validate(document)


@pytest.mark.parametrize("mutation", ["missing", "confidence", "wrong-page", "schedule"])
def test_complete_plan_guards_stay_strict_after_verified_ancestry(mutation):
    root, document = view_document(("first text", "second text", "last text"))
    segmentation.segmenter_page_textes(document.pages[0])
    plan = render_plan.build_document_render_plan(document)
    assert plan.validate(document) == []
    instructions = plan.instructions_for_page(0)
    if mutation == "missing":
        instructions[0].element.lignes.clear()
    elif mutation == "confidence":
        instructions[0].element.lignes[0].confidence = 0.0
    elif mutation == "wrong-page":
        instructions[0].element.lignes[0].source_page_index = 1
    else:
        plan.instructions_by_page[0] = tuple(reversed(instructions))
    assert "unverified-source-transform:acquired" in plan.validate(document)
