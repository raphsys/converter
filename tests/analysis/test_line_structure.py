"""Typographic line structure: leaders, hard breaks and geometric alignment."""
import pytest

from pdfexact.analysis.line_structure import geometric_alignment, hard_break_reason, is_leader_line, split_leader
from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.ir import FontRef, Line, Span


def line(text, x0, x1, y=100.0, size=10.0, bold=False):
    bbox = BBox(u(x0), u(y), u(x1), u(y + size))
    span = Span(text, FontRef("f", "Arial", bold, False), size, "000000", bbox=bbox)
    return Line(bbox, [span], bbox.hauteur, bbox.largeur)


@pytest.mark.parametrize("text", [
    "1.1 General........................1",
    "Introduction and Purpose of the Study.............vii",
    "Methodology    ......................vii",
    "Figure 17 – Locations - - - - - - - - 27",
])
def test_dot_leader_rows_are_recognised(text):
    assert is_leader_line(line(text, 72, 542))


@pytest.mark.parametrize("text", ["Appendix A. Field Data Collection Forms", "Version 1.2.3 released", "Total: 12"])
def test_ordinary_rows_are_not_leader_rows(text):
    assert not is_leader_line(line(text, 72, 300))


def test_leader_split_keeps_label_and_page_and_names_the_leader():
    assert split_leader("1.1 General........1 ") == ("1.1 General", "1", "dot")
    assert split_leader("Plain text") is None


def test_a_leader_row_always_ends_its_line():
    previous, current = line("1. Introduction ..........1", 72, 542), line("1.1 General.......1", 93, 542, y=112)
    assert hard_break_reason(previous, current, right_edge=u(542)) == "leader-row"


def test_a_line_that_stops_while_the_next_word_would_fit_is_a_hard_break():
    previous = line("Appendix A. Field Data Collection Forms", 72, 268)
    current = line("Appendix B. HWM Location Maps and Summary Table", 72, 332, y=117)
    assert hard_break_reason(previous, current, right_edge=u(540)) == "short-line"


def test_a_full_line_of_running_prose_continues():
    previous = line("The system validates incoming data and reports every", 72, 536)
    current = line("anomaly to the operator.", 72, 190, y=112)
    assert hard_break_reason(previous, current, right_edge=u(540)) is None


def test_right_and_centered_blocks_are_inferred_from_their_edges():
    right = [line("Hazard Mitigation Technical Assistance Program", 148, 545.4, size=14),
             line("Contract No. EMW-2000-CO-0247", 267, 545.4, y=115, size=14),
             line("Gaithersburg, MD 20878", 338, 539.9, y=130, size=14)]
    assert geometric_alignment(right) == "right"
    centered = [line("A centred heading", 200, 400), line("on two lines", 240, 360, y=112)]
    assert geometric_alignment(centered) == "center"


def test_indented_leader_lists_and_left_blocks_are_not_right_aligned():
    toc = [line("1. Introduction ..........1", 72, 542.5), line("1.1 General.......1", 93.6, 542.5, y=112),
           line("1.2 Purpose.......2", 93.6, 542.5, y=124)]
    assert geometric_alignment(toc) is None
    left = [line("Appendix A. Field Data", 72, 268), line("Appendix B. HWM Location", 72, 332, y=117)]
    assert geometric_alignment(left) is None
