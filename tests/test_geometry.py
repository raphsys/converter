import pymupdf
import pytest

from pdfexact.geometry import (
    EMU_PER_PT,
    BBox,
    bbox_depuis_rect,
    emu_vers_pt,
    pt_vers_emu,
    pt_vers_twips,
    se_chevauchent,
    union,
)


def test_un_pouce_vaut_914400_emu():
    assert pt_vers_emu(72) == 914400


def test_conversion_en_twips():
    assert pt_vers_twips(12) == 240


def test_conversion_retour_en_points():
    assert emu_vers_pt(EMU_PER_PT) == pytest.approx(1.0)


def test_conversion_arrondit_au_lieu_de_tronquer():
    assert pt_vers_emu(0.00005) == 1


def test_bbox_expose_largeur_et_hauteur():
    boite = BBox(100, 200, 400, 600)

    assert boite.largeur == 300
    assert boite.hauteur == 400


def test_bbox_depuis_rect_convertit_en_emu():
    boite = bbox_depuis_rect(pymupdf.Rect(0, 0, 72, 144))

    assert boite.x1 == 914400
    assert boite.y1 == 1828800


def test_une_page_a4_fait_les_bonnes_dimensions():
    """595 x 842 pt, les dimensions que PyMuPDF donne pour une A4."""
    boite = bbox_depuis_rect(pymupdf.Rect(0, 0, 595, 842))

    assert boite.largeur == 7556500
    assert boite.hauteur == 10693400


def test_union_englobe_les_deux_boites():
    resultat = union(BBox(0, 0, 10, 10), BBox(5, 5, 20, 30))

    assert resultat == BBox(0, 0, 20, 30)


def test_union_est_commutative():
    a, b = BBox(0, 0, 10, 10), BBox(5, 5, 20, 30)

    assert union(a, b) == union(b, a)


def test_chevauchement_detecte():
    assert se_chevauchent(BBox(0, 0, 10, 10), BBox(5, 5, 15, 15))


def test_boites_disjointes_ne_se_chevauchent_pas():
    assert not se_chevauchent(BBox(0, 0, 10, 10), BBox(20, 20, 30, 30))


def test_boites_qui_se_touchent_ne_se_chevauchent_pas():
    """Un contact bord à bord n'est pas un chevauchement : l'aire d'intersection est nulle."""
    assert not se_chevauchent(BBox(0, 0, 10, 10), BBox(10, 0, 20, 10))


def test_une_boite_incluse_dans_une_autre_se_chevauche():
    assert se_chevauchent(BBox(0, 0, 100, 100), BBox(10, 10, 20, 20))
