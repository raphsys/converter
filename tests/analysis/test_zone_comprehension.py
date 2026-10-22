"""Comprehension is asked once per layout zone and its paragraphs are final."""
import pytest

from pdfexact.analysis.text_segmentation import segmenter_page_textes
from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.ir import FontRef, Line, Page, Span, TextBox
from pdfexact.layout.text_comprehension import (
    TextUnderstandingDecision, configurer_fournisseur_comprehension_texte, contexte_comprehension_texte,
)

TEXTS = ("The survey teams recorded high water marks along", "the coast of Hancock County during the week",
         "after the storm passed over the region.")


def page():
    blocks = []
    for index, text in enumerate(TEXTS):
        y = 100 + 12 * index
        bbox = BBox(u(72), u(y), u(400), u(y + 10))
        span = Span(text, FontRef("f", "Arial", False, False), 10, "000000", bbox=bbox)
        line = Line(bbox, [span], bbox.hauteur, bbox.largeur, layout_frame_id="zone-1",
                    layout_frame_role="text-column", layout_frame_strategy="word-text")
        blocks.append(TextBox(bbox, [line], layout_frame_id="zone-1", layout_frame_role="text-column",
                              layout_frame_strategy="word-text"))
    return Page(0, u(612), u(792), blocks)


@pytest.mark.parametrize(("groups", "paragraphs"), [
    (((0,), (1,), (2,)), 3),   # the model keeps each row apart: no geometric re-merge
    (((0, 1, 2),), 1),         # the model joins rows coming from three source blocks
])
def test_zone_is_one_request_and_its_groups_are_final(groups, paragraphs):
    requests = []

    def provider(kind, lines, role, context):
        requests.append((kind, tuple(lines)))
        return TextUnderstandingDecision("paragraph", "segment-page", 0.9, ("test",), line_groups=groups)

    target = page()
    with contexte_comprehension_texte():
        configurer_fournisseur_comprehension_texte(provider)
        segmenter_page_textes(target)
    assert [request for request in requests if request[0] == "page-segmentation"] == [("page-segmentation", TEXTS)]
    assert len(target.elements) == paragraphs
