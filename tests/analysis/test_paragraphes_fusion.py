"""Paragraphs: geometry always required, then the PP-DocLayout zone or the semantic continuation (vysi)."""
from pdfexact.analysis.paragraphes import continuation_semantique, fusionner_paragraphes
from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.ir import FontRef, Line, Span, TextBox
from pdfexact.layout.ai import LayoutAIZone

ARIAL = FontRef("f", "Arial", False, False)
ARIAL_GRAS = FontRef("g", "Arial", True, False)


def _ligne(texte, y, x0=72, x1=400, taille=10.0, police=ARIAL):
    box = BBox(u(x0), u(y), u(x1), u(y + taille * 1.2))
    return TextBox(box, [Line(box, [Span(texte, police, taille, "000000")], box.hauteur, box.largeur)])


def _textes(groupes):
    return [" | ".join("".join(s.texte for s in unite.lignes[0].spans) for unite in groupe) for groupe in groupes]


def _zone(label, x0, y0, x1, y1):
    return LayoutAIZone("z", label, "text", 0.9, BBox(u(x0), u(y0), u(x1), u(y1)), "paddlex", "t")


def test_semantic_continuation_follows_vysi():
    assert continuation_semantique("Missions are being developed to", "ensure that all agendas")
    assert continuation_semantique("The habitat must be designed", "with a long-term view")
    assert continuation_semantique("Les missions sont conçues pour", "garantir que tous les objectifs")
    assert continuation_semantique("A" * 85, "Next part of a long line")
    assert not continuation_semantique("The plan is complete.", "Next steps are")
    assert not continuation_semantique("Results", "Overview")


def test_lines_of_one_pp_doclayout_text_zone_form_one_paragraph():
    groupes = [[_ligne("Missions With a Primary Objective of", 100)], [_ligne("Infrastructure Assembly Performed by", 114)],
               [_ligne("Humans or Robots", 128, x1=180)]]
    fusion = fusionner_paragraphes(groupes, zones=[_zone("text", 70, 98, 402, 142)])
    assert _textes(fusion) == ["Missions With a Primary Objective of | Infrastructure Assembly Performed by | Humans or Robots"]


def test_a_sentence_running_on_joins_lines_outside_any_zone():
    groupes = [[_ligne("The system of systems is derived from", 100)], [_ligne("the exploration vision and its goals.", 114)]]
    assert len(fusionner_paragraphes(groupes)) == 1


def test_geometry_is_always_required():
    loin = [[_ligne("The system of systems is derived from", 100)], [_ligne("the exploration vision.", 200)]]
    autre_colonne = [[_ligne("The system of systems is derived from", 100, 72, 280)],
                     [_ligne("the exploration vision.", 114, 320, 540)]]
    assert len(fusionner_paragraphes(loin)) == 2
    assert len(fusionner_paragraphes(autre_colonne)) == 2


def test_an_obstacle_between_the_lines_separates_them():
    groupes = [[_ligne("The system of systems is derived from", 100)], [_ligne("the exploration vision.", 122)]]
    assert len(fusionner_paragraphes(groupes)) == 1  # close enough on their own
    assert len(fusionner_paragraphes(groupes, obstacles=[BBox(u(72), u(112.5), u(400), u(121.5))])) == 2


def test_a_finished_sentence_or_another_typography_starts_a_new_paragraph():
    fini = [[_ligne("The plan is complete.", 100)], [_ligne("Next steps are listed below", 114)]]
    titre = [[_ligne("Concept Exploration and Refinement", 100, police=ARIAL_GRAS)], [_ligne("of the lunar architecture", 114)]]
    assert len(fusionner_paragraphes(fini)) == 2
    assert len(fusionner_paragraphes(titre)) == 2


def test_a_list_item_starts_a_new_paragraph_even_inside_a_zone():
    groupes = [[_ligne("– Managed as a significant national priority", 100)], [_ligne("– Regular, visible demonstrations", 114)]]
    assert len(fusionner_paragraphes(groupes, zones=[_zone("text", 70, 98, 402, 130)])) == 2


def test_multi_entry_zones_are_not_merged():
    groupes = [[_ligne("Introduction ........ 3", 100)], [_ligne("Methods ........ 7", 114)]]
    assert len(fusionner_paragraphes(groupes, zones=[_zone("content", 70, 98, 402, 130)])) == 2


def test_a_background_holding_both_lines_does_not_separate_them():
    # Slides: text drawn over a box or picture that holds the whole paragraph.
    groupes = [[_ligne("Missions Are Being Developed to", 100)], [_ligne("Ensure That All Agendas Will Be", 114)]]
    fond = BBox(u(60), u(90), u(420), u(140))
    assert len(fusionner_paragraphes(groupes, zones=[_zone("text", 70, 98, 402, 130)], obstacles=[fond])) == 1


def test_labels_of_a_figure_are_not_joined_by_meaning():
    groupes = [[_ligne("highest", 100, x1=160)], [_ligne("mixing", 114, x1=160)], [_ligne("salt wedge", 128, x1=160)]]
    figure = [_zone("image", 60, 90, 300, 150)]
    assert len(fusionner_paragraphes(groupes, zones=figure)) == 3
    assert len(fusionner_paragraphes(groupes)) == 1  # outside any zone, meaning still joins
