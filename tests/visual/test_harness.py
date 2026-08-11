import numpy as np
import pytest

from pdfexact.geometry import pt_vers_emu
from pdfexact.ir import Document, Page
from pdfexact.render.package import ecrire_docx
from tests.visual.harness import (
    comparer,
    docx_vers_pdf,
    rapport_de_comparaison,
    rendre_en_images,
    score_ssim,
)


@pytest.fixture
def docx_page_vide(tmp_path):
    sortie = tmp_path / "essai.docx"
    ecrire_docx(
        Document(pages=[Page(0, pt_vers_emu(595), pt_vers_emu(842))]), sortie
    )
    return sortie


def test_une_image_est_identique_a_elle_meme():
    image = np.random.default_rng(0).random((64, 64))

    assert score_ssim(image, image) == pytest.approx(1.0)


def test_deux_images_opposees_ont_un_score_bas():
    assert score_ssim(np.zeros((64, 64)), np.ones((64, 64))) < 0.1


def test_deux_images_sans_rapport_tombent_autour_de_zero():
    """Le SSIM vit dans [-1, 1] : sans rapport donne ~0, et peut passer en négatif."""
    generateur = np.random.default_rng(1)

    resultat = score_ssim(generateur.random((64, 64)), generateur.random((64, 64)))

    assert -1.0 <= resultat <= 1.0
    assert abs(resultat) < 0.2


def test_des_images_de_tailles_differentes_sont_recadrees():
    """LibreOffice recale les pages sur son format normalisé : les tailles diffèrent."""
    resultat = score_ssim(np.zeros((100, 100)), np.zeros((80, 90)))

    assert resultat == pytest.approx(1.0)


def test_une_image_minuscule_ne_fait_pas_lever_le_ssim():
    """En dessous de la fenêtre du SSIM, on retombe sur une comparaison exacte."""
    assert score_ssim(np.zeros((3, 3)), np.zeros((3, 3))) == 1.0
    assert score_ssim(np.zeros((3, 3)), np.ones((3, 3))) == 0.0


def test_un_bruit_leger_degrade_peu_le_score():
    base = np.zeros((128, 128))
    bruitee = base.copy()
    bruitee[64, 64] = 1.0

    assert score_ssim(base, bruitee) > 0.9


def test_le_rendu_donne_une_image_par_page(pdf_texte):
    images = rendre_en_images(pdf_texte, dpi=72)

    assert len(images) == 1
    assert images[0].ndim == 2
    assert images[0].max() <= 1.0


def test_le_dpi_agit_sur_la_taille_du_rendu(pdf_texte):
    petite = rendre_en_images(pdf_texte, dpi=36)[0]
    grande = rendre_en_images(pdf_texte, dpi=72)[0]

    assert grande.shape[0] > petite.shape[0]


def test_conversion_docx_vers_pdf(docx_page_vide, tmp_path):
    resultat = docx_vers_pdf(docx_page_vide, tmp_path)

    assert resultat.exists()
    assert resultat.suffix == ".pdf"


def test_libreoffice_accepte_un_docx_invalide_sans_broncher(tmp_path):
    """Mesure du comportement réel, pour qu'on ne s'y fie pas comme test de validité.

    LibreOffice convertit du texte brut renommé en .docx sans erreur. Une conversion
    réussie ne dit donc rien de la conformité OOXML du fichier ; celle-ci se vérifie
    structurellement dans tests/render/test_package.py.
    """
    faux = tmp_path / "faux.docx"
    faux.write_bytes(b"ceci n'est pas un zip OOXML")

    produit = docx_vers_pdf(faux, tmp_path)

    assert produit.exists(), "comportement constaté : LibreOffice accepte et convertit"


def test_comparer_retourne_un_score_par_page(pdf_texte, docx_page_vide):
    scores = comparer(pdf_texte, docx_page_vide, dpi=72)

    assert len(scores) == 1
    assert 0.0 <= scores[0] <= 1.0


def test_le_rapport_signale_les_pages_sous_le_seuil():
    texte = rapport_de_comparaison([0.99, 0.42], seuil=0.95)

    assert "page 1" in texte and "ok" in texte
    assert "page 2" in texte and "ECHEC" in texte
