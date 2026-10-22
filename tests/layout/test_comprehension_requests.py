"""Model requests are compact and split instead of refused."""
import pytest

from pdfexact.layout import text_comprehension_local as local

EMU = 12700


def row(index, y, *, text="Appendix A. Field Data Collection Forms"):
    return {
        "index": index, "text": text, "bbox": [72 * EMU, y * EMU, 268 * EMU, (y + 10) * EMU],
        "source_ids": ["p3:pdf-native:Line:" + "0" * 24, "p3:pdf-native:Span:" + "1" * 24],
        "layout_frame_id": "frame-7", "layout_role": "text-column", "semantic_role": None,
        "orientation": "horizontal", "angle_deg": 0.0, "alignment": "left",
        "styles": [{"font": "Arial", "size_pt": 10.0, "bold": True, "italic": False, "color": "000000"}],
        "dominant_style": {"font": "Arial", "size_pt": 10.0, "bold": True, "italic": False, "color": "000000"},
        "spacing_before_emu": 0, "blank_separator_before": False, "boundary_before": None,
        "boundary_after": None, "segmentation_owner": f"element:{index}",
    }


def context():
    return {
        "lines": [row(0, 100), row(1, 117.4)],
        "neighbors": [row(index, 300 + index * 12) for index in range(80)],
        "obstacles": [[72 * EMU, 110 * EMU, 300 * EMU, 112 * EMU], [72 * EMU, 600 * EMU, 300 * EMU, 650 * EMU]],
        "page_index": 3, "frame_strategy": "word-text",
        "coordinate_system": {"origin": "top-left", "units": "EMU"},
    }


def test_model_view_keeps_line_facts_and_drops_page_wide_context():
    view = local._metadonnees_modele(context())
    assert "neighbors" not in view
    assert view["page_index"] == 3
    first = view["lines"][0]
    assert first == {"i": 0, "bbox_pt": [72.0, 100.0, 268.0, 110.0], "size_pt": 10.0, "bold": True,
                     "alignment": "left", "role": "text-column"}
    # Only obstacles crossing the band of the requested lines matter to their boundaries.
    assert view["obstacles_pt"] == [[72.0, 110.0, 300.0, 112.0]]


def test_model_view_is_much_smaller_than_the_full_context():
    import json

    assert len(json.dumps(local._metadonnees_modele(context()))) * 20 < len(json.dumps(context()))


@pytest.mark.parametrize(("count", "size"), [(10, 4), (17, 5), (3, 2), (5, 9)])
def test_windows_overlap_by_one_line_so_every_adjacent_pair_is_judged_once(count, size):
    windows = local._fenetres(count, size)
    assert all(len(window) <= max(size, 2) for window in windows)
    pairs = [(index, index + 1) for window in windows for index in window[:-1]]
    assert sorted(pairs) == [(index, index + 1) for index in range(count - 1)]


def test_window_decisions_are_sewn_into_one_contiguous_partition():
    windows = [range(0, 4), range(3, 6)]
    groups = [((0, 1), (2, 3)), ((0,), (1, 2))]  # local indices per window
    assert local._recoudre_groupes(6, windows, groups) == ((0, 1), (2, 3), (4, 5))


def test_oversized_segmentation_is_split_into_windows_and_every_window_reaches_the_model():
    from pdfexact.layout.text_comprehension import TextUnderstandingDecision

    lines = tuple(f"Appendix {letter}. Title" for letter in "ABCDEFG")
    ctx = {"lines": [row(index, 100 + 17 * index, text=text) for index, text in enumerate(lines)], "page_index": 3}
    seen = []

    def model(kind, window_lines, role, window_context):
        seen.append((window_lines, [r["index"] for r in window_context["lines"]]))
        # The model keeps every entry on its own line.
        return TextUnderstandingDecision("list", "segment-page", 0.9, ("model",),
                                         line_groups=tuple((index,) for index in range(len(window_lines))))

    decision = local._segmenter_par_fenetres(model, lambda kind, ls, role, c: len(ls) > 3,
                                             "page-segmentation", lines, "text-column", ctx)
    assert decision.line_groups == tuple((index,) for index in range(7))
    assert all(len(window) <= 3 for window, _ in seen)
    assert all(indices == list(range(len(window))) for window, indices in seen)
    assert {line for window, _ in seen for line in window} == set(lines)


def test_a_window_without_decision_fails_the_whole_request():
    lines = ("a", "b", "c", "d", "e")
    ctx = {"lines": [row(index, 100 + 12 * index, text=text) for index, text in enumerate(lines)]}
    assert local._segmenter_par_fenetres(lambda *args: None, lambda kind, ls, role, c: len(ls) > 2,
                                         "page-segmentation", lines, None, ctx) is None
