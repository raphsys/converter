"""Transformation de l'IR en word/document.xml.

Chaque page devient une section : taille exacte, marges nulles, un paragraphe vide qui
sert uniquement de point d'ancrage. Tous les éléments sont des formes flottantes
positionnées par rapport à la page, donc hors du flux — rien ne peut refluer.
"""
from pdfexact.geometry import emu_vers_pt, pt_vers_twips
from pdfexact.ir import Document, Page

_ENTETE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    "<w:document "
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'mc:Ignorable="wps">'
    "<w:body>"
)

_PIED = "</w:body></w:document>"


def _section_xml(page: Page) -> str:
    """Section aux dimensions exactes de la page PDF, sans aucune marge."""
    largeur = pt_vers_twips(emu_vers_pt(page.largeur_emu))
    hauteur = pt_vers_twips(emu_vers_pt(page.hauteur_emu))
    return (
        "<w:sectPr>"
        f'<w:pgSz w:w="{largeur}" w:h="{hauteur}"/>'
        '<w:pgMar w:top="0" w:right="0" w:bottom="0" w:left="0" '
        'w:header="0" w:footer="0" w:gutter="0"/>'
        "</w:sectPr>"
    )


def _ancres_de_page(page: Page, compteur: list, relations, media: dict) -> str:
    """Rend tous les éléments de la page, dans l'ordre de superposition.

    Vide pour l'instant : les types d'élément sont branchés par les tâches suivantes.
    """
    return ""


def construire_document_xml(document: Document, relations) -> str:
    """Assemble document.xml. `relations` est un GestionnaireRelations."""
    morceaux = [_ENTETE]
    compteur = [0]

    for position, page in enumerate(document.pages):
        derniere = position == len(document.pages) - 1
        ancres = _ancres_de_page(page, compteur, relations, document.media)
        paragraphe_contenu = f"<w:r>{ancres}</w:r>" if ancres else ""

        if derniere:
            # La section de la dernière page se déclare au niveau du corps, pas dans
            # les propriétés d'un paragraphe. C'est la règle OOXML.
            morceaux.append(f"<w:p>{paragraphe_contenu}</w:p>")
            morceaux.append(_section_xml(page))
        else:
            morceaux.append(
                f"<w:p><w:pPr>{_section_xml(page)}</w:pPr>{paragraphe_contenu}</w:p>"
            )

    if not document.pages:
        morceaux.append("<w:p/>")

    morceaux.append(_PIED)
    return "".join(morceaux)
