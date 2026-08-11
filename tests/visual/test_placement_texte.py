"""Fidélité de la chaîne texte, mesurée numériquement puis visuellement.

Le critère principal n'est pas le SSIM mais l'écart de coordonnées : on relit les
baselines réelles dans le PDF issu du docx et on les compare à celles de la source.
Un dixième de point s'y voit, là où une comparaison d'images ne montrerait rien.
"""
import pytest

from pdfexact.extract.document import extraire
from pdfexact.render.package import ecrire_docx
from tests.visual.harness import comparer, ecarts_de_placement, rapport_de_comparaison

# Seuils sur le cas nominal — police du PDF réellement retrouvée dans la bibliothèque.
# Un point vaut 0,35 mm ; un demi-point d'écart est en dessous du trait d'un glyphe.
TOLERANCE_POSITION_PT = 0.5
TOLERANCE_LARGEUR_PCT = 1.0
SEUIL_SSIM = 0.90


@pytest.fixture
def conversion(tmp_path, pdf_police_connue):
    document = extraire(pdf_police_connue)
    sortie = tmp_path / "police_connue.docx"
    ecrire_docx(document, sortie)
    return pdf_police_connue, sortie


def test_toutes_les_lignes_se_retrouvent_dans_le_resultat(conversion):
    source, docx = conversion

    ecarts = ecarts_de_placement(source, docx)

    assert ecarts["apparies"] == ecarts["total_source"] == 3


def test_les_baselines_tombent_au_bon_endroit(conversion):
    """Valide la formule de placement : haut = baseline - ascendante."""
    source, docx = conversion

    ecarts = ecarts_de_placement(source, docx)

    assert abs(ecarts["dy_median_pt"]) < TOLERANCE_POSITION_PT, ecarts


def test_aucune_ligne_ne_derive_isolement(conversion):
    """Une seule ligne mal placée suffit à trahir la conversion, même si la médiane tient."""
    source, docx = conversion

    ecarts = ecarts_de_placement(source, docx)

    assert ecarts["dy_max_pt"] < 2.0, ecarts


def test_les_abscisses_sont_conservees(conversion):
    source, docx = conversion

    ecarts = ecarts_de_placement(source, docx)

    assert abs(ecarts["dx_median_pt"]) < TOLERANCE_POSITION_PT, ecarts


def test_la_largeur_des_lignes_est_conservee(conversion):
    """Valide la correction d'espacement : l'écart est réparti sur chaque caractère."""
    source, docx = conversion

    ecarts = ecarts_de_placement(source, docx)

    assert abs(ecarts["dlargeur_median_pct"]) < TOLERANCE_LARGEUR_PCT, ecarts


def test_le_rendu_est_visuellement_fidele(conversion):
    source, docx = conversion

    scores = comparer(source, docx, dpi=150)

    assert scores, "aucune page comparée"
    assert all(score >= SEUIL_SSIM for score in scores), rapport_de_comparaison(
        scores, SEUIL_SSIM
    )


def test_une_police_absente_est_signalee(pdf_texte):
    """Les polices non retrouvées doivent rester traçables jusqu'au rapport."""
    document = extraire(pdf_texte)

    assert document.polices
    for asset in document.polices.values():
        assert isinstance(asset.reconnue, bool)
