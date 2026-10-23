"""Tables of contents: the layout AI says which zone is one, rows give entries.

The layout model labels the zone (role "table-of-contents"); no layout of
contents is listed here. Inside such a zone each row is an entry, unless it
continues the previous row: that row carried no page reference while the
zone's entries do carry references.
"""
from pdfexact.analysis.text_segmentation import segmenter_page_textes
from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.ir import FontRef, Line, Page, Span, TextBox
from pdfexact.layout.text_comprehension import configurer_fournisseur_comprehension_texte, contexte_comprehension_texte

TOC = "table-of-contents"


def _paragraphs(texts, role=TOC):
    lines = []
    for index, text in enumerate(texts):
        y = 100 + 12 * index
        bbox = BBox(u(72), u(y), u(540), u(y + 10))
        span = Span(text, FontRef("f", "Arial", False, False), 10, "000000", bbox=bbox)
        lines.append(Line(bbox, [span], bbox.hauteur, bbox.largeur, layout_frame_id="zone-1",
                          layout_frame_role="text-column", layout_frame_strategy="word-text",
                          semantic_role=role))
    bbox = BBox(u(72), lines[0].bbox.y0, u(540), lines[-1].bbox.y1)
    page = Page(0, u(612), u(792), [TextBox(bbox, lines, layout_frame_id="zone-1", layout_frame_role="text-column",
                                            layout_frame_strategy="word-text", semantic_role=role)])
    with contexte_comprehension_texte():
        configurer_fournisseur_comprehension_texte(None)
        segmenter_page_textes(page)
    return [len(element.lignes) for element in page.elements]


def test_each_row_ending_with_a_page_reference_is_an_entry():
    assert _paragraphs([
        "1 Introduction                                   1",
        "2 Methods .............................. 4",
        "Preface\tiv",
        "Annex A                                     40–44",
    ]) == [1, 1, 1, 1]


def test_a_row_without_reference_continues_into_the_row_that_ends_the_entry():
    assert _paragraphs([
        "Table 1. Stream Gage Flood Stage and Discharges for the",
        "Coastal Counties of Mississippi ...................... 11",
        "Table 2. Summary of Comparisons of HWM Elevations .... 16",
    ]) == [2, 1]


def test_without_any_page_reference_each_row_is_an_entry():
    assert _paragraphs([
        "Appendix A. Field Data Collection Forms",
        "Appendix B. HWM Location Maps and Summary Table",
        "Introduction",
    ]) == [1, 1, 1]


def test_rows_the_layout_ai_did_not_label_as_contents_are_not_split_as_entries():
    assert _paragraphs([
        "The survey teams recorded high water marks in the year",
        "2005 along the coast and found levels close to 12",
        "feet above the normal tide in the three counties.",
    ], role="body") == [3]


def test_a_wrapped_title_ending_on_a_word_or_a_number_is_not_mistaken_for_a_reference():
    assert _paragraphs([
        "Chapter 3. Results of the Survey of Phase 2",
        "and Observations on Civil Works ............ 21",
        "Part I. Conclusions of the Annex C",
        "Recommendations .............................. 30",
    ]) == [2, 2]


def test_a_reference_in_its_own_span_counts_without_any_blank_in_the_text():
    lines = []
    for index, (title, number) in enumerate((("Introduction", "1"), ("Methods", "4"))):
        y = 100 + 12 * index
        spans = [Span(title, FontRef("f", "Arial", False, False), 10, "000000",
                      bbox=BBox(u(72), u(y), u(160), u(y + 10))),
                 Span(number, FontRef("f", "Arial", False, False), 10, "000000",
                      bbox=BBox(u(530), u(y), u(540), u(y + 10)))]
        bbox = BBox(u(72), u(y), u(540), u(y + 10))
        lines.append(Line(bbox, spans, bbox.hauteur, bbox.largeur, layout_frame_id="zone-1",
                          layout_frame_role="text-column", layout_frame_strategy="word-text", semantic_role=TOC))
    lines.append(Line(BBox(u(72), u(124), u(300), u(134)),
                      [Span("Results of the field survey", FontRef("f", "Arial", False, False), 10, "000000",
                            bbox=BBox(u(72), u(124), u(300), u(134)))],
                      u(10), u(228), layout_frame_id="zone-1", layout_frame_role="text-column",
                      layout_frame_strategy="word-text", semantic_role=TOC))
    page = Page(0, u(612), u(792), [TextBox(BBox(u(72), u(100), u(540), u(134)), lines, layout_frame_id="zone-1",
                                            layout_frame_role="text-column", layout_frame_strategy="word-text",
                                            semantic_role=TOC)])
    with contexte_comprehension_texte():
        configurer_fournisseur_comprehension_texte(None)
        segmenter_page_textes(page)
    assert [len(element.lignes) for element in page.elements][:2] == [1, 1]
