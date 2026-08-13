"""Transformation de l'IR en word/document.xml.

Chaque page devient une section : taille exacte, marges nulles, un paragraphe vide qui
sert uniquement de point d'ancrage. Tous les éléments sont des formes flottantes
positionnées par rapport à la page, donc hors du flux — rien ne peut refluer.
"""
from xml.sax.saxutils import escape

from pdfexact.geometry import emu_vers_pt, pt_vers_emu, pt_vers_twips
from pdfexact.ir import (
    Document,
    FlowParagraph,
    ImageEl,
    LinkZone,
    Page,
    RasterEl,
    ShapeEl,
    TableEl,
    Span,
    TextBox,
)
from pdfexact.render.drawing import (
    _run_xml,
    forme_xml,
    image_xml,
    table_xml,
    zone_lien_xml,
    zone_texte_xml,
)

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
    orientation = ' w:orient="landscape"' if page.largeur_emu > page.hauteur_emu else ""
    return (
        "<w:sectPr>"
        f'<w:pgSz w:w="{largeur}" w:h="{hauteur}"{orientation}/>'
        '<w:pgMar w:top="0" w:right="0" w:bottom="0" w:left="0" '
        'w:header="0" w:footer="0" w:gutter="0"/>'
        "</w:sectPr>"
    )


def _section_flux_xml(page: Page) -> str:
    """Section Word éditable : mêmes dimensions page, marges utilisables."""
    largeur = pt_vers_twips(emu_vers_pt(page.largeur_emu))
    hauteur = pt_vers_twips(emu_vers_pt(page.hauteur_emu))
    orientation = ' w:orient="landscape"' if page.largeur_emu > page.hauteur_emu else ""
    marge_h = pt_vers_twips(42)
    marge_v = pt_vers_twips(36)
    return (
        "<w:sectPr>"
        f'<w:pgSz w:w="{largeur}" w:h="{hauteur}"{orientation}/>'
        f'<w:pgMar w:top="{marge_v}" w:right="{marge_h}" '
        f'w:bottom="{marge_v}" w:left="{marge_h}" '
        'w:header="0" w:footer="0" w:gutter="0"/>'
        "</w:sectPr>"
    )


def _ancres_de_page(page: Page, compteur: list, relations, media: dict) -> str:
    """Rend tous les éléments de la page, dans l'ordre de superposition.

    `relativeHeight` croît avec l'ordre du flux de contenu PDF, ce qui reproduit les
    recouvrements de l'original.
    """
    morceaux = []
    for z, element in enumerate(page.elements, start=1):
        compteur[0] += 1

        if isinstance(element, TextBox):
            for ligne in element.lignes:
                morceaux.append(zone_texte_xml(ligne, compteur[0], z, relations))
                compteur[0] += 1

        elif isinstance(element, (ImageEl, RasterEl)):
            item = media[element.media_ref]
            rel_id = relations.ajouter(
                f"media/{item.media_ref}.{item.extension}", "image"
            )
            morceaux.append(image_xml(element, compteur[0], z, rel_id))

        elif isinstance(element, ShapeEl):
            morceaux.append(forme_xml(element, compteur[0], z))

        elif isinstance(element, TableEl):
            morceaux.append(table_xml(element, compteur[0], z, relations))

        elif isinstance(element, LinkZone) and element.uri:
            rel_id = relations.ajouter(element.uri, "hyperlink", externe=True)
            morceaux.append(zone_lien_xml(element, compteur[0], z, rel_id))

    return "".join(morceaux)


def _paragraphe_flux_xml(paragraphe: FlowParagraph, relations, sect_pr: str = "") -> str:
    """Rend un paragraphe Word réel, pas une forme flottante."""
    espace_avant = max(pt_vers_twips(emu_vers_pt(paragraphe.espace_avant_emu)), 0)
    espace_apres = max(pt_vers_twips(emu_vers_pt(paragraphe.espace_apres_emu)), 0)
    if paragraphe.alignement == "center" and len(paragraphe.texte) <= 120:
        espace_avant = min(espace_avant, 80)
        espace_apres = min(espace_apres, 20)
    else:
        espace_avant = min(espace_avant, 120)
        espace_apres = min(espace_apres, 10)
    interligne = max(pt_vers_twips(emu_vers_pt(paragraphe.interligne_emu)), 1)
    gauche = 0
    droite = 0
    premiere = pt_vers_twips(emu_vers_pt(paragraphe.retrait_premiere_ligne_emu))
    police = paragraphe.police
    familles = {
        "Nimbus Roman": "Times New Roman",
        "Times-Roman": "Times New Roman",
        "Times": "Times New Roman",
        "Nimbus Sans": "Arial",
        "Helvetica": "Arial",
        "Nimbus Mono PS": "Courier New",
        "Courier": "Courier New",
        "URW Gothic": "Arial",
        "AvantGarde": "Arial",
        "URW Bookman": "Bookman Old Style",
        "Bookman": "Bookman Old Style",
    }
    famille = familles.get(police.famille, police.famille)
    police = type(police)(famille, famille, police.gras, police.italique)
    size_pt = paragraphe.size_pt
    if paragraphe.alignement == "center" and len(paragraphe.texte) <= 90:
        size_pt = min(max(size_pt, 9.5), 12.0)
    else:
        size_pt = min(max(size_pt, 8.8), 10.6)
    span = Span(
        texte=paragraphe.texte,
        police=police,
        size_pt=size_pt,
        couleur=paragraphe.couleur,
    )
    ppr = (
        "<w:pPr>"
        f'<w:spacing w:before="{espace_avant}" w:after="{espace_apres}" '
        f'w:line="{max(180, min(interligne, 230))}" w:lineRule="auto"/>'
        f'<w:ind w:left="{gauche}" w:right="{droite}" w:firstLine="{premiere}"/>'
        f'<w:jc w:val="{paragraphe.alignement}"/>'
        f"{sect_pr}</w:pPr>"
    )
    return f"<w:p>{ppr}{_run_xml(span, relations)}</w:p>"


def _image_inline_xml(element, compteur: list, relations, media: dict, largeur_max_emu: int) -> str:
    item = media[element.media_ref]
    rel_id = relations.ajouter(f"media/{item.media_ref}.{item.extension}", "image")
    largeur = max(element.bbox.largeur, 1)
    hauteur = max(element.bbox.hauteur, 1)
    if largeur > largeur_max_emu:
        ratio = largeur_max_emu / largeur
        largeur = largeur_max_emu
        hauteur = max(1, int(hauteur * ratio))
    hauteur_max = pt_vers_emu(220)
    if hauteur > hauteur_max:
        ratio = hauteur_max / hauteur
        hauteur = hauteur_max
        largeur = max(1, int(largeur * ratio))
    compteur[0] += 1
    contenu = (
        '<w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{largeur}" cy="{hauteur}"/>'
        '<wp:effectExtent l="0" t="0" r="0" b="0"/>'
        f'<wp:docPr id="{compteur[0]}" name="{escape(item.media_ref)}"/>'
        '<a:graphic><a:graphicData '
        'uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic>'
        f'<pic:nvPicPr><pic:cNvPr id="{compteur[0]}" name="{escape(item.media_ref)}"/>'
        '<pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip r:embed="{rel_id}"/>'
        '<a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        '<pic:spPr><a:xfrm><a:off x="0" y="0"/>'
        f'<a:ext cx="{largeur}" cy="{hauteur}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        '</pic:pic></a:graphicData></a:graphic>'
        '</wp:inline></w:drawing>'
    )
    return (
        '<w:p><w:pPr><w:spacing w:before="30" w:after="30"/>'
        '<w:jc w:val="center"/></w:pPr>'
        f'<w:r>{contenu}</w:r></w:p>'
    )


def _ancres_xml(elements, compteur: list, relations, media: dict) -> str:
    morceaux = []
    for z, element in enumerate(elements, start=1):
        compteur[0] += 1

        if isinstance(element, TextBox):
            for ligne in element.lignes:
                morceaux.append(zone_texte_xml(ligne, compteur[0], z, relations))
                compteur[0] += 1

        elif isinstance(element, (ImageEl, RasterEl)):
            item = media[element.media_ref]
            rel_id = relations.ajouter(
                f"media/{item.media_ref}.{item.extension}", "image"
            )
            morceaux.append(image_xml(element, compteur[0], z, rel_id))

        elif isinstance(element, ShapeEl):
            morceaux.append(forme_xml(element, compteur[0], z))

        elif isinstance(element, TableEl):
            morceaux.append(table_xml(element, compteur[0], z, relations))

        elif isinstance(element, LinkZone) and element.uri:
            rel_id = relations.ajouter(element.uri, "hyperlink", externe=True)
            morceaux.append(zone_lien_xml(element, compteur[0], z, rel_id))

    return "".join(morceaux)


def _page_flux_xml(page: Page, derniere: bool, compteur: list, relations, media: dict) -> str:
    morceaux = []
    elements = page.elements
    section = "" if derniere else _section_flux_xml(page)
    largeur_max_image = page.largeur_emu - pt_vers_emu(120)

    for element in elements:
        if isinstance(element, FlowParagraph):
            morceaux.append(_paragraphe_flux_xml(element, relations))
        elif isinstance(element, (ImageEl, RasterEl)):
            morceaux.append(_image_inline_xml(element, compteur, relations, media, largeur_max_image))
        else:
            continue

    if section:
        morceaux.append(f"<w:p><w:pPr>{section}</w:pPr></w:p>")
    return "".join(morceaux)


def construire_document_xml(document: Document, relations) -> str:
    """Assemble document.xml. `relations` est un GestionnaireRelations."""
    morceaux = [_ENTETE]
    compteur = [0]

    for position, page in enumerate(document.pages):
        derniere = position == len(document.pages) - 1
        if any(isinstance(element, FlowParagraph) for element in page.elements):
            morceaux.append(
                _page_flux_xml(page, derniere, compteur, relations, document.media)
            )
            if derniere:
                morceaux.append(_section_flux_xml(page))
            continue

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
