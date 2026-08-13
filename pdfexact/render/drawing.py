"""Fragments DrawingML.

Chaque élément de page est une forme flottante ancrée en position absolue par rapport à
la page. Marges internes nulles, habillage désactivé, aucun ajustement automatique : rien
ne doit pouvoir décaler quoi que ce soit.
"""
from xml.sax.saxutils import escape

from pdfexact.geometry import emu_vers_pt, pt_vers_twips
from pdfexact.ir import Line, Span

_GABARIT_ANCRE = (
    '<w:drawing><wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" '
    'relativeHeight="{z}" behindDoc="{derriere}" locked="0" layoutInCell="1" '
    'allowOverlap="1">'
    '<wp:simplePos x="0" y="0"/>'
    '<wp:positionH relativeFrom="page"><wp:posOffset>{x}</wp:posOffset></wp:positionH>'
    '<wp:positionV relativeFrom="page"><wp:posOffset>{y}</wp:posOffset></wp:positionV>'
    '<wp:extent cx="{largeur}" cy="{hauteur}"/>'
    '<wp:effectExtent l="0" t="0" r="0" b="0"/>'
    "<wp:wrapNone/>"
    '<wp:docPr id="{identifiant}" name="{nom}"/>'
    "{contenu}"
    "</wp:anchor></w:drawing>"
)


def _ancre(bbox, identifiant: int, z: int, nom: str, contenu: str, derriere: bool = False) -> str:
    return _GABARIT_ANCRE.format(
        z=z,
        derriere=1 if derriere else 0,
        x=max(bbox.x0, 0),
        y=max(bbox.y0, 0),
        largeur=max(bbox.largeur, 1),
        hauteur=max(bbox.hauteur, 1),
        identifiant=identifiant,
        nom=nom,
        contenu=contenu,
    )


def _run_xml(span, relations=None) -> str:
    """Un run avec sa police, son corps, sa couleur et sa correction d'espacement."""
    famille = escape(span.police.famille)
    proprietes = [
        f'<w:rFonts w:ascii="{famille}" w:hAnsi="{famille}" w:cs="{famille}"/>'
    ]
    if span.police.gras:
        proprietes.append("<w:b/>")
    if span.police.italique:
        proprietes.append("<w:i/>")
    if getattr(span, "invisible", False):
        proprietes.append("<w:vanish/>")
    proprietes.append(f'<w:color w:val="{span.couleur}"/>')
    demi_points = max(round(span.size_pt * 2), 1)
    proprietes.append(f'<w:sz w:val="{demi_points}"/>')
    proprietes.append(f'<w:szCs w:val="{demi_points}"/>')
    if span.espacement_twips:
        proprietes.append(f'<w:spacing w:val="{span.espacement_twips}"/>')

    run = (
        f'<w:r><w:rPr>{"".join(proprietes)}</w:rPr>'
        f'<w:t xml:space="preserve">{escape(span.texte)}</w:t></w:r>'
    )

    if span.lien and relations is not None:
        rel_id = relations.ajouter(span.lien, "hyperlink", externe=True)
        return f'<w:hyperlink r:id="{rel_id}">{run}</w:hyperlink>'
    return run


def zone_texte_xml(ligne: Line, identifiant: int, z: int, relations=None) -> str:
    """Rend une ligne de texte comme forme flottante contenant une zone de texte.

    Une zone par ligne, et non par bloc : dès qu'une zone contient plusieurs lignes, c'est
    Word qui calcule les retours à la ligne et l'interligne, avec ses propres métriques.
    L'écart s'accumule et le bas du bloc dérive. Une ligne par zone supprime ce calcul.

    `lineRule="exact"` fixe la hauteur de ligne : sans lui, Word applique son interligne
    et tout le contenu descend.
    """
    interligne = max(pt_vers_twips(emu_vers_pt(ligne.hauteur_ligne_emu)), 1)
    runs = "".join(_run_xml(span, relations) for span in ligne.spans)
    alignement = getattr(ligne, "alignement", "left") or "left"

    paragraphe = (
        "<w:p><w:pPr>"
        f'<w:spacing w:before="0" w:after="0" w:line="{interligne}" w:lineRule="exact"/>'
        '<w:ind w:left="0" w:right="0" w:firstLine="0"/>'
        f'<w:jc w:val="{alignement}"/>'
        "</w:pPr>"
        f"{runs}</w:p>"
    )

    contenu = (
        "<a:graphic><a:graphicData "
        'uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        '<wps:wsp><wps:cNvSpPr txBox="1"/>'
        "<wps:spPr>"
        '<a:xfrm><a:off x="0" y="0"/>'
        f'<a:ext cx="{max(ligne.bbox.largeur, 1)}" cy="{max(ligne.bbox.hauteur, 1)}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "<a:noFill/><a:ln><a:noFill/></a:ln>"
        "</wps:spPr>"
        f"<wps:txbx><w:txbxContent>{paragraphe}</w:txbxContent></wps:txbx>"
        '<wps:bodyPr rot="0" spcFirstLastPara="0" vertOverflow="overflow" '
        'horzOverflow="clip" vert="horz" wrap="none" '
        'lIns="0" tIns="0" rIns="0" bIns="0" anchor="t" anchorCtr="0">'
        "<a:noAutofit/></wps:bodyPr>"
        "</wps:wsp></a:graphicData></a:graphic>"
    )

    return _ancre(ligne.bbox, identifiant, z, f"Ligne {identifiant}", contenu)


def image_xml(element, identifiant: int, z: int, rel_id: str, derriere: bool = False) -> str:
    """Rend une image, ou une région rastérisée, comme image flottante ancrée."""
    largeur = max(element.bbox.largeur, 1)
    hauteur = max(element.bbox.hauteur, 1)

    contenu = (
        "<a:graphic><a:graphicData "
        'uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        "<pic:pic>"
        f'<pic:nvPicPr><pic:cNvPr id="{identifiant}" name="{element.media_ref}"/>'
        "<pic:cNvPicPr/></pic:nvPicPr>"
        f'<pic:blipFill><a:blip r:embed="{rel_id}"/>'
        "<a:stretch><a:fillRect/></a:stretch></pic:blipFill>"
        '<pic:spPr><a:xfrm><a:off x="0" y="0"/>'
        f'<a:ext cx="{largeur}" cy="{hauteur}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        "</pic:pic></a:graphicData></a:graphic>"
    )

    return _ancre(element.bbox, identifiant, z, f"Image {identifiant}", contenu, derriere)


def table_xml(element, identifiant: int, z: int, relations=None) -> str:
    """Rend un tableau PDF détecté en vrai tableau Word, ancré à la page."""
    largeur = max(element.bbox.largeur, 1)
    hauteur = max(element.bbox.hauteur, 1)
    grid = "".join(
        f'<w:gridCol w:w="{max(pt_vers_twips(emu_vers_pt(w)), 1)}"/>'
        for w in element.col_widths_emu
    )
    rows_xml = []
    for row in element.rows:
        tr_height = max(pt_vers_twips(emu_vers_pt(row.bbox.hauteur)), 1)
        cells_xml = []
        for cell in row.cells:
            tc_width = max(pt_vers_twips(emu_vers_pt(cell.bbox.largeur)), 1)
            grid_span = (
                f'<w:gridSpan w:val="{cell.col_span}"/>'
                if cell.col_span > 1
                else ""
            )
            shading = f'<w:shd w:fill="{cell.fond}"/>' if cell.fond else ""
            span = Span(
                texte=cell.texte,
                police=element.police,
                size_pt=element.size_pt,
                couleur=element.couleur,
            )
            cells_xml.append(
                "<w:tc>"
                "<w:tcPr>"
                f'<w:tcW w:w="{tc_width}" w:type="dxa"/>'
                f"{grid_span}{shading}"
                '<w:tcMar><w:top w:w="15" w:type="dxa"/><w:left w:w="25" w:type="dxa"/>'
                '<w:bottom w:w="15" w:type="dxa"/><w:right w:w="25" w:type="dxa"/></w:tcMar>'
                "</w:tcPr>"
                '<w:p><w:pPr><w:spacing w:before="0" w:after="0"/>'
                '<w:jc w:val="center"/></w:pPr>'
                f"{_run_xml(span, relations)}</w:p>"
                "</w:tc>"
            )
        rows_xml.append(
            "<w:tr>"
            f'<w:trPr><w:trHeight w:val="{tr_height}" w:hRule="atLeast"/></w:trPr>'
            f"{''.join(cells_xml)}</w:tr>"
        )

    tbl = (
        "<w:tbl>"
        "<w:tblPr>"
        f'<w:tblW w:w="{max(pt_vers_twips(emu_vers_pt(largeur)), 1)}" w:type="dxa"/>'
        '<w:tblLayout w:type="fixed"/>'
        '<w:tblBorders>'
        '<w:top w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:left w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '</w:tblBorders>'
        "</w:tblPr>"
        f"<w:tblGrid>{grid}</w:tblGrid>"
        f"{''.join(rows_xml)}"
        "</w:tbl>"
    )

    contenu = (
        "<a:graphic><a:graphicData "
        'uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        '<wps:wsp><wps:cNvSpPr txBox="1"/>'
        "<wps:spPr>"
        '<a:xfrm><a:off x="0" y="0"/>'
        f'<a:ext cx="{largeur}" cy="{hauteur}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "<a:noFill/><a:ln><a:noFill/></a:ln>"
        "</wps:spPr>"
        f"<wps:txbx><w:txbxContent>{tbl}</w:txbxContent></wps:txbx>"
        '<wps:bodyPr rot="0" spcFirstLastPara="0" vertOverflow="clip" '
        'horzOverflow="clip" vert="horz" wrap="none" '
        'lIns="0" tIns="0" rIns="0" bIns="0" anchor="t" anchorCtr="0">'
        "<a:noAutofit/></wps:bodyPr>"
        "</wps:wsp></a:graphicData></a:graphic>"
    )

    return _ancre(element.bbox, identifiant, z, f"Tableau {identifiant}", contenu)


def _commandes_xml(chemins, origine_x: int, origine_y: int) -> str:
    """Traduit les chemins en éléments de a:path, en coordonnées relatives à la bbox."""
    morceaux = []
    for chemin in chemins:
        for operateur, points in chemin:
            relatifs = [(x - origine_x, y - origine_y) for x, y in points]
            balises = "".join(f'<a:pt x="{x}" y="{y}"/>' for x, y in relatifs)

            if operateur == "move":
                morceaux.append(f"<a:moveTo>{balises}</a:moveTo>")
            elif operateur == "line":
                morceaux.append(f"<a:lnTo>{balises}</a:lnTo>")
            elif operateur == "cubic":
                morceaux.append(f"<a:cubicBezTo>{balises}</a:cubicBezTo>")
            elif operateur == "quad":
                morceaux.append(f"<a:quadBezTo>{balises}</a:quadBezTo>")
            elif operateur == "close":
                morceaux.append("<a:close/>")
    return "".join(morceaux)


def forme_xml(element, identifiant: int, z: int, derriere: bool = False) -> str:
    """Rend une forme vectorielle en géométrie personnalisée DrawingML."""
    largeur = max(element.bbox.largeur, 1)
    hauteur = max(element.bbox.hauteur, 1)

    if element.remplissage:
        alpha = ""
        if element.alpha < 1.0:
            alpha = f'<a:alpha val="{max(0, round(element.alpha * 100000))}"/>'
        remplissage = (
            f'<a:solidFill><a:srgbClr val="{element.remplissage}">{alpha}</a:srgbClr>'
            "</a:solidFill>"
        )
    else:
        remplissage = "<a:noFill/>"

    if element.contour and element.epaisseur_emu > 0:
        pointilles = f'<a:prstDash val="{element.pointilles}"/>' if element.pointilles else ""
        trait = (
            f'<a:ln w="{element.epaisseur_emu}">'
            f'<a:solidFill><a:srgbClr val="{element.contour}"/></a:solidFill>'
            f"{pointilles}</a:ln>"
        )
    else:
        trait = "<a:ln><a:noFill/></a:ln>"

    commandes = _commandes_xml(element.chemins, element.bbox.x0, element.bbox.y0)

    contenu = (
        "<a:graphic><a:graphicData "
        'uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        "<wps:wsp><wps:cNvSpPr/>"
        "<wps:spPr>"
        f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{largeur}" cy="{hauteur}"/></a:xfrm>'
        "<a:custGeom><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/>"
        f'<a:rect l="0" t="0" r="{largeur}" b="{hauteur}"/>'
        f'<a:pathLst><a:path w="{largeur}" h="{hauteur}">{commandes}</a:path></a:pathLst>'
        "</a:custGeom>"
        f"{remplissage}{trait}"
        "</wps:spPr>"
        '<wps:bodyPr rot="0" anchor="t"/>'
        "</wps:wsp></a:graphicData></a:graphic>"
    )

    return _ancre(element.bbox, identifiant, z, f"Forme {identifiant}", contenu, derriere)


def zone_lien_xml(element, identifiant: int, z: int, rel_id: str) -> str:
    """Rend un lien de zone comme rectangle invisible cliquable."""
    largeur = max(element.bbox.largeur, 1)
    hauteur = max(element.bbox.hauteur, 1)

    contenu = (
        "<a:graphic><a:graphicData "
        'uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        "<wps:wsp><wps:cNvSpPr/><wps:spPr>"
        f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{largeur}" cy="{hauteur}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "<a:noFill/><a:ln><a:noFill/></a:ln>"
        f'<a:hlinkClick r:id="{rel_id}"/>'
        "</wps:spPr><wps:bodyPr/></wps:wsp></a:graphicData></a:graphic>"
    )

    return _ancre(element.bbox, identifiant, z, f"Lien {identifiant}", contenu)
