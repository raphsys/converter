from pathlib import Path

import pymupdf
import pytest

from pdfexact.geometry import BBox, PageGeometry, emu_vers_pt, etat_page, pt_vers_emu
from pdfexact.layout import LayoutBlock, LayoutPage, analyser_page


def test_analyzer_collecte_signaux_bruts_page():
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=120)
    page.insert_text((20, 24), "Hello layout")
    page.draw_rect(pymupdf.Rect(10, 50, 180, 72), color=(1, 0, 0), fill=(1, 0, 0))

    analyse = analyser_page(page)

    assert isinstance(analyse, LayoutPage)
    assert analyse.page_index == 0
    assert analyse.width == pt_vers_emu(200)
    assert analyse.height == pt_vers_emu(120)
    assert analyse.text_blocks
    assert analyse.drawing_blocks
    assert analyse.metrics["native_line_count"] >= 1
    assert "Hello layout" in analyse.text_blocks[0].text


def test_layout_page_expose_bboxes_de_lignes_natives():
    line_bbox = BBox(1, 2, 3, 4)
    page = LayoutPage(
        page_index=0,
        width=100,
        height=100,
        rotation=0,
        text_blocks=(
            LayoutBlock(
                "text",
                line_bbox,
                "test",
                metadata={"line_bboxes": (line_bbox,)},
            ),
        ),
    )

    assert page.native_line_bboxes() == [line_bbox]


def test_analyzer_preserve_cropbox_rotation_sur_page_tournee_reelle():
    pdf = Path("/home/raphael/Mes_Projets/vysi/vysi_real_corpus/pdf_native/3ca73e1072f8fcad_000750.pdf")
    if not pdf.exists():
        pytest.skip("corpus local absent")
    doc = pymupdf.open(pdf)
    page = doc[0]
    original = etat_page(page)
    rect_initial = pymupdf.Rect(page.rect)
    geometrie = PageGeometry.depuis_page(page)

    analyse = analyser_page(page, geometrie=geometrie)

    assert etat_page(page) == original
    assert page.rect == rect_initial
    assert round(emu_vers_pt(analyse.height), 2) == pytest.approx(424.26, abs=0.01)
    titre = next(block for block in analyse.text_blocks if "Colonies of ANTS" in (block.text or ""))
    assert emu_vers_pt(titre.bbox.y0) < 30
