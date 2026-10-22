"""Paint order comes from painted components, not inherited container values."""
from pdfexact.analysis.provenance import source_paint_index
from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.ir import FontRef, Line, Span, TextBox


def _view(span_sequence, container_sequence):
    bbox = BBox(u(350), u(140), u(410), u(154))
    span = Span("Definition", FontRef("f", "Times", True, False), 12, "000000", bbox=bbox, z_index=span_sequence)
    line = Line(bbox, [span], bbox.hauteur, bbox.largeur, z_index=span_sequence)
    return TextBox(bbox, [line], z_index=container_sequence)


def test_inherited_container_sequence_does_not_hide_later_painted_text():
    # The view inherited 7 from a block whose first label was painted at 7;
    # its own glyphs were painted at 10, after a fill painted at 8.
    assert source_paint_index(_view(10, 7)) == 10


def test_container_sequence_remains_the_fallback_without_component_sequences():
    assert source_paint_index(_view(None, 7)) == 7


def test_earliest_painted_component_is_kept():
    view = _view(10, 7)
    view.lignes[0].spans.append(Span("x", FontRef("f", "Times", False, False), 12, "000000",
                                     bbox=view.bbox, z_index=4))
    assert source_paint_index(view) == 4
