from pdfexact.extract.document import (
    _cadres_lecture_depuis_plan,
    _extraire_texte_pdf_natif_word_native,
    _filtrer_textes_intersectant_zones,
    _filtrer_textes_couverts,
    _filtrer_tableaux_contredits_par_ia,
    _filtrer_zones_lisibles_ocr,
    _forme_bordure_page_clusterisante,
    _page_image_pleine_sans_texte_natif,
    _page_pdf_natif_mixe,
    _page_pdf_natif_dominant,
    _preparer_ocr_visible_page_image,
    _tableau_ressemble_graphe,
    _zones_images_lisibles_ocr,
    _zones_visuelles_ia_a_rasteriser,
    _zone_rasterisable,
    _zone_touche_tableau,
)
from pdfexact.geometry import BBox, pt_vers_emu
from io import BytesIO

from PIL import Image

from pdfexact.fallback.rasterize import bboxes_segmentees, segmenter_elements_visuels_page
from pdfexact.ir import Document, FlowParagraph, FontRef, ImageEl, Line, MediaItem, Page, ShapeEl, Span, TableCell, TableEl, TableRow, TextBox
from pdfexact.layout.ai import LayoutAIZone
from pdfexact.layout.model import LayoutRegion
from pdfexact.layout.planner import LayoutPlanItem


def _bbox_pt(x0, y0, x1, y1):
    return BBox(pt_vers_emu(x0), pt_vers_emu(y0), pt_vers_emu(x1), pt_vers_emu(y1))


def test_filtre_ocr_couvert_par_zone_visuelle_native():
    police = FontRef("Test", "Arial", False, False)
    couvert = TextBox(
        bbox=_bbox_pt(100, 100, 220, 120),
        lignes=[
            Line(
                bbox=_bbox_pt(100, 100, 220, 120),
                spans=[Span("Visible label", police, 12, "000000")],
                hauteur_ligne_emu=pt_vers_emu(14),
                largeur_cible_emu=pt_vers_emu(120),
            )
        ],
    )
    dehors = FlowParagraph(
        bbox=_bbox_pt(260, 100, 360, 120),
        texte="Outside paragraph",
        police=police,
        size_pt=12,
        couleur="000000",
    )

    elements = _filtrer_textes_couverts([couvert, dehors], [_bbox_pt(90, 90, 230, 130)])

    assert elements == [dehors]


def test_filtre_ocr_intersectant_zone_raster_integrale():
    police = FontRef("Test", "Arial", False, False)
    zone_raster = _bbox_pt(20, 20, 140, 260)
    titre = FlowParagraph(
        bbox=_bbox_pt(18, 44, 170, 145),
        texte="It All Works",
        police=police,
        size_pt=30,
        couleur="FFFFFF",
        lignes=[
            Line(
                bbox=_bbox_pt(25, 60, 105, 92),
                spans=[Span("It All", police, 30, "FFFFFF", bbox=_bbox_pt(25, 60, 105, 92))],
                hauteur_ligne_emu=pt_vers_emu(34),
                largeur_cible_emu=pt_vers_emu(80),
            )
        ],
    )
    paragraphe = FlowParagraph(
        bbox=_bbox_pt(170, 60, 360, 120),
        texte="Outside paragraph",
        police=police,
        size_pt=12,
        couleur="000000",
    )

    elements = _filtrer_textes_intersectant_zones([titre, paragraphe], [zone_raster])

    assert elements == [paragraphe]


def test_filtre_zone_formule_ne_supprime_pas_tout_le_bloc_texte():
    police = FontRef("Test", "Arial", False, False)
    haut = Line(
        bbox=_bbox_pt(60, 520, 320, 535),
        spans=[Span("Sample Problem 1.02", police, 10, "000000", bbox=_bbox_pt(60, 520, 320, 535))],
        hauteur_ligne_emu=pt_vers_emu(15),
        largeur_cible_emu=pt_vers_emu(260),
    )
    formule = Line(
        bbox=_bbox_pt(180, 625, 250, 650),
        spans=[Span("e = Vvoids / Vgrains", police, 10, "000000", bbox=_bbox_pt(180, 625, 250, 650))],
        hauteur_ligne_emu=pt_vers_emu(25),
        largeur_cible_emu=pt_vers_emu(70),
    )
    bas = Line(
        bbox=_bbox_pt(60, 665, 320, 720),
        spans=[Span("Here, Vgrains is the total volume", police, 10, "000000", bbox=_bbox_pt(60, 665, 320, 720))],
        hauteur_ligne_emu=pt_vers_emu(55),
        largeur_cible_emu=pt_vers_emu(260),
    )
    bloc = TextBox(bbox=_bbox_pt(60, 520, 320, 720), lignes=[haut, formule, bas])

    elements = _filtrer_textes_intersectant_zones([bloc], [_bbox_pt(175, 620, 255, 655)])

    assert len(elements) == 1
    assert isinstance(elements[0], TextBox)
    assert [ligne.spans[0].texte for ligne in elements[0].lignes] == [
        "Sample Problem 1.02",
        "Here, Vgrains is the total volume",
    ]


def test_table_ia_devient_cadre_lecture_sans_vrai_tableau_word():
    zone = _bbox_pt(50, 120, 360, 500)
    plan = [
        LayoutPlanItem(
            kind="ai-zone",
            bbox=zone,
            strategy="word-table",
            editable=True,
            confidence=0.82,
            region=LayoutRegion(
                kind="ai-zone",
                bbox=zone,
                confidence=0.82,
                editable=True,
                strategy="word-table",
                style_hints={"source": "paddlex"},
            ),
        )
    ]

    assert _cadres_lecture_depuis_plan(plan) == [zone]


def test_vrai_tableau_pdf_ne_devient_pas_cadre_lecture_de_secours():
    zone = _bbox_pt(50, 120, 360, 500)
    plan = [
        LayoutPlanItem(
            kind="real-table",
            bbox=zone,
            strategy="word-table",
            editable=True,
            confidence=0.95,
            region=LayoutRegion(
                kind="real-table",
                bbox=zone,
                confidence=0.95,
                editable=True,
                strategy="word-table",
                style_hints={"source": "pdf-table"},
            ),
        )
    ]

    assert _cadres_lecture_depuis_plan(plan) == []


def test_zone_raster_touchant_vrai_tableau_est_bloquee():
    police = FontRef("Test", "Arial", False, False)
    table = TableEl(
        bbox=_bbox_pt(50, 100, 350, 220),
        rows=[TableRow(_bbox_pt(50, 100, 350, 120), [TableCell(_bbox_pt(50, 100, 350, 120), "A")])],
        col_widths_emu=[pt_vers_emu(300)],
        police=police,
        size_pt=8,
    )

    assert _zone_touche_tableau(_bbox_pt(45, 95, 360, 225), [table])
    assert not _zone_touche_tableau(_bbox_pt(360, 230, 390, 260), [table])


def test_grande_image_lisible_ne_bloque_pas_ocr_word_native():
    page = Page(index=0, largeur_emu=pt_vers_emu(612), hauteur_emu=pt_vers_emu(792))
    grande_image_texte = _bbox_pt(54, 275, 558, 715)
    petite_image_logo = _bbox_pt(54, 80, 130, 160)
    table = _bbox_pt(40, 720, 570, 760)

    lisibles = _zones_images_lisibles_ocr([grande_image_texte, petite_image_logo], page)
    zones = _filtrer_zones_lisibles_ocr([grande_image_texte, petite_image_logo, table], lisibles)

    assert lisibles == [grande_image_texte]
    assert grande_image_texte not in zones
    assert petite_image_logo in zones
    assert table in zones


def test_page_image_pleine_reste_detectee_meme_avec_texte_natif():
    page = Page(index=0, largeur_emu=pt_vers_emu(310), hauteur_emu=pt_vers_emu(500))
    pleine_page = _bbox_pt(0, 0, 310, 500)

    assert _page_image_pleine_sans_texte_natif([pleine_page], [], page)
    assert not _page_image_pleine_sans_texte_natif([pleine_page], [_bbox_pt(20, 20, 120, 35)], page)
    lignes_natives = [_bbox_pt(20, 20 + index * 12, 120, 35 + index * 12) for index in range(8)]
    assert not _page_image_pleine_sans_texte_natif([pleine_page], lignes_natives, page)
    assert _page_pdf_natif_mixe(lignes_natives, [pleine_page], page)


def test_page_image_est_decoupee_en_tuiles_contigues():
    page = _bbox_pt(0, 0, 310, 500)
    tuiles = bboxes_segmentees(page)

    assert len(tuiles) == 24
    assert max(zone.largeur * zone.hauteur for zone in tuiles) < page.largeur * page.hauteur
    assert min(zone.x0 for zone in tuiles) == page.x0
    assert max(zone.x1 for zone in tuiles) == page.x1
    assert min(zone.y0 for zone in tuiles) == page.y0
    assert max(zone.y1 for zone in tuiles) == page.y1


def test_garde_fou_ir_decoupe_un_visuel_pleine_page():
    page = _bbox_pt(0, 0, 310, 500)
    donnees = BytesIO()
    Image.new("RGB", (120, 180), "white").save(donnees, format="PNG")
    media = {"source": MediaItem("source", donnees.getvalue(), "png")}

    elements = segmenter_elements_visuels_page(
        [ImageEl(page, "source")],
        media,
        page.largeur,
        page.hauteur,
    )

    assert len(elements) == 24
    assert all(element.bbox != page for element in elements)


def test_page_pdf_natif_dominant_declenche_seulement_sur_vrai_texte_pdf():
    page = Page(index=0, largeur_emu=pt_vers_emu(612), hauteur_emu=pt_vers_emu(792))
    lignes = [_bbox_pt(60, 80 + index * 14, 280, 90 + index * 14) for index in range(14)]

    assert _page_pdf_natif_dominant(lignes, [], page)
    assert not _page_pdf_natif_dominant([], [_bbox_pt(0, 0, 612, 792)], page)
    assert not _page_pdf_natif_dominant(lignes[:4], [], page)
    assert _page_pdf_natif_dominant(lignes[:8], [], page)


def test_page_pdf_natif_conserve_texte_dans_zone_visuelle_sans_texte(monkeypatch):
    police = FontRef("Test", "Arial", False, False)
    bbox = _bbox_pt(40, 120, 170, 136)
    ligne = Line(
        bbox=bbox,
        spans=[Span("Checkpoint 2", police, 10, "000000", bbox=bbox)],
        hauteur_ligne_emu=pt_vers_emu(16),
        largeur_cible_emu=pt_vers_emu(130),
    )
    texte = TextBox(bbox=bbox, lignes=[ligne])
    monkeypatch.setattr("pdfexact.extract.document.extraire_texte", lambda _page, _polices: [texte])

    page_ir = Page(index=0, largeur_emu=pt_vers_emu(300), hauteur_emu=pt_vers_emu(400))

    elements = _extraire_texte_pdf_natif_word_native(
        object(),
        {},
        None,
        [],
        [_bbox_pt(20, 100, 220, 180)],
        page_ir,
        Document(),
    )

    assert len(elements) == 1
    assert isinstance(elements[0], FlowParagraph)
    assert elements[0].texte == "Checkpoint 2"


def test_micro_zone_vectorielle_ne_part_pas_en_rasterisation():
    page = Page(index=0, largeur_emu=pt_vers_emu(440), hauteur_emu=pt_vers_emu(680))

    assert not _zone_rasterisable(BBox(0, 0, 1, 1), page)
    assert _zone_rasterisable(_bbox_pt(40, 40, 45, 45), page)


def test_zone_ia_composite_ne_remplace_pas_un_objet_natif_large():
    page = Page(index=0, largeur_emu=pt_vers_emu(612), hauteur_emu=pt_vers_emu(792))
    image_native = _bbox_pt(36, 24, 428, 452)
    zone_composite = _bbox_pt(34, 23, 576, 466)
    image_item = LayoutPlanItem(
        kind="image",
        bbox=image_native,
        strategy="raster-image",
        editable=False,
        confidence=0.99,
        region=LayoutRegion(
            kind="image",
            bbox=image_native,
            confidence=0.99,
            editable=False,
            strategy="raster-image",
            style_hints={"source": "pdf-image"},
        ),
    )
    composite_item = LayoutPlanItem(
        kind="image",
        bbox=zone_composite,
        strategy="raster-image",
        editable=False,
        confidence=0.91,
        region=LayoutRegion(
            kind="image",
            bbox=zone_composite,
            confidence=0.91,
            editable=False,
            strategy="raster-image",
            style_hints={"source": "paddlex"},
        ),
    )

    zones = _zones_visuelles_ia_a_rasteriser(
        [image_item, composite_item],
        [image_native],
        page,
    )

    assert zones == []


def test_zone_ia_isolee_reste_rasterisable():
    page = Page(index=0, largeur_emu=pt_vers_emu(612), hauteur_emu=pt_vers_emu(792))
    zone = _bbox_pt(80, 180, 520, 520)
    item = LayoutPlanItem(
        kind="figure-or-diagram",
        bbox=zone,
        strategy="raster-image",
        editable=False,
        confidence=0.91,
        region=LayoutRegion(
            kind="figure-or-diagram",
            bbox=zone,
            confidence=0.91,
            editable=False,
            strategy="raster-image",
            style_hints={"source": "paddlex"},
        ),
    )

    assert _zones_visuelles_ia_a_rasteriser([item], [], page) == [zone]


def test_couche_ocr_image_pleine_est_visible_et_preservee():
    police = FontRef("OCR", "Arial", False, False)
    texte = TextBox(
        bbox=_bbox_pt(20, 20, 180, 36),
        lignes=[
            Line(
                bbox=_bbox_pt(20, 20, 180, 36),
                spans=[Span("Compression du signal", police, 12, "000000", espacement_twips=-40)],
                hauteur_ligne_emu=pt_vers_emu(16),
                largeur_cible_emu=pt_vers_emu(160),
            )
        ],
    )

    lignes = _preparer_ocr_visible_page_image([texte])

    assert lignes == 1
    assert getattr(texte, "preserve_as_textbox")
    assert not texte.lignes[0].spans[0].invisible
    assert texte.lignes[0].spans[0].couleur == "000000"
    assert texte.lignes[0].spans[0].espacement_twips == -40


def test_graphe_detecte_comme_faux_tableau():
    police = FontRef("Test", "Arial", False, False)
    table = TableEl(
        bbox=_bbox_pt(280, 420, 465, 738),
        rows=[
            TableRow(_bbox_pt(280, 420, 465, 480), [TableCell(_bbox_pt(280, 420, 360, 480), "8\n7 (statesx/eV/atom)\n6\n5"), TableCell(_bbox_pt(360, 420, 465, 480), "")]),
            TableRow(_bbox_pt(280, 480, 465, 540), [TableCell(_bbox_pt(280, 480, 360, 540), ""), TableCell(_bbox_pt(360, 480, 465, 540), "Atom 8")]),
            TableRow(_bbox_pt(280, 540, 465, 600), [TableCell(_bbox_pt(280, 540, 360, 600), ""), TableCell(_bbox_pt(360, 540, 465, 600), "3 -2 -1 0 1 2\nEnergy (eV)")]),
            TableRow(_bbox_pt(280, 600, 465, 660), [TableCell(_bbox_pt(280, 600, 360, 660), "6"), TableCell(_bbox_pt(360, 600, 465, 660), "")]),
            TableRow(_bbox_pt(280, 660, 465, 738), [TableCell(_bbox_pt(280, 660, 360, 738), "5 (statesx/eV/atom)\n4\n3\n2 5f\nPDOS"), TableCell(_bbox_pt(360, 660, 465, 738), "")]),
        ],
        col_widths_emu=[pt_vers_emu(80), pt_vers_emu(105)],
        police=police,
        size_pt=8,
    )

    assert _tableau_ressemble_graphe(table)


def test_tableau_missing_data_patterns_ne_devient_pas_graphe():
    police = FontRef("Test", "Arial", False, False)
    table = TableEl(
        bbox=_bbox_pt(54, 87, 377, 179),
        rows=[
            TableRow(_bbox_pt(54, 87, 377, 101), [TableCell(_bbox_pt(54, 87, 94, 101), "Substance"), TableCell(_bbox_pt(94, 87, 377, 101), "Missing Data Patterns, %", col_span=8)]),
            TableRow(_bbox_pt(54, 101, 377, 115), [TableCell(_bbox_pt(54, 101, 94, 115), ""), TableCell(_bbox_pt(94, 101, 165, 115), "Inconsistent Data", col_span=2), TableCell(_bbox_pt(165, 101, 235, 115), "Don’t Know", col_span=2), TableCell(_bbox_pt(235, 101, 306, 115), "Refused", col_span=2), TableCell(_bbox_pt(306, 101, 377, 115), "Blank", col_span=2)]),
            TableRow(_bbox_pt(54, 115, 377, 145), [TableCell(_bbox_pt(54, 115, 94, 145), ""), TableCell(_bbox_pt(94, 115, 129, 145), "1994-\n1998\nPAPI"), TableCell(_bbox_pt(129, 115, 165, 145), "1999\nCAI"), TableCell(_bbox_pt(165, 115, 200, 145), "1994-\n1998\nPAPI"), TableCell(_bbox_pt(200, 115, 235, 145), "1999\nCAI"), TableCell(_bbox_pt(235, 115, 271, 145), "1994-\n1998\nPAPI"), TableCell(_bbox_pt(271, 115, 306, 145), "1999\nCAI"), TableCell(_bbox_pt(306, 115, 341, 145), "1994-\n1998\nPAPI"), TableCell(_bbox_pt(341, 115, 377, 145), "1999\nCAI")]),
            TableRow(_bbox_pt(54, 145, 377, 179), [TableCell(_bbox_pt(54, 145, 94, 179), "Marijuana\nCocaine\nCigarettes"), TableCell(_bbox_pt(94, 145, 129, 179), "0.19\n0.35\n0.17"), TableCell(_bbox_pt(129, 145, 165, 179), "0.54\n0.58\n0.42"), TableCell(_bbox_pt(165, 145, 200, 179), "0.10\n0.06\n0.11"), TableCell(_bbox_pt(200, 145, 235, 179), "1.17\n1.91\n2.53"), TableCell(_bbox_pt(235, 145, 271, 179), "0.01\n0.00\n0.01"), TableCell(_bbox_pt(271, 145, 306, 179), "0.56\n0.67\n0.19"), TableCell(_bbox_pt(306, 145, 341, 179), "0.14\n0.34\n0.34"), TableCell(_bbox_pt(341, 145, 377, 179), "0.06\n0.22\n0.00")]),
        ],
        col_widths_emu=[pt_vers_emu(40)] + [pt_vers_emu(35)] * 8,
        police=police,
        size_pt=6,
    )

    assert not _tableau_ressemble_graphe(table)


def test_table_pymupdf_grande_contredite_par_ia_est_rejetee():
    police = FontRef("Test", "Arial", False, False)
    table = TableEl(
        bbox=_bbox_pt(78, 74, 540, 718),
        rows=[
            TableRow(
                _bbox_pt(78, 74 + index * 160, 540, 74 + (index + 1) * 160),
                [
                    TableCell(_bbox_pt(78, 74, 230, 234), "diagram label" if index == 0 else ""),
                    TableCell(_bbox_pt(230, 74, 390, 234), "paragraph text"),
                    TableCell(_bbox_pt(390, 74, 540, 234), ""),
                ],
            )
            for index in range(4)
        ],
        col_widths_emu=[pt_vers_emu(152), pt_vers_emu(160), pt_vers_emu(150)],
        police=police,
        size_pt=10,
    )
    zones_ia = [
        LayoutAIZone(
            zone_id="z1",
            label="image",
            role="visual",
            confidence=0.95,
            bbox=_bbox_pt(74, 128, 187, 206),
            source="paddlex",
            model_id="test",
        )
    ]

    gardes = _filtrer_tableaux_contredits_par_ia(
        [table],
        zones_ia,
        pt_vers_emu(612),
        pt_vers_emu(792),
        actif=True,
    )

    assert gardes == []


def test_table_dense_reste_acceptee_meme_si_ia_rate_la_table():
    police = FontRef("Test", "Arial", False, False)
    rows = []
    for row_index in range(30):
        cells = []
        for col_index in range(4):
            cells.append(
                TableCell(
                    _bbox_pt(40 + col_index * 80, 80 + row_index * 12, 120 + col_index * 80, 92 + row_index * 12),
                    "A",
                )
            )
        rows.append(TableRow(_bbox_pt(40, 80 + row_index * 12, 360, 92 + row_index * 12), cells))
    table = TableEl(
        bbox=_bbox_pt(40, 80, 360, 440),
        rows=rows,
        col_widths_emu=[pt_vers_emu(80)] * 4,
        police=police,
        size_pt=8,
    )

    gardes = _filtrer_tableaux_contredits_par_ia(
        [table],
        [],
        pt_vers_emu(612),
        pt_vers_emu(792),
        actif=True,
    )

    assert gardes == [table]


def test_bordure_page_large_ne_clusterise_pas_toute_la_page():
    page = Page(index=0, largeur_emu=pt_vers_emu(612), hauteur_emu=pt_vers_emu(792))
    bordure = ShapeEl(
        bbox=_bbox_pt(49, 18, 562, 765),
        chemins=[[("move", ((_bbox_pt(49, 18, 562, 765).x0, _bbox_pt(49, 18, 562, 765).y0),))]],
        remplissage=None,
        contour="3E7898",
        epaisseur_emu=pt_vers_emu(0.25),
    )
    fond = ShapeEl(
        bbox=_bbox_pt(49, 18, 562, 765),
        chemins=[],
        remplissage="FFFFFF",
        contour=None,
        epaisseur_emu=0,
    )

    assert _forme_bordure_page_clusterisante(bordure, page)
    assert not _forme_bordure_page_clusterisante(fond, page)


def test_graphe_scientifique_court_detecte_comme_faux_tableau():
    police = FontRef("Test", "Arial", False, False)
    table = TableEl(
        bbox=_bbox_pt(130, 470, 360, 644),
        rows=[
            TableRow(
                _bbox_pt(130, 470, 360, 540),
                [
                    TableCell(_bbox_pt(130, 470, 210, 540), "50\n40\n30"),
                    TableCell(_bbox_pt(210, 470, 285, 540), "B, GPa"),
                    TableCell(_bbox_pt(285, 470, 360, 540), "T,K"),
                ],
            ),
            TableRow(
                _bbox_pt(130, 540, 360, 644),
                [
                    TableCell(_bbox_pt(130, 540, 210, 644), "20\n10\n0"),
                    TableCell(_bbox_pt(210, 540, 285, 644), ""),
                    TableCell(_bbox_pt(285, 540, 360, 644), "0.2 0.4 0.6"),
                ],
            ),
        ],
        col_widths_emu=[pt_vers_emu(80), pt_vers_emu(75), pt_vers_emu(75)],
        police=police,
        size_pt=8,
    )

    assert _tableau_ressemble_graphe(table)


def test_graphe_a_quatre_colonnes_detecte_comme_faux_tableau():
    police = FontRef("Test", "Arial", False, False)
    table = TableEl(
        bbox=_bbox_pt(289, 30, 576, 508),
        rows=[
            TableRow(
                _bbox_pt(289, 30, 576, 80),
                [
                    TableCell(_bbox_pt(289, 30, 350, 80), "In (∂T/∂P)s"),
                    TableCell(_bbox_pt(350, 30, 420, 80), "K/GPa"),
                    TableCell(_bbox_pt(420, 30, 500, 80), "P/GPa"),
                    TableCell(_bbox_pt(500, 30, 576, 80), "Radius/X mm"),
                ],
            ),
            *[
                TableRow(
                    _bbox_pt(289, 80 + i * 45, 576, 125 + i * 45),
                    [
                        TableCell(_bbox_pt(289, 80 + i * 45, 350, 125 + i * 45), f"{i / 10:.1f}"),
                        TableCell(_bbox_pt(350, 80 + i * 45, 420, 125 + i * 45), ""),
                        TableCell(_bbox_pt(420, 80 + i * 45, 500, 125 + i * 45), f"{i}"),
                        TableCell(_bbox_pt(500, 80 + i * 45, 576, 125 + i * 45), ""),
                    ],
                )
                for i in range(1, 5)
            ],
        ],
        col_widths_emu=[pt_vers_emu(61), pt_vers_emu(70), pt_vers_emu(80), pt_vers_emu(76)],
        police=police,
        size_pt=8,
    )

    assert _tableau_ressemble_graphe(table)


def test_graphe_axes_radius_detecte_comme_faux_tableau():
    police = FontRef("Test", "Arial", False, False)
    table = TableEl(
        bbox=_bbox_pt(333, 395, 438, 656),
        rows=[
            TableRow(
                _bbox_pt(333, 395, 438, 525),
                [
                    TableCell(
                        _bbox_pt(333, 395, 385, 525),
                        "30 20 10 mm 0 Radius, -10 -20 -30 30 20 10 mm 0 Radius, -10 -20 -30",
                    ),
                    TableCell(_bbox_pt(385, 395, 438, 525), ""),
                ],
            ),
            TableRow(
                _bbox_pt(333, 525, 438, 656),
                [
                    TableCell(_bbox_pt(333, 525, 385, 656), "30 20 10 mm"),
                    TableCell(_bbox_pt(385, 525, 438, 656), "0 10 20 30 40 50 60 70 80 X, mm"),
                ],
            ),
        ],
        col_widths_emu=[pt_vers_emu(52), pt_vers_emu(53)],
        police=police,
        size_pt=8,
    )

    assert _tableau_ressemble_graphe(table)
