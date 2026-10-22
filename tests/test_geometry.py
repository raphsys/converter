from io import BytesIO

import pymupdf
import pytest
from PIL import Image

from pdfexact.geometry import (
    EMU_PER_PT,
    BBox,
    PageGeometry,
    bbox_depuis_rect,
    emu_vers_pt,
    etat_page,
    preserver_etat_page,
    pt_vers_emu,
    pt_vers_twips,
    se_chevauchent,
    union,
)
from pdfexact.extract.fonts import collecter_polices
from pdfexact.extract.images import extraire_images
from pdfexact.extract.text import extraire_texte
from pdfexact.fontlib import construire, dossiers_par_defaut


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


def test_page_tournee_90_devient_paysage():
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.set_rotation(90)

    geometrie = PageGeometry.depuis_page(page)

    assert geometrie.paysage
    assert round(geometrie.largeur_pt) == 792
    assert round(geometrie.hauteur_pt) == 612


def test_rectangle_natif_est_converti_en_coordonnees_affichees():
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.set_rotation(90)
    geometrie = PageGeometry.depuis_page(page)

    bbox = geometrie.bbox_depuis_rect_natif(pymupdf.Rect(72, 50, 147, 738))

    assert round(emu_vers_pt(bbox.x0)) == 54
    assert round(emu_vers_pt(bbox.y0)) == 72
    assert round(emu_vers_pt(bbox.x1)) == 742
    assert round(emu_vers_pt(bbox.y1)) == 147


def test_texte_natif_tourne_est_normalise_dans_le_repere_affiche():
    """Le texte PDF natif et la page tournee doivent produire une ligne horizontale."""
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    # Le flux natif est tourne de 90 degres ; la rotation de page le remet
    # horizontal dans le document visible paysage.
    page.insert_text((100, 300), "Rotated title", fontsize=24, rotate=90)
    page.set_rotation(90)
    try:
        polices = collecter_polices(doc, construire(dossiers=dossiers_par_defaut()))
        elements = extraire_texte(
            page,
            polices,
            geometrie=PageGeometry.depuis_page(page),
        )
    finally:
        doc.close()

    assert len(elements) == 1
    element = elements[0]
    assert element.orientation == "horizontal"
    assert element.angle_deg == pytest.approx(0.0)
    assert emu_vers_pt(element.bbox.largeur) > emu_vers_pt(element.bbox.hauteur)


def test_image_native_tournee_est_placee_dans_le_repere_affiche():
    """Une image conserve sa position apres la rotation de page, sans double rotation."""
    tampon = BytesIO()
    Image.new("RGB", (100, 100), (20, 40, 60)).save(tampon, format="PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_image(pymupdf.Rect(100, 200, 300, 400), stream=tampon.getvalue())
    page.set_rotation(90)
    try:
        geometrie = PageGeometry.depuis_page(page)
        elements = extraire_images(page, doc, {}, geometrie=geometrie)
    finally:
        doc.close()

    assert len(elements) == 1
    bbox = elements[0].bbox
    assert tuple(round(emu_vers_pt(value)) for value in (bbox.x0, bbox.y0, bbox.x1, bbox.y1)) == (
        392,
        100,
        592,
        300,
    )


def test_preserve_etat_page_restaure_cropbox_rotation_et_rect():
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.set_cropbox(pymupdf.Rect(93.9, 0, 518.16, 792))
    page.set_rotation(90)
    original = etat_page(page)
    rect_initial = pymupdf.Rect(page.rect)

    with preserver_etat_page(page):
        page.set_cropbox(page.mediabox)
        page.set_rotation(0)

    assert etat_page(page) == original
    assert page.rect == rect_initial


@pytest.mark.parametrize("y0_pt", [137.0, 137.2, 137.45, 160.1, 183.33])
def test_un_filet_fin_garde_la_meme_epaisseur_quelle_que_soit_sa_position(y0_pt):
    from pdfexact.geometry import GRILLE_DIXIEME_MM_EMU, quantifier_bbox

    filet = quantifier_bbox(BBox(pt_vers_emu(83), pt_vers_emu(y0_pt), pt_vers_emu(229), pt_vers_emu(y0_pt + 0.72)))
    reference = quantifier_bbox(BBox(pt_vers_emu(83), pt_vers_emu(300), pt_vers_emu(229), pt_vers_emu(300.72)))
    assert filet.hauteur == reference.hauteur == 3 * GRILLE_DIXIEME_MM_EMU
    centre = (pt_vers_emu(y0_pt) + pt_vers_emu(y0_pt + 0.72)) / 2
    assert abs((filet.y0 + filet.y1) / 2 - centre) <= GRILLE_DIXIEME_MM_EMU / 2


def test_une_boite_epaisse_conserve_son_enveloppe():
    from pdfexact.geometry import quantifier_bbox

    boite = BBox(pt_vers_emu(10.1), pt_vers_emu(20.1), pt_vers_emu(200.3), pt_vers_emu(80.3))
    q = quantifier_bbox(boite)
    assert q.x0 <= boite.x0 and q.y0 <= boite.y0 and q.x1 >= boite.x1 and q.y1 >= boite.y1
