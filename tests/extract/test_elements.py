"""Extraction des images, du vectoriel, des clusters et des liens."""
import pymupdf

from pdfexact.extract.images import extraire_images
from pdfexact.extract.layout_map import PageLayoutMap, quantifier_bbox
from pdfexact.extract.links import appliquer_liens
from pdfexact.extract.ocr import (
    _corriger_elements_ocr,
    _dedoublonner_elements_ocr,
    _normaliser_marqueur_colonne_droite,
    _reconstruire_lignes_depuis_mots_colonnes,
    _semble_formule,
    _touche_zone_ignoree,
)
from pdfexact.extract.text import extraire_texte
from pdfexact.extract.fonts import collecter_polices
from pdfexact.extract.vector import (
    boite_du_cluster,
    doit_rasteriser,
    extraire_vectoriel,
    regrouper,
)
from pdfexact.fallback.rasterize import page_a_des_degrades, rasteriser_region
from pdfexact.geometry import BBox, pt_vers_emu, se_chevauchent
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


def test_un_mini_trait_horizontal_tres_epais_devient_vertical():
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.draw_line((305, 370), (306, 370), width=560)

    formes = extraire_vectoriel(page)

    assert len(formes) == 1
    assert formes[0].bbox.hauteur >= pt_vers_emu(550)
    assert formes[0].bbox.largeur <= pt_vers_emu(2)


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


def test_un_degrade_sur_la_page_ne_force_pas_un_cluster_simple():
    """Un shading local ne doit pas rasteriser un cluster indépendant."""
    assert not doit_rasteriser([_forme(0, 0, 10, 10)], True, seuil=300)


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


def test_une_ligne_native_verticale_conserve_sa_bbox_complete():
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((100, 300), "Photo by Author", fontsize=6, rotate=90, fontname="helv")
    try:
        blocs = extraire_texte(page, collecter_polices(doc))
    finally:
        doc.close()

    ligne = blocs[0].lignes[0]
    assert ligne.orientation == "vertical"
    assert ligne.bbox.hauteur > ligne.bbox.largeur * 4


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


def test_les_lignes_ocr_superposees_sont_dedoublonnees():
    bbox = BBox(10, 10, 110, 30)

    corriges = _dedoublonner_elements_ocr(
        [
            ("FEMA", 0.80, bbox),
            ("FOR PUBLIC RELEASE", 0.92, bbox),
        ]
    )

    assert corriges == [("FOR PUBLIC RELEASE", 0.92, bbox)]


def test_les_lignes_ocr_incluses_sur_la_meme_ligne_sont_dedoublonnees():
    grand = BBox(10, 100, 500, 120)
    petit = BBox(40, 101, 260, 121)

    corriges = _dedoublonner_elements_ocr(
        [
            ("a partial noisy duplicate", 0.80, petit),
            ("This is the complete OCR line that should be kept", 0.90, grand),
        ]
    )

    assert corriges == [("This is the complete OCR line that should be kept", 0.90, grand)]


def test_locr_recouvrant_un_tableau_protege_est_filtre():
    zone_tableau = BBox(100, 100, 500, 420)
    ligne_ocr_debordante = BBox(80, 112, 520, 132)

    assert _touche_zone_ignoree(ligne_ocr_debordante, [zone_tableau])


def test_locr_ligne_fusionnee_est_reconstruite_par_colonne_native():
    colonnes = [
        BBox(pt_vers_emu(50), pt_vers_emu(80), pt_vers_emu(190), pt_vers_emu(240)),
        BBox(pt_vers_emu(220), pt_vers_emu(80), pt_vers_emu(360), pt_vers_emu(240)),
        BBox(pt_vers_emu(390), pt_vers_emu(80), pt_vers_emu(530), pt_vers_emu(240)),
    ]
    mots = [
        ("Left", 0.9, BBox(pt_vers_emu(55), pt_vers_emu(100), pt_vers_emu(82), pt_vers_emu(112))),
        ("one", 0.9, BBox(pt_vers_emu(88), pt_vers_emu(100), pt_vers_emu(112), pt_vers_emu(112))),
        ("Middle", 0.9, BBox(pt_vers_emu(225), pt_vers_emu(100), pt_vers_emu(270), pt_vers_emu(112))),
        ("two", 0.9, BBox(pt_vers_emu(276), pt_vers_emu(100), pt_vers_emu(300), pt_vers_emu(112))),
        ("Right", 0.9, BBox(pt_vers_emu(395), pt_vers_emu(100), pt_vers_emu(430), pt_vers_emu(112))),
        ("three", 0.9, BBox(pt_vers_emu(436), pt_vers_emu(100), pt_vers_emu(480), pt_vers_emu(112))),
        ("Next", 0.9, BBox(pt_vers_emu(55), pt_vers_emu(124), pt_vers_emu(90), pt_vers_emu(136))),
        ("line", 0.9, BBox(pt_vers_emu(96), pt_vers_emu(124), pt_vers_emu(122), pt_vers_emu(136))),
    ]

    lignes = _reconstruire_lignes_depuis_mots_colonnes(mots, colonnes)
    textes = [ligne.texte for ligne in lignes]

    assert "Left one" in textes
    assert "Middle two" in textes
    assert "Right three" in textes
    assert "Next line" in textes
    assert next(ligne for ligne in lignes if ligne.texte == "Left one").bbox.x1 <= colonnes[0].x1
    assert next(ligne for ligne in lignes if ligne.texte == "Middle two").bbox.x0 >= colonnes[1].x0


def test_locr_ligne_fusionnee_respecte_cadres_lecture_decoupes():
    cadres = [
        BBox(pt_vers_emu(50), pt_vers_emu(80), pt_vers_emu(190), pt_vers_emu(140)),
        BBox(pt_vers_emu(50), pt_vers_emu(220), pt_vers_emu(300), pt_vers_emu(300)),
        BBox(pt_vers_emu(220), pt_vers_emu(80), pt_vers_emu(360), pt_vers_emu(300)),
    ]
    mots = [
        ("Top", 0.9, BBox(pt_vers_emu(55), pt_vers_emu(100), pt_vers_emu(82), pt_vers_emu(112))),
        ("left", 0.9, BBox(pt_vers_emu(88), pt_vers_emu(100), pt_vers_emu(116), pt_vers_emu(112))),
        ("Hidden", 0.9, BBox(pt_vers_emu(55), pt_vers_emu(175), pt_vers_emu(100), pt_vers_emu(187))),
        ("gap", 0.9, BBox(pt_vers_emu(106), pt_vers_emu(175), pt_vers_emu(128), pt_vers_emu(187))),
        ("Bottom", 0.9, BBox(pt_vers_emu(55), pt_vers_emu(240), pt_vers_emu(104), pt_vers_emu(252))),
        ("left", 0.9, BBox(pt_vers_emu(110), pt_vers_emu(240), pt_vers_emu(138), pt_vers_emu(252))),
        ("Right", 0.9, BBox(pt_vers_emu(225), pt_vers_emu(175), pt_vers_emu(260), pt_vers_emu(187))),
        ("ok", 0.9, BBox(pt_vers_emu(266), pt_vers_emu(175), pt_vers_emu(286), pt_vers_emu(187))),
    ]

    lignes = _reconstruire_lignes_depuis_mots_colonnes(mots, cadres)
    textes = [ligne.texte for ligne in lignes]

    assert "Top left" in textes
    assert "Bottom left" in textes
    assert "Right ok" in textes
    assert "Hidden gap" not in textes


def test_locr_ne_reconstruit_pas_sans_colonnes_natives():
    mots = [
        ("mot", 0.9, BBox(pt_vers_emu(20 + index * 16), 0, pt_vers_emu(30 + index * 16), 10))
        for index in range(6)
    ]

    assert _reconstruire_lignes_depuis_mots_colonnes(mots, []) == []


# --- carte géométrique ----------------------------------------------------


def test_la_quantification_conserve_lenveloppe():
    boite = BBox(1, 3599, 3601, 7201)

    assert quantifier_bbox(boite) == BBox(0, 0, 7200, 10800)


def test_la_carte_recale_locr_sur_la_ligne_native():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(600), hauteur_emu=pt_vers_emu(800))
    natif = BBox(pt_vers_emu(72), pt_vers_emu(120), pt_vers_emu(450), pt_vers_emu(134))
    ocr = BBox(pt_vers_emu(70), pt_vers_emu(119), pt_vers_emu(595), pt_vers_emu(136))
    carte.ajouter(
        "native-line",
        natif,
        "test",
        text="Final Report Hurricane Katrina in Mississippi",
        font_name="JoannaMT",
        size_pt=18,
    )

    assert carte.recaler_ligne_ocr(ocr, "Final Report Hurricane Katrina in Mississippi") == natif


def test_la_carte_ne_recale_pas_sur_un_texte_natif_incompatible():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(600), hauteur_emu=pt_vers_emu(800))
    natif = BBox(pt_vers_emu(72), pt_vers_emu(120), pt_vers_emu(450), pt_vers_emu(134))
    ocr = BBox(pt_vers_emu(70), pt_vers_emu(119), pt_vers_emu(595), pt_vers_emu(136))
    carte.ajouter("native-line", natif, "test", text="remxsgifwvnrLambqcnktmrim")

    recale = carte.recaler_ligne_ocr(
        ocr,
        "The accumulated knowledge has been technology transferred to actuation mechanisms.",
    )

    assert recale != natif


def test_la_carte_ne_deplace_pas_une_ligne_vers_une_autre_colonne():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(600), hauteur_emu=pt_vers_emu(800))
    natif = BBox(pt_vers_emu(86), pt_vers_emu(433), pt_vers_emu(533), pt_vers_emu(447))
    ocr = BBox(pt_vers_emu(190), pt_vers_emu(433), pt_vers_emu(533), pt_vers_emu(447))
    carte.ajouter(
        "native-line",
        natif,
        "test",
        text="The formal action by the President to make a state eligible for major",
    )

    recale = carte.recaler_ligne_ocr(
        ocr,
        "The formal action by the President to make a state eligible for major",
    )

    assert recale.x0 >= pt_vers_emu(180)


def test_la_carte_recale_sur_une_ligne_native_fusionnee():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(600), hauteur_emu=pt_vers_emu(800))
    carte.ajouter(
        "native-visual-line",
        BBox(pt_vers_emu(56), pt_vers_emu(225), pt_vers_emu(560), pt_vers_emu(241)),
        "test",
        text="bad native fragments but correct visual width",
    )
    ocr = BBox(pt_vers_emu(56), pt_vers_emu(225), pt_vers_emu(346), pt_vers_emu(241))

    recale = carte.recaler_ligne_ocr(
        ocr,
        "the accumulated knowledge has been technology transferred to actuation mechanisms.",
    )

    assert recale.x1 == pt_vers_emu(560)
    assert recale.x0 == pt_vers_emu(56)


def test_la_carte_nelargit_pas_un_mot_court_sur_une_ligne_fusionnee():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(600), hauteur_emu=pt_vers_emu(800))
    carte.ajouter(
        "native-visual-line",
        BBox(pt_vers_emu(86), pt_vers_emu(655), pt_vers_emu(293), pt_vers_emu(670)),
        "test",
        text="WWL Wind Water Line",
    )
    ocr = BBox(pt_vers_emu(86), pt_vers_emu(655), pt_vers_emu(110), pt_vers_emu(670))

    recale = carte.recaler_ligne_ocr(ocr, "WWL")

    assert recale.x1 < pt_vers_emu(140)


def test_la_ligne_fusionnee_ne_deplace_pas_le_bord_gauche_ocr():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(600), hauteur_emu=pt_vers_emu(800))
    carte.ajouter(
        "native-visual-line",
        BBox(pt_vers_emu(86), pt_vers_emu(433), pt_vers_emu(533), pt_vers_emu(447)),
        "test",
        text="Disaster declaration The formal action by the President to make a state eligible",
    )
    ocr = BBox(pt_vers_emu(190), pt_vers_emu(433), pt_vers_emu(533), pt_vers_emu(447))

    recale = carte.recaler_ligne_ocr(
        ocr,
        "The formal action by the President to make a state eligible",
    )

    assert recale.x0 == pt_vers_emu(190)
    assert recale.x1 == pt_vers_emu(533)


def test_la_carte_contraint_une_ligne_ocr_longue_au_cadre_natif():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(600), hauteur_emu=pt_vers_emu(800))
    carte.ajouter(
        "native-line",
        BBox(pt_vers_emu(80), pt_vers_emu(100), pt_vers_emu(500), pt_vers_emu(114)),
        "test",
        text="A native text frame establishes the right margin",
    )
    ocr = BBox(pt_vers_emu(80), pt_vers_emu(150), pt_vers_emu(598), pt_vers_emu(164))

    contraint = carte.contraindre_bbox_texte(
        ocr,
        "This OCR line is long enough to be constrained by the native text frame",
    )

    assert contraint.x1 <= pt_vers_emu(508)


def test_la_carte_contraint_une_ligne_ocr_longue_a_sa_colonne_native():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(600), hauteur_emu=pt_vers_emu(800))
    for index in range(8):
        y0 = 90 + index * 22
        carte.ajouter(
            "native-line",
            BBox(pt_vers_emu(55), pt_vers_emu(y0), pt_vers_emu(205), pt_vers_emu(y0 + 12)),
            "test",
            text=f"Left column native text line number {index}",
        )
        carte.ajouter(
            "native-line",
            BBox(pt_vers_emu(225), pt_vers_emu(y0), pt_vers_emu(375), pt_vers_emu(y0 + 12)),
            "test",
            text=f"Middle column native text line number {index}",
        )
        carte.ajouter(
            "native-line",
            BBox(pt_vers_emu(395), pt_vers_emu(y0), pt_vers_emu(545), pt_vers_emu(y0 + 12)),
            "test",
            text=f"Right column native text line number {index}",
        )
    ocr = BBox(pt_vers_emu(56), pt_vers_emu(290), pt_vers_emu(548), pt_vers_emu(305))

    contraint = carte.contraindre_bbox_texte(
        ocr,
        "This OCR line starts in the first column but was detected across the whole page",
    )

    assert contraint.x0 <= pt_vers_emu(58)
    assert contraint.x1 <= pt_vers_emu(210)


def test_la_carte_decoupe_les_cadres_lecture_autour_des_visuels():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(600), hauteur_emu=pt_vers_emu(800))
    for index in range(8):
        y0 = 90 + index * 32
        carte.ajouter(
            "native-line",
            BBox(pt_vers_emu(55), pt_vers_emu(y0), pt_vers_emu(205), pt_vers_emu(y0 + 12)),
            "test",
            text=f"Left column native text line number {index}",
        )
        carte.ajouter(
            "native-line",
            BBox(pt_vers_emu(225), pt_vers_emu(y0), pt_vers_emu(545), pt_vers_emu(y0 + 12)),
            "test",
            text=f"Right column native text line number {index}",
        )

    image = BBox(pt_vers_emu(55), pt_vers_emu(150), pt_vers_emu(205), pt_vers_emu(220))
    carte.ajouter("image", image, "test-image")

    cadres = carte.cadres_lecture_natifs()
    cadres_gauche = [
        cadre
        for cadre in cadres
        if cadre.x0 <= pt_vers_emu(60) and cadre.x1 >= pt_vers_emu(190)
    ]

    assert len(cadres_gauche) == 2
    assert all(not se_chevauchent(cadre, image) for cadre in cadres_gauche)

    ocr = BBox(pt_vers_emu(56), pt_vers_emu(230), pt_vers_emu(548), pt_vers_emu(245))
    contraint = carte.contraindre_bbox_texte(
        ocr,
        "This OCR line starts below an image and must stay inside the left reading frame",
    )

    assert contraint.x1 <= pt_vers_emu(210)


def test_la_carte_utilise_les_cadres_lecture_taxonomiques():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(600), hauteur_emu=pt_vers_emu(800))
    carte.ajouter_cadre_lecture(
        BBox(pt_vers_emu(55), pt_vers_emu(80), pt_vers_emu(205), pt_vers_emu(720))
    )
    carte.ajouter_cadre_lecture(
        BBox(pt_vers_emu(225), pt_vers_emu(80), pt_vers_emu(545), pt_vers_emu(720))
    )

    colonnes = carte.cadres_colonnes_natives()

    assert len(colonnes) == 2

    ocr = BBox(pt_vers_emu(56), pt_vers_emu(150), pt_vers_emu(548), pt_vers_emu(164))
    contraint = carte.contraindre_bbox_texte(
        ocr,
        "This OCR line starts in a taxonomy frame but spans across the page",
    )

    assert contraint.x1 <= pt_vers_emu(210)


def test_la_carte_decoupe_les_cadres_taxonomiques_autour_des_visuels():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(600), hauteur_emu=pt_vers_emu(800))
    carte.ajouter_cadre_lecture(
        BBox(pt_vers_emu(55), pt_vers_emu(80), pt_vers_emu(205), pt_vers_emu(720))
    )
    carte.ajouter_cadre_lecture(
        BBox(pt_vers_emu(225), pt_vers_emu(80), pt_vers_emu(545), pt_vers_emu(720))
    )
    image = BBox(pt_vers_emu(55), pt_vers_emu(150), pt_vers_emu(205), pt_vers_emu(220))
    carte.ajouter("image", image, "test-image")

    cadres = carte.cadres_lecture_natifs()
    cadres_gauche = [
        cadre
        for cadre in cadres
        if cadre.x0 <= pt_vers_emu(60) and cadre.x1 >= pt_vers_emu(190)
    ]

    assert len(cadres_gauche) == 2
    assert all(not se_chevauchent(cadre, image) for cadre in cadres_gauche)

    ocr = BBox(pt_vers_emu(56), pt_vers_emu(230), pt_vers_emu(548), pt_vers_emu(245))
    contraint = carte.contraindre_bbox_texte(
        ocr,
        "This OCR line starts below an image and must stay inside the left taxonomy frame",
    )

    assert contraint.x1 <= pt_vers_emu(210)


def test_la_carte_garde_le_texte_lateral_a_cote_dune_image():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(612), hauteur_emu=pt_vers_emu(792))
    carte.ajouter_cadre_lecture(
        BBox(pt_vers_emu(52), pt_vers_emu(55), pt_vers_emu(558), pt_vers_emu(723))
    )
    image = BBox(pt_vers_emu(351), pt_vers_emu(140), pt_vers_emu(567), pt_vers_emu(315))
    carte.ajouter("image", image, "test-image")

    cadres = carte.cadres_lecture_natifs()

    assert any(
        cadre.x0 <= pt_vers_emu(54)
        and cadre.x1 >= pt_vers_emu(309)
        and cadre.y0 <= pt_vers_emu(145)
        and cadre.y1 >= pt_vers_emu(302)
        for cadre in cadres
    )
    assert all(not se_chevauchent(cadre, image) for cadre in cadres)


def test_la_carte_ne_borne_pas_une_page_monocolonne_comme_multicolonne():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(600), hauteur_emu=pt_vers_emu(800))
    for index in range(8):
        y0 = 90 + index * 22
        carte.ajouter(
            "native-line",
            BBox(pt_vers_emu(55), pt_vers_emu(y0), pt_vers_emu(545), pt_vers_emu(y0 + 12)),
            "test",
            text=f"Single wide native text line number {index} with enough content",
        )
    ocr = BBox(pt_vers_emu(56), pt_vers_emu(290), pt_vers_emu(590), pt_vers_emu(305))

    contraint = carte.contraindre_bbox_texte(
        ocr,
        "This OCR line belongs to a single wide column and should keep the global frame",
    )

    assert contraint.x1 > pt_vers_emu(545)


def test_la_carte_detecte_une_ocr_courte_contradictoire():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(600), hauteur_emu=pt_vers_emu(800))
    bbox = BBox(pt_vers_emu(452), pt_vers_emu(733), pt_vers_emu(580), pt_vers_emu(753))
    carte.ajouter("native-line", bbox, "test", text="FOR PUBLIC RELEASE")

    assert carte.contredit_texte_natif(bbox, "FEMA")


def test_la_carte_detecte_un_texte_court_pres_dun_logo():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(600), hauteur_emu=pt_vers_emu(800))
    carte.ajouter(
        "image",
        BBox(pt_vers_emu(32), pt_vers_emu(704), pt_vers_emu(78), pt_vers_emu(750)),
        "test-logo",
    )
    texte = BBox(pt_vers_emu(80), pt_vers_emu(722), pt_vers_emu(132), pt_vers_emu(742))

    assert carte.proche_petit_visuel(texte)


def test_la_carte_preserve_un_texte_court_confirme_par_le_pdf_natif():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(600), hauteur_emu=pt_vers_emu(800))
    bbox = BBox(pt_vers_emu(510), pt_vers_emu(120), pt_vers_emu(526), pt_vers_emu(134))
    carte.ajouter("native-line", bbox, "test", text="39")
    carte.ajouter(
        "image",
        BBox(pt_vers_emu(490), pt_vers_emu(110), pt_vers_emu(540), pt_vers_emu(150)),
        "test-logo",
    )

    assert carte.proche_petit_visuel(bbox)
    assert carte.confirme_texte_natif(bbox, "39")


def test_une_ligne_ocr_de_tableau_touche_la_zone_ignoree():
    cellule = BBox(pt_vers_emu(72), pt_vers_emu(120), pt_vers_emu(140), pt_vers_emu(132))
    tableau = BBox(pt_vers_emu(70), pt_vers_emu(90), pt_vers_emu(540), pt_vers_emu(720))

    assert _touche_zone_ignoree(cellule, [tableau])


def test_un_identifiant_de_tableau_nest_pas_une_formule():
    assert not _semble_formule("KMSC-02-35")
    assert not _semble_formule("30.330756 -89.376202")
    assert not _semble_formule("C11 REDUCED 20%")


def test_une_equation_reste_une_formule():
    assert _semble_formule("A11 + A55 = 2ω²")


def test_numero_de_sommaire_lu_comme_tiret_est_corrige_en_colonne_droite():
    class Page:
        class Rect:
            width = 600

        rect = Rect()

    bbox = BBox(pt_vers_emu(520), pt_vers_emu(100), pt_vers_emu(540), pt_vers_emu(112))

    assert _normaliser_marqueur_colonne_droite(Page(), bbox, "--17") == "17"


def test_un_nombre_negatif_hors_colonne_droite_nest_pas_corrige():
    class Page:
        class Rect:
            width = 600

        rect = Rect()

    bbox = BBox(pt_vers_emu(120), pt_vers_emu(100), pt_vers_emu(140), pt_vers_emu(112))

    assert _normaliser_marqueur_colonne_droite(Page(), bbox, "-17") == "-17"
