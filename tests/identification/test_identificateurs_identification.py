"""The AIs decide: PP-DocLayout zones and native PDF facts, combined in a cascade."""
import json

import pytest

from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.identification import referentiel
from pdfexact.identification.base import Candidat, decider
from pdfexact.identification.identificateurs import contexte_page, decider_element, registre_par_defaut
from pdfexact.identification.referentiel import famille
from pdfexact.ir import FontRef, ImageEl, Line, LinkZone, Page, ShapeEl, Span, TableEl, TextBox
from pdfexact.layout.ai import LayoutAIZone

ARIAL = FontRef("f", "Arial", False, False)


def _box(x0, y0, x1, y1):
    return BBox(u(x0), u(y0), u(x1), u(y1))


def _texte(text, box):
    return TextBox(box, [Line(box, [Span(text, ARIAL, 10.0, "000000")], box.hauteur, box.largeur)])


def _page(elements, zones=()):
    page = Page(0, u(612), u(792), list(elements))
    page.zones_layout = list(zones)
    return page


def _zone(label, box, confidence=0.9):
    return LayoutAIZone("z", label, "text", confidence, box, "paddlex", "test")


def _decision(element, page, registre=None):
    return decider_element(element, page, contexte_page(page), registre)


def test_scores_of_one_type_combine_and_settle_the_status():
    decision = decider([Candidat("intertitre", 0.6, "a"), Candidat("intertitre", 0.5, "b"), Candidat("paragraphe", 0.4, "c")])
    assert (decision.type, decision.famille, decision.statut) == ("intertitre", "texte", "identifie")
    assert decision.confiance == pytest.approx(0.8)
    assert decision.alternatives == (("paragraphe", 0.4),)


def test_close_scores_are_ambiguous_noise_is_ignored_and_nothing_is_not_identified():
    assert decider([Candidat("intertitre", 0.7, "a"), Candidat("paragraphe", 0.65, "b")]).statut == "ambigu"
    assert decider([Candidat("qr_code", 0.01, "bruit")]).statut == "non_identifie"
    vide = decider([])
    assert (vide.type, vide.statut, vide.confiance) == ("inconnu", "non_identifie", 0.0)
    assert decider([], repli="image_generique").type == "image_generique"


def test_only_types_of_the_referential_can_come_out():
    assert famille("paragraphe") == "texte"
    with pytest.raises(ValueError):
        decider([Candidat("bold_word", 0.9, "x")])


@pytest.mark.parametrize("label,attendu", [
    ("doc_title", "titre_document"), ("paragraph_title", "intertitre"), ("text", "paragraphe"),
    ("header", "en_tete"), ("footer", "pied_de_page"), ("number", "numero_page"), ("figure_title", "legende"),
    ("content", "entree_sommaire"), ("footnote", "note_bas_page"), ("formula", "formule_bloc"),
])
def test_the_pp_doclayout_zone_of_a_text_gives_its_role(label, attendu):
    texte = _texte("Some text", _box(72, 100, 300, 116))
    decision = _decision(texte, _page([texte], [_zone(label, _box(70, 98, 302, 118))]))
    assert decision.type == attendu and decision.statut == "identifie"
    assert any(f"pp-doclayout:{label}" in indice for indice in decision.indices)


def test_an_element_and_a_zone_are_associated_when_one_lies_mostly_in_the_other():
    # The text box includes the line leading: twice as tall as the zone around its glyphs.
    ligne = _texte("Submitted to:", _box(432, 279, 546, 296))
    # The image box includes white margins around the detected seal.
    logo = ImageEl(_box(363, 315, 562, 411), "logo")
    page = _page([ligne, logo], [_zone("text", _box(432, 284, 539, 293), 0.78), _zone("image", _box(381, 334, 438, 390))])
    assert _decision(ligne, page).type == "paragraphe"
    assert "pp-doclayout:image" in _decision(logo, page).indices[0]


def test_among_several_zones_the_one_sharing_most_area_wins():
    texte = _texte("Results", _box(72, 100, 300, 140))
    page = _page([texte], [_zone("paragraph_title", _box(72, 100, 300, 112)), _zone("text", _box(72, 112, 300, 140))])
    assert _decision(texte, page).type == "paragraphe"


def test_visual_zones_and_native_facts():
    graphique = ImageEl(_box(72, 420, 400, 600), "g")
    sceau = ImageEl(_box(420, 420, 520, 520), "s")
    tableau = TableEl(_box(72, 200, 540, 400), [], [], ARIAL, 10.0)
    externe = LinkZone(_box(72, 100, 200, 112), uri="https://example.org")
    interne = LinkZone(_box(72, 120, 200, 132), page_cible=4)
    page = _page([graphique, sceau, tableau, externe, interne],
                 [_zone("chart", _box(70, 418, 402, 602)), _zone("seal", _box(418, 418, 522, 522))])
    assert [_decision(e, page).type for e in (graphique, sceau, tableau, externe, interne)] == [
        "graphique", "sceau", "tableau", "lien", "renvoi"]


def test_without_any_source_an_element_is_not_identified_rather_than_guessed():
    texte = _texte("Hurricane Katrina", _box(72, 60, 500, 90))
    forme = ShapeEl(_box(20, 20, 592, 772), [], None, "0000FF", u(1))
    image = ImageEl(_box(72, 100, 300, 300), "i")
    page = _page([texte, forme, image])
    assert [(_decision(e, page).type, _decision(e, page).statut) for e in (texte, forme, image)] == [
        ("inconnu", "non_identifie"), ("inconnu", "non_identifie"), ("image_generique", "non_identifie")]


def test_sources_complete_each_other_in_a_cascade():
    appels = []

    class Affineur:
        nom = "affineur"
        natures = frozenset({"image"})

        def pertinent(self, element, contexte, candidats):
            return not any(c.score >= 0.7 and c.type != "image_generique" for c in candidats)

        def candidats(self, element, contexte):
            appels.append(element.media_ref)
            return [Candidat("photo", 0.8, "affineur")]

    graphique = ImageEl(_box(72, 420, 400, 600), "graphique")
    generique = ImageEl(_box(72, 100, 400, 300), "generique")
    page = _page([graphique, generique], [_zone("chart", _box(70, 418, 402, 602)), _zone("image", _box(70, 98, 402, 302))])
    registre = registre_par_defaut(Affineur())
    assert _decision(graphique, page, registre).type == "graphique"
    assert _decision(generique, page, registre).type == "photo"
    assert appels == ["generique"]


def test_the_referential_stays_open_to_extension_files_and_runtime_types(tmp_path, monkeypatch):
    extensions = tmp_path / "extensions"
    extensions.mkdir()
    (extensions / "chimie.json").write_text(json.dumps({
        "familles": {"chimie": "Chimie"}, "types": [{"id": "structure_moleculaire", "famille": "chimie", "libelle": "x"}]}))
    monkeypatch.setattr(referentiel, "DOSSIER_EXTENSIONS", extensions)
    referentiel.recharger()
    try:
        assert famille("structure_moleculaire") == "chimie" and famille("paragraphe") == "texte"
        referentiel.etendre_referentiel({"cachet_douane": "image"})
        assert decider([Candidat("cachet_douane", 0.9, "plugin")]).type == "cachet_douane"
        with pytest.raises(ValueError):
            referentiel.etendre_referentiel({"paragraphe": "image"})
        with pytest.raises(ValueError):
            referentiel.etendre_referentiel({"x_inconnu": "famille_absente"})
    finally:
        monkeypatch.undo()
        referentiel.recharger()
    with pytest.raises(ValueError):
        famille("cachet_douane")


def test_a_failing_source_is_reported_and_the_others_go_on(caplog):
    class EnPanne:
        nom = "en-panne"
        natures = frozenset({"text"})

        def candidats(self, element, contexte):
            raise RuntimeError("image vide")

    texte = _texte("Some text", _box(72, 100, 300, 116))
    page = _page([texte], [_zone("text", _box(70, 98, 302, 118))])
    with caplog.at_level("WARNING"):
        decision = _decision(texte, page, registre_par_defaut(EnPanne()))
    assert decision.type == "paragraphe"
    assert any("en-panne" in indice and "image vide" in indice for indice in decision.indices)
    assert "en-panne" in caplog.text
