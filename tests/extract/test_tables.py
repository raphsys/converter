from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest

from pdfexact.extract.fonts import collecter_polices
from pdfexact.extract.tables import (
    _colonnes_cellule,
    _positions_x_table,
    _semble_faux_tableau_de_mise_en_page,
    extraire_tableaux,
    extraire_tableaux_listing,
)
from pdfexact.geometry import BBox, etat_page, pt_vers_emu


def _rect_pt(x0, y0, x1, y1):
    return (x0, y0, x1, y1)


def test_grille_table_absorbe_micro_colonnes_vides_dentete():
    table = SimpleNamespace(
        bbox=_rect_pt(0, 0, 300, 80),
        rows=[
            SimpleNamespace(
                cells=[
                    _rect_pt(0, 0, 50, 20),
                    _rect_pt(50, 0, 55, 20),
                    _rect_pt(55, 0, 200, 20),
                    None,
                    None,
                    _rect_pt(200, 0, 300, 20),
                ]
            ),
            SimpleNamespace(
                cells=[
                    None,
                    _rect_pt(50, 20, 100, 40),
                    _rect_pt(100, 20, 150, 40),
                    _rect_pt(150, 20, 200, 40),
                    _rect_pt(200, 20, 250, 40),
                    _rect_pt(250, 20, 300, 40),
                ]
            ),
        ],
    )

    positions = _positions_x_table(table)
    positions_pt = [round(position / pt_vers_emu(1), 1) for position in positions]

    assert 55.0 not in positions_pt
    assert positions_pt == [0.0, 50.0, 100.0, 150.0, 200.0, 250.0, 300.0]

    debut, fin = _colonnes_cellule(
        BBox(pt_vers_emu(55), pt_vers_emu(0), pt_vers_emu(200), pt_vers_emu(20)),
        positions,
    )
    assert (debut, fin) == (1, 4)


def test_rejette_grand_cadre_2x2_de_colonnes_comme_faux_tableau():
    assert _semble_faux_tableau_de_mise_en_page(
        bbox=BBox(pt_vers_emu(60), pt_vers_emu(80), pt_vers_emu(560), pt_vers_emu(720)),
        page_width=pt_vers_emu(612),
        page_height=pt_vers_emu(792),
        row_count=2,
        col_count=2,
        textes=[
            [
                "Long paragraph text flowing inside a magazine column, not a table cell.",
                "Another long paragraph continuing the article layout rather than tabular data.",
            ],
            ["more prose", "more prose"],
        ],
    )


def test_rejette_schema_boites_comme_faux_tableau_sparse_sans_grille():
    textes = [["" for _ in range(9)] for _ in range(13)]
    textes[0][0] = "Test Missions - Preliminary Mission Categories to Meet"
    textes[2][1] = "Assembly"
    textes[5][4] = "Human"
    textes[7][6] = "Missions With a Primary Objective of Demonstrating Habitation"

    assert _semble_faux_tableau_de_mise_en_page(
        bbox=BBox(pt_vers_emu(81), pt_vers_emu(134), pt_vers_emu(384), pt_vers_emu(505)),
        page_width=pt_vers_emu(792),
        page_height=pt_vers_emu(612),
        row_count=13,
        col_count=9,
        textes=textes,
        lignes_grille=1,
    )


def test_listing_subject_number_percent_devient_tableau_word_natif():
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((36, 47), "Table DP-1. Profile of General Demographic Characteristics: 2000", fontsize=8)
    page.insert_text((114, 96), "Subject", fontsize=8)
    page.insert_text((238, 96), "Number", fontsize=8)
    page.insert_text((275, 96), "Percent", fontsize=8)
    page.insert_text((383, 96), "Subject", fontsize=8)
    page.insert_text((507, 96), "Number", fontsize=8)
    page.insert_text((544, 96), "Percent", fontsize=8)
    page.draw_line((36, 90), (305, 90), width=1)
    page.draw_line((36, 107), (305, 107), width=1)
    page.draw_line((305, 90), (575, 90), width=1)
    page.draw_line((305, 107), (575, 107), width=1)
    page.draw_line((36, 651), (575, 651), width=1)
    for index in range(24):
        y = 118 + index * 10
        page.insert_text((39, y), f"Left row {index} . . . . . . . . . . . . . .", fontsize=8)
        page.insert_text((247, y), str(index), fontsize=8)
        page.insert_text((283, y), "1.0", fontsize=8)
        page.insert_text((309, y), f"Right row {index} . . . . . . . . . . . .", fontsize=8)
        page.insert_text((516, y), str(index), fontsize=8)
        page.insert_text((552, y), "2.0", fontsize=8)

    tableaux = extraire_tableaux_listing(page, collecter_polices(doc))

    assert len(tableaux) == 1
    assert len(tableaux[0].col_widths_emu) == 6
    assert not tableaux[0].bordures_globales
    assert tableaux[0].rows[0].cells[0].texte == "Subject"


def test_listing_subject_number_percent_trop_dense_reste_positionne():
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((114, 96), "Subject", fontsize=8)
    page.insert_text((238, 96), "Number", fontsize=8)
    page.insert_text((275, 96), "Percent", fontsize=8)
    page.insert_text((383, 96), "Subject", fontsize=8)
    page.insert_text((507, 96), "Number", fontsize=8)
    page.insert_text((544, 96), "Percent", fontsize=8)
    page.draw_line((36, 90), (575, 90), width=1)
    page.draw_line((36, 107), (575, 107), width=1)
    page.draw_line((36, 651), (575, 651), width=1)
    for index in range(70):
        y = 118 + index * 7
        page.insert_text((39, y), f"Left row {index} . . . . . . . . . . . . . .", fontsize=6)
        page.insert_text((247, y), str(index), fontsize=6)
        page.insert_text((283, y), "1.0", fontsize=6)
        page.insert_text((309, y), f"Right row {index} . . . . . . . . . . . .", fontsize=6)
        page.insert_text((516, y), str(index), fontsize=6)
        page.insert_text((552, y), "2.0", fontsize=6)

    assert extraire_tableaux_listing(page, collecter_polices(doc)) == []


def test_garde_vraie_table_dense_meme_si_nombreuses_cellules_vides():
    textes = [
        ["Item", "Q1", "Q2", "Q3", "Q4", "Total"],
        ["A", "1", "", "3", "", "4"],
        ["B", "", "2", "", "4", "6"],
        ["C", "1", "1", "1", "1", "4"],
        ["D", "", "", "2", "2", "4"],
        ["Total", "2", "3", "6", "7", "18"],
    ]

    assert not _semble_faux_tableau_de_mise_en_page(
        bbox=BBox(pt_vers_emu(80), pt_vers_emu(120), pt_vers_emu(520), pt_vers_emu(420)),
        page_width=pt_vers_emu(792),
        page_height=pt_vers_emu(612),
        row_count=6,
        col_count=6,
        textes=textes,
        lignes_grille=10,
    )


def test_cb3536_magazine_frames_ne_sont_pas_des_tableaux_word():
    pdf = "/home/raphael/Mes_Projets/vysi/vysi_real_corpus/pdf_native/cb3536e7070a8a08_000341.pdf"
    doc = pymupdf.open(pdf)
    polices = collecter_polices(doc)

    assert extraire_tableaux(doc[0], polices) == []
    assert extraire_tableaux(doc[1], polices) == []


def test_extraire_tableaux_preserve_cropbox_rotation_sur_page_tournee_reelle():
    pdf = Path("/home/raphael/Mes_Projets/vysi/vysi_real_corpus/pdf_native/3ca73e1072f8fcad_000750.pdf")
    if not pdf.exists():
        pytest.skip("corpus local absent")
    doc = pymupdf.open(pdf)
    page = doc[0]
    polices = collecter_polices(doc)
    original = etat_page(page)
    rect_initial = pymupdf.Rect(page.rect)

    extraire_tableaux(page, polices)

    assert etat_page(page) == original
    assert page.rect == rect_initial
