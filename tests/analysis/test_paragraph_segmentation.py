from copy import deepcopy

import pytest

from pdfexact.analysis.decisions import RenderMode
from pdfexact.analysis.text_geometry import geometry_contract_for, line_has_text, paragraph_bbox_from_lines
from pdfexact.analysis.text_segmentation import segmenter_page_textes
from pdfexact.geometry import BBox, pt_vers_emu, quantifier_bbox
from pdfexact.ir import Document, FlowParagraph, FontRef, ImageEl, Line, Page, Span, TextBox
from pdfexact.layout.text_comprehension import (
    TextUnderstandingDecision,
    configurer_fournisseur_comprehension_texte,
)
from pdfexact.render.reflow import fusionner_flow_paragraphes, prepare_document_elements, prepare_page_elements
from pdfexact.render.render_plan import build_document_render_plan, build_page_render_plan
from pdfexact.render.bbox_debug import _native_paragraph_xml


def box(x0, y0, x1, y1):
    return BBox(*(pt_vers_emu(v) for v in (x0, y0, x1, y1)))


def line(text, y, *, x=40, width=200, bold=False, size=10):
    bbox = box(x, y, x + width, y + 12)
    font = FontRef("Bold" if bold else "Regular", "Arial", bold, False)
    return Line(bbox, [Span(text, font, size, "123456")], pt_vers_emu(12), bbox.largeur)


def page_of(lines, extra=()):
    bbox = BBox(min(v.bbox.x0 for v in lines), min(v.bbox.y0 for v in lines),
                max(v.bbox.x1 for v in lines), max(v.bbox.y1 for v in lines))
    return Page(0, pt_vers_emu(600), pt_vers_emu(800), [TextBox(bbox, lines), *extra])


def texts(page):
    return [" ".join("".join(s.texte for s in v.spans) for v in e.lignes if line_has_text(v))
            for e in page.elements if isinstance(e, TextBox)]


def test_blank_rows_separate_paragraphs_but_not_their_visible_geometry():
    lines = [line("A first paragraph.", 20), line(" ", 34, width=3),
             line("Another paragraph.", 48)]
    page = page_of(lines)
    segmenter_page_textes(page)
    assert texts(page) == ["A first paragraph.", "Another paragraph."]
    assert page.elements[0].bbox == quantifier_bbox(lines[0].bbox)
    assert page.elements[1].presentation["source_spacing_before_emu"] > 0
    assert [row for element in page.elements for row in element.lignes if not line_has_text(row)] == [lines[1]]


def test_geometry_ignores_blank_rows_without_removing_spaces_from_runs():
    content = line("  Keep internal  spaces.  ", 50)
    page = page_of([line("\t ", 20, width=3), content, line(" ", 90, width=3)])
    geometry = geometry_contract_for(page.elements[0])
    assert geometry.line_bboxes == (content.bbox,)
    assert paragraph_bbox_from_lines(page.elements[0].lignes) == quantifier_bbox(content.bbox)
    assert content.spans[0].texte == "  Keep internal  spaces.  "


def test_whitespace_fragment_on_same_row_is_not_a_paragraph_separator():
    rows = [line(" ", 20, width=20), line("Indented first line", 20, x=65),
            line("and its continuation.", 34)]
    page = page_of(rows)
    segmenter_page_textes(page)
    assert len(texts(page)) == 1
    assert len([row for row in page.elements[0].lignes if line_has_text(row)]) == 2
    assert page.elements[0].lignes == rows


def test_heading_and_list_items_are_not_one_pdf_paragraph():
    page = page_of([line("Some introductory prose", 20), line("continues here.", 34),
                    line("Section heading", 48, bold=True),
                    line("\u2022 First list item", 62), line("continues on another line.", 76, x=55),
                    line("\u2022 Another list item", 90)])
    segmenter_page_textes(page)
    assert texts(page) == ["Some introductory prose continues here.", "Section heading",
                           "\u2022 First list item continues on another line.", "\u2022 Another list item"]


def test_inline_bold_run_does_not_split_a_paragraph():
    first = line("A normal line with ", 20)
    first.spans.append(Span("emphasis", FontRef("Bold", "Arial", True, False), 10, "123456"))
    second = line("a normal continuation.", 34)
    page = page_of([first, second])
    segmenter_page_textes(page)
    assert len(texts(page)) == 1
    assert page.elements[0].lignes[0].spans == first.spans


def test_emphasis_wrapped_onto_a_whole_line_is_not_a_new_paragraph():
    page = page_of([line("A sentence with", 20), line("a strongly emphasized phrase", 34, bold=True),
                    line("continues in the normal style.", 48)])
    segmenter_page_textes(page)
    assert len(texts(page)) == 1
    assert page.elements[0].lignes[1].spans[0].police.gras


def test_paragraph_indent_after_sentence_is_not_a_same_row_blank_line():
    blank = line(" ", 48, width=20)
    page = page_of([line("First paragraph starts", 20, x=65), line("and ends here.", 34),
                    blank, line("Second paragraph starts", 48, x=65),
                    line("and continues.", 62)])
    segmenter_page_textes(page)
    assert texts(page) == ["First paragraph starts and ends here.",
                           "Second paragraph starts and continues."]
    assert [row for element in page.elements for row in element.lignes if not line_has_text(row)] == [blank]


def test_large_gap_and_intervening_image_protect_boundaries():
    page = page_of([line("First caption", 20), line("Second caption", 150)],
                   [ImageEl(box(40, 60, 240, 130), "figure")])
    segmenter_page_textes(page)
    assert texts(page) == ["First caption", "Second caption"]


def test_foreground_between_close_lines_is_not_a_background_behind_them():
    rows = [line("Text above the object", 20), line("text below the object", 40)]
    separated = page_of(deepcopy(rows), [ImageEl(box(40, 33, 240, 39), "foreground")])
    continuous = page_of(deepcopy(rows), [ImageEl(box(10, 10, 300, 100), "background")])
    segmenter_page_textes(separated)
    segmenter_page_textes(continuous)
    assert len(texts(separated)) == 2
    assert len(texts(continuous)) == 1


def test_line_frame_is_used_instead_of_source_first_frame():
    first, second = line("Title", 20, bold=True), line("Body text.", 48)
    first.layout_frame_id, first.layout_frame_role = "title", "heading"
    second.layout_frame_id, second.layout_frame_role = "body", "text-column"
    page = page_of([first, second])
    page.elements[0].layout_frame_id = "title"
    segmenter_page_textes(page)
    assert [v.layout_frame_id for v in page.elements] == ["title", "body"]


def test_locked_paragraphs_survive_same_frame_and_repeated_reflow():
    page = page_of([line("First paragraph.", 20), line(" ", 34, width=3),
                    line("Second paragraph.", 48)])
    page.elements[0].layout_frame_id = "shared-column"
    page.elements[0].layout_frame_role = "text-column"
    segmenter_page_textes(page)
    ids = [v.presentation.get("paragraph_id") for v in page.elements]
    assert len(ids) == len(set(ids)) == 2 and all(ids)
    prepared = prepare_page_elements(page.elements)
    again = prepare_page_elements(prepared)
    assert len(prepared) == len(again) == 2
    assert [v.presentation["paragraph_id"] for v in again] == ids


@pytest.mark.parametrize("groups", [((0, 1), (1, 2)), ((0, 2),), ((2, 1, 0),), ((0, 99),)])
def test_invalid_ai_partition_never_loses_duplicates_or_reorders_lines(groups):
    original = [line("First prose line", 20), line("continues here", 34), line("and finishes.", 48)]
    page = page_of(deepcopy(original))
    configurer_fournisseur_comprehension_texte(
        lambda *args: TextUnderstandingDecision("paragraph", "segment-page", .99, line_groups=groups)
    )
    try:
        segmenter_page_textes(page)
    finally:
        configurer_fournisseur_comprehension_texte(None)
    assert [v.spans for e in page.elements for v in e.lignes] == [v.spans for v in original]


def test_ai_cannot_bridge_blank_separator_or_large_gap():
    blank = line(" ", 40, width=3)
    page = page_of([line("First caption", 20), blank, line("Second caption", 150)])
    configurer_fournisseur_comprehension_texte(
        lambda *args: TextUnderstandingDecision("paragraph", "segment-page", .99, line_groups=((0, 1),))
    )
    try:
        segmenter_page_textes(page)
    finally:
        configurer_fournisseur_comprehension_texte(None)
    assert texts(page) == ["First caption", "Second caption"]
    assert [row for element in page.elements for row in element.lignes if not line_has_text(row)] == [blank]


def test_one_failed_ai_block_does_not_skip_remaining_blocks_or_discard_their_decision():
    page = page_of([line("First paragraph", 20), line("continues.", 34)])
    other = page_of([line("Second paragraph", 100), line("Separate paragraph", 114)])
    page.elements.extend(other.elements)
    calls = []

    def provider(kind, rows, role, metadata):
        assert metadata["coordinate_system"]["units"] == "EMU"
        assert metadata["lines"][0]["styles"][0]["color"] == "123456"
        calls.append(rows)
        if len(calls) == 1:
            return None
        return TextUnderstandingDecision("paragraph", "segment-page", .99, line_groups=((0,), (1,)))

    configurer_fournisseur_comprehension_texte(provider)
    try:
        segmenter_page_textes(page)
    finally:
        configurer_fournisseur_comprehension_texte(None)
    assert len(calls) == 2
    assert texts(page) == ["First paragraph continues.", "Second paragraph", "Separate paragraph"]


def test_continuous_legacy_fragments_remain_mergeable_but_not_distant_captions():
    first, second = line("The paragraph continues", 20), line("on this next line.", 34)
    near = [TextBox(v.bbox, [v], layout_frame_id="column", layout_frame_role="text-column")
            for v in (first, second)]
    assert len(prepare_page_elements(near)) == 1
    far = deepcopy(near)
    far[1].bbox = far[1].lignes[0].bbox = box(40, 200, 240, 212)
    assert len(prepare_page_elements(far)) == 2


def test_source_fragments_need_positive_continuity_not_only_a_common_frame():
    first, second = line("A multiline heading", 20, bold=True), line("continued here", 34, bold=True)
    page = page_of([first])
    page.elements.extend(page_of([second]).elements)
    for item in page.elements:
        item.layout_frame_id = "heading-region"
        item.layout_frame_role = "heading"
    segmenter_page_textes(page)
    assert texts(page) == ["A multiline heading continued here"]
    assert page.elements[0].presentation["segmentation_owners"] == ["element:0", "element:1"]
    assert len(prepare_page_elements(page.elements)) == 1


def test_paragraph_ids_are_page_scoped_even_when_pdf_line_ids_repeat():
    first = page_of([line("First paragraph", 20), line("and its continuation.", 34)])
    for item in first.elements:
        for index, row in enumerate(item.lignes):
            row.source_id = f"line:{index}"
    second = deepcopy(first)
    second.index = 1
    document = Document(pages=[first, second])
    plan = build_document_render_plan(document)
    ids = [item.element.element_id for items in plan.pages.values() for item in items]
    assert len(ids) == len(set(ids)) == 2


def test_segmented_native_paragraph_keeps_runs_styles_and_source_coordinates():
    first = line("A sentence with ", 20)
    styled = Span("a styled run", FontRef("ItalicBold", "Arial", True, True), 10, "A13B50",
                  souligne=True, barre=True)
    first.spans.append(styled)
    second = line("and a continuation.", 34)
    page = page_of([first, second])
    segmenter_page_textes(page)
    element = page.elements[0]
    original_lines = deepcopy(element.lignes)
    xml = _native_paragraph_xml(element)
    assert xml.count("<w:p>") == 1
    assert '<w:sz w:val="20"/>' in xml
    assert '<w:color w:val="A13B50"/>' in xml
    assert '<w:b/>' in xml and '<w:i/>' in xml
    assert 'w:u' in xml and '<w:strike/>' in xml
    assert element.lignes == original_lines
    assert element.bbox == quantifier_bbox(BBox(first.bbox.x0, first.bbox.y0, second.bbox.x1, second.bbox.y1))


@pytest.mark.parametrize("ai_merge", [False, True])
def test_distinct_real_frames_split_one_source_block_even_when_ai_merges(ai_merge):
    rows = [line(f"Row {index}", 20 + index * 14) for index in range(4)]
    for index, row in enumerate(rows):
        row.layout_frame_id = "frame-A" if index < 2 else "frame-B"
        row.layout_frame_role = "text-column"
        row.layout_frame_bbox = box(40, 20 if index < 2 else 48, 240, 46 if index < 2 else 74)
    page = page_of(deepcopy(rows))
    configurer_fournisseur_comprehension_texte(
        (lambda *args: TextUnderstandingDecision(
            "paragraph", "segment-page", .99, line_groups=((0, 1, 2, 3),)
        )) if ai_merge else None
    )
    try:
        segmenter_page_textes(page)
    finally:
        configurer_fournisseur_comprehension_texte(None)
    assert texts(page) == ["Row 0 Row 1", "Row 2 Row 3"]
    assert page.elements[1].presentation["boundary_before"] == "layout-frame-change"
    assert [row for element in page.elements for row in element.lignes] == rows


@pytest.mark.parametrize("frames, count", [
    ((None, None, None), 1),
    (("frame-A", None, "frame-A"), 1),
    ((None, "frame-A", None), 1),
    (("frame-A", None, "frame-B"), 2),
    (("frame-A", "inferred:0:text-column:40:34:240:46", "frame-A"), 1),
    (("frame-A", "inferred:0:text-column:40:34:240:46", "frame-B"), 2),
    (("inferred:0:text-column:40:20:240:32", "inferred:1:text-column:40:34:240:46"), 1),
])
def test_unattached_lines_do_not_create_or_hide_real_frame_boundaries(frames, count):
    rows = [line(f"Row {index}", 20 + index * 14) for index in range(len(frames))]
    for row, frame in zip(rows, frames):
        row.layout_frame_id = frame
    page = page_of(rows)
    segmenter_page_textes(page)
    assert len(texts(page)) == count
    assert sum(len(element.lignes) for element in page.elements) == len(rows)


@pytest.mark.parametrize("separator", ["gap", "style", "obstacle", "role", "same-row-role"])
def test_inferred_frames_still_respect_non_frame_boundaries(separator):
    first, second = line("First text", 20), line("second text", 34)
    first.layout_frame_id = "inferred:0:text-column:40:20:240:32"
    second.layout_frame_id = "inferred:1:text-column:40:34:240:46"
    first.layout_frame_role = second.layout_frame_role = "text-column"
    extra = []
    if separator == "gap":
        second.bbox = box(40, 80, 240, 92)
    elif separator == "style":
        second.spans[0].size_pt = 18
    elif separator == "obstacle":
        second.bbox = box(40, 40, 240, 52)
        extra.append(ImageEl(box(40, 33, 240, 39), "foreground"))
    else:
        first.layout_frame_role = "heading"
        if separator == "same-row-role":
            first.bbox, second.bbox = box(40, 20, 120, 32), box(144, 20, 224, 32)
    page = page_of([first, second], extra)
    segmenter_page_textes(page)
    assert texts(page) == ["First text", "second text"]
    expected = {"gap": "vertical-gap", "style": "block-style-change",
                "obstacle": "visual-obstacle", "role": "role-change", "same-row-role": "role-change"}
    assert page.elements[-1].presentation["boundary_before"] == expected[separator]


def test_dropcap_and_unattached_continuation_keep_independent_native_nodes():
    initial = line("A", 20, width=20, size=30)
    initial.bbox = box(40, 20, 60, 60)
    initial.layout_frame_id = "dropcap"
    rows = [line("paragraph begins", 20, x=65), line("and continues", 34, x=65),
            line("below the initial.", 48)]
    rows[0].layout_frame_id = "body"
    page = page_of([initial])
    page.elements.extend(page_of(rows).elements)
    segmenter_page_textes(page)
    assert texts(page) == ["A", "paragraph begins and continues below the initial."]
    assert [len(element.lignes) for element in page.elements] == [1, 3]


def locked_paragraph(text, y, paragraph_id, *, x=40, width=200, multiline=False):
    rows = [line(text, y, x=x, width=width)]
    if multiline:
        rows.append(line("its locked continuation", y + 14, x=x, width=width))
    element = page_of(rows).elements[0]
    element.source_id = paragraph_id
    element.source_ids = (f"source:{paragraph_id}",)
    element.layout_frame_id = "shared-frame"
    element.layout_frame_role = "text-column"
    element.presentation = {"paragraph_validated": True, "paragraph_id": paragraph_id,
                            "boundary_before": "approved-boundary", "custom": {"keep": [1, 2]}}
    element.geometry = geometry_contract_for(element)
    element.lignes[0].spans.append(Span(" styled", FontRef("BI", "Arial", True, True),
                                       11.25, "A13B50"))
    return element


@pytest.mark.parametrize("via_reflow", [False, True])
@pytest.mark.parametrize("explicit_boundary", [False, True])
def test_mixed_page_preserves_locked_nodes_ids_styles_and_coordinates(via_reflow, explicit_boundary):
    locked = [locked_paragraph("First independent paragraph", 20, "page:0:paragraph:0"),
              locked_paragraph("Second independent paragraph", 34, "page:0:paragraph:1")]
    if not explicit_boundary:
        for element in locked:
            element.presentation.pop("boundary_before")
    snapshots = deepcopy(locked)
    page = page_of([line("New unvalidated paragraph", 48), line("and its continuation", 62)])
    page.elements[0].layout_frame_id = "shared-frame"
    page.elements = [*locked, *page.elements]
    original = deepcopy(page)
    calls = []

    def provider(kind, rows, role, metadata):
        calls.append(rows)
        return None

    configurer_fournisseur_comprehension_texte(provider)
    try:
        if via_reflow:
            result = prepare_document_elements(Document(pages=[page]))[0]
            assert page == original
        else:
            segmenter_page_textes(page)
            result = page.elements
        assert len(result) == 3
        if via_reflow:
            for element, saved in zip(result, locked):
                assert element is not saved
                assert element.source_id == saved.source_id
                assert element.source_ids == saved.source_ids
                assert element.bbox == saved.bbox
                assert element.lignes == saved.lignes
                assert element.presentation == saved.presentation
                assert element.presentation["custom"] is not saved.presentation["custom"]
                assert all(left is not right for left, right in zip(element.lignes, saved.lignes))
        else:
            assert all(any(element is saved for element in result) for saved in locked)
        assert locked == snapshots
        ids = [element.presentation["paragraph_id"] for element in result]
        assert len(ids) == len(set(ids))
        assert ids[:2] == ["page:0:paragraph:0", "page:0:paragraph:1"]
        assert ids[2] == "page:0:paragraph:2"
        assert calls == [("New unvalidated paragraph", "and its continuation")]
        page.elements = result
        segmenter_page_textes(page)
        assert page.elements == result
        assert all(left is right for left, right in zip(page.elements, result))
        assert len(calls) == 1
        if via_reflow:
            result[0].presentation["custom"]["keep"].append(3)
            result[0].lignes[0].spans[0].texte = "Modified prepared copy"
            assert locked == snapshots
    finally:
        configurer_fournisseur_comprehension_texte(None)


@pytest.mark.parametrize("one_source", [False, True])
@pytest.mark.parametrize("same_row", [False, True])
def test_unvalidated_fragments_cannot_merge_across_interleaved_locked_paragraph(one_source, same_row):
    if same_row:
        before = line("Before", 20, x=40, width=80)
        locked = locked_paragraph("Independent", 20, "page:0:paragraph:0", x=125, width=14)
        after = line("after", 20, x=144, width=80)
    else:
        before = line("Before", 20)
        locked = locked_paragraph("Independent", 27, "page:0:paragraph:0")
        after = line("after", 34)
    snapshot = deepcopy(locked)
    page = page_of([before, after] if one_source else [before])
    if not one_source:
        page.elements.extend(page_of([after]).elements)
    for element in page.elements:
        element.layout_frame_id = "shared-frame"
    page.elements.append(locked)
    segmenter_page_textes(page)
    assert len(texts(page)) == 3
    assert locked == snapshot
    assert any(element is locked for element in page.elements)
    assert len({element.presentation["paragraph_id"] for element in page.elements}) == 3


def test_locked_multiline_node_is_not_sent_to_provider_or_split():
    locked = locked_paragraph("Locked first row", 20, "page:3:paragraph:0", multiline=True)
    snapshot = deepcopy(locked)
    page = page_of([line("New paragraph", 80), line("continues here", 94)])
    page.index = 3
    page.elements.insert(0, locked)
    segmenter_page_textes(page)
    assert page.elements[0] is locked
    assert locked == snapshot
    assert len(page.elements) == 2
    assert page.elements[1].presentation["paragraph_id"] == "page:3:paragraph:1"


def test_new_paragraph_ids_reserve_both_locked_source_and_paragraph_ids():
    locked = locked_paragraph("Locked", 20, "page:0:paragraph:0")
    locked.source_id = "page:0:paragraph:1"
    page = page_of([line("New paragraph", 80), line("continues here", 94)])
    page.elements.insert(0, locked)
    snapshot = deepcopy(locked)
    segmenter_page_textes(page)
    assert locked == snapshot
    assert page.elements[0] is locked
    assert page.elements[1].source_id == "page:0:paragraph:2"
    assert page.elements[1].presentation["paragraph_id"] == "page:0:paragraph:2"


def test_ai_cannot_join_one_source_across_a_locked_neighbour():
    page = page_of([line("Before", 20), line("after", 34)])
    locked = locked_paragraph("Locked", 27, "page:0:paragraph:0")
    page.elements.append(locked)
    snapshot = deepcopy(locked)
    configurer_fournisseur_comprehension_texte(
        lambda *args: TextUnderstandingDecision("paragraph", "segment-page", .99, line_groups=((0, 1),))
    )
    try:
        segmenter_page_textes(page)
    finally:
        configurer_fournisseur_comprehension_texte(None)
    assert len(page.elements) == 3
    assert any(element is locked for element in page.elements)
    assert locked == snapshot


def test_locked_node_in_other_column_does_not_interrupt_continuous_rows():
    page = page_of([line("Before", 20), line("after", 34)])
    locked = locked_paragraph("Other column", 27, "page:0:paragraph:0", x=350, width=150)
    page.elements.append(locked)
    segmenter_page_textes(page)
    assert len(page.elements) == 2
    assert texts(page)[0] == "Before after"
    assert any(element is locked for element in page.elements)


def test_distinct_frames_are_boundaries_for_same_row_fragments_too():
    rows = [line("Left", 20, width=80), line("Right", 20, x=144, width=80)]
    rows[0].layout_frame_id, rows[1].layout_frame_id = "frame-A", "frame-B"
    page = page_of(rows)
    segmenter_page_textes(page)
    assert texts(page) == ["Left", "Right"]


@pytest.mark.parametrize("separate_sources", [False, True])
@pytest.mark.parametrize("obstacle, count", [
    (box(125, 20, 139, 32), 2),
    (box(125, 5, 139, 19), 1),
    (box(125, 33, 139, 48), 1),
    (box(10, 10, 250, 70), 1),
])
def test_same_row_obstacle_uses_gap_corridor_not_background_or_nearby_images(separate_sources, obstacle, count):
    rows = [line("Left caption", 20, x=40, width=80), line("Right caption", 20, x=144, width=80)]
    page = page_of(rows if not separate_sources else rows[:1], [ImageEl(obstacle, "visual")])
    if separate_sources:
        page.elements.extend(page_of(rows[1:]).elements)
    for element in page.elements:
        if isinstance(element, TextBox):
            element.layout_frame_id = "shared-frame"
    segmenter_page_textes(page)
    assert len(texts(page)) == count


def test_ai_cannot_merge_same_row_captions_through_foreground():
    page = page_of([line("Left caption", 20, width=80), line("Right caption", 20, x=144, width=80)],
                   [ImageEl(box(125, 20, 139, 32), "foreground")])
    configurer_fournisseur_comprehension_texte(
        lambda *args: TextUnderstandingDecision("paragraph", "segment-page", .99, line_groups=((0, 1),))
    )
    try:
        segmenter_page_textes(page)
    finally:
        configurer_fournisseur_comprehension_texte(None)
    assert texts(page) == ["Left caption", "Right caption"]


@pytest.mark.parametrize("orientation, angle, curved", [
    ("vertical", 90.0, False), ("diagonal-up", 25.0, False),
    ("horizontal", 3.0, False), ("curved", 0.0, True),
])
def test_block_only_direction_is_copied_to_default_line_without_mutating_source(orientation, angle, curved):
    row = line("Special direction", 20)
    page = page_of([row])
    source = page.elements[0]
    source.orientation, source.angle_deg, source.curved = orientation, angle, curved
    snapshot = deepcopy(source)
    segmenter_page_textes(page)
    result = page.elements[0]
    assert (result.orientation, result.angle_deg, result.curved) == (orientation, angle, curved)
    copied = result.lignes[0]
    assert (copied.orientation, copied.angle_deg, copied.curved) == (orientation, angle, curved)
    assert result.presentation["orientation_source"] == "source-block-fallback"
    assert result.geometry == geometry_contract_for(result)
    assert source == snapshot
    assert copied.spans == row.spans
    assert copied.bbox == row.bbox


@pytest.mark.parametrize("evidence", ["orientation", "angle", "curve", "baseline", "quad", "span"])
def test_line_direction_evidence_is_not_overridden_by_block(evidence):
    row = line("Line direction is authoritative", 20)
    if evidence == "orientation":
        row.orientation, row.angle_deg = "diagonal-down", -30.0
    elif evidence == "angle":
        row.angle_deg = 2.5
    elif evidence == "curve":
        row.curved = True
    elif evidence == "baseline":
        row.baseline_points = ((row.bbox.x0, row.bbox.y1), (row.bbox.x1, row.bbox.y1))
    elif evidence == "quad":
        row.quad = ((row.bbox.x0, row.bbox.y0), (row.bbox.x1, row.bbox.y0 + 100),
                    (row.bbox.x1, row.bbox.y1), (row.bbox.x0, row.bbox.y1 - 100))
    else:
        row.spans[0].angle_deg = 4.0
    page = page_of([row])
    page.elements[0].orientation, page.elements[0].angle_deg = "vertical", 90.0
    original = deepcopy(row)
    segmenter_page_textes(page)
    result = page.elements[0]
    assert result.lignes[0] == original
    assert (result.orientation, result.angle_deg, result.curved) == (row.orientation, row.angle_deg, row.curved)
    assert "orientation_source" not in result.presentation


@pytest.mark.parametrize("ai_merge", [False, True])
@pytest.mark.parametrize("middle_frame", ["no-middle", None, "inferred:0:text-column:40:34:240:46"])
def test_proven_prose_continuity_survives_real_frame_changes(ai_merge, middle_frame):
    content = ["The project continues across several regions",
               "while preserving its existing operational interfaces"]
    frames = ["frame-A", "frame-B"]
    if middle_frame != "no-middle":
        content.insert(1, "with compatible geometry and unchanged source typography")
        frames.insert(1, middle_frame)
    rows = [line(text, 20 + 14 * index) for index, text in enumerate(content)]
    for row, frame in zip(rows, frames):
        row.layout_frame_id, row.layout_frame_role = frame, "text-column"
    original = deepcopy(rows)
    page = page_of(rows)
    configurer_fournisseur_comprehension_texte(
        (lambda *args: TextUnderstandingDecision("paragraph", "segment-page", .99,
                                                line_groups=(tuple(range(len(rows))),))) if ai_merge else None
    )
    try:
        segmenter_page_textes(page)
    finally:
        configurer_fournisseur_comprehension_texte(None)
    assert texts(page) == [" ".join(content)]
    assert page.elements[0].lignes == original
    assert len(page.elements[0].presentation["segmentation_owners"]) == 1


@pytest.mark.parametrize("ai_merge", [False, True])
@pytest.mark.parametrize("guard", ["end-sentence", "list", "style", "column", "same-row-column", "obstacle",
                                  "blank", "gap", "validated", "role", "labels", "uppercase", "orientation"])
def test_cross_frame_prose_proof_cannot_override_boundaries(ai_merge, guard):
    rows = [line("The project continues across several regions", 20),
            line("while preserving its existing operational interfaces", 34)]
    for row, frame in zip(rows, ("frame-A", "frame-B")):
        row.layout_frame_id, row.layout_frame_role = frame, "text-column"
    extra = []
    expected = 2
    if guard == "end-sentence":
        rows[0].spans[0].texte += "."
    elif guard == "list":
        rows[1].spans[0].texte = "1. " + rows[1].spans[0].texte
    elif guard == "style":
        rows[1].spans[0].couleur = "FF0000"
    elif guard == "column":
        rows[1].bbox = box(350, 34, 550, 46)
    elif guard == "same-row-column":
        rows[1].bbox = box(264, 20, 464, 32)
    elif guard == "obstacle":
        rows[1].bbox = box(40, 40, 240, 52)
        extra.append(ImageEl(box(40, 33, 240, 39), "foreground"))
    elif guard == "blank":
        rows[1].bbox = box(40, 40, 240, 52)
        rows.insert(1, line(" ", 34, width=3))
    elif guard == "gap":
        rows[1].bbox = box(40, 80, 240, 92)
    elif guard == "validated":
        extra.append(locked_paragraph("Independent validated node", 27, "page:0:paragraph:0"))
        expected = 3
    elif guard == "role":
        rows[1].layout_frame_role = "heading"
    elif guard == "labels":
        rows[0].spans[0].texte, rows[1].spans[0].texte = "Row 0", "Row 1"
    elif guard == "uppercase":
        rows[1].spans[0].texte = rows[1].spans[0].texte.capitalize()
    else:
        for row in rows:
            row.orientation, row.angle_deg = "vertical", 90.0
    page = page_of(rows, extra)
    configurer_fournisseur_comprehension_texte(
        (lambda *args: TextUnderstandingDecision("paragraph", "segment-page", .99,
                                                line_groups=((0, 1),))) if ai_merge else None
    )
    try:
        segmenter_page_textes(page)
    finally:
        configurer_fournisseur_comprehension_texte(None)
    assert len(texts(page)) == expected


@pytest.mark.parametrize("ai_merge", [False, True])
@pytest.mark.parametrize("case, count", [("prose", 1), ("labels", 2), ("end-sentence", 2),
                                       ("multiline-owner", 2), ("explicit-boundary", 2),
                                       ("same-row-column", 2), ("same-row-same-frame", 1)])
def test_cross_frame_source_fragments_require_proof_and_preserve_owner_constraints(ai_merge, case, count):
    page = page_of([line("The project continues across several regions", 20)])
    page.elements.extend(page_of([line("while preserving its existing operational interfaces", 34)]).elements)
    for element, frame in zip(page.elements, ("frame-A", "frame-B")):
        element.layout_frame_id, element.layout_frame_role = frame, "text-column"
    if case == "labels":
        for index, element in enumerate(page.elements):
            element.lignes[0].spans[0].texte = f"Row {index}"
    elif case == "end-sentence":
        page.elements[0].lignes[0].spans[0].texte += "."
    elif case == "multiline-owner":
        first = line("The project continues across several regions", 6)
        page.elements[0].lignes.insert(0, first)
        page.elements[0].bbox = box(40, 6, 240, 32)
    elif case == "explicit-boundary":
        page.elements[1].presentation["boundary_before"] = "approved-boundary"
    elif case in {"same-row-column", "same-row-same-frame"}:
        page.elements[1].bbox = page.elements[1].lignes[0].bbox = box(264, 20, 464, 32)
        if case == "same-row-same-frame":
            page.elements[1].layout_frame_id = page.elements[0].layout_frame_id
    configurer_fournisseur_comprehension_texte(
        (lambda kind, rows, *args: TextUnderstandingDecision("paragraph", "segment-page", .99,
                                                           line_groups=(tuple(range(len(rows))),))) if ai_merge else None
    )
    try:
        segmenter_page_textes(page)
    finally:
        configurer_fournisseur_comprehension_texte(None)
    assert len(texts(page)) == count
    owners = [element.presentation["segmentation_owners"] for element in page.elements]
    assert owners == ([["element:0", "element:1"]] if count == 1 else [["element:0"], ["element:1"]])


@pytest.mark.parametrize("distinct_frames", [False, True])
@pytest.mark.parametrize("path", ["segmentation-block", "segmentation-fragments", "legacy-textbox", "legacy-flow"])
def test_fused_paragraph_container_covers_all_frames_without_changing_source(path, distinct_frames):
    rows = [line("The project continues across several regions", 20),
            line("while preserving its existing operational interfaces", 34, width=240)]
    frame_boxes = ([box(40, 20, 240, 32), box(40, 34, 280, 46)] if distinct_frames
                   else [box(35, 15, 290, 60)] * 2)
    for index, row in enumerate(rows):
        row.layout_frame_id = "frame-B" if distinct_frames and index else "frame-A"
        row.layout_frame_bbox = frame_boxes[index]
        row.layout_frame_role, row.layout_frame_strategy = "text-column", "word-text"
        row.source_id = f"source-line:{index}"
    elements = ([page_of(rows).elements[0]] if path == "segmentation-block"
                else [page_of([row]).elements[0] for row in rows])
    for index, element in enumerate(elements):
        row = element.lignes[0]
        for name in ("layout_frame_id", "layout_frame_bbox", "layout_frame_role", "layout_frame_strategy"):
            setattr(element, name, getattr(row, name))
        element.source_id = f"source-block:{index}"
        element.source_ids = (element.source_id, *(row.source_id for row in element.lignes))
    if path == "legacy-flow":
        elements = [FlowParagraph(
            bbox=element.bbox, texte="".join(span.texte for span in element.lignes[0].spans),
            police=element.lignes[0].spans[0].police, size_pt=10, couleur="123456",
            lignes=element.lignes, spans=element.lignes[0].spans,
            layout_frame_id=element.layout_frame_id, layout_frame_bbox=element.layout_frame_bbox,
            layout_frame_role=element.layout_frame_role, layout_frame_strategy=element.layout_frame_strategy,
            source_id=element.source_id, source_ids=element.source_ids,
        ) for element in elements]
    source = deepcopy(elements)
    page = Page(0, pt_vers_emu(600), pt_vers_emu(800), list(elements))
    if path.startswith("segmentation"):
        segmenter_page_textes(page)
        assert len(page.elements) == 1
        fused = page.elements[0]
    else:
        fused = fusionner_flow_paragraphes(elements)
    assert elements == source
    assert fused.lignes == rows
    assert fused.layout_frame_role == "text-column"
    assert fused.layout_frame_strategy == "word-text"
    assert {row.source_id for row in rows}.issubset(fused.source_ids)
    if distinct_frames:
        assert fused.layout_frame_id is None
        assert fused.layout_frame_bbox == fused.bbox
        assert fused.layout_frame_bbox.largeur >= rows[1].bbox.largeur
    else:
        assert fused.layout_frame_id == "frame-A"
        assert fused.layout_frame_bbox == frame_boxes[0]
    plan = build_page_render_plan(page, [fused])
    planned = plan.for_page(0)[0]
    assert planned.element.attributes["layout_frame_bbox"] == fused.layout_frame_bbox
    assert planned.element.attributes["geometry_locked"] is True
    assert planned.element.bbox == fused.bbox
    assert planned.decision.mode in {RenderMode.POSITIONED_TEXT, RenderMode.LOCKED_NATIVE_PARAGRAPH}
    assert planned.decision.editable
    assert plan.validate() == []
    assert elements == source
