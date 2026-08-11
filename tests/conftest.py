import io

import pymupdf
import pytest
from PIL import Image


@pytest.fixture
def pdf_texte(tmp_path):
    """Une page A4, deux lignes de texte de polices et corps différents."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Ligne en Helvetica douze", fontname="helv", fontsize=12)
    page.insert_text((72, 200), "Ligne en Times dix-huit", fontname="tiro", fontsize=18)
    chemin = tmp_path / "texte.pdf"
    doc.save(chemin)
    doc.close()
    return chemin


@pytest.fixture
def pdf_vectoriel(tmp_path):
    """Un rectangle rempli et une ligne colorée."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    forme = page.new_shape()
    forme.draw_rect(pymupdf.Rect(50, 50, 200, 150))
    forme.finish(color=(0, 0, 0), fill=(1, 0, 0), width=2)
    forme.draw_line(pymupdf.Point(50, 200), pymupdf.Point(300, 260))
    forme.finish(color=(0, 0, 1), width=3)
    forme.commit()
    chemin = tmp_path / "vectoriel.pdf"
    doc.save(chemin)
    doc.close()
    return chemin


@pytest.fixture
def pdf_image(tmp_path):
    """Une image PNG 4x4 placée deux fois — vérifie la déduplication."""
    tampon = io.BytesIO()
    Image.new("RGB", (4, 4), (0, 128, 255)).save(tampon, format="PNG")
    octets = tampon.getvalue()

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(pymupdf.Rect(50, 50, 150, 150), stream=octets)
    page.insert_image(pymupdf.Rect(200, 50, 300, 150), stream=octets)
    chemin = tmp_path / "image.pdf"
    doc.save(chemin)
    doc.close()
    return chemin


@pytest.fixture
def pdf_liens(tmp_path):
    """Un lien externe posé sur une zone rectangulaire recouvrant du texte."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Site officiel", fontname="helv", fontsize=12)
    page.insert_link({
        "kind": pymupdf.LINK_URI,
        "from": pymupdf.Rect(72, 88, 200, 104),
        "uri": "https://example.org/",
    })
    chemin = tmp_path / "liens.pdf"
    doc.save(chemin)
    doc.close()
    return chemin
