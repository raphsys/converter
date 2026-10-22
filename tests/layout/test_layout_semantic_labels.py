"""Layout AI labels reach the lines as semantic roles; PaddleX runs tuned for CPU."""
import pytest

from pdfexact.extract.document import _attacher_frames_texte
from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.ir import FontRef, Line, Span, TextBox
from pdfexact.layout import ai
from pdfexact.layout.ai import LayoutAIZone


@pytest.mark.parametrize(("label", "role"), [
    ("text", "body"), ("doc_title", "title"), ("paragraph_title", "heading"), ("header", "header"),
    ("footer", "footer"), ("figure_title", "caption"), ("content", "table-of-contents"),
    ("reference", "reference"), ("reference_content", "reference"), ("footnote", "footnote"),
    ("number", "page-number"), ("abstract", "abstract"), ("aside_text", "aside"),
    ("algorithm", "algorithm"), ("formula_number", "formula-number"),
])
def test_every_text_label_has_a_semantic_role(label, role):
    assert ai.role_semantique_etiquette(label) == role


@pytest.mark.parametrize("label", ["number", "footnote", "abstract", "algorithm", "reference_content"])
def test_text_zones_formerly_dropped_are_text(label):
    assert ai._role(label) == "text"


def test_visual_labels_have_no_text_role():
    assert ai.role_semantique_etiquette("image") is None


def _line(text, y):
    bbox = BBox(u(72), u(y), u(540), u(y + 10))
    return Line(bbox, [Span(text, FontRef("f", "Arial", True, False), 10, "000000", bbox=bbox)], bbox.hauteur, bbox.largeur)


def test_lines_take_the_semantic_role_of_their_layout_zone():
    toc = [_line("1. Introduction .......... 1", 252), _line("1.1 General .......... 1", 264)]
    block = TextBox(BBox(u(72), u(252), u(540), u(274)), toc)
    zone = LayoutAIZone("z1", "content", "text", 0.9, BBox(u(70), u(245), u(545), u(280)), "paddlex", "PP-DocLayout_plus-L")
    (result,) = _attacher_frames_texte([block], [], [zone])
    assert [line.semantic_role for line in result.lignes] == ["table-of-contents", "table-of-contents"]
    assert result.semantic_role == "table-of-contents"


def test_paddlex_cpu_options_use_onednn_when_available_and_every_core(monkeypatch):
    monkeypatch.setattr(ai.os, "cpu_count", lambda: 8)
    option = ai._options_cpu_paddlex()
    assert option.cpu_threads == 8
    from paddlex.inference.utils.misc import is_mkldnn_available

    assert option.run_mode == ("mkldnn" if is_mkldnn_available() else "paddle")
