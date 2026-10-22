"""Typed source ancestors survive segmentation and mixed text containers."""
from copy import deepcopy

import pytest

from pdfexact.analysis import text_segmentation as segmentation
from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.ir import Document, FontRef, Line, Page, Span, TextBox, element_source_ids
from pdfexact.layout.text_comprehension import (
    configurer_fournisseur_comprehension_texte,
    contexte_comprehension_texte,
)
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




























