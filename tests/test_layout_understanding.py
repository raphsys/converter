from pdfexact.geometry import BBox, pt_vers_emu
from pdfexact.extract.layout_map import PageLayoutMap
from pdfexact.ir import FontRef, ImageEl, ShapeEl, TableEl, TableRow, TableCell, TextBox, Line, Span
from pdfexact.layout import LayoutAIZone, comprendre_page, filtrer_elements_proteges
from pdfexact.layout.ai import _normaliser_detections
from pdfexact.report import DiagnosticElement, DiagnosticLayout, Rapport


def _bbox_pt(x0, y0, x1, y1):
    return BBox(pt_vers_emu(x0), pt_vers_emu(y0), pt_vers_emu(x1), pt_vers_emu(y1))


def test_comprehension_protege_tableaux_et_images():
    police = FontRef("Test", "Arial", False, False)
    table = TableEl(
        bbox=_bbox_pt(50, 80, 350, 240),
        rows=[
            TableRow(
                bbox=_bbox_pt(50, 80, 350, 100),
                cells=[TableCell(_bbox_pt(50, 80, 200, 100), "A")],
            )
        ],
        col_widths_emu=[pt_vers_emu(150)],
        police=police,
        size_pt=9,
    )
    image = ImageEl(bbox=_bbox_pt(60, 260, 260, 420), media_ref="image1")

    page = comprendre_page(
        largeur_emu=pt_vers_emu(612),
        hauteur_emu=pt_vers_emu(792),
        tableaux=[table],
        images=[image],
        formes=[],
        zones_rasterisees=[],
    )

    assert len(page.zones_ocr) == 2
    assert {zone.kind for zone in page.zones} == {"table", "image"}
    assert {element.role for element in page.elements} == {"real-table", "image"}
    table_decision = next(element for element in page.elements if element.role == "real-table")
    assert table_decision.strategy == "word-table"
    assert table_decision.editable


def test_comprehension_preserve_texte_natif_dans_table_bandeau():
    police = FontRef("Test", "Arial", False, False)
    table = TableEl(
        bbox=_bbox_pt(36, 78, 576, 146),
        rows=[TableRow(_bbox_pt(36, 78, 576, 146), [TableCell(_bbox_pt(36, 78, 576, 146), "")])],
        col_widths_emu=[pt_vers_emu(540)],
        police=police,
        size_pt=9,
    )
    lignes = [
        _bbox_pt(40, 132, 180, 143),
        _bbox_pt(459, 132, 572, 143),
    ]

    page = comprendre_page(
        largeur_emu=pt_vers_emu(612),
        hauteur_emu=pt_vers_emu(792),
        tableaux=[table],
        images=[],
        formes=[],
        zones_rasterisees=[],
        lignes_natives=lignes,
    )

    preservations = [
        element for element in page.elements
        if element.source == "native-text-in-protected-visual"
    ]
    assert len(preservations) == 2


def test_comprehension_preserve_texte_natif_dans_bandeau_couleur():
    bandeau = ShapeEl(_bbox_pt(36, 128, 576, 146), [], "000000", None, 0)
    lignes = [
        _bbox_pt(40, 132, 180, 143),
        _bbox_pt(459, 132, 572, 143),
    ]

    page = comprendre_page(
        largeur_emu=pt_vers_emu(612),
        hauteur_emu=pt_vers_emu(792),
        tableaux=[],
        images=[],
        formes=[bandeau],
        zones_rasterisees=[],
        lignes_natives=lignes,
    )

    preservations = [
        element for element in page.elements
        if element.source == "native-text-in-protected-visual"
    ]
    assert len(preservations) == 2


def test_filtre_fuites_ocr_dans_zones_protegees():
    police = FontRef("OCR", "Arial", False, False)
    ligne = Line(
        bbox=_bbox_pt(60, 90, 240, 106),
        spans=[Span("doublon", police, 9, "000000")],
        hauteur_ligne_emu=pt_vers_emu(12),
        largeur_cible_emu=pt_vers_emu(180),
    )
    texte = TextBox(bbox=ligne.bbox, lignes=[ligne])

    gardes = filtrer_elements_proteges([texte], [_bbox_pt(50, 80, 350, 240)])

    assert gardes == []


def test_comprehension_detecte_deux_colonnes():
    lignes = []
    for index in range(8):
        y0 = 80 + index * 18
        lignes.append(_bbox_pt(60, y0, 250, y0 + 10))
        lignes.append(_bbox_pt(330, y0, 520, y0 + 10))

    page = comprendre_page(
        largeur_emu=pt_vers_emu(612),
        hauteur_emu=pt_vers_emu(792),
        tableaux=[],
        images=[],
        formes=[],
        zones_rasterisees=[],
        lignes_natives=lignes,
    )

    assert "two-column" in page.profiles
    colonnes = [element for element in page.elements if element.role == "text-column"]
    assert len(colonnes) == 2
    assert all(element.strategy == "word-text" for element in colonnes)
    assert all(element.editable for element in colonnes)


def test_comprehension_utilise_zone_ia_caption_comme_texte_word():
    caption = LayoutAIZone(
        zone_id="z1",
        label="caption",
        role="caption",
        confidence=0.91,
        bbox=_bbox_pt(360, 390, 545, 430),
        source="paddlex",
        model_id="ppstructurev3/PP-DocLayout_plus-L",
    )

    page = comprendre_page(
        largeur_emu=pt_vers_emu(612),
        hauteur_emu=pt_vers_emu(792),
        tableaux=[],
        images=[],
        formes=[],
        zones_rasterisees=[],
        zones_ia=[caption],
    )

    decision = next(element for element in page.elements if element.role == "caption")
    assert "layout-ai" in page.profiles
    assert decision.strategy == "word-text"
    assert decision.editable
    assert page.zones_ocr == []


def test_comprehension_protege_zone_vectorielle_complexe():
    formes = []
    for index in range(8):
        x0 = 100 + index * 10
        formes.append(
            ShapeEl(
                bbox=_bbox_pt(x0, 120, x0 + 1, 190),
                chemins=[],
                remplissage=None,
                contour="000000",
                epaisseur_emu=pt_vers_emu(0.5),
            )
        )
        formes.append(
            ShapeEl(
                bbox=_bbox_pt(90, 130 + index * 7, 210, 131 + index * 7),
                chemins=[],
                remplissage=None,
                contour="000000",
                epaisseur_emu=pt_vers_emu(0.5),
            )
        )

    page = comprendre_page(
        largeur_emu=pt_vers_emu(612),
        hauteur_emu=pt_vers_emu(792),
        tableaux=[],
        images=[],
        formes=formes,
        zones_rasterisees=[],
    )

    assert "complex-vector" in page.profiles
    assert any(zone.kind == "complex-vector-zone" for zone in page.zones)
    assert page.zones_ocr
    decision = next(element for element in page.elements if element.role == "figure-or-diagram")
    assert decision.strategy == "raster-immutable"
    assert not decision.editable


def test_comprehension_protege_conteneur_graphique_blanc():
    cadre = ShapeEl(
        bbox=_bbox_pt(220, 90, 560, 350),
        chemins=[],
        remplissage="FFFFFF",
        contour="000000",
        epaisseur_emu=pt_vers_emu(0.5),
    )
    formes = [cadre]
    for index in range(3):
        formes.append(
            ShapeEl(
                bbox=_bbox_pt(245, 130 + index * 55, 545, 131 + index * 55),
                chemins=[],
                remplissage=None,
                contour="000000",
                epaisseur_emu=pt_vers_emu(0.5),
            )
        )
    formes.append(
        ShapeEl(
            bbox=_bbox_pt(245, 125, 246, 310),
            chemins=[],
            remplissage=None,
            contour="000000",
            epaisseur_emu=pt_vers_emu(0.5),
        )
    )

    page = comprendre_page(
        largeur_emu=pt_vers_emu(612),
        hauteur_emu=pt_vers_emu(792),
        tableaux=[],
        images=[],
        formes=formes,
        zones_rasterisees=[],
    )

    assert "complex-vector" in page.profiles
    decision = next(element for element in page.elements if element.role == "figure-or-diagram")
    assert decision.bbox.x0 <= cadre.bbox.x0
    assert decision.bbox.x1 >= cadre.bbox.x1
    assert decision.strategy == "raster-immutable"


def test_grand_rectangle_blanc_vide_reste_editable():
    cadre = ShapeEl(
        bbox=_bbox_pt(50, 90, 260, 330),
        chemins=[],
        remplissage="FFFFFF",
        contour="000000",
        epaisseur_emu=pt_vers_emu(0.5),
    )

    page = comprendre_page(
        largeur_emu=pt_vers_emu(612),
        hauteur_emu=pt_vers_emu(792),
        tableaux=[],
        images=[],
        formes=[cadre],
        zones_rasterisees=[],
    )

    assert "complex-vector" not in page.profiles
    assert page.zones_ocr == []


def test_bandeau_colore_ne_bloque_pas_ocr_mais_protege_layout():
    bandeau = ShapeEl(
        bbox=_bbox_pt(70, 90, 520, 112),
        chemins=[],
        remplissage="000080",
        contour=None,
        epaisseur_emu=0,
    )

    page = comprendre_page(
        largeur_emu=pt_vers_emu(612),
        hauteur_emu=pt_vers_emu(792),
        tableaux=[],
        images=[],
        formes=[bandeau],
        zones_rasterisees=[],
    )

    assert "colored-bands" in page.profiles
    assert any(zone.kind == "color-band" for zone in page.zones)
    assert page.zones_ocr == []
    assert page.zones_layout == [bandeau.bbox]
    decision = next(element for element in page.elements if element.role == "section-band")
    assert decision.strategy == "shape-background"
    assert not decision.editable
    assert page.zones_strategie("shape-background") == [bandeau.bbox]


def test_comprehension_classe_image_pleine_page_comme_scan_immuable():
    image = ImageEl(bbox=_bbox_pt(5, 5, 607, 787), media_ref="scan")

    page = comprendre_page(
        largeur_emu=pt_vers_emu(612),
        hauteur_emu=pt_vers_emu(792),
        tableaux=[],
        images=[image],
        formes=[],
        zones_rasterisees=[],
    )

    assert "scanned-or-image-page" in page.profiles
    decision = next(element for element in page.elements if element.role == "scanned-page")
    assert decision.strategy == "raster-image"
    assert not decision.editable


def test_plan_distingue_elements_editables_et_immuables():
    police = FontRef("Test", "Arial", False, False)
    table = TableEl(
        bbox=_bbox_pt(50, 80, 350, 240),
        rows=[
            TableRow(
                bbox=_bbox_pt(50, 80, 350, 100),
                cells=[TableCell(_bbox_pt(50, 80, 200, 100), "A")],
            )
        ],
        col_widths_emu=[pt_vers_emu(150)],
        police=police,
        size_pt=9,
    )
    scan = ImageEl(bbox=_bbox_pt(5, 5, 607, 787), media_ref="scan")
    lignes = []
    for index in range(8):
        y0 = 300 + index * 18
        lignes.append(_bbox_pt(60, y0, 250, y0 + 10))
        lignes.append(_bbox_pt(330, y0, 520, y0 + 10))

    page = comprendre_page(
        largeur_emu=pt_vers_emu(612),
        hauteur_emu=pt_vers_emu(792),
        tableaux=[table],
        images=[scan],
        formes=[],
        zones_rasterisees=[],
        lignes_natives=lignes,
    )

    assert {element.role for element in page.elements_editables} == {
        "real-table",
        "text-column",
    }
    assert {element.role for element in page.elements_immuables} == {"scanned-page"}
    assert page.zones_strategie("word-table") == [table.bbox]
    assert page.zones_strategie("raster-image") == [scan.bbox]


def test_layout_map_restaure_leaders_natifs_perdus_par_ocr():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(612), hauteur_emu=pt_vers_emu(792))
    bbox = _bbox_pt(80, 180, 520, 194)
    carte.ajouter(
        "native-line",
        bbox,
        "test",
        text="Figure 1: Hurricane Rita Storm Track------------------------------- 2",
    )

    texte = carte.texte_natif_preferable(
        bbox,
        "Figure 1: Hurricane Rita Storm Track 2",
    )

    assert "-------------------------------" in texte
    assert texte.endswith("2")


def test_layout_map_identifie_ligne_native_restauree():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(612), hauteur_emu=pt_vers_emu(792))
    bbox = _bbox_pt(80, 180, 520, 194)
    carte.ajouter(
        "native-line",
        bbox,
        "test",
        text="Figure 1: Hurricane Rita Storm Track------------------------------- 2",
    )

    premier = carte.remplacement_texte_natif(
        _bbox_pt(82, 181, 505, 193),
        "Figure 1: Hurricane Rita Storm Track 2",
    )
    second = carte.remplacement_texte_natif(
        _bbox_pt(84, 181, 508, 193),
        "Figure 1 Hurricane Rita Storm Track 2",
    )

    assert premier is not None
    assert second is not None
    assert premier.text == second.text
    assert premier.bbox == second.bbox


def test_rapport_expose_diagnostics_layout():
    rapport = Rapport(
        diagnostics_layout=[
            DiagnosticLayout(
                index=0,
                resume="layout-page: text=1",
                profiles=["two-column"],
                elements={"text-column": 2},
                inventory=[
                    DiagnosticElement(
                        kind="text-column",
                        role="text-column",
                        source="native-lines",
                        strategy="word-text",
                        bbox={"x0": 10, "y0": 20, "x1": 110, "y1": 80},
                        editable=True,
                        confidence=0.9,
                        reasons=["paragraph"],
                    )
                ],
                zones_ocr=0,
                zones_layout=0,
                layout_ai={"status": "layout_ai_fallback"},
            )
        ]
    )

    assert "Diagnostics layout : 1 page(s)." in rapport.resume()
    assert '"diagnostics_layout"' in rapport.vers_json()
    assert '"inventory"' in rapport.vers_json()
    assert '"word-text"' in rapport.vers_json()
    assert "layout_ai_fallback" in rapport.vers_json()


def test_layout_ai_normalise_generateur_paddlex_detresult():
    class FauxDetResult:
        json = {
            "res": {
                "boxes": [
                    {
                        "label": "text",
                        "score": 0.98,
                        "coordinate": [10.0, 20.0, 110.0, 70.0],
                    }
                ]
            }
        }

    zones = _normaliser_detections(
        (item for item in [FauxDetResult()]),
        provider="paddlex",
        model_id="ppstructurev3/PP-DocLayout_plus-L",
        page_width_pt=200,
        page_height_pt=100,
        image_width=200,
        image_height=100,
    )

    assert len(zones) == 1
    assert zones[0].label == "text"
    assert zones[0].role == "text"
