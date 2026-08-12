"""Extraction des images, du vectoriel, des clusters et des liens."""
import pymupdf
import pytest

from pdfexact.extract.images import extraire_images
from pdfexact.extract.links import appliquer_liens
from pdfexact.extract.ocr import _corriger_elements_ocr
from pdfexact.extract.text import extraire_texte
from pdfexact.extract.fonts import collecter_polices
from pdfexact.extract.vector import (
    boite_du_cluster,
    doit_rasteriser,
    extraire_vectoriel,
    regrouper,
)
from pdfexact.fallback.rasterize import page_a_des_degrades, rasteriser_region
from pdfexact.geometry import BBox, pt_vers_emu
from pdfexact.ir import ShapeEl


# --- images ---------------------------------------------------------------


def test_les_deux_placements_sont_extraits(pdf_image):
    doc = pymupdf.open(pdf_image)
    media = {}
    try:
        elements = extraire_images(doc[0], doc, media)
    finally:
        doc.close()

    assert len(elements) == 2


def test_limage_repetee_nest_stockee_quune_fois(pdf_image):
    doc = pymupdf.open(pdf_image)
    media = {}
    try:
        elements = extraire_images(doc[0], doc, media)
    finally:
        doc.close()

    assert len(media) == 1
    assert elements[0].media_ref == elements[1].media_ref
    assert elements[0].bbox != elements[1].bbox


def test_le_media_porte_des_octets_et_une_extension(pdf_image):
    doc = pymupdf.open(pdf_image)
    media = {}
    try:
        extraire_images(doc[0], doc, media)
    finally:
        doc.close()

    item = next(iter(media.values()))
    assert len(item.donnees) > 0
    assert item.extension in ("png", "jpeg", "jpg")


# --- vectoriel ------------------------------------------------------------


def _formes(chemin):
    doc = pymupdf.open(chemin)
    try:
        return extraire_vectoriel(doc[0])
    finally:
        doc.close()


def test_les_dessins_sont_extraits(pdf_vectoriel):
    assert len(_formes(pdf_vectoriel)) >= 2


def test_le_rectangle_rouge_est_reconnu(pdf_vectoriel):
    remplissages = {f.remplissage for f in _formes(pdf_vectoriel) if f.remplissage}

    assert "FF0000" in remplissages


def test_les_chemins_sont_des_commandes_nommees(pdf_vectoriel):
    for forme in _formes(pdf_vectoriel):
        for chemin in forme.chemins:
            for operateur, points in chemin:
                assert operateur in ("move", "line", "cubic", "quad", "close")
                assert all(isinstance(c, int) for point in points for c in point)


def test_une_bbox_plate_recoit_une_epaisseur(pdf_vectoriel):
    """Une ligne horizontale a une bbox d'aire nulle : elle serait non rendable."""
    for forme in _formes(pdf_vectoriel):
        assert forme.bbox.largeur > 0
        assert forme.bbox.hauteur > 0


# --- clusters -------------------------------------------------------------


def _forme(x0, y0, x1, y1):
    return ShapeEl(
        bbox=BBox(x0, y0, x1, y1),
        chemins=[[("move", ((x0, y0),)), ("line", ((x1, y1),))]],
        remplissage=None,
        contour="000000",
        epaisseur_emu=12700,
    )


def test_des_formes_disjointes_font_des_clusters_distincts():
    assert len(regrouper([_forme(0, 0, 10, 10), _forme(100, 100, 110, 110)])) == 2


def test_des_formes_qui_se_chevauchent_fusionnent():
    clusters = regrouper([_forme(0, 0, 20, 20), _forme(10, 10, 30, 30)])

    assert len(clusters) == 1 and len(clusters[0]) == 2


def test_la_fusion_est_transitive():
    """A touche B, B touche C, mais A ne touche pas C : un seul cluster attendu."""
    clusters = regrouper(
        [_forme(0, 0, 20, 20), _forme(15, 15, 35, 35), _forme(30, 30, 50, 50)]
    )

    assert len(clusters) == 1 and len(clusters[0]) == 3


def test_liste_vide_ne_produit_aucun_cluster():
    assert regrouper([]) == []


def test_la_boite_du_cluster_englobe_ses_membres():
    cluster = [_forme(0, 0, 20, 20), _forme(15, 15, 35, 35)]

    assert boite_du_cluster(cluster) == BBox(0, 0, 35, 35)


def test_un_petit_cluster_sans_degrade_nest_pas_rasterise():
    assert not doit_rasteriser([_forme(0, 0, 10, 10)], False, seuil=300)


def test_un_degrade_sur_la_page_force_le_repli():
    assert doit_rasteriser([_forme(0, 0, 10, 10)], True, seuil=300)


def test_un_cluster_trop_dense_est_rasterise():
    cluster = [_forme(i, i, i + 5, i + 5) for i in range(400)]

    assert doit_rasteriser(cluster, False, seuil=300)


# --- repli raster ---------------------------------------------------------


def test_la_region_produit_un_element_raster(pdf_vectoriel):
    doc = pymupdf.open(pdf_vectoriel)
    media = {}
    boite = BBox(pt_vers_emu(50), pt_vers_emu(50), pt_vers_emu(200), pt_vers_emu(150))
    try:
        element = rasteriser_region(doc[0], boite, media, dpi=72)
    finally:
        doc.close()

    assert element.bbox == boite
    assert media[element.media_ref].extension == "png"
    assert media[element.media_ref].donnees.startswith(b"\x89PNG")


def test_deux_regions_produisent_des_references_distinctes(pdf_vectoriel):
    doc = pymupdf.open(pdf_vectoriel)
    media = {}
    try:
        a = rasteriser_region(doc[0], BBox(0, 0, pt_vers_emu(100), pt_vers_emu(100)), media, 72)
        b = rasteriser_region(
            doc[0], BBox(pt_vers_emu(100), 0, pt_vers_emu(200), pt_vers_emu(100)), media, 72
        )
    finally:
        doc.close()

    assert a.media_ref != b.media_ref and len(media) == 2


def test_un_pdf_sans_degrade_est_detecte(pdf_vectoriel):
    doc = pymupdf.open(pdf_vectoriel)
    try:
        assert page_a_des_degrades(doc, doc[0]) is False
    finally:
        doc.close()


# --- liens ----------------------------------------------------------------


def _liens(chemin):
    doc = pymupdf.open(chemin)
    try:
        page = doc[0]
        blocs = extraire_texte(page, collecter_polices(doc))
        return blocs, appliquer_liens(page, blocs)
    finally:
        doc.close()


def test_le_lien_est_pose_sur_le_span_recouvert(pdf_liens):
    blocs, zones = _liens(pdf_liens)

    liens = [s.lien for b in blocs for l in b.lignes for s in l.spans]
    assert "https://example.org/" in liens
    assert zones == [], "un lien couvrant du texte ne doit pas laisser de zone"


def test_un_lien_sans_texte_devient_une_zone(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_link({
        "kind": pymupdf.LINK_URI,
        "from": pymupdf.Rect(400, 400, 500, 450),
        "uri": "https://exemple.test/zone",
    })
    chemin = tmp_path / "zone.pdf"
    doc.save(chemin)
    doc.close()

    blocs, zones = _liens(chemin)

    assert blocs == []
    assert len(zones) == 1 and zones[0].uri == "https://exemple.test/zone"


def test_un_lien_interne_porte_la_page_cible(tmp_path):
    doc = pymupdf.open()
    doc.new_page(width=595, height=842)
    doc.new_page(width=595, height=842)
    doc[0].insert_link({
        "kind": pymupdf.LINK_GOTO,
        "from": pymupdf.Rect(100, 100, 200, 120),
        "page": 1,
    })
    chemin = tmp_path / "interne.pdf"
    doc.save(chemin)
    doc.close()

    _blocs, zones = _liens(chemin)

    assert zones[0].page_cible == 1
    assert zones[0].uri is None


# --- OCR ------------------------------------------------------------------


def test_les_mots_ocr_adjacents_sont_corriges():
    elements = [
        ("TECIINOI", 0.91, BBox(10, 10, 20, 20)),
        ("OGY", 0.89, BBox(20, 10, 26, 20)),
        ("TRANSFIX", 0.96, BBox(30, 10, 50, 20)),
    ]

    corriges = _corriger_elements_ocr(elements)

    assert corriges == [
        ("TECHNOLOGY", 0.89, BBox(10, 10, 26, 20)),
        ("TRANSFIX", 0.96, BBox(30, 10, 50, 20)),
    ]
