from pdfexact.geometry import BBox, pt_vers_emu
from pdfexact.ir import FlowParagraph, FontRef, ImageEl, Line, ShapeEl, Span, TableCell, TableEl, TableRow, TextBox
from pdfexact.layout.ai import LayoutAIZone
from pdfexact.layout import (
    LayoutBlock,
    LayoutPage,
    classer_regions,
    comprendre_page,
    detecter_regions_colonnes,
    filtrer_elements_selon_plan,
    planifier_regions,
    zones_layout_du_plan,
    zones_ocr_du_plan,
    zones_protegees_du_plan,
)


def _bbox_pt(x0, y0, x1, y1):
    return BBox(pt_vers_emu(x0), pt_vers_emu(y0), pt_vers_emu(x1), pt_vers_emu(y1))


def test_classifier_transforme_comprehension_en_regions():
    police = FontRef("Test", "Arial", False, False)
    table = TableEl(
        bbox=_bbox_pt(40, 40, 180, 90),
        rows=[TableRow(_bbox_pt(40, 40, 180, 90), [TableCell(_bbox_pt(40, 40, 180, 90), "A")])],
        col_widths_emu=[pt_vers_emu(140)],
        police=police,
        size_pt=9,
    )
    bandeau = ShapeEl(_bbox_pt(30, 120, 190, 140), [], "003366", None, 0)
    comprehension = comprendre_page(
        largeur_emu=pt_vers_emu(220),
        hauteur_emu=pt_vers_emu(300),
        tableaux=[table],
        images=[],
        formes=[bandeau],
        zones_rasterisees=[],
    )
    analyse = LayoutPage(page_index=0, width=pt_vers_emu(220), height=pt_vers_emu(300), rotation=0)

    regions = classer_regions(analyse, comprehension)

    assert [region.kind for region in regions] == ["real-table", "section-band"]
    assert [region.strategy for region in regions] == ["word-table", "shape-background"]


def test_classifier_brut_classe_image_pleine_page():
    image = LayoutBlock("image", _bbox_pt(0, 0, 200, 290), "test")
    analyse = LayoutPage(
        page_index=0,
        width=pt_vers_emu(200),
        height=pt_vers_emu(300),
        rotation=0,
        image_blocks=(image,),
    )

    regions = classer_regions(analyse)

    assert regions[0].kind == "scanned-page"
    assert regions[0].strategy == "raster-image"
    assert not regions[0].editable


def test_classifier_brut_detecte_colonnes_depuis_lignes_natives():
    lignes = []
    for index in range(8):
        y0 = 40 + index * 16
        lignes.append(_bbox_pt(20, y0, 90, y0 + 8))
        lignes.append(_bbox_pt(120, y0, 190, y0 + 8))
    analyse = LayoutPage(
        page_index=0,
        width=pt_vers_emu(220),
        height=pt_vers_emu(260),
        rotation=0,
        text_blocks=(
            LayoutBlock(
                "text",
                _bbox_pt(20, 40, 190, 170),
                "test",
                metadata={"line_bboxes": tuple(lignes), "line_count": len(lignes)},
            ),
        ),
    )

    regions = classer_regions(analyse)

    assert [region.kind for region in regions] == ["text-column", "text-column"]
    assert all(region.strategy == "word-text" for region in regions)


def test_detecter_regions_colonnes_reste_reutilisable():
    lignes = []
    for index in range(4):
        y0 = 40 + index * 16
        lignes.append(_bbox_pt(20, y0, 90, y0 + 8))
        lignes.append(_bbox_pt(120, y0, 190, y0 + 8))

    colonnes = detecter_regions_colonnes(lignes, pt_vers_emu(220), pt_vers_emu(260))

    assert len(colonnes) == 2


def test_detecter_regions_colonnes_rejette_cadres_qui_se_chevauchent():
    lignes = []
    for index in range(8):
        y0 = 40 + index * 16
        lignes.append(_bbox_pt(60, y0, 520, y0 + 8))
        lignes.append(_bbox_pt(220, y0, 550, y0 + 8))

    assert detecter_regions_colonnes(lignes, pt_vers_emu(612), pt_vers_emu(792)) == []


def test_planner_separe_editable_et_zones_protegees():
    regions = [
        LayoutBlock("text", _bbox_pt(10, 10, 100, 30), "test"),
    ]
    analyse = LayoutPage(
        page_index=0,
        width=pt_vers_emu(200),
        height=pt_vers_emu(300),
        rotation=0,
        text_blocks=tuple(regions),
        table_candidates=(LayoutBlock("table-candidate", _bbox_pt(10, 50, 180, 90), "test"),),
        drawing_blocks=(
            LayoutBlock(
                "drawing",
                _bbox_pt(10, 110, 180, 130),
                "test",
                metadata={"has_fill": True},
            ),
        ),
    )

    plan = planifier_regions(classer_regions(analyse))
    zones = zones_protegees_du_plan(plan)

    assert [item.strategy for item in plan] == ["word-text", "word-table", "shape-background"]
    assert [zone.kind for zone in zones] == ["table-candidate", "shape-background"]
    assert not zones[0].protect_ocr
    assert zones[0].protect_layout
    assert not zones[1].protect_ocr
    assert zones[1].protect_layout


def test_planner_expose_zones_ocr_et_layout_fusionnees():
    analyse = LayoutPage(
        page_index=0,
        width=pt_vers_emu(200),
        height=pt_vers_emu(300),
        rotation=0,
        table_candidates=(
            LayoutBlock("table-candidate", _bbox_pt(10, 50, 80, 90), "test"),
            LayoutBlock("table-candidate", _bbox_pt(81, 50, 150, 90), "test"),
        ),
        drawing_blocks=(
            LayoutBlock(
                "drawing",
                _bbox_pt(10, 110, 150, 130),
                "test",
                metadata={"has_fill": True},
            ),
        ),
    )

    plan = planifier_regions(classer_regions(analyse))

    assert zones_ocr_du_plan(plan) == []
    assert zones_layout_du_plan(plan) == [
        _bbox_pt(10, 50, 150, 90),
        _bbox_pt(10, 110, 150, 130),
    ]


def test_planner_filtre_fuites_ocr_dans_zones_protegees():
    police = FontRef("OCR", "Arial", False, False)
    span = Span("doublon", police, 9, "000000")
    ligne = Line(_bbox_pt(20, 55, 70, 65), [span], pt_vers_emu(10), pt_vers_emu(50))
    texte_table = TextBox(ligne.bbox, [ligne])
    texte_hors_zone = FlowParagraph(_bbox_pt(20, 140, 120, 155), "ok", police, 9, "000000")
    analyse = LayoutPage(
        page_index=0,
        width=pt_vers_emu(200),
        height=pt_vers_emu(300),
        rotation=0,
        table_candidates=(LayoutBlock("table-candidate", _bbox_pt(10, 50, 150, 90), "test"),),
    )
    plan = planifier_regions(classer_regions(analyse))

    assert filtrer_elements_selon_plan([texte_table, texte_hors_zone], plan) == [
        texte_table,
        texte_hors_zone,
    ]


def test_planner_protege_ocr_seulement_pour_vrai_tableau_pdf():
    police = FontRef("OCR", "Arial", False, False)
    table = TableEl(
        bbox=_bbox_pt(20, 50, 160, 100),
        rows=[TableRow(_bbox_pt(20, 50, 160, 100), [TableCell(_bbox_pt(20, 50, 160, 100), "Cell")])],
        col_widths_emu=[pt_vers_emu(140)],
        police=police,
        size_pt=9,
    )
    comprehension = comprendre_page(
        largeur_emu=pt_vers_emu(220),
        hauteur_emu=pt_vers_emu(300),
        tableaux=[table],
        images=[],
        formes=[],
        zones_rasterisees=[],
    )
    analyse = LayoutPage(page_index=0, width=pt_vers_emu(220), height=pt_vers_emu(300), rotation=0)
    plan = planifier_regions(classer_regions(analyse, comprehension))

    zones = zones_protegees_du_plan(plan)

    assert zones[0].source == "pdf-table"
    assert zones[0].protect_ocr


def test_planner_preserve_texte_natif_dans_forme_simple_couverte_par_image():
    police = FontRef("OCR", "Arial", False, False)
    ligne_bbox = _bbox_pt(112, 164, 162, 184)
    span = Span("Vision", police, 20, "000000")
    ligne = Line(ligne_bbox, [span], pt_vers_emu(20), pt_vers_emu(50))
    libelle = FlowParagraph(ligne_bbox, "Vision", police, 20, "000000", lignes=[ligne])
    fuite = FlowParagraph(_bbox_pt(230, 230, 245, 240), "0.5", police, 8, "000000")
    boite = ShapeEl(_bbox_pt(100, 155, 175, 190), [], "FFFF00", "000000", pt_vers_emu(1))

    comprehension = comprendre_page(
        largeur_emu=pt_vers_emu(792),
        hauteur_emu=pt_vers_emu(612),
        tableaux=[],
        images=[],
        formes=[boite],
        zones_rasterisees=[],
        lignes_natives=[ligne_bbox],
        zones_ia=[
            LayoutAIZone(
                zone_id="ai1",
                label="image",
                role="visual",
                confidence=0.90,
                bbox=_bbox_pt(70, 120, 700, 460),
                source="test",
                model_id="test",
            )
        ],
    )
    analyse = LayoutPage(page_index=0, width=pt_vers_emu(792), height=pt_vers_emu(612), rotation=0)
    plan = planifier_regions(classer_regions(analyse, comprehension))

    assert any(item.strategy == "word-text" and item.bbox == ligne_bbox for item in plan)
    assert filtrer_elements_selon_plan([libelle, fuite], plan) == [libelle]


def test_planner_ne_reinjecte_pas_le_texte_natif_dans_une_image_protegee():
    police = FontRef("OCR", "Arial", False, False)
    ligne_bbox = _bbox_pt(180, 210, 260, 226)
    span = Span("Requirements", police, 20, "000000")
    ligne = Line(ligne_bbox, [span], pt_vers_emu(20), pt_vers_emu(80))
    libelle = FlowParagraph(ligne_bbox, "Requirements", police, 20, "000000", lignes=[ligne])
    fuite = FlowParagraph(_bbox_pt(120, 300, 128, 310), "0.5", police, 8, "000000")
    image = ImageEl(_bbox_pt(90, 140, 500, 430), "diagram")

    comprehension = comprendre_page(
        largeur_emu=pt_vers_emu(792),
        hauteur_emu=pt_vers_emu(612),
        tableaux=[],
        images=[image],
        formes=[],
        zones_rasterisees=[],
        lignes_natives=[ligne_bbox],
    )
    analyse = LayoutPage(page_index=0, width=pt_vers_emu(792), height=pt_vers_emu(612), rotation=0)
    plan = planifier_regions(classer_regions(analyse, comprehension))

    assert not any(item.strategy == "word-text" and item.bbox == ligne_bbox for item in plan)
    assert filtrer_elements_selon_plan([libelle, fuite], plan) == []


def test_word_native_conserve_texte_ocr_dans_zone_image_protegee():
    police = FontRef("OCR", "Arial", False, False)
    ligne_bbox = _bbox_pt(180, 210, 260, 226)
    span = Span("Requirements", police, 20, "000000")
    ligne = Line(ligne_bbox, [span], pt_vers_emu(20), pt_vers_emu(80))
    libelle = FlowParagraph(ligne_bbox, "Requirements", police, 20, "000000", lignes=[ligne])
    image = ImageEl(_bbox_pt(90, 140, 500, 430), "diagram")

    comprehension = comprendre_page(
        largeur_emu=pt_vers_emu(792),
        hauteur_emu=pt_vers_emu(612),
        tableaux=[],
        images=[image],
        formes=[],
        zones_rasterisees=[],
        lignes_natives=[ligne_bbox],
    )
    analyse = LayoutPage(page_index=0, width=pt_vers_emu(792), height=pt_vers_emu(612), rotation=0)
    plan = planifier_regions(classer_regions(analyse, comprehension))

    assert filtrer_elements_selon_plan([libelle], plan, preserver_texte_natif=True) == [libelle]


def test_planner_ignore_sous_zone_texte_ia_dans_zone_visuelle_ia():
    image_zone = LayoutAIZone(
        zone_id="ai-image",
        label="image",
        role="visual",
        confidence=0.91,
        bbox=_bbox_pt(80, 120, 520, 430),
        source="test",
        model_id="test",
    )
    texte_interne = LayoutAIZone(
        zone_id="ai-text",
        label="paragraph_title",
        role="text",
        confidence=0.88,
        bbox=_bbox_pt(120, 180, 260, 210),
        source="test",
        model_id="test",
    )

    comprehension = comprendre_page(
        largeur_emu=pt_vers_emu(792),
        hauteur_emu=pt_vers_emu(612),
        tableaux=[],
        images=[],
        formes=[],
        zones_rasterisees=[],
        zones_ia=[image_zone, texte_interne],
    )
    analyse = LayoutPage(page_index=0, width=pt_vers_emu(792), height=pt_vers_emu(612), rotation=0)
    plan = planifier_regions(classer_regions(analyse, comprehension))

    assert any(item.strategy == "raster-image" and item.bbox == image_zone.bbox for item in plan)
    assert not any(item.strategy == "word-text" and item.bbox == texte_interne.bbox for item in plan)


def test_planner_conserve_texte_natif_word_native_dans_vrai_tableau():
    police = FontRef("OCR", "Arial", False, False)
    ligne_bbox = _bbox_pt(30, 60, 70, 72)
    span = Span("Cell", police, 9, "000000")
    ligne = Line(ligne_bbox, [span], pt_vers_emu(10), pt_vers_emu(40))
    texte_table = FlowParagraph(ligne_bbox, "Cell", police, 9, "000000", lignes=[ligne])
    table = TableEl(
        bbox=_bbox_pt(20, 50, 160, 100),
        rows=[TableRow(_bbox_pt(20, 50, 160, 100), [TableCell(_bbox_pt(20, 50, 160, 100), "Cell")])],
        col_widths_emu=[pt_vers_emu(140)],
        police=police,
        size_pt=9,
    )

    comprehension = comprendre_page(
        largeur_emu=pt_vers_emu(220),
        hauteur_emu=pt_vers_emu(300),
        tableaux=[table],
        images=[],
        formes=[],
        zones_rasterisees=[],
        lignes_natives=[ligne_bbox],
    )
    analyse = LayoutPage(page_index=0, width=pt_vers_emu(220), height=pt_vers_emu(300), rotation=0)
    plan = planifier_regions(classer_regions(analyse, comprehension))

    assert not any(item.strategy == "word-text" and item.bbox == ligne_bbox for item in plan)
    assert filtrer_elements_selon_plan([texte_table], plan) == []
    assert filtrer_elements_selon_plan([texte_table], plan, preserver_texte_natif=True) == [texte_table]
