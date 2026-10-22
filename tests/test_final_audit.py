import json

from pdfexact.final_audit import _auditer_couverture_visuelle, _zone_couverte
from pdfexact.geometry import BBox, pt_vers_emu
from pdfexact.ir import Document, FlowParagraph, FontRef, ImageEl, MediaItem, Page, RasterEl
from pdfexact.layout.ai import LayoutAIPage, LayoutAIZone
from pdfexact.report import CertificationFinale, Rapport


def _bbox_pt(x0, y0, x1, y1):
    return BBox(pt_vers_emu(x0), pt_vers_emu(y0), pt_vers_emu(x1), pt_vers_emu(y1))


def _zone(role="visual", bbox=None):
    return LayoutAIZone(
        zone_id="z1",
        label="image",
        role=role,
        confidence=0.9,
        bbox=bbox or _bbox_pt(10, 10, 110, 80),
        source="test",
        model_id="test",
    )


def test_zone_visuelle_couverte_par_image_existante():
    zone = _bbox_pt(10, 10, 110, 80)
    image = ImageEl(_bbox_pt(9, 9, 111, 81), "img1")

    assert _zone_couverte(zone, [image]) is True


def test_audit_recupere_une_zone_visuelle_non_couverte():
    document = Document(pages=[Page(0, pt_vers_emu(200), pt_vers_emu(200), [])], media={})
    layout = LayoutAIPage("layout_ai_detected", "test", "test", None, (_zone(),))
    resultat = CertificationFinale(active=True)

    def rasterizer(_page_pdf, bbox, media, dpi=120):
        media["recovered"] = MediaItem("recovered", b"png", "png")
        return RasterEl(bbox, "recovered")

    class FakeDoc:
        page_count = 1

        def load_page(self, _index):
            return object()

    _auditer_couverture_visuelle(
        FakeDoc(),
        document,
        [layout],
        resultat,
        dpi=120,
        rasterizer=rasterizer,
    )

    assert resultat.zones_visuelles_recuperees == 1
    assert isinstance(document.pages[0].elements[0], RasterEl)
    assert "recovered" in document.media


def test_audit_recupere_une_zone_table_non_couverte():
    document = Document(pages=[Page(0, pt_vers_emu(200), pt_vers_emu(200), [])], media={})
    layout = LayoutAIPage("layout_ai_detected", "test", "test", None, (_zone(role="table"),))
    resultat = CertificationFinale(active=True)

    def rasterizer(_page_pdf, bbox, media, dpi=120):
        media["table"] = MediaItem("table", b"png", "png")
        return RasterEl(bbox, "table")

    class FakeDoc:
        page_count = 1

        def load_page(self, _index):
            return object()

    _auditer_couverture_visuelle(
        FakeDoc(),
        document,
        [layout],
        resultat,
        dpi=120,
        rasterizer=rasterizer,
    )

    assert resultat.zones_visuelles_recuperees == 1
    assert resultat.zones_visuelles_non_couvertes == 0
    assert isinstance(document.pages[0].elements[0], RasterEl)


def test_audit_recupere_une_zone_visuelle_couverte_mais_differente():
    zone_bbox = _bbox_pt(10, 10, 110, 80)
    parasite = FlowParagraph(
        _bbox_pt(30, 30, 60, 45),
        "texte OCR dans image",
        FontRef("f", "Arial", False, False),
        10,
        "000000",
    )
    document = Document(
        pages=[Page(0, pt_vers_emu(200), pt_vers_emu(200), [ImageEl(zone_bbox, "old"), parasite])],
        media={"old": MediaItem("old", b"old", "png")},
    )
    layout = LayoutAIPage("layout_ai_detected", "test", "test", None, (_zone(bbox=zone_bbox),))
    resultat = CertificationFinale(active=True)

    def rasterizer(_page_pdf, bbox, media, dpi=120):
        media["recovered"] = MediaItem("recovered", b"png", "png")
        return RasterEl(bbox, "recovered")

    def comparer_zone(_page_pdf, _page_convertie, _bbox, dpi=120):
        return 0.5

    class FakeDoc:
        page_count = 1

        def load_page(self, _index):
            return object()

    _auditer_couverture_visuelle(
        FakeDoc(),
        document,
        [layout],
        resultat,
        dpi=120,
        rasterizer=rasterizer,
        doc_converti=FakeDoc(),
        comparer_zone=comparer_zone,
    )

    assert resultat.zones_visuelles_comparees == 1
    assert resultat.score_zone_visuelle_min == 0.5
    assert resultat.zones_visuelles_recuperees == 1
    assert isinstance(document.pages[0].elements[0], RasterEl)
    assert parasite not in document.pages[0].elements


def test_rapport_json_contient_la_certification_finale():
    rapport = Rapport(pages_totales=1, certification_finale=CertificationFinale(active=True))

    donnees = json.loads(rapport.vers_json())

    assert donnees["certification_finale"]["active"] is True
    assert "Certification finale" in rapport.resume()


def test_rapport_certification_incomplete_si_export_docx_pdf_indisponible():
    certification = CertificationFinale(
        active=True,
        avertissements=["audit_rendu_ignore:export_docx_pdf_indisponible"],
        ratio_texte=1.0,
    )
    rapport = Rapport(pages_totales=1, certification_finale=certification)

    resume = rapport.resume()

    assert "Certification finale : INCOMPLÈTE" in resume
    assert "À REVOIR" not in resume
