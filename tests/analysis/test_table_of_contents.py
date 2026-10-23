"""Every kind of table of contents: each entry is its own paragraph.

An entry is recognised by its page reference, wherever the document puts it:
after leader dots, right-aligned after a blank, after a tab, or on the left.
Without a leader, the reference must be set apart by a blank and aligned with
the reference of another row, so justified prose ending on a number is kept.
"""
import pytest

from pdfexact.analysis.text_segmentation import segmenter_page_textes
from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.ir import FontRef, Line, Page, Span, TextBox
from pdfexact.layout.text_comprehension import configurer_fournisseur_comprehension_texte, contexte_comprehension_texte

FONT = FontRef("f", "Arial", False, False)
CHAR_PT = 5.0


def _row(parts, y):
    """parts: (text, x_pt) pieces of one row, each one span."""
    spans = []
    for text, x in parts:
        bbox = BBox(u(x), u(y), u(x + CHAR_PT * len(text)), u(y + 10))
        spans.append(Span(text, FONT, 10, "000000", bbox=bbox))
    bbox = BBox(spans[0].bbox.x0, u(y), spans[-1].bbox.x1, u(y + 10))
    return Line(bbox, spans, bbox.hauteur, bbox.largeur, layout_frame_id="zone-1",
                layout_frame_role="text-column", layout_frame_strategy="word-text")


def _paragraphs(rows):
    lines = [_row(parts, 100 + 12 * index) for index, parts in enumerate(rows)]
    bbox = BBox(min(line.bbox.x0 for line in lines), lines[0].bbox.y0,
                max(line.bbox.x1 for line in lines), lines[-1].bbox.y1)
    page = Page(0, u(612), u(792), [TextBox(bbox, lines, layout_frame_id="zone-1",
                                            layout_frame_role="text-column", layout_frame_strategy="word-text")])
    with contexte_comprehension_texte():
        configurer_fournisseur_comprehension_texte(None)
        segmenter_page_textes(page)
    return [len(element.lignes) for element in page.elements]


def _right(title, number, x=72):
    """Title on the left, page number right-aligned at 500 pt."""
    return [(title, x), (number, 500 - CHAR_PT * len(number))]


def test_leader_dots_entries():
    assert _paragraphs([
        [("Table 1. Stream Gage Flood Stage and Discharges ..........11", 72)],
        [("Table 2. Summary of Comparisons of HWM Elevations ........16", 72)],
        [("Table 3. Coastal Flooding Type ...........................20", 72)],
    ]) == [1, 1, 1]


def test_right_aligned_numbers_without_leaders():
    assert _paragraphs([_right("1 Introduction", "1"), _right("2 Methods", "4"),
                        _right("2.1 Field survey", "5"), _right("3 Results", "12")]) == [1, 1, 1, 1]


def test_tab_separated_numbers_and_roman_numerals():
    assert _paragraphs([
        [("Preface\tiv", 72)], [("Foreword\tvii", 72)], [("Chapter 1\t1", 72)],
    ]) == [1, 1, 1]


def test_page_ranges():
    assert _paragraphs([_right("Annex A", "40–44"), _right("Annex B", "45-52")]) == [1, 1]


def test_page_numbers_on_the_left():
    assert _paragraphs([
        [("3", 72), ("Introduction", 110)], [("7", 72), ("Survey method", 110)],
        [("12", 72), ("Results", 110)],
    ]) == [1, 1, 1]


def test_an_entry_whose_title_wraps_stays_one_paragraph():
    assert _paragraphs([
        [("Table 1. Stream Gage Flood Stage and Discharges for the", 72)],
        _right("Coastal Counties of Mississippi", "11"),
        _right("Table 2. Summary of Comparisons", "16"),
    ]) == [2, 1]


def test_indented_levels_keep_one_entry_per_row():
    assert _paragraphs([_right("1 Introduction", "1"), _right("1.1 Scope", "2", x=90),
                        _right("1.2 Sources", "3", x=90)]) == [1, 1, 1]


def test_justified_prose_ending_on_numbers_is_not_a_table_of_contents():
    assert _paragraphs([
        [("The survey teams recorded high water marks in 2005", 72)],
        [("along the coast and found levels close to 12", 72)],
        [("feet above the normal tide in the three counties.", 72)],
    ]) == [3]


def test_a_single_isolated_number_without_leader_is_not_enough():
    assert _paragraphs([
        [("The level reached", 72)], _right("then dropped to", "8"),
        [("before the next tide came in.", 72)],
    ]) == [3]


def test_entries_without_page_numbers_are_told_by_a_repeated_label_and_a_changing_marker():
    assert _paragraphs([
        [("Appendix A. Field Data Collection Forms", 72)],
        [("Appendix B. HWM Location Maps and Summary Table", 72)],
        [("Appendix C. Survey Sheets from Hancock County", 72)],
    ]) == [1, 1, 1]


def test_a_label_repeated_with_the_same_marker_is_prose_not_entries():
    assert _paragraphs([
        [("Figure 2 compares the levels measured by the two teams and", 72)],
        [("Figure 2 also shows the stations of the three counties.", 72)],
    ]) == [2]
