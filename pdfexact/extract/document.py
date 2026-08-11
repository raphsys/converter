"""Ouverture du PDF et assemblage du Document."""
import pymupdf

from pdfexact.extract.fonts import collecter_polices
from pdfexact.extract.text import extraire_texte
from pdfexact.geometry import pt_vers_emu
from pdfexact.ir import Document, Page


def extraire(chemin_pdf, pages=None, bibliotheque=None) -> Document:
    """Construit l'IR complet à partir d'un PDF.

    `pages` : indices 0-based à convertir, ou None pour tout le document.
    """
    doc = pymupdf.open(chemin_pdf)
    try:
        polices = collecter_polices(doc, bibliotheque)
        indices = range(doc.page_count) if pages is None else pages

        document = Document(polices=polices)
        for index in indices:
            page_pdf = doc[index]
            page_ir = Page(
                index=index,
                largeur_emu=pt_vers_emu(page_pdf.rect.width),
                hauteur_emu=pt_vers_emu(page_pdf.rect.height),
            )
            page_ir.elements.extend(extraire_texte(page_pdf, polices))
            document.pages.append(page_ir)

        return document
    finally:
        doc.close()
