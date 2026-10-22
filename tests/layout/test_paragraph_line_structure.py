"""The paragraph plan keeps intentional line breaks and keeps rows inside their source width."""
import pytest

from pdfexact.analysis.text_geometry import block_alignment
from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.ir import FontRef, Line, Span, TextBox
from pdfexact.layout import paragraph_planner
from pdfexact.layout import text_comprehension as comprehension
from pdfexact.layout.paragraph_planner import planifier_paragraphe


@pytest.fixture(autouse=True)
def deterministic_reflow():
    token = comprehension._ANALYSE.set(comprehension._AnalysisState(None))
    yield
    comprehension._ANALYSE.reset(token)


def row(text, x0, x1, y, size=10.0):
    bbox = BBox(u(x0), u(y), u(x1), u(y + size))
    span = Span(text, FontRef("f", "Arial", True, False), size, "000000", bbox=bbox)
    return Line(bbox, [span], bbox.hauteur, bbox.largeur)


def block(rows):
    return TextBox(BBox(min(r.bbox.x0 for r in rows), min(r.bbox.y0 for r in rows),
                        max(r.bbox.x1 for r in rows), max(r.bbox.y1 for r in rows)), rows)


def toc():
    return block([row("1. Introduction ......................1", 72, 542.5, 252.2),
                  row("1.1 General.........................1", 93.6, 542.5, 263.7),
                  row("1.2 Purpose.........................2", 93.6, 542.5, 275.2)])


def appendices():
    return block([row("Appendix A. Field Data Collection Forms", 72, 268.4, 561.9),
                  row("Appendix B. HWM Location Maps and Summary Table", 72, 331.8, 579.3),
                  row("Appendix C. Survey Sheets from Hancock County", 72, 311.7, 596.9)])


def test_leader_rows_keep_one_row_per_entry():
    plan = planifier_paragraphe(toc())
    assert [plan.action_between(index) for index in range(2)] == ["preserve_break", "preserve_break"]
    assert plan.estimated_line_count == 3


def test_short_rows_of_a_list_keep_their_breaks_against_the_column_edge():
    plan = planifier_paragraphe(appendices(), column_right=u(540))
    assert [plan.action_between(index) for index in range(2)] == ["preserve_break", "preserve_break"]


def test_running_prose_still_reflows():
    prose = block([row("The system validates incoming data and reports every", 72, 536, 100),
                   row("anomaly to the operator through the console.", 72, 300, 112)])
    assert planifier_paragraphe(prose, column_right=u(540)).action_between(0) == "space"


def test_right_aligned_rows_are_a_composition_with_fixed_breaks():
    address = block([row("URS Group, Inc.", 411.7, 545.4, 583, 14), row("200 Orchard Ridge Drive", 337.4, 545.4, 597.6, 14),
                     row("Suite 101", 460.3, 545.4, 612.3, 14)])
    assert planifier_paragraphe(address).preserve_lines
    assert block_alignment(address) == "right"


def test_leader_lists_are_left_aligned_not_justified():
    figures = block([row(f"Figure {n} – A title of the figure number {n} ..............{n + 9}", 72, 542.5, 112 + 14.5 * n)
                     for n in range(1, 8)])
    assert block_alignment(figures) == "left"


@pytest.mark.parametrize(("measured", "expected"), [(600.0, 90), (300.0, 180), (553.0, 98), (520.0, 100)])
def test_fixed_rows_are_scaled_to_their_source_width_whatever_the_substitute_font(monkeypatch, measured, expected):
    title = block([row("Final Coastal and Riverine High", 31.5, 582.4, 415.2, 42),
                   row("Water Mark Collection for", 31.5, 490.3, 464.2, 42),
                   row("Hurricane Katrina in Mississippi", 31.5, 584.1, 513.2, 42)])
    title.semantic_role = "title"
    monkeypatch.setattr(paragraph_planner, "_police_largeur", lambda *args: None)
    monkeypatch.setattr(paragraph_planner, "_largeur_ligne_pt",
                        lambda line, polices: measured if line is title.lignes[0] else None)
    plan = planifier_paragraphe(title, polices={"f": object()})
    assert plan.preserve_lines
    assert abs(plan.line_width_scale_percent[0] - expected) <= 1
    assert plan.line_width_scale_percent[1:] == (100, 100)


@pytest.mark.parametrize(("percent", "expected"), [(176, '<w:w w:val="176"/>'), (55, '<w:w w:val="55"/>'), (100, None)])
def test_row_scale_is_written_in_both_directions(percent, expected):
    from pdfexact.render.text_runs import RunInstruction, render_runs

    xml = render_runs((RunInstruction(row("Collection", 0, 80, 0).spans[0], width_percent=percent),))
    assert (expected in xml) if expected else "<w:w " not in xml


def test_scaled_rows_drop_character_spacing_whatever_the_direction():
    from types import SimpleNamespace
    from dataclasses import replace

    from pdfexact.render.text_runs import prepare_runs

    line = row("Collection", 0, 80, 0)
    line.spans[0] = replace(line.spans[0], espacement_twips=18)
    composition = SimpleNamespace(action_between=lambda index: "space", line_width_scale_percent=(150,), line_spacing_twips=(0,))
    (token,) = prepare_runs(block([line]), [line], composition, native=True)
    assert token.width_percent == 150 and token.span.espacement_twips == 0


def _texts(tokens):
    return [token.span.texte if token.span is not None else token.command for token in tokens]


def test_leader_rows_become_a_right_tab_with_a_dot_leader_at_the_source_edge():
    from pdfexact.render.geometry_adapter import twips
    from pdfexact.render.text_backend import prepare_text_instructions, render_native_paragraph

    text = prepare_text_instructions(toc())
    tokens = _texts(text.native_runs)
    assert not any("..." in str(token) for token in tokens)
    assert tokens[:3] == ["1. Introduction", "tab", "1"]
    assert "1.1 General" in tokens and "2" in tokens
    position = twips(u(542.5) - text.geometry.bbox.x0)
    assert f'<w:tab w:val="right" w:leader="dot" w:pos="{position}"/>' in render_native_paragraph(text)
    assert "<w:br/>" in render_native_paragraph(text)


def test_column_edge_reaches_the_planner_through_text_instructions():
    from pdfexact.render.text_backend import prepare_text_instructions

    text = prepare_text_instructions(appendices(), column_right=u(540))
    assert _texts(text.native_runs).count("break") == 2


def test_rows_with_matching_metrics_are_not_condensed(monkeypatch):
    lists = appendices()
    monkeypatch.setattr(paragraph_planner, "_police_largeur", lambda *args: None)
    monkeypatch.setattr(paragraph_planner, "_largeur_ligne_pt", lambda line, polices: line.bbox.largeur / 12700 * 0.995)
    plan = planifier_paragraphe(lists, polices={"f": object()}, column_right=u(540))
    assert plan.line_width_scale_percent == (100, 100, 100)
