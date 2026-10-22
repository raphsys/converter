"""Primitives OOXML communes pour les sections de page."""
from __future__ import annotations

from pdfexact.geometry import emu_vers_pt, pt_vers_twips


def section_xml(page, *, next_page: bool = True) -> str:
    """Construit une section sans marge avec les dimensions de la page source."""
    width = pt_vers_twips(emu_vers_pt(page.largeur_emu))
    height = pt_vers_twips(emu_vers_pt(page.hauteur_emu))
    orientation = ' w:orient="landscape"' if page.largeur_emu > page.hauteur_emu else ""
    page_type = '<w:type w:val="nextPage"/>' if next_page else ""
    return (
        "<w:sectPr>"
        f"{page_type}<w:pgSz w:w=\"{width}\" w:h=\"{height}\"{orientation}/>"
        '<w:pgMar w:top="0" w:right="0" w:bottom="0" w:left="0" w:header="0" w:footer="0" w:gutter="0"/>'
        "</w:sectPr>"
    )


def minimal_section_paragraph_xml(section: str) -> str:
    return (
        "<w:p><w:pPr>"
        '<w:spacing w:before="0" w:after="0" w:line="1" w:lineRule="exact"/>'
        f"{section}</w:pPr></w:p>"
    )
