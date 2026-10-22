import zipfile
import re
from xml.etree import ElementTree

import pymupdf
import pytest

from pdfexact.extract.document import extraire
from pdfexact.fontlib import construire, dossiers_par_defaut
from pdfexact.ir import Document, FontRef, Line, Page, Span, TextBox, TextGeometry
from pdfexact.geometry import BBox, PageGeometry, bbox_depuis_rect, pt_vers_emu
from pdfexact.render.bbox_debug import (
    _native_paragraph_xml,
    annotate_pdf_bboxes,
    fill_existing_bbox_docx,
    write_bbox_only_docx,
)
from pdfexact.layout.paragraph_planner import planifier_paragraphe
from pdfexact.report import Rapport


@pytest.mark.parametrize("rotation", (0, 90, 180, 270))
@pytest.mark.parametrize("crop", (False, True))
@pytest.mark.parametrize("irregular", (False, True))
def test_pdf_annote_respecte_repere_visible(rotation, crop, irregular, tmp_path):
    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "annotated.pdf"
    visible_rect = pymupdf.Rect(40, 50, 150, 95)
    with pymupdf.open() as source:
        page = source.new_page(width=320, height=240)
        if crop:
            page.set_cropbox(pymupdf.Rect(20, 15, 300, 225))
        page.set_rotation(rotation)
        native_rect = visible_rect * page.derotation_matrix
        geometry = PageGeometry.depuis_page(page)
        cropbox = page.cropbox
        page.set_rotation(0)
        page.draw_rect(native_rect, color=(0, 0, 1))
        page.set_rotation(rotation)
        source.save(source_path)

    bbox = bbox_depuis_rect(visible_rect)
    font = FontRef("Test", "Arial", False, False)
    lines = [bbox_depuis_rect(pymupdf.Rect(40, 50, 150, 70))]
    if irregular:
        lines.append(bbox_depuis_rect(pymupdf.Rect(50, 75, 130, 95)))
    element = TextBox(
        bbox,
        [Line(box, [Span("text", font, 10, "000000")], box.hauteur, box.largeur)
         for box in lines],
        geometry=TextGeometry(kind="variable-width-flow", line_bboxes=tuple(lines)),
    )
    document = Document(pages=[Page(0, geometry.largeur_emu, geometry.hauteur_emu, [element])])

    records = annotate_pdf_bboxes(source_path, output_path, document)

    assert len(records) == 1
    assert records[0].bbox == bbox
    with pymupdf.open(output_path) as output:
        page = output[0]
        assert page.rotation == rotation
        assert page.cropbox == cropbox
        drawings = page.get_drawings()
        assert len(drawings) == 2
        actual = drawings[-1]["rect"] * page.rotation_matrix
        assert tuple(actual) == pytest.approx(tuple(visible_rect), abs=0.01)
        if irregular:
            edges = drawings[-1]["items"]
            assert edges[0][1] == edges[-1][2]
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(3, 3), alpha=False)
        r, g, b = pixmap.pixel(120, 180)
        assert r > g + 50 and r > b + 50


def test_bbox_debug_produit_pdf_annote_et_docx_sans_texte(pdf_texte, tmp_path):
    document = extraire(
        pdf_texte,
        pages=[0],
        bibliotheque=construire(dossiers=dossiers_par_defaut()),
        text_mode="spans",
        strict=True,
        rapport=Rapport(),
    )
    pdf_out = tmp_path / "bboxes.pdf"
    docx_out = tmp_path / "bboxes.docx"

    records = annotate_pdf_bboxes(pdf_texte, pdf_out, document)
    write_bbox_only_docx(document, docx_out)

    assert records
    assert pdf_out.exists()
    assert docx_out.exists()
    with pymupdf.open(pdf_out) as rendered:
        assert len(rendered[0].get_drawings()) >= len(records)
    with zipfile.ZipFile(docx_out) as archive:
        xml = archive.read("word/document.xml")
        ElementTree.fromstring(xml)
        assert b"<w:t>" not in xml
        assert b"<w:t " not in xml
        assert xml.count(b"<wp:anchor") == len(records)


def test_bbox_debug_ne_justifie_pas_un_titre_et_justifie_le_corps():
    font = FontRef("Test", "Arial", False, False)

    def bloc(textes, taille):
        lignes = []
        for index, texte in enumerate(textes):
            bbox = BBox(
                pt_vers_emu(60),
                pt_vers_emu(100 + index * 14),
                pt_vers_emu(280),
                pt_vers_emu(112 + index * 14),
            )
            lignes.append(Line(bbox, [Span(texte, font, taille, "000000")], pt_vers_emu(12), bbox.largeur))
        return TextBox(BBox(pt_vers_emu(60), pt_vers_emu(100), pt_vers_emu(280), pt_vers_emu(140)), lignes)

    titre = _native_paragraph_xml(bloc(["Meat Safety", "Success Story"], 30))
    corps = _native_paragraph_xml(
        bloc(
            [
                "Leafy vegetables are not the only foods that benefit",
                "from research and careful processing in this facility.",
                "The implementation remains consistent across phases.",
            ],
            10,
        )
    )

    assert '<w:jc w:val="left"/>' in titre
    assert '<w:jc w:val="both"/>' in corps


def test_les_cadres_de_diagnostic_ne_passent_pas_dans_le_docx_final(pdf_texte, tmp_path):
    document = extraire(
        pdf_texte,
        pages=[0],
        bibliotheque=construire(dossiers=dossiers_par_defaut()),
        text_mode="spans",
        strict=True,
        rapport=Rapport(),
    )
    bbox_docx = tmp_path / "bboxes.docx"
    final_docx = tmp_path / "non_text.docx"
    write_bbox_only_docx(document, bbox_docx)
    fill_existing_bbox_docx(bbox_docx, document, final_docx)

    with zipfile.ZipFile(final_docx) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "E60D0D" not in xml.upper()


def test_paragraphe_natif_conserve_les_tailles_dans_un_seul_w_p():
    font = FontRef("Test", "Arial", False, False)
    lignes = [
        Line(
            BBox(pt_vers_emu(60), pt_vers_emu(100), pt_vers_emu(180), pt_vers_emu(112)),
            [Span("Large", font, 14, "000000")],
            pt_vers_emu(12),
            pt_vers_emu(120),
        ),
        Line(
            BBox(pt_vers_emu(70), pt_vers_emu(114), pt_vers_emu(180), pt_vers_emu(124)),
            [Span("small", font, 8, "000000")],
            pt_vers_emu(10),
            pt_vers_emu(110),
        ),
    ]
    element = TextBox(
        BBox(pt_vers_emu(60), pt_vers_emu(100), pt_vers_emu(180), pt_vers_emu(124)),
        lignes,
    )

    xml = _native_paragraph_xml(element)

    assert xml.count("<w:p>") == 1
    assert '<w:sz w:val="28"/>' in xml
    assert '<w:sz w:val="16"/>' in xml


def test_plan_natif_conserve_la_taille_et_ajuste_le_tracking(monkeypatch):
    font = FontRef("Test", "Arial", False, False)
    line_bbox = BBox(
        pt_vers_emu(60), pt_vers_emu(100), pt_vers_emu(560), pt_vers_emu(112)
    )
    span = Span("Final Coastal and Riverine High", font, 42, "000000")
    line_bbox_2 = BBox(
        pt_vers_emu(60), pt_vers_emu(114), pt_vers_emu(560), pt_vers_emu(126)
    )
    element = TextBox(
        BBox(line_bbox.x0, line_bbox.y0, line_bbox_2.x1, line_bbox_2.y1),
        [
            Line(line_bbox, [span], pt_vers_emu(12), line_bbox.largeur),
            Line(line_bbox_2, [Span("Water Mark Collection", font, 42, "000000")], pt_vers_emu(12), line_bbox_2.largeur),
        ],
    )

    monkeypatch.setattr(
        "pdfexact.extract.fonts.mesurer_largeur_pt",
        lambda texte, _asset, taille: len(texte) * taille,
    )
    plan = planifier_paragraphe(element, {"Test": object()})

    assert plan.preserve_lines is True
    assert plan.line_spacing_twips[0] < 0
    assert span.size_pt == 42


def test_paragraphe_natif_ne_depasse_pas_une_bbox_adjacente():
    font = FontRef("Test", "Arial", False, False)
    lignes = [
        Line(
            BBox(pt_vers_emu(60), pt_vers_emu(100), pt_vers_emu(180), pt_vers_emu(112)),
            [Span("text", font, 14, "000000")],
            pt_vers_emu(12),
            pt_vers_emu(120),
        ),
        Line(
            BBox(pt_vers_emu(60), pt_vers_emu(114), pt_vers_emu(180), pt_vers_emu(126)),
            [Span("more", font, 14, "000000")],
            pt_vers_emu(12),
            pt_vers_emu(120),
        ),
    ]
    element = TextBox(
        BBox(pt_vers_emu(60), pt_vers_emu(100), pt_vers_emu(180), pt_vers_emu(126)),
        lignes,
    )
    voisin = BBox(pt_vers_emu(60), pt_vers_emu(127), pt_vers_emu(180), pt_vers_emu(140))

    xml = _native_paragraph_xml(element, occupied_bboxes=(voisin,))

    hauteur = int(re.search(r'w:h="(\d+)"', xml).group(1))
    assert hauteur < 560
