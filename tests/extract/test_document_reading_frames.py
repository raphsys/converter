from pdfexact.extract import document as document_module
from pdfexact.extract.document import _attacher_frames_texte, _cadres_lecture_depuis_plan, extraire
from pdfexact.fontlib import construire, dossiers_par_defaut
from pdfexact.geometry import BBox, pt_vers_emu
from pdfexact.ir import FontRef, Line, Span, TextBox
from pdfexact.layout.ai import LayoutAIPage, LayoutAIZone
from pdfexact.layout.model import LayoutRegion
from pdfexact.layout.planner import LayoutPlanItem


def _item(kind: str, bbox: BBox, source: str, reasons: list[str] | None = None) -> LayoutPlanItem:
    region = LayoutRegion(
        kind=kind,
        bbox=bbox,
        confidence=0.7,
        editable=True,
        strategy="word-text",
        style_hints={"source": source, "reasons": reasons or []},
    )
    return LayoutPlanItem(
        kind=kind,
        bbox=bbox,
        strategy="word-text",
        editable=True,
        confidence=0.7,
        region=region,
    )


def _bbox(x0: float, y0: float, x1: float, y1: float) -> BBox:
    return BBox(pt_vers_emu(x0), pt_vers_emu(y0), pt_vers_emu(x1), pt_vers_emu(y1))


def test_les_cadres_natifs_priment_sur_les_mini_cadres_geometriques():
    gauche = _bbox(55, 80, 210, 720)
    droite = _bbox(230, 80, 545, 720)
    plan = [
        _item("text-column", gauche, "native-lines"),
        _item("text-column", droite, "native-lines"),
    ]
    for index in range(8):
        y0 = 95 + index * 22
        plan.append(_item("text-column", _bbox(58, y0, 205, y0 + 12), "geometric"))
        plan.append(_item("text-column", _bbox(235, y0, 540, y0 + 12), "geometric"))

    cadres = _cadres_lecture_depuis_plan(plan)

    assert cadres == [gauche, droite]


def test_les_cadres_geometriques_sont_fusionnes_en_colonnes_quand_il_ny_a_pas_de_source_native():
    plan = []
    for index in range(6):
        y0 = 90 + index * 24
        plan.append(_item("text-column", _bbox(55, y0, 210, y0 + 13), "geometric"))
        plan.append(_item("text-column", _bbox(232, y0 + 2, 545, y0 + 15), "geometric"))

    cadres = _cadres_lecture_depuis_plan(plan)

    assert len(cadres) == 2
    assert cadres[0].x0 == pt_vers_emu(55)
    assert cadres[0].y0 == pt_vers_emu(90)
    assert cadres[0].y1 == pt_vers_emu(90 + 5 * 24 + 13)
    assert cadres[1].x0 == pt_vers_emu(232)
    assert cadres[1].y1 == pt_vers_emu(90 + 5 * 24 + 15)


def test_les_textes_natifs_dans_les_visuels_restent_des_cadres_de_preservation():
    colonne = _bbox(55, 80, 210, 720)
    label_dans_schema = _bbox(300, 210, 360, 225)
    plan = [
        _item("text-column", colonne, "native-lines"),
        _item(
            "text-column",
            label_dans_schema,
            "native-text-in-protected-visual",
            ["native-text-inside-protected-visual"],
        ),
    ]

    cadres = _cadres_lecture_depuis_plan(plan)

    assert colonne in cadres
    assert label_dans_schema in cadres


def test_attacher_frames_ia_couvre_les_lignes_natives_sans_plan_ocr():
    police = FontRef("Test", "Arial", False, False)
    ligne = Line(
        _bbox(60, 120, 260, 134),
        [Span("Texte natif", police, 11, "000000")],
        pt_vers_emu(14),
        pt_vers_emu(200),
    )
    bloc = TextBox(ligne.bbox, [ligne])
    zone = LayoutAIZone(
        zone_id="ai-text-1",
        label="text",
        role="text",
        confidence=0.96,
        bbox=_bbox(50, 100, 300, 160),
        source="paddlex",
        model_id="test",
    )

    result = _attacher_frames_texte([bloc], [], [zone])

    assert result[0].layout_frame_role == "text-column"
    assert result[0].lignes[0].layout_frame_id
    assert result[0].lignes[0].layout_frame_bbox == zone.bbox


def test_extraire_spans_execute_layout_ia_et_transmet_ses_zones(pdf_texte, monkeypatch):
    zone = LayoutAIZone(
        zone_id="ai-text-1",
        label="text",
        role="text",
        confidence=0.96,
        bbox=_bbox(40, 70, 300, 230),
        source="test-provider",
        model_id="test-model",
    )
    appels = []

    def fake_layout(*args, **kwargs):
        appels.append(kwargs)
        return LayoutAIPage(
            status="layout_ai_detected",
            provider="test-provider",
            model_id="test-model",
            model_path=None,
            zones=(zone,),
        )

    monkeypatch.setattr(document_module, "detecter_layout_ia", fake_layout)
    document = extraire(
        pdf_texte,
        pages=[0],
        bibliotheque=construire(dossiers=dossiers_par_defaut()),
        text_mode="spans",
        strict=True,
    )

    textes = [
        element
        for element in document.pages[0].elements
        if isinstance(element, TextBox)
    ]
    assert appels and appels[0]["required"] is False
    assert textes
    assert any(element.layout_frame_id for element in textes)
