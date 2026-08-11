"""Fragments DrawingML.

Chaque élément de page est une forme flottante ancrée en position absolue par rapport à
la page. Marges internes nulles, habillage désactivé, aucun ajustement automatique : rien
ne doit pouvoir décaler quoi que ce soit.
"""
from xml.sax.saxutils import escape

from pdfexact.geometry import emu_vers_pt, pt_vers_twips
from pdfexact.ir import Line

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

    paragraphe = (
        "<w:p><w:pPr>"
        f'<w:spacing w:before="0" w:after="0" w:line="{interligne}" w:lineRule="exact"/>'
        '<w:ind w:left="0" w:right="0" w:firstLine="0"/>'
        '<w:jc w:val="left"/>'
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
        'horzOverflow="overflow" vert="horz" wrap="none" '
        'lIns="0" tIns="0" rIns="0" bIns="0" anchor="t" anchorCtr="0">'
        "<a:noAutofit/></wps:bodyPr>"
        "</wps:wsp></a:graphicData></a:graphic>"
    )

    return _ancre(ligne.bbox, identifiant, z, f"Ligne {identifiant}", contenu)
