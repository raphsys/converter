"""Transformation de l'IR en word/document.xml."""
import re
from dataclasses import replace
from io import BytesIO
from xml.sax.saxutils import escape

from PIL import Image

from pdfexact.geometry import BBox, emu_vers_pt, pt_vers_emu, pt_vers_twips, quantifier_bbox, se_chevauchent, union
from pdfexact.analysis.geometry import bbox_area, intersection_area, intersection_over_min_area
from pdfexact.ir import (
    Document,
    FlowParagraph,
    ImageEl,
    Line,
    LinkZone,
    Page,
    RasterEl,
    ShapeEl,
    TableEl,
    Span,
    TextBox,
)
from pdfexact.layout.text_comprehension import comprendre_ligne_texte
from pdfexact.render.drawing import (
    _run_xml,
    forme_xml,
    image_xml,
    table_body_xml,
    table_cell_background_overlays_xml,
    table_grid_overlays_xml,
    table_text_overlays_xml,
    table_xml,
    zone_lien_xml,
    zone_paragraphe_xml,
    zone_texte_xml,
)
from pdfexact.render.section_layout import minimal_section_paragraph_xml, section_xml

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
_MARGE_FLUX_H_PT = 42
_MARGE_FLUX_V_PT = 36
_ECHELLE_GRILLE_MIN = 0.86
_LEADER_RE = re.compile(
    r"^(?P<label>.+?)\s*(?P<leader>(?:[-._]\s*){6,})\s*(?P<page>-?\d{1,4}|[ivxlcdm]{1,8})\s*$",
    re.IGNORECASE,
)
_ITEM_LISTE_RE = re.compile(r"^\s*(?:\d{1,3}|[A-Za-z])[\.)]\s+\S")
_MOT_PROSE_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’-]*")


def _tableau_dense_exact(element: TableEl, page: Page) -> bool:
    cellules = sum(len(row.cells) for row in element.rows)
    return (
        page.largeur_emu > page.hauteur_emu
        or element.bbox.largeur >= page.largeur_emu * 0.60
        or element.bbox.hauteur >= page.hauteur_emu * 0.18
        or cellules >= 120
    )


def _bbox_dans_table_dense(bbox, tables: list[TableEl]) -> bool:
    cx = (bbox.x0 + bbox.x1) // 2
    cy = (bbox.y0 + bbox.y1) // 2
    return any(table.bbox.x0 <= cx <= table.bbox.x1 and table.bbox.y0 <= cy <= table.bbox.y1 for table in tables)


def _section_xml(page: Page) -> str:
    """Section aux dimensions exactes de la page PDF, sans aucune marge."""
    return section_xml(page)


def _section_flux_xml(page: Page) -> str:
    """Section Word éditable : mêmes dimensions page, marges utilisables."""
    return section_xml(page)


def _paragraphe_section_minimal_xml(section: str) -> str:
    return minimal_section_paragraph_xml(section)


def _elements_avec_ombres_derriere(elements: list, media: dict) -> list:
    """Replace les masques/ombres gris derrière les rasters colorés qu'ils accompagnent."""
    if not elements:
        return elements

    couleurs_cache: dict[str, tuple[bool, bool]] = {}

    def profil(element) -> tuple[bool, bool]:
        if not isinstance(element, (ImageEl, RasterEl)):
            return False, False
        if element.media_ref not in couleurs_cache:
            couleurs_cache[element.media_ref] = _profil_image_media(media.get(element.media_ref))
        return couleurs_cache[element.media_ref]

    ombres: dict[int, float] = {}
    for index, element in enumerate(elements):
        est_gris, est_colore = profil(element)
        if not est_gris or est_colore:
            continue
        meilleur_index: int | None = None
        meilleur_recouvrement = 0.0
        for autre_index, autre in enumerate(elements):
            if autre is element or not isinstance(autre, (ImageEl, RasterEl)):
                continue
            autre_gris, autre_colore = profil(autre)
            if autre_gris or not autre_colore:
                continue
            recouvrement = _recouvrement_min_bbox(element.bbox, autre.bbox)
            if recouvrement > meilleur_recouvrement:
                meilleur_index = autre_index
                meilleur_recouvrement = recouvrement
        if meilleur_index is not None and meilleur_recouvrement >= 0.55 and index > meilleur_index:
            ombres[index] = meilleur_index - 0.1

    if not ombres:
        return elements
    return [
        element
        for _cle, element in sorted(
            ((ombres.get(index, float(index)), element) for index, element in enumerate(elements)),
            key=lambda item: item[0],
        )
    ]


def _ordonner_bandeaux_sur_images(elements: list, page: Page) -> list:
    """Remet les bandeaux vectoriels au-dessus des images qu'ils encadrent.

    Les extracteurs PDF livrent souvent les formes et les images dans des listes
    distinctes. Un bandeau noir ou colore peut donc etre emis avant sa photo et
    disparaitre sous elle. Cette regle reste geometrique et generique : elle ne
    depend ni du document ni d'un libelle particulier.
    """
    images = [
        element
        for element in elements
        if isinstance(element, (ImageEl, RasterEl))
    ]
    if not images:
        return elements
    bandeaux = []
    autres = []
    for element in elements:
        est_bandeau = _est_bandeau_sur_image(element, images, page)
        if est_bandeau:
            bandeaux.append(element)
        else:
            autres.append(element)
    return autres + bandeaux if bandeaux else elements


def _est_bandeau_sur_image(element, images: list, page: Page) -> bool:
    return (
        isinstance(element, ShapeEl)
        and bool(element.remplissage)
        and element.bbox.largeur >= page.largeur_emu * 0.60
        and element.bbox.hauteur <= page.hauteur_emu * 0.10
        and any(_recouvrement_min_bbox(element.bbox, image.bbox) >= 0.12 for image in images)
    )


def _profil_image_media(media_item) -> tuple[bool, bool]:
    if media_item is None or media_item.extension.lower() not in {"png", "jpg", "jpeg"}:
        return False, False
    try:
        image = Image.open(BytesIO(media_item.donnees)).convert("RGB")
        image.thumbnail((80, 80))
    except Exception:  # noqa: BLE001
        return False, False

    pixels = list(image.getdata())
    if not pixels:
        return False, False
    gris = 0
    colores = 0
    sombres_colores = 0
    for r, g, b in pixels:
        ecart = max(r, g, b) - min(r, g, b)
        luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
        if ecart <= 18:
            gris += 1
        if ecart >= 35:
            colores += 1
            if luminance <= 230:
                sombres_colores += 1
    total = len(pixels)
    est_gris = gris / total >= 0.82
    est_colore = colores / total >= 0.18 or sombres_colores / total >= 0.08
    return est_gris, est_colore


def _recouvrement_min_bbox(a: BBox, b: BBox) -> float:
    return intersection_over_min_area(a, b)


def _table_recouvre_texte_positionne(table: TableEl, elements) -> bool:
    touches = 0
    for element in elements:
        if isinstance(element, TextBox):
            lignes = element.lignes
        elif isinstance(element, FlowParagraph):
            lignes = element.lignes or [_ligne_depuis_paragraphe(element)]
        else:
            continue
        for ligne in lignes:
            if _intersection_bbox(ligne.bbox, table.bbox) / max(_aire_bbox(ligne.bbox), 1) < 0.35:
                continue
            touches += 1
            if touches >= 2:
                return True
    return False


def _table_fond_grille_xml(table: TableEl, compteur: list, z: int) -> str:
    return table_cell_background_overlays_xml(table, compteur, z) + table_grid_overlays_xml(table, compteur, z + 1)


def _ancres_source(page: Page, compteur: list, relations, media: dict, polices: dict | None = None) -> str:
    # Local import: bbox_debug also uses the compatibility package writer.
    from pdfexact.render.bbox_debug import (
        _layered_native_paragraph_xml,
        _paint_z,
        _source_paint_index,
        _text_paint_fragments,
    )

    visuals = [element for element in page.elements if isinstance(element, (ImageEl, RasterEl, ShapeEl))]
    fragments = [
        fragment
        for element in page.elements
        for fragment in (
            _text_paint_fragments(element, visuals)
            if isinstance(element, (TextBox, FlowParagraph)) else [element]
        )
    ]
    last = max((_source_paint_index(element) for element in fragments if _source_paint_index(element) is not None), default=0)
    ordered = sorted(enumerate(fragments), key=lambda item: _paint_z(item[1], 100 + 10 * (last + item[0] + 1)))
    morceaux = []
    for index, element in ordered:
        compteur[0] += 1
        z = _paint_z(element, 100 + 10 * (last + index + 1))
        if isinstance(element, (TextBox, FlowParagraph)):
            morceaux.append(_layered_native_paragraph_xml(element, compteur[0], z, polices=polices))
        elif isinstance(element, (ImageEl, RasterEl)):
            item = media[element.media_ref]
            rel_id = relations.ajouter(f"media/{item.media_ref}.{item.extension}", "image")
            morceaux.append(image_xml(element, compteur[0], z, rel_id, derriere=False))
        elif isinstance(element, ShapeEl):
            morceaux.append(forme_xml(element, compteur[0], z))
        elif isinstance(element, TableEl):
            morceaux.append(table_xml(element, compteur[0], z, relations))
        elif isinstance(element, LinkZone) and element.uri:
            rel_id = relations.ajouter(element.uri, "hyperlink", externe=True)
            morceaux.append(zone_lien_xml(element, compteur[0], z, rel_id))
    return "".join(morceaux)


def _ancres_de_page(page: Page, compteur: list, relations, media: dict, polices: dict | None = None) -> str:
    """Rend tous les éléments de la page, dans l'ordre de superposition.

    `relativeHeight` croît avec l'ordre du flux de contenu PDF, ce qui reproduit les
    recouvrements de l'original.
    """
    if any(getattr(element, "z_index", None) is not None for element in page.elements):
        return _ancres_source(page, compteur, relations, media, polices)
    morceaux = []
    zones_texte = [
        element.bbox
        for element in page.elements
        if isinstance(element, (FlowParagraph, TextBox))
    ]
    elements_page = _ordonner_bandeaux_sur_images(
        _elements_avec_ombres_derriere(page.elements, media),
        page,
    )
    for z, element in enumerate(elements_page, start=1):
        compteur[0] += 1

        if isinstance(element, TextBox):
            for ligne in element.lignes:
                morceaux.append(zone_texte_xml(ligne, compteur[0], z, relations, page.largeur_emu, polices))
                compteur[0] += 1

        elif isinstance(element, (ImageEl, RasterEl)):
            item = media[element.media_ref]
            rel_id = relations.ajouter(
                f"media/{item.media_ref}.{item.extension}", "image"
            )
            derriere = (
                False
                if getattr(element, "purpose", None) in {"formula", "symbol"}
                else any(se_chevauchent(element.bbox, zone) for zone in zones_texte)
            )
            morceaux.append(image_xml(element, compteur[0], z, rel_id, derriere=derriere))

        elif isinstance(element, ShapeEl):
            if _forme_fond_blanc_page(element, page):
                continue
            morceaux.append(forme_xml(element, compteur[0], z))

        elif isinstance(element, TableEl):
            if _table_recouvre_texte_positionne(element, elements_page):
                morceaux.append(_table_fond_grille_xml(element, compteur, z))
            else:
                morceaux.append(table_xml(element, compteur[0], z, relations))

        elif isinstance(element, LinkZone) and element.uri:
            rel_id = relations.ajouter(element.uri, "hyperlink", externe=True)
            morceaux.append(zone_lien_xml(element, compteur[0], z, rel_id))

    return "".join(morceaux)


def _aire_bbox(bbox) -> int:
    return bbox_area(bbox)


def _intersection_bbox(a, b) -> int:
    return intersection_area(a, b)


def _fond_pour_paragraphe(paragraphe: FlowParagraph, fonds: list[ShapeEl]) -> str | None:
    """Associe un aplat PDF au paragraphe Word qui le porte."""
    aire_paragraphe = max(_aire_bbox(paragraphe.bbox), 1)
    for fond in fonds:
        if not fond.remplissage:
            continue
        intersection = _intersection_bbox(paragraphe.bbox, fond.bbox)
        if intersection / aire_paragraphe >= 0.18:
            return fond.remplissage

        hauteur = max(paragraphe.bbox.hauteur, 1)
        boite_elargie = type(paragraphe.bbox)(
            paragraphe.bbox.x0,
            paragraphe.bbox.y0 - hauteur,
            paragraphe.bbox.x1,
            paragraphe.bbox.y1 + hauteur,
        )
        if _intersection_bbox(boite_elargie, fond.bbox) / max(_aire_bbox(fond.bbox), 1) >= 0.35:
            return fond.remplissage
    return None


def _couleur_sombre(couleur: str | None) -> bool:
    if not couleur or len(couleur) != 6:
        return False
    try:
        r = int(couleur[0:2], 16)
        g = int(couleur[2:4], 16)
        b = int(couleur[4:6], 16)
    except ValueError:
        return False
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) < 96


def _couleur_claire(couleur: str | None) -> bool:
    if not couleur or len(couleur) != 6:
        return False
    try:
        r = int(couleur[0:2], 16)
        g = int(couleur[2:4], 16)
        b = int(couleur[4:6], 16)
    except ValueError:
        return False
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) >= 245


def _forme_fond_blanc_page(element: ShapeEl, page: Page) -> bool:
    if element.z_index is not None:
        return False
    if not element.remplissage or not _couleur_claire(element.remplissage):
        return False
    aire_page = max(page.largeur_emu * page.hauteur_emu, 1)
    if _aire_bbox(element.bbox) / aire_page < 0.70:
        return False
    marge = pt_vers_emu(42)
    return (
        element.bbox.x0 <= marge
        and element.bbox.y0 <= marge
        and element.bbox.x1 >= page.largeur_emu - marge
        and element.bbox.y1 >= page.hauteur_emu - marge
    )


def _copier_span(span: Span, *, size_pt: float, espacement_twips: int) -> Span:
    return Span(
        texte=span.texte,
        police=span.police,
        size_pt=size_pt,
        couleur=span.couleur,
        espacement_twips=espacement_twips,
        lien=span.lien,
        invisible=span.invisible,
        souligne=span.souligne,
        barre=span.barre,
        capitales=span.capitales,
        exposant=span.exposant,
        indice=span.indice,
        surlignage=span.surlignage,
        bbox=span.bbox,
    )


def _span_reflow(span: Span) -> Span:
    texte = re.sub(r"[ \u00a0\u2000-\u200a\u202f]+", " ", span.texte or "").strip()
    return Span(
        texte=texte,
        police=span.police,
        size_pt=span.size_pt,
        couleur=span.couleur,
        espacement_twips=span.espacement_twips,
        lien=span.lien,
        invisible=span.invisible,
        souligne=span.souligne,
        barre=span.barre,
        capitales=span.capitales,
        exposant=span.exposant,
        indice=span.indice,
        surlignage=span.surlignage,
        bbox=span.bbox,
    )


def _span_avec_texte(span: Span, texte: str) -> Span:
    return Span(
        texte=texte,
        police=span.police,
        size_pt=span.size_pt,
        couleur=span.couleur,
        espacement_twips=span.espacement_twips,
        lien=span.lien,
        invisible=span.invisible,
        souligne=span.souligne,
        barre=span.barre,
        capitales=span.capitales,
        exposant=span.exposant,
        indice=span.indice,
        surlignage=span.surlignage,
        bbox=span.bbox,
    )


def _spans_sans_bords_vides(spans: list[Span]) -> list[Span]:
    if not spans or any("\t" in span.texte or "\n" in span.texte for span in spans):
        return spans

    nettoyes = list(spans)
    premier = next((i for i, span in enumerate(nettoyes) if span.texte), None)
    dernier = next((i for i in range(len(nettoyes) - 1, -1, -1) if nettoyes[i].texte), None)
    if premier is None or dernier is None:
        return spans

    change = False
    texte_premier = re.sub(r"^[ \u00a0\u2000-\u200a\u202f]+", "", nettoyes[premier].texte)
    texte_dernier = re.sub(r"[ \u00a0\u2000-\u200a\u202f]+$", "", nettoyes[dernier].texte)
    if texte_premier != nettoyes[premier].texte:
        nettoyes[premier] = _span_avec_texte(nettoyes[premier], texte_premier)
        change = True
    if dernier == premier:
        texte_dernier = re.sub(r"[ \u00a0\u2000-\u200a\u202f]+$", "", nettoyes[dernier].texte)
    if texte_dernier != nettoyes[dernier].texte:
        nettoyes[dernier] = _span_avec_texte(nettoyes[dernier], texte_dernier)
        change = True

    return [span for span in nettoyes if span.texte] if change else spans


def _spans_reflow_ligne(spans: list[Span]) -> list[Span]:
    resultat: list[Span] = []
    for span in _spans_sans_bords_vides(spans):
        texte = re.sub(r"[ \u00a0\u2000-\u200a\u202f]+", " ", span.texte or "")
        if not texte:
            continue
        if not resultat:
            texte = texte.lstrip()
        elif resultat[-1].texte.endswith(" ") and texte.startswith(" "):
            texte = texte.lstrip()
        resultat.append(_span_avec_texte(span, texte))
    if resultat:
        dernier = resultat[-1]
        texte = dernier.texte.rstrip()
        if texte != dernier.texte:
            resultat[-1] = _span_avec_texte(dernier, texte)
    return [span for span in resultat if span.texte]


def _ajuster_spans_a_largeur(
    spans: list[Span],
    largeur_cible_emu: int,
    polices: dict | None,
    *,
    compact: bool = False,
) -> list[Span]:
    if not polices or not spans or largeur_cible_emu <= 0:
        return spans
    if any("\t" in span.texte or "\n" in span.texte for span in spans):
        return spans
    texte_ligne = "".join(span.texte for span in spans)
    ligne_mots_lisible = re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]{2,}\s+[A-Za-zÀ-ÖØ-öø-ÿ]{2,}", texte_ligne)

    try:
        from pdfexact.extract.fonts import mesurer_largeur_pt
    except Exception:  # noqa: BLE001
        return spans

    largeur_mesuree = 0.0
    caracteres = 0
    for span in spans:
        if not span.texte:
            continue
        asset = polices.get(span.police.font_id)
        if asset is None:
            return spans
        largeur_mesuree += mesurer_largeur_pt(span.texte, asset, span.size_pt)
        caracteres += len(span.texte)

    largeur_cible = emu_vers_pt(largeur_cible_emu) * 0.985
    if caracteres <= 1 or largeur_mesuree <= largeur_cible + 0.25:
        return spans

    # Une ligne de prose trop large doit rester lisible. Une compression de
    # caracteres excessive provoque des chevauchements visibles dans Word.
    if ligne_mots_lisible:
        facteur = max(0.76, min(0.99, (largeur_cible / largeur_mesuree) * 0.98))
        if facteur < 0.995:
            return [
                _copier_span(
                    span,
                    size_pt=max(6.0, round(span.size_pt * facteur, 2)),
                    espacement_twips=0,
                )
                for span in spans
            ]

    interstices = max(caracteres - 1, 1)
    correction_pt = (largeur_cible - largeur_mesuree) / interstices
    espacement = round(pt_vers_twips(correction_pt))
    limite = -4 if ligne_mots_lisible else -24
    espacement = max(limite, min(0, espacement))

    if espacement == 0:
        return spans
    return [
        _copier_span(
            span,
            size_pt=span.size_pt,
            espacement_twips=max(limite, min(0, int(span.espacement_twips or 0) + espacement)),
        )
        for span in spans
    ]


def _ajuster_spans_a_boite(
    spans: list[Span],
    largeur_cible_emu: int,
    hauteur_cible_emu: int,
    polices: dict | None,
    *,
    compact: bool = False,
) -> list[Span]:
    ajustes = _ajuster_spans_a_largeur(
        spans,
        largeur_cible_emu,
        polices,
        compact=compact,
    )
    return ajustes


def _paragraphe_fond_fixe_xml(paragraphe: FlowParagraph, relations, fond: ShapeEl) -> str:
    """Rend un bandeau/label comme bloc Word natif aux dimensions PDF."""
    fond_bbox = quantifier_bbox(fond.bbox)
    marge_gauche = pt_vers_emu(_MARGE_FLUX_H_PT)
    largeur = max(pt_vers_twips(emu_vers_pt(fond_bbox.largeur)), 1)
    hauteur = max(pt_vers_twips(emu_vers_pt(fond_bbox.hauteur)), 1)
    indentation = max(pt_vers_twips(emu_vers_pt(fond_bbox.x0 - marge_gauche)), 0)
    couleur = paragraphe.couleur
    if _couleur_sombre(fond.remplissage) and couleur.upper() in {"000000", "111111"}:
        couleur = "FFFFFF"
    police = paragraphe.police
    span = Span(
        texte=paragraphe.texte,
        police=police,
        size_pt=paragraphe.size_pt,
        couleur=couleur,
        espacement_twips=paragraphe.espacement_twips,
        souligne=paragraphe.souligne,
        barre=paragraphe.barre,
        capitales=paragraphe.capitales,
        surlignage=paragraphe.surlignage,
    )
    avant = max(pt_vers_twips(emu_vers_pt(paragraphe.espace_avant_emu)), 0)
    espace = (
        "<w:p><w:pPr>"
        f'<w:spacing w:before="{min(avant, 80)}" w:after="0" w:line="1" w:lineRule="exact"/>'
        "</w:pPr></w:p>"
        if avant
        else ""
    )
    return (
        f"{espace}"
        "<w:tbl>"
        "<w:tblPr>"
        f'<w:tblW w:w="{largeur}" w:type="dxa"/>'
        '<w:tblLayout w:type="fixed"/>'
        f'<w:tblInd w:w="{indentation}" w:type="dxa"/>'
        '<w:tblBorders><w:top w:val="nil"/><w:left w:val="nil"/>'
        '<w:bottom w:val="nil"/><w:right w:val="nil"/>'
        '<w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders>'
        "</w:tblPr>"
        f'<w:tblGrid><w:gridCol w:w="{largeur}"/></w:tblGrid>'
        "<w:tr>"
        f'<w:trPr><w:trHeight w:val="{hauteur}" w:hRule="exact"/></w:trPr>'
        "<w:tc><w:tcPr>"
        f'<w:tcW w:w="{largeur}" w:type="dxa"/>'
        f'<w:shd w:fill="{fond.remplissage}"/>'
        '<w:vAlign w:val="center"/>'
        '<w:tcMar><w:top w:w="0" w:type="dxa"/><w:left w:w="0" w:type="dxa"/>'
        '<w:bottom w:w="0" w:type="dxa"/><w:right w:w="0" w:type="dxa"/></w:tcMar>'
        "</w:tcPr>"
        '<w:p><w:pPr><w:spacing w:before="0" w:after="0"/>'
        f'<w:jc w:val="{paragraphe.alignement}"/></w:pPr>'
        f"{_run_xml(span, relations)}</w:p>"
        "</w:tc></w:tr></w:tbl>"
    )


def _paragraphe_flux_xml(
    paragraphe: FlowParagraph,
    relations,
    sect_pr: str = "",
    fond: str | None = None,
    largeur_page_emu: int | None = None,
    polices: dict | None = None,
    espacement_externe: bool = False,
    echelle_verticale: float = 1.0,
) -> str:
    """Rend un paragraphe Word réel, pas une forme flottante."""
    espace_avant_emu = 0 if espacement_externe else paragraphe.espace_avant_emu
    espace_apres_emu = 0 if espacement_externe else paragraphe.espace_apres_emu
    espace_avant = max(pt_vers_twips(emu_vers_pt(espace_avant_emu * echelle_verticale)), 0)
    espace_apres = max(pt_vers_twips(emu_vers_pt(espace_apres_emu * echelle_verticale)), 0)
    if paragraphe.alignement == "center" and len(paragraphe.texte) <= 120:
        espace_avant = min(espace_avant, 80)
        espace_apres = min(espace_apres, 20)
    else:
        espace_avant = min(espace_avant, 120)
        espace_apres = min(espace_apres, 10)
    interligne = max(pt_vers_twips(emu_vers_pt(paragraphe.interligne_emu * echelle_verticale)), 1)
    entree_leader = _LEADER_RE.match(paragraphe.texte.strip())
    gauche = max(pt_vers_twips(emu_vers_pt(paragraphe.retrait_gauche_emu)), 0)
    droite = max(pt_vers_twips(emu_vers_pt(paragraphe.retrait_droite_emu)), 0)
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
    police = type(police)(police.font_id, famille, police.gras, police.italique)
    size_pt = paragraphe.size_pt
    flux_exact = largeur_page_emu is not None and paragraphe.retrait_gauche_emu > 0
    couleur = paragraphe.couleur
    if fond and _couleur_sombre(fond) and couleur.upper() in {"000000", "111111"}:
        couleur = "FFFFFF"
    span = Span(
        texte=paragraphe.texte,
        police=police,
        size_pt=size_pt,
        couleur=couleur,
        souligne=paragraphe.souligne,
        barre=paragraphe.barre,
        capitales=paragraphe.capitales,
        surlignage=paragraphe.surlignage,
    )
    spans_rendu = [span]
    if paragraphe.spans and entree_leader is None:
        spans_rendu = []
        for source in paragraphe.spans:
            police_source = source.police
            famille_source = familles.get(police_source.famille, police_source.famille)
            police_run = type(police_source)(
                police_source.font_id,
                famille_source,
                police_source.gras,
                police_source.italique,
            )
            taille_run = source.size_pt
            couleur_run = source.couleur
            if fond and _couleur_sombre(fond) and couleur_run.upper() in {"000000", "111111"}:
                couleur_run = "FFFFFF"
            spans_rendu.append(
                Span(
                    texte=source.texte,
                    police=police_run,
                    size_pt=taille_run,
                    couleur=couleur_run,
                    espacement_twips=source.espacement_twips or paragraphe.espacement_twips,
                    lien=source.lien,
                    invisible=source.invisible,
                    souligne=source.souligne,
                    barre=source.barre,
                    capitales=source.capitales,
                    exposant=source.exposant,
                    indice=source.indice,
                    surlignage=source.surlignage,
                    bbox=source.bbox,
                )
            )
    if flux_exact and entree_leader is None:
        spans_rendu = _ajuster_spans_a_largeur(spans_rendu, paragraphe.bbox.largeur, polices)
    tabs = ""
    if entree_leader is not None:
        leader_texte = entree_leader.group("leader")
        leader = "dot" if "." in leader_texte else "underscore" if "_" in leader_texte else "hyphen"
        page_largeur_pt = emu_vers_pt(largeur_page_emu) if largeur_page_emu else emu_vers_pt(paragraphe.bbox.x1)
        gauche = max(pt_vers_twips(emu_vers_pt(paragraphe.bbox.x0) - _MARGE_FLUX_H_PT), 0)
        tab_pos_pt = emu_vers_pt(paragraphe.bbox.x1) - _MARGE_FLUX_H_PT
        tab_pos_pt = min(max(tab_pos_pt, 1), max(page_largeur_pt - 2 * _MARGE_FLUX_H_PT, 1))
        tabs = (
            "<w:tabs>"
            f'<w:tab w:val="right" w:leader="{leader}" w:pos="{pt_vers_twips(tab_pos_pt)}"/>'
            "</w:tabs>"
        )
        span = Span(
            texte=entree_leader.group("label").rstrip(),
            police=span.police,
            size_pt=span.size_pt,
            couleur=span.couleur,
            espacement_twips=span.espacement_twips,
            lien=span.lien,
            invisible=span.invisible,
            souligne=span.souligne,
            barre=span.barre,
            capitales=span.capitales,
            exposant=span.exposant,
            indice=span.indice,
            surlignage=span.surlignage,
        )
    elif premiere < 0:
        tabs = f'<w:tabs><w:tab w:val="left" w:pos="{gauche}"/></w:tabs>'
    shading = f'<w:shd w:fill="{fond}"/>' if fond else ""
    ppr = (
        "<w:pPr>"
        f'<w:spacing w:before="{espace_avant}" w:after="{espace_apres}" '
        f'w:line="{interligne if flux_exact else max(120, min(interligne, 230))}" w:lineRule="exact"/>'
        f"{tabs}"
        f'<w:ind w:left="{gauche}" w:right="{droite}" w:firstLine="{premiere}"/>'
        f'<w:jc w:val="{"left" if entree_leader is not None else paragraphe.alignement}"/>'
        f"{shading}"
        f"{sect_pr}</w:pPr>"
    )
    if entree_leader is not None:
        page_span = Span(
            texte=entree_leader.group("page"),
            police=span.police,
            size_pt=span.size_pt,
            couleur=span.couleur,
            espacement_twips=span.espacement_twips,
            lien=span.lien,
            invisible=span.invisible,
            souligne=span.souligne,
            barre=span.barre,
            capitales=span.capitales,
            exposant=span.exposant,
            indice=span.indice,
            surlignage=span.surlignage,
        )
        return f"<w:p>{ppr}{_run_xml(span, relations)}<w:r><w:tab/></w:r>{_run_xml(page_span, relations)}</w:p>"
    return f"<w:p>{ppr}{''.join(_run_xml(run, relations) for run in spans_rendu)}</w:p>"


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


def _espace_vertical_xml(hauteur_emu: int, echelle: float = 1.0) -> str:
    hauteur = max(pt_vers_twips(emu_vers_pt(hauteur_emu * echelle)), 1)
    return (
        "<w:p><w:pPr>"
        f'<w:spacing w:before="{hauteur}" w:after="0" w:line="1" w:lineRule="exact"/>'
        "</w:pPr></w:p>"
    )


def _ancres_xml(elements, compteur: list, relations, media: dict) -> str:
    morceaux = []
    for z, element in enumerate(elements, start=1):
        compteur[0] += 1

        if isinstance(element, TextBox):
            for ligne in element.lignes:
                morceaux.append(zone_texte_xml(ligne, compteur[0], z, relations, page.largeur_emu))
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


def _ancres_visuelles_xml(
    elements,
    compteur: list,
    relations,
    media: dict,
    page: Page,
    skip_ids: set[int] | None = None,
    zones_flux: list | None = None,
    polices: dict | None = None,
) -> str:
    skip_ids = skip_ids or set()
    zones_flux = zones_flux or []
    morceaux = []
    elements = _elements_avec_ombres_derriere(list(elements), media)
    zones_formules = [
        element.bbox
        for element in elements
        if isinstance(element, RasterEl) and getattr(element, "purpose", None) == "formula"
    ]
    for z, element in enumerate(elements, start=1):
        if id(element) in skip_ids:
            continue
        if isinstance(element, FlowParagraph) and getattr(element, "orientation", "horizontal") != "horizontal":
            compteur[0] += 1
            morceaux.append(
                zone_texte_xml(
                    _ligne_depuis_paragraphe(element),
                    compteur[0],
                    z,
                    relations,
                    page.largeur_emu,
                    polices,
                )
            )
        elif isinstance(element, (ImageEl, RasterEl)):
            compteur[0] += 1
            item = media[element.media_ref]
            rel_id = relations.ajouter(f"media/{item.media_ref}.{item.extension}", "image")
            derriere = (
                False
                if getattr(element, "purpose", None) in {"formula", "symbol"}
                else any(se_chevauchent(element.bbox, zone) for zone in zones_flux)
            )
            morceaux.append(image_xml(element, compteur[0], z, rel_id, derriere=derriere))
        elif isinstance(element, TextBox):
            for ligne in element.lignes:
                compteur[0] += 1
                morceaux.append(zone_texte_xml(_ligne_ajustee_largeur(ligne, polices), compteur[0], z, relations, page.largeur_emu, polices))
        elif isinstance(element, ShapeEl):
            if _forme_fond_blanc_page(element, page):
                continue
            compteur[0] += 1
            derriere = bool(element.remplissage) and (
                any(se_chevauchent(element.bbox, zone) for zone in zones_flux)
                or any(se_chevauchent(element.bbox, zone) for zone in zones_formules)
            )
            morceaux.append(forme_xml(element, compteur[0], z, derriere=derriere))
        elif isinstance(element, LinkZone) and element.uri:
            compteur[0] += 1
            rel_id = relations.ajouter(element.uri, "hyperlink", externe=True)
            morceaux.append(zone_lien_xml(element, compteur[0], z, rel_id))
    return "".join(morceaux)


def _ligne_depuis_paragraphe(paragraphe: FlowParagraph) -> Line:
    if paragraphe.spans:
        spans = [
            Span(
                texte=span.texte,
                police=span.police,
                size_pt=span.size_pt,
                couleur=span.couleur,
                espacement_twips=span.espacement_twips or paragraphe.espacement_twips,
                lien=span.lien,
                invisible=span.invisible,
                souligne=span.souligne,
                barre=span.barre,
                capitales=span.capitales,
                exposant=span.exposant,
                indice=span.indice,
                surlignage=span.surlignage,
                bbox=span.bbox,
            )
            for span in paragraphe.spans
        ]
    else:
        spans = [
            Span(
                texte=paragraphe.texte,
                police=paragraphe.police,
                size_pt=paragraphe.size_pt,
                couleur=paragraphe.couleur,
                espacement_twips=paragraphe.espacement_twips,
                souligne=paragraphe.souligne,
                barre=paragraphe.barre,
                capitales=paragraphe.capitales,
                surlignage=paragraphe.surlignage,
            )
        ]
    ligne = Line(
        bbox=paragraphe.bbox,
        spans=spans,
        hauteur_ligne_emu=max(paragraphe.interligne_emu, paragraphe.bbox.hauteur),
        largeur_cible_emu=paragraphe.bbox.largeur,
        alignement=paragraphe.alignement,
        layout_frame_id=paragraphe.layout_frame_id,
        layout_frame_role=paragraphe.layout_frame_role,
        layout_frame_strategy=paragraphe.layout_frame_strategy,
        layout_frame_bbox=paragraphe.layout_frame_bbox,
        source_id=paragraphe.source_id,
        angle_deg=paragraphe.angle_deg,
        orientation=paragraphe.orientation,
        baseline_points=paragraphe.baseline_points,
        semantic_role=paragraphe.semantic_role,
        z_index=paragraphe.z_index,
        curved=paragraphe.curved,
    )
    ligne.retrait_gauche_emu = max(0, paragraphe.retrait_gauche_emu - paragraphe.bbox.x0)
    ligne.retrait_premiere_ligne_emu = paragraphe.retrait_premiere_ligne_emu
    return ligne


def _lignes_depuis_paragraphe(paragraphe: FlowParagraph) -> list[Line]:
    return paragraphe.lignes or [_ligne_depuis_paragraphe(paragraphe)]


def _ligne_ajustee_largeur(ligne: Line, polices: dict | None) -> Line:
    texte_ligne = "".join(span.texte for span in ligne.spans).strip()
    if _LEADER_RE.match(texte_ligne):
        spans = _spans_sans_bords_vides(ligne.spans)
        if spans is ligne.spans:
            return ligne
        return Line(
            bbox=ligne.bbox,
            spans=spans,
            hauteur_ligne_emu=ligne.hauteur_ligne_emu,
            largeur_cible_emu=ligne.largeur_cible_emu,
            alignement=ligne.alignement,
            layout_frame_id=ligne.layout_frame_id,
            layout_frame_role=ligne.layout_frame_role,
            layout_frame_strategy=ligne.layout_frame_strategy,
            layout_frame_bbox=ligne.layout_frame_bbox,
            source_id=ligne.source_id,
            angle_deg=ligne.angle_deg,
            orientation=ligne.orientation,
            baseline_points=ligne.baseline_points,
            semantic_role=ligne.semantic_role,
            z_index=ligne.z_index,
            curved=ligne.curved,
        )
    decision = comprendre_ligne_texte(
        texte_ligne,
        frame_role=getattr(ligne, "layout_frame_role", None),
        frame_strategy=getattr(ligne, "layout_frame_strategy", None),
    )
    compact = decision.action != "candidate-paragraph-line" and not _ligne_prose_probable(texte_ligne, ligne)
    spans_source = _spans_sans_bords_vides(ligne.spans)
    spans = _ajuster_spans_a_boite(
        spans_source,
        ligne.largeur_cible_emu or ligne.bbox.largeur,
        ligne.bbox.hauteur,
        polices,
        compact=compact,
    )
    if spans is ligne.spans:
        return ligne
    ajustee = Line(
        bbox=ligne.bbox,
        spans=spans,
        hauteur_ligne_emu=ligne.hauteur_ligne_emu,
        largeur_cible_emu=ligne.largeur_cible_emu,
        alignement=ligne.alignement,
        layout_frame_id=ligne.layout_frame_id,
        layout_frame_role=ligne.layout_frame_role,
        layout_frame_strategy=ligne.layout_frame_strategy,
        layout_frame_bbox=ligne.layout_frame_bbox,
        source_id=ligne.source_id,
        angle_deg=ligne.angle_deg,
        orientation=ligne.orientation,
        baseline_points=ligne.baseline_points,
        semantic_role=ligne.semantic_role,
        z_index=ligne.z_index,
        curved=ligne.curved,
    )
    ajustee.retrait_gauche_emu = getattr(ligne, "retrait_gauche_emu", 0)
    ajustee.retrait_premiere_ligne_emu = getattr(ligne, "retrait_premiere_ligne_emu", 0)
    return ajustee


def _ligne_prose_probable(texte: str, ligne: Line) -> bool:
    mots = _MOT_PROSE_RE.findall(texte)
    if len(mots) < 6:
        return False
    if _ITEM_LISTE_RE.match(texte):
        return True
    if emu_vers_pt(ligne.bbox.largeur) < 80:
        return False
    style = next((span for span in ligne.spans if span.texte.strip()), ligne.spans[0] if ligne.spans else None)
    if style is not None and style.size_pt >= 18:
        return False
    lettres = [car for car in texte if car.isalpha()]
    if not lettres:
        return False
    if sum(1 for car in lettres if car.isupper()) / len(lettres) > 0.70:
        return False
    return len(lettres) / max(len(texte), 1) >= 0.45


def _paragraphe_ajuste_largeur(paragraphe: FlowParagraph, polices: dict | None) -> FlowParagraph:
    if not paragraphe.lignes:
        spans = _ajuster_spans_a_largeur(paragraphe.spans, paragraphe.bbox.largeur, polices)
        if spans is paragraphe.spans:
            return paragraphe
        return FlowParagraph(
            bbox=paragraphe.bbox,
            texte=paragraphe.texte,
            police=paragraphe.police,
            size_pt=paragraphe.size_pt,
            couleur=paragraphe.couleur,
            alignement=paragraphe.alignement,
            retrait_gauche_emu=paragraphe.retrait_gauche_emu,
            retrait_droite_emu=paragraphe.retrait_droite_emu,
            retrait_premiere_ligne_emu=paragraphe.retrait_premiere_ligne_emu,
            espace_avant_emu=paragraphe.espace_avant_emu,
            espace_apres_emu=paragraphe.espace_apres_emu,
            interligne_emu=paragraphe.interligne_emu,
            souligne=paragraphe.souligne,
            barre=paragraphe.barre,
            capitales=paragraphe.capitales,
            surlignage=paragraphe.surlignage,
            espacement_twips=paragraphe.espacement_twips,
            spans=spans,
            lignes=[],
            layout_frame_id=paragraphe.layout_frame_id,
            layout_frame_role=paragraphe.layout_frame_role,
            layout_frame_strategy=paragraphe.layout_frame_strategy,
            layout_frame_bbox=paragraphe.layout_frame_bbox,
            vertical_alignement=paragraphe.vertical_alignement,
            source_id=paragraphe.source_id,
            angle_deg=paragraphe.angle_deg,
            orientation=paragraphe.orientation,
            baseline_points=paragraphe.baseline_points,
            semantic_role=paragraphe.semantic_role,
            z_index=paragraphe.z_index,
            curved=paragraphe.curved,
        )

    lignes = [_ligne_ajustee_largeur(ligne, polices) for ligne in paragraphe.lignes]
    spans: list[Span] = []
    reflow_naturel = _paragraphe_reflow_naturel(paragraphe)
    for index, ligne in enumerate(lignes):
        reference_ligne = ligne.spans[0] if ligne.spans else None
        if index:
            reference = next((span for span in spans if span.texte.strip()), None)
            reference = reference or reference_ligne
            if reference is not None:
                spans.append(
                    Span(
                        " " if reflow_naturel else "\n",
                        reference.police,
                        reference.size_pt,
                        reference.couleur,
                        espacement_twips=reference.espacement_twips,
                        souligne=reference.souligne,
                        barre=reference.barre,
                        capitales=reference.capitales,
                        exposant=reference.exposant,
                        indice=reference.indice,
                        surlignage=reference.surlignage,
                    )
                )
        decalage_ligne = ligne.bbox.x0 - paragraphe.bbox.x0
        if not reflow_naturel and decalage_ligne > pt_vers_emu(3) and reference_ligne is not None:
            spans.append(
                Span(
                    "\t",
                    reference_ligne.police,
                    reference_ligne.size_pt,
                    reference_ligne.couleur,
                    espacement_twips=reference_ligne.espacement_twips,
                    souligne=reference_ligne.souligne,
                    barre=reference_ligne.barre,
                    capitales=reference_ligne.capitales,
                    exposant=reference_ligne.exposant,
                    indice=reference_ligne.indice,
                    surlignage=reference_ligne.surlignage,
                )
            )
        if reflow_naturel:
            spans.extend(_spans_reflow_ligne(ligne.spans))
        else:
            spans.extend(_spans_sans_bords_vides(ligne.spans))

    return FlowParagraph(
        bbox=paragraphe.bbox,
        texte=paragraphe.texte,
        police=paragraphe.police,
        size_pt=paragraphe.size_pt,
        couleur=paragraphe.couleur,
        alignement=paragraphe.alignement,
        retrait_gauche_emu=paragraphe.retrait_gauche_emu,
        retrait_droite_emu=paragraphe.retrait_droite_emu,
        retrait_premiere_ligne_emu=paragraphe.retrait_premiere_ligne_emu,
        espace_avant_emu=paragraphe.espace_avant_emu,
        espace_apres_emu=paragraphe.espace_apres_emu,
        interligne_emu=paragraphe.interligne_emu,
        souligne=paragraphe.souligne,
        barre=paragraphe.barre,
        capitales=paragraphe.capitales,
        surlignage=paragraphe.surlignage,
        espacement_twips=paragraphe.espacement_twips,
        spans=spans,
        lignes=lignes,
        layout_frame_id=paragraphe.layout_frame_id,
        layout_frame_role=paragraphe.layout_frame_role,
        layout_frame_strategy=paragraphe.layout_frame_strategy,
        layout_frame_bbox=paragraphe.layout_frame_bbox,
        vertical_alignement=paragraphe.vertical_alignement,
        source_id=paragraphe.source_id,
        angle_deg=paragraphe.angle_deg,
        orientation=paragraphe.orientation,
        baseline_points=paragraphe.baseline_points,
        semantic_role=paragraphe.semantic_role,
        z_index=paragraphe.z_index,
        curved=paragraphe.curved,
    )


def _texte_ligne_reflow(ligne: Line) -> str:
    return "".join(span.texte for span in ligne.spans).strip()


def _paragraphe_reflow_naturel(paragraphe: FlowParagraph) -> bool:
    if paragraphe.alignement == "both":
        return True
    if paragraphe.layout_frame_role != "text-column" or paragraphe.alignement != "left":
        return False
    if len(paragraphe.lignes) < 2 or len(paragraphe.lignes) > 4:
        return False
    textes = [_texte_ligne_reflow(ligne) for ligne in paragraphe.lignes if _texte_ligne_reflow(ligne)]
    if not textes:
        return False
    if any(_LEADER_RE.match(texte) for texte in textes):
        return False
    if not _ITEM_LISTE_RE.match(textes[0]):
        return False
    if any(_ITEM_LISTE_RE.match(texte) for texte in textes[1:]):
        return False
    return True


def _colonnes_flow(paragraphes: list[FlowParagraph], page: Page) -> list[list[FlowParagraph]]:
    """Regroupe les paragraphes qui appartiennent a des colonnes PDF distinctes."""
    if len(paragraphes) < 4:
        return []
    positions = sorted({element.bbox.x0 for element in paragraphes})
    seuil = page.largeur_emu * 0.16
    groupes: list[list[int]] = []
    for position in positions:
        if not groupes or position - groupes[-1][-1] > seuil:
            groupes.append([position])
        else:
            groupes[-1].append(position)
    groupes_solides = [groupe for groupe in groupes if len(groupe) >= 2]
    if len(groupes_solides) < 2:
        return []
    centres = [sum(groupe) / len(groupe) for groupe in groupes_solides]
    resultat = [[] for _ in centres]
    for element in paragraphes:
        index = min(range(len(centres)), key=lambda item: abs(element.bbox.x0 - centres[item]))
        resultat[index].append(element)
    return [sorted(groupe, key=lambda item: (item.bbox.y0, item.bbox.x0)) for groupe in resultat]


def _paragraphes_pleine_largeur_flow(
    paragraphes: list[FlowParagraph],
    page: Page,
) -> list[FlowParagraph]:
    """Garde les titres et lignes transversales hors des cellules de colonnes."""
    larges = [
        paragraphe
        for paragraphe in paragraphes
        if paragraphe.bbox.largeur >= page.largeur_emu * 0.52
        and paragraphe.bbox.y0 <= page.hauteur_emu * 0.35
    ]
    if not larges:
        return []
    # Un titre est souvent découpé en lignes PDF de largeurs différentes. Les lignes
    # courtes voisines doivent rester dans le même bloc pleine largeur, sinon une
    # ligne comme « Management District » est faussement envoyée dans une colonne.
    marge_y = page.hauteur_emu * 0.04
    debut = min(element.bbox.y0 for element in larges) - marge_y
    fin = max(element.bbox.y1 for element in larges) + marge_y
    return [
        paragraphe
        for paragraphe in paragraphes
        if paragraphe in larges
        or (
            debut <= paragraphe.bbox.y0
            and paragraphe.bbox.y1 <= fin
            and paragraphe.bbox.x0 <= page.largeur_emu * 0.15
        )
    ]


def _fusionner_colonnes_traversees(
    colonnes: list[list[FlowParagraph]],
    page: Page,
) -> list[list[FlowParagraph]]:
    """Fusionne deux cellules quand une légende traverse leur séparation."""
    resultat = [list(colonne) for colonne in colonnes]
    index = 0
    seuil_largeur = page.largeur_emu * 0.45
    while index + 1 < len(resultat):
        frontiere = min(element.bbox.x0 for element in resultat[index + 1])
        traverse = any(
            element.bbox.largeur >= seuil_largeur
            and element.bbox.x1 > frontiere + pt_vers_emu(4)
            for element in resultat[index]
        )
        if traverse:
            resultat[index].extend(resultat.pop(index + 1))
            resultat[index].sort(key=lambda item: (item.bbox.y0, item.bbox.x0))
            continue
        index += 1
    return resultat


def _table_colonnes_flow_xml(
    colonnes: list[list[FlowParagraph]],
    page: Page,
    compteur: list,
    relations,
    polices: dict | None,
    origine_y_emu: int = 0,
) -> str:
    """Place des paragraphes normaux dans des cellules invisibles de colonnes."""
    nombre = len(colonnes)
    origines = [0]
    origines.extend(
        min(element.bbox.x0 for element in colonne)
        for colonne in colonnes[1:]
    )
    largeurs = [
        max(1, (origines[index + 1] if index + 1 < nombre else page.largeur_emu) - origine)
        for index, origine in enumerate(origines)
    ]
    morceaux = []
    max_bas = max(element.bbox.y1 for colonne in colonnes for element in colonne)
    hauteur_requise = max(0, max_bas - origine_y_emu)
    hauteur_disponible = max(page.hauteur_emu - origine_y_emu, 1)
    echelle_verticale = min(1.0, (hauteur_disponible / max(hauteur_requise * 1.24, 1)) * 0.99)
    echelle_verticale = max(0.80, echelle_verticale)
    for index, colonne in enumerate(colonnes):
        origine = origines[index]
        largeur = largeurs[index]
        largeur_twips = max(1, pt_vers_twips(emu_vers_pt(largeur)))
        precedent_bas = 0
        contenus = []
        for element in colonne:
            element = _paragraphe_ajuste_largeur(element, polices)
            avant = max(0, element.bbox.y0 - origine_y_emu - precedent_bas)
            contenus.append(
                zone_paragraphe_xml(
                    element,
                    compteur[0],
                    index + 1,
                    relations,
                    natif=True,
                    espacement_avant_emu=avant,
                    flux_origine_x_emu=origine,
                    flux_largeur_emu=largeur,
                    echelle_verticale=echelle_verticale,
                    polices=polices,
                )
            )
            compteur[0] += 1
            precedent_bas = max(precedent_bas, element.bbox.y1)
        morceaux.append(
            "<w:tc><w:tcPr>"
            f'<w:tcW w:w="{largeur_twips}" w:type="dxa"/>'
            '<w:tcMar><w:top w:w="0" w:type="dxa"/><w:left w:w="0" w:type="dxa"/>'
            '<w:bottom w:w="0" w:type="dxa"/><w:right w:w="0" w:type="dxa"/></w:tcMar>'
            "</w:tcPr>"
            f"{''.join(contenus)}</w:tc>"
        )
    grille = "".join(
        f'<w:gridCol w:w="{max(1, pt_vers_twips(emu_vers_pt(largeur)))}"/>'
        for largeur in largeurs
    )
    largeur_totale_twips = sum(
        max(1, pt_vers_twips(emu_vers_pt(largeur))) for largeur in largeurs
    )
    return (
        "<w:tbl><w:tblPr>"
        f'<w:tblW w:w="{largeur_totale_twips}" w:type="dxa"/>'
        '<w:tblLayout w:type="fixed"/>'
        '<w:tblBorders><w:top w:val="nil"/><w:left w:val="nil"/><w:bottom w:val="nil"/>'
        '<w:right w:val="nil"/><w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders>'
        "</w:tblPr>"
        f"<w:tblGrid>{grille}</w:tblGrid>"
        f"<w:tr>{''.join(morceaux)}</w:tr></w:tbl>"
    )


def _bornes_stables(valeurs: list[int], tolerance: int) -> list[int]:
    """Fusionne les bords quasi identiques sans perdre les vrais bords de zones."""
    resultats: list[int] = []
    for valeur in sorted(set(valeurs)):
        if not resultats or valeur - resultats[-1] > tolerance:
            resultats.append(valeur)
        else:
            resultats[-1] = round((resultats[-1] + valeur) / 2)
    return resultats


def _fusionner_fragments_meme_ligne(
    fragments: list[tuple[int, FlowParagraph]],
) -> list[tuple[int, FlowParagraph]]:
    """Fusionne les atomes PDF qui occupent la meme ligne visuelle.

    Les puces, symboles, lettrines et petits marqueurs sont souvent des objets PDF
    separes du texte principal. Ils doivent devenir des runs dans le meme paragraphe
    Word, sinon une cellule fixe les empile et mange une ligne de contenu.
    """
    if len(fragments) < 2:
        return fragments
    groupes: list[list[tuple[int, FlowParagraph]]] = []
    for fragment in sorted(fragments, key=lambda item: (item[1].bbox.y0, item[1].bbox.x0)):
        _, element = fragment
        centre_y = (element.bbox.y0 + element.bbox.y1) / 2
        hauteur = max(element.bbox.hauteur, 1)
        groupe_trouve = None
        for groupe in reversed(groupes):
            _, precedent = groupe[-1]
            # Deux régions distinctes peuvent être parfaitement alignées sur la
            # même ligne (colonnes, légende et panneau voisin). Elles doivent rester
            # deux paragraphes Word dans leurs cellules respectives.
            if getattr(element, "layout_frame_id", None) != getattr(precedent, "layout_frame_id", None):
                continue
            centre_precedent = (precedent.bbox.y0 + precedent.bbox.y1) / 2
            seuil = max(pt_vers_emu(2.5), min(hauteur, precedent.bbox.hauteur) * 0.65)
            if abs(centre_y - centre_precedent) <= seuil:
                groupe_trouve = groupe
                break
            if element.bbox.y0 - precedent.bbox.y1 > pt_vers_emu(6):
                break
        if groupe_trouve is None:
            groupes.append([fragment])
        else:
            groupe_trouve.append(fragment)

    resultat: list[tuple[int, FlowParagraph]] = []
    for groupe in groupes:
        if len(groupe) == 1:
            resultat.extend(groupe)
            continue
        groupe = sorted(groupe, key=lambda item: item[1].bbox.x0)
        premier_span = next(
            (span for span in groupe[0][1].spans if span.texte.strip()),
            None,
        )
        spans = []
        bbox = groupe[0][1].bbox
        texte_parts = []
        for index, (_, element) in enumerate(groupe):
            if index and premier_span is not None and element.bbox.x0 > bbox.x1:
                spans.append(
                    Span(
                        " ",
                        premier_span.police,
                        premier_span.size_pt,
                        premier_span.couleur,
                    )
                )
            spans.extend(element.spans)
            texte_parts.append(element.texte)
            bbox = union(bbox, element.bbox)
        base = groupe[0][1]
        fusion = replace(
            base,
            bbox=bbox,
            texte=" ".join(part.strip() for part in texte_parts if part.strip()),
            spans=spans,
            lignes=[],
            retrait_droite_emu=max(0, base.retrait_droite_emu),
        )
        resultat.append((max(item[0] for item in groupe), fusion))
    return resultat


def _grille_vertical_layout(
    paragraphes: list[FlowParagraph],
    page: Page,
) -> tuple[list[int], list[int], int, bool]:
    """Calcule les bandes Word et leur hauteur effective.

    Les bandes sont calculees une seule fois pour que les cellules Word respectent
    les contraintes verticales des paragraphes sans modifier les coordonnees PDF
    des images et formes ancrees.
    """
    tolerance = pt_vers_emu(1.5)
    hauteur_grille = max(pt_vers_emu(1), page.hauteur_emu - pt_vers_emu(18))
    bornes_y = [0, hauteur_grille]
    cadres_texte = {
        element.layout_frame_id: element.layout_frame_bbox
        for element in paragraphes
        if element.layout_frame_id
        and element.layout_frame_bbox is not None
    }
    for element in paragraphes:
        bornes_y.extend(
            (
                max(0, min(element.bbox.y0, hauteur_grille)),
                max(0, min(element.bbox.y1, hauteur_grille)),
            )
        )
    for cadre in cadres_texte.values():
        bornes_y.extend(
            (
                max(0, min(cadre.y0, hauteur_grille)),
                max(0, min(cadre.y1, hauteur_grille)),
            )
        )
    bornes_y = _bornes_stables(bornes_y, tolerance)
    bornes_y[0] = 0
    bornes_y[-1] = hauteur_grille

    def index_bord(valeur: int, debut: bool) -> int:
        distances = [abs(item - valeur) for item in bornes_y]
        meilleur = min(range(len(bornes_y)), key=distances.__getitem__)
        return meilleur if debut else max(meilleur, 1)

    hauteurs_source: list[int] = []
    hauteurs_min: list[int] = []
    for row in range(len(bornes_y) - 1):
        hauteur = max(1, bornes_y[row + 1] - bornes_y[row])
        minimum = 0
        for element in paragraphes:
            # Le cadre definit le conteneur, mais la position verticale appartient
            # toujours a l'atome de texte. Utiliser la hauteur du cadre ici empile
            # toutes les lignes d'une colonne dans sa premiere bande.
            bbox_reference = element.bbox
            row0 = max(0, min(index_bord(bbox_reference.y0, True), len(bornes_y) - 2))
            if row0 != row:
                continue
            taille_maximale = max(
                (float(span.size_pt) for span in element.spans if span.texte.strip()),
                default=float(element.size_pt),
            )
            if element.layout_frame_role == "heading" and taille_maximale >= 16:
                minimum += pt_vers_twips(taille_maximale * 1.25 * _ECHELLE_GRILLE_MIN)
            elif element.layout_frame_id:
                minimum = max(
                    minimum,
                    pt_vers_twips(
                        max(taille_maximale * 1.08 * _ECHELLE_GRILLE_MIN, 1.0)
                    ),
                )
        hauteurs_source.append(max(1, pt_vers_twips(emu_vers_pt(hauteur))))
        hauteurs_min.append(max(1, minimum))

    hauteur_disponible_twips = max(1, pt_vers_twips(emu_vers_pt(hauteur_grille)))
    hauteurs = [max(source, minimum) for source, minimum in zip(hauteurs_source, hauteurs_min)]
    excedent = max(0, sum(hauteurs) - hauteur_disponible_twips)
    compactage_force = sum(hauteurs_min) > hauteur_disponible_twips
    marges_reductibles = [
        max(0, hauteur - minimum)
        for hauteur, minimum in zip(hauteurs, hauteurs_min)
    ]
    total_reductible = sum(marges_reductibles)
    if excedent and total_reductible:
        restant = excedent
        for index, marge in enumerate(marges_reductibles):
            if not marge:
                continue
            reduction = min(marge, max(1, round(excedent * marge / total_reductible)))
            reduction = min(reduction, restant)
            hauteurs[index] -= reduction
            restant -= reduction
            if restant <= 0:
                break
    # Certaines pages ont de nombreux cadres superposes ou des lignes OCR tres
    # rapprochees. La borne historique de 86 % protegeait la lisibilite, mais
    # pouvait rendre la grille plus haute que la page et repousser les dernieres
    # lignes sur la page suivante. Une compression proportionnelle est preferable
    # a une sortie hors page ; elle ne s'applique que lorsque les minima eux-memes
    # depassent l'espace imprimable.
    if restant > 0 and sum(hauteurs) > 0:
        facteur = hauteur_disponible_twips / sum(hauteurs)
        hauteurs = [max(1, round(hauteur * facteur)) for hauteur in hauteurs]
        difference = sum(hauteurs) - hauteur_disponible_twips
        if difference > 0:
            for index in range(len(hauteurs) - 1, -1, -1):
                reduction = min(difference, max(0, hauteurs[index] - 1))
                hauteurs[index] -= reduction
                difference -= reduction
                if difference <= 0:
                    break
    return bornes_y, hauteurs, hauteur_grille, compactage_force


def _grille_regions_flow_xml(
    paragraphes: list[FlowParagraph],
    page: Page,
    compteur: list,
    relations,
    polices: dict | None,
) -> str:
    """Place les textes dans une grille 2D Word fondée sur leurs régions source.

    Une page composée de plusieurs cadres ne doit pas être réduite à une seule
    ligne de cellules. Les bords des régions deviennent les bords d'une grille
    fixe ; les paragraphes restent de vrais paragraphes Word dans les cellules.
    """
    tolerance = pt_vers_emu(1.5)
    cadres = [
        element.layout_frame_bbox
        for element in paragraphes
        if element.layout_frame_bbox is not None
    ]
    bornes_x = [0, page.largeur_emu]
    for element in paragraphes:
        cadre = element.layout_frame_bbox or element.bbox
        bornes_x.extend((cadre.x0, cadre.x1))
    bornes_x = _bornes_stables(bornes_x, tolerance)
    bornes_x[0] = 0
    bornes_x[-1] = page.largeur_emu

    bornes_y, hauteurs, hauteur_grille, compactage_force = _grille_vertical_layout(paragraphes, page)

    if len(bornes_x) < 2 or len(bornes_y) < 2:
        return ""

    def index_bord(bords: list[int], valeur: int, debut: bool) -> int:
        distances = [abs(item - valeur) for item in bords]
        meilleur = min(range(len(bords)), key=distances.__getitem__)
        if debut:
            return meilleur
        return max(meilleur, 1)

    contenu: dict[tuple[int, int], list[tuple[int, FlowParagraph]]] = {}
    for element in sorted(paragraphes, key=lambda item: (item.bbox.y0, item.bbox.x0)):
        cadre = element.layout_frame_bbox or element.bbox
        col0 = index_bord(bornes_x, cadre.x0, True)
        col1 = index_bord(bornes_x, cadre.x1, False)
        bbox_verticale = element.bbox
        row0 = index_bord(bornes_y, bbox_verticale.y0, True)
        row1 = index_bord(bornes_y, bbox_verticale.y1, False)
        col0 = max(0, min(col0, len(bornes_x) - 2))
        col1 = max(col0 + 1, min(col1, len(bornes_x) - 1))
        row0 = max(0, min(row0, len(bornes_y) - 2))
        row1 = max(row0 + 1, min(row1, len(bornes_y) - 1))
        largeur = bornes_x[col1] - bornes_x[col0]
        zone = _paragraphe_ajuste_largeur(element, polices)
        compteur[0] += 1
        cle = (row0, col0)
        contenu.setdefault(cle, []).append((col1 - col0, zone))

    lignes_xml: list[str] = []
    for row in range(len(bornes_y) - 1):
        hauteur_twips = max(1, hauteurs[row])
        cellules: list[str] = []
        col = 0
        while col < len(bornes_x) - 1:
            fragments = contenu.get((row, col), [])
            fragments = _fusionner_fragments_meme_ligne(fragments)
            fragments = [
                (span, _paragraphe_ajuste_largeur(element, polices))
                for span, element in fragments
            ]
            span = max((item[0] for item in fragments), default=1)
            span = min(span, len(bornes_x) - 1 - col)
            largeur = max(1, bornes_x[col + span] - bornes_x[col])
            largeur_twips = max(1, pt_vers_twips(emu_vers_pt(largeur)))
            grid_span = f'<w:gridSpan w:val="{span}"/>' if span > 1 else ""
            hauteur_contenu = sum(
                max(
                    pt_vers_twips(emu_vers_pt(max(element.interligne_emu, element.bbox.hauteur))),
                    pt_vers_twips(float(element.size_pt) * 1.08),
                )
                for _, element in fragments
            )
            echelle_locale = min(
                1.0,
                (hauteur_twips * 0.94) / max(hauteur_contenu, 1),
            )
            if compactage_force:
                echelle_locale = max(0.62, echelle_locale)
            else:
                echelle_locale = max(_ECHELLE_GRILLE_MIN, echelle_locale)
            contenu_cellule = []
            for _, element in fragments:
                contenu_cellule.append(
                    zone_paragraphe_xml(
                        element,
                        compteur[0],
                        row + 1,
                        relations,
                        natif=True,
                        espacement_avant_emu=0,
                        flux_origine_x_emu=bornes_x[col],
                        flux_largeur_emu=max(largeur, 1),
                        echelle_verticale=echelle_locale,
                        echelle_police=echelle_locale,
                        polices=polices,
                    )
                )
                compteur[0] += 1
            cellules.append(
                "<w:tc><w:tcPr>"
                f'<w:tcW w:w="{largeur_twips}" w:type="dxa"/>'
                + grid_span
                + '<w:tcMar><w:top w:w="0" w:type="dxa"/>'
                '<w:left w:w="0" w:type="dxa"/>'
                '<w:bottom w:w="0" w:type="dxa"/>'
                '<w:right w:w="0" w:type="dxa"/></w:tcMar>'
                "</w:tcPr>"
                + ("".join(contenu_cellule) or '<w:p><w:pPr><w:spacing w:before="0" w:after="0"/></w:pPr></w:p>')
                + "</w:tc>"
            )
            col += span
        lignes_xml.append(
            f'<w:tr><w:trPr><w:trHeight w:val="{hauteur_twips}" w:hRule="exact"/>'
            '<w:cantSplit/></w:trPr>'
            + "".join(cellules)
            + "</w:tr>"
        )

    grille = "".join(
        f'<w:gridCol w:w="{max(1, pt_vers_twips(emu_vers_pt(bornes_x[index + 1] - bornes_x[index])))}"/>'
        for index in range(len(bornes_x) - 1)
    )
    largeur_totale = max(1, pt_vers_twips(emu_vers_pt(page.largeur_emu)))
    return (
        "<w:tbl><w:tblPr>"
        f'<w:tblW w:w="{largeur_totale}" w:type="dxa"/>'
        '<w:tblLayout w:type="fixed"/>'
        '<w:tblBorders><w:top w:val="nil"/><w:left w:val="nil"/>'
        '<w:bottom w:val="nil"/><w:right w:val="nil"/>'
        '<w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders>'
        "</w:tblPr>"
        f"<w:tblGrid>{grille}</w:tblGrid>"
        + "".join(lignes_xml)
        + "</w:tbl>"
    )


def _page_absolue_xml(page: Page, derniere: bool, compteur: list, relations, media: dict, polices: dict | None) -> str:
    morceaux = []
    ancres = []
    paragraphes_natifs = []
    tables = []
    elements_page = _ordonner_bandeaux_sur_images(
        _elements_avec_ombres_derriere(page.elements, media),
        page,
    )
    tables_denses = [
        element
        for element in elements_page
        if isinstance(element, TableEl) and _tableau_dense_exact(element, page)
    ]
    zones_texte = [
        element.bbox
        for element in elements_page
        if isinstance(element, (FlowParagraph, TextBox))
    ]
    zones_formules = [
        element.bbox
        for element in elements_page
        if isinstance(element, RasterEl) and getattr(element, "purpose", None) == "formula"
    ]
    paragraphes_ordonnes = sorted(
        (
            element
            for element in elements_page
            if isinstance(element, FlowParagraph)
            and getattr(element, "orientation", "horizontal") == "horizontal"
        ),
        key=lambda element: (element.bbox.y0, element.bbox.x0),
    )
    paragraphes_flow = [
        element
        for element in paragraphes_ordonnes
        if not _bbox_dans_table_dense(element.bbox, tables_denses)
    ]
    cadres_flow = {
        element.layout_frame_id
        for element in paragraphes_flow
        if element.layout_frame_id and element.layout_frame_bbox is not None
    }
    grille_regions_flow = len(cadres_flow) >= 2 and len(paragraphes_flow) >= 4
    colonnes_flow = [] if grille_regions_flow else _colonnes_flow(paragraphes_flow, page)
    paragraphes_pleine_largeur = (
        [] if grille_regions_flow else _paragraphes_pleine_largeur_flow(paragraphes_flow, page)
    )
    paragraphes_colonnes = [
        element for element in paragraphes_flow if element not in paragraphes_pleine_largeur
    ]
    if colonnes_flow and paragraphes_pleine_largeur:
        colonnes_flow = _colonnes_flow(paragraphes_colonnes, page)
    if colonnes_flow:
        colonnes_flow = _fusionner_colonnes_traversees(colonnes_flow, page)
    espacements_avant = {}
    precedent_bas = 0
    for element in paragraphes_ordonnes:
        espacements_avant[id(element)] = max(0, element.bbox.y0 - precedent_bas)
        precedent_bas = max(precedent_bas, element.bbox.y1)
    for z, element in enumerate(elements_page, start=1):
        compteur[0] += 1
        if isinstance(element, FlowParagraph) and getattr(element, "orientation", "horizontal") != "horizontal":
            ancres.append(
                zone_texte_xml(
                    _ligne_depuis_paragraphe(element),
                    compteur[0],
                    z,
                    relations,
                    page.largeur_emu,
                    polices,
                )
            )
        elif isinstance(element, FlowParagraph):
            # Les paragraphes sont émis plus bas dans l'ordre spatial. Ici on ne
            # traite que les objets flottants et les fonds afin de ne pas suivre
            # l'ordre des blocs renvoyé par le PDF.
            continue
        elif isinstance(element, TextBox):
            for ligne in element.lignes:
                if _bbox_dans_table_dense(ligne.bbox, tables_denses):
                    continue
                ancres.append(zone_texte_xml(_ligne_ajustee_largeur(ligne, polices), compteur[0], z, relations, page.largeur_emu, polices))
                compteur[0] += 1
        elif isinstance(element, (ImageEl, RasterEl)):
            item = media[element.media_ref]
            rel_id = relations.ajouter(f"media/{item.media_ref}.{item.extension}", "image")
            derriere = any(se_chevauchent(element.bbox, zone) for zone in zones_texte)
            ancres.append(image_xml(element, compteur[0], z, rel_id, derriere=derriere))
        elif isinstance(element, ShapeEl):
            if _forme_fond_blanc_page(element, page):
                continue
            derriere = bool(element.remplissage) and (
                any(se_chevauchent(element.bbox, zone) for zone in zones_texte)
                or any(se_chevauchent(element.bbox, zone) for zone in zones_formules)
            )
            ancres.append(
                forme_xml(
                    element,
                    compteur[0],
                    z,
                    derriere=derriere,
                )
            )
        elif isinstance(element, TableEl):
            if _tableau_dense_exact(element, page):
                ancres.append(table_cell_background_overlays_xml(element, compteur, z))
                ancres.append(table_grid_overlays_xml(element, compteur, z + 1))
                ancres.append(
                    table_text_overlays_xml(
                        element,
                        compteur,
                        z + 2,
                        relations,
                        page.largeur_emu,
                        polices,
                    )
                )
            elif _table_recouvre_texte_positionne(element, elements_page):
                ancres.append(_table_fond_grille_xml(element, compteur, z))
            else:
                tables.append(
                    table_body_xml(
                        element,
                        relations,
                        strict_geometry=True,
                        positionne=True,
                        texte_cellules=True,
                    )
                )
        elif isinstance(element, LinkZone) and element.uri:
            rel_id = relations.ajouter(element.uri, "hyperlink", externe=True)
            ancres.append(zone_lien_xml(element, compteur[0], z, rel_id))

    grille_xml = None
    if grille_regions_flow:
        # Les images/formes positionnees doivent etre rattachees au premier
        # paragraphe de la page. Si la grille est emise avant ce paragraphe,
        # LibreOffice rattache les ancres au paragraphe suivant et les repousse
        # sur la page suivante.
        grille_xml = _grille_regions_flow_xml(
            paragraphes_flow,
            page,
            compteur,
            relations,
            polices,
        )
    elif not colonnes_flow:
        for z, element in enumerate(paragraphes_ordonnes, start=1):
            if _bbox_dans_table_dense(element.bbox, tables_denses):
                continue
            compteur[0] += 1
            paragraphes_natifs.append(
                zone_paragraphe_xml(
                    _paragraphe_ajuste_largeur(element, polices),
                    compteur[0],
                    z,
                    relations,
                    natif=True,
                    espacement_avant_emu=espacements_avant.get(id(element), 0),
                    polices=polices,
                )
            )
    morceaux.extend(tables)
    if ancres:
        morceaux.append(
            '<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="1" '
            f'w:lineRule="exact"/></w:pPr><w:r>{"".join(ancres)}</w:r></w:p>'
        )
    if grille_xml:
        morceaux.append(grille_xml)
    if colonnes_flow:
        y_colonne_max = max(element.bbox.y1 for colonne in colonnes_flow for element in colonne)
        # Une ligne d'en-tete peut commencer avant le titre pleine largeur. On ne
        # prend donc pas le premier paragraphe de colonne comme frontiere : les
        # zones larges situees dans le tiers superieur sont des en-tetes de page.
        seuil_entete = page.hauteur_emu * 0.35
        pleine_largeur_avant = [
            element for element in paragraphes_pleine_largeur if element.bbox.y0 <= seuil_entete
        ]
        pleine_largeur_apres = [
            element for element in paragraphes_pleine_largeur if element not in pleine_largeur_avant
        ]
        origine_y_emu = max(
            (element.bbox.y1 for element in pleine_largeur_avant),
            default=0,
        )
        precedent_pleine_largeur = 0
        for element in sorted(pleine_largeur_avant, key=lambda item: (item.bbox.y0, item.bbox.x0)):
            compteur[0] += 1
            morceaux.append(
                zone_paragraphe_xml(
                    _paragraphe_ajuste_largeur(element, polices),
                    compteur[0],
                    0,
                    relations,
                    natif=True,
                    espacement_avant_emu=max(0, element.bbox.y0 - precedent_pleine_largeur),
                    polices=polices,
                )
            )
            precedent_pleine_largeur = max(precedent_pleine_largeur, element.bbox.y1)
        morceaux.append(
            _table_colonnes_flow_xml(
                colonnes_flow,
                page,
                compteur,
                relations,
                polices,
                origine_y_emu=origine_y_emu,
            )
        )
        for element in sorted(pleine_largeur_apres, key=lambda item: (item.bbox.y0, item.bbox.x0)):
            compteur[0] += 1
            morceaux.append(
                zone_paragraphe_xml(
                    _paragraphe_ajuste_largeur(element, polices),
                    compteur[0],
                    0,
                    relations,
                    natif=True,
                    espacement_avant_emu=max(0, element.bbox.y0 - y_colonne_max),
                    polices=polices,
                )
            )
    else:
        morceaux.extend(paragraphes_natifs)
    if not derniere:
        morceaux.append(_paragraphe_section_minimal_xml(_section_xml(page)))
    return "".join(morceaux)


def _nombre_lignes_paragraphe(paragraphe: FlowParagraph) -> int:
    if paragraphe.spans:
        return max(1, max(str(span.texte).count("\n") + 1 for span in paragraphe.spans))
    return max(1, str(paragraphe.texte).count("\n") + 1)


def _echelle_verticale_flux(page: Page, elements) -> float:
    """Compresse les pages Word natives qui déborderaient malgré les positions PDF."""
    flux = [
        element
        for element in elements
        if isinstance(element, (FlowParagraph, TableEl)) and getattr(element, "bbox", None) is not None
    ]
    if not flux:
        return 1.0

    total = 0
    precedent_bas = 0
    for element in flux:
        bbox = element.bbox
        total += max(0, bbox.y0 - precedent_bas)
        if isinstance(element, FlowParagraph):
            lignes = _nombre_lignes_paragraphe(element)
            interligne = max(element.interligne_emu, pt_vers_emu(element.size_pt * 1.08))
            total += max(bbox.hauteur, int(interligne * lignes * 1.08))
        else:
            total += bbox.hauteur
        precedent_bas = max(precedent_bas, bbox.y1)

    disponible = max(page.hauteur_emu - pt_vers_emu(4), 1)
    occupation = total / disponible
    if occupation < 0.84:
        return 1.0

    charge_word = 1.0 + min(0.30, max(0.0, occupation - 0.84) * 1.15 + max(0, len(flux) - 8) * 0.012)
    total_estime = total * charge_word
    if total_estime <= disponible:
        return 1.0
    return max(0.78, min(1.0, (disponible / total_estime) * 0.985))


def _page_flux_xml(page: Page, derniere: bool, compteur: list, relations, media: dict, polices: dict | None = None) -> str:
    morceaux = []
    elements = sorted(
        page.elements,
        key=lambda element: (
            getattr(getattr(element, "bbox", None), "y0", 0),
            getattr(getattr(element, "bbox", None), "x0", 0),
        ),
    )
    section = "" if derniere else _section_flux_xml(page)
    fonds = [
        element
        for element in elements
        if isinstance(element, ShapeEl) and element.remplissage
    ]
    fonds_utilises = set()
    for element in elements:
        if not isinstance(element, FlowParagraph):
            continue
        fond = _fond_pour_paragraphe(element, fonds)
        if not fond:
            continue
        fond_element = next(
            (
                item
                for item in fonds
                if item.remplissage == fond and _fond_pour_paragraphe(element, [item]) == fond
            ),
            None,
        )
        if fond_element is not None:
            fonds_utilises.add(id(fond_element))

    zones_flux = [
        element.bbox
        for element in elements
        if isinstance(element, (FlowParagraph, TableEl, TextBox))
    ]
    ancres_visuelles = _ancres_visuelles_xml(
        elements,
        compteur,
        relations,
        media,
        page,
        skip_ids=fonds_utilises,
        zones_flux=zones_flux,
        polices=polices,
    )
    if ancres_visuelles:
        morceaux.append(
            '<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="1" '
            f'w:lineRule="exact"/></w:pPr><w:r>{ancres_visuelles}</w:r></w:p>'
        )

    page_exact_flow = any(
        isinstance(element, FlowParagraph)
        and getattr(element, "orientation", "horizontal") == "horizontal"
        and element.retrait_gauche_emu > 0
        for element in elements
    )
    echelle_verticale = _echelle_verticale_flux(page, elements) if page_exact_flow else 1.0
    precedent_bas = 0

    for z, element in enumerate(elements, start=1):
        bbox = getattr(element, "bbox", None)
        participe_flux = isinstance(element, (FlowParagraph, TableEl))
        if page_exact_flow and participe_flux and bbox is not None:
            gap = bbox.y0 - precedent_bas
            if gap > pt_vers_emu(1):
                morceaux.append(_espace_vertical_xml(gap))

        if isinstance(element, FlowParagraph):
            if getattr(element, "orientation", "horizontal") != "horizontal":
                continue
            fond = _fond_pour_paragraphe(element, fonds)
            if fond:
                fond_element = next(
                    (
                        item
                        for item in fonds
                        if item.remplissage == fond and _fond_pour_paragraphe(element, [item]) == fond
                    ),
                    None,
                )
                if fond_element is not None and fond_element.bbox.largeur > element.bbox.largeur * 1.08:
                    morceaux.append(_paragraphe_fond_fixe_xml(element, relations, fond_element))
                    if page_exact_flow and bbox is not None:
                        precedent_bas = max(precedent_bas, bbox.y1)
                    continue
            morceaux.append(
                _paragraphe_flux_xml(
                    element,
                    relations,
                    fond=fond,
                    largeur_page_emu=page.largeur_emu,
                    polices=polices,
                    espacement_externe=page_exact_flow,
                    echelle_verticale=echelle_verticale,
                )
            )
        elif isinstance(element, TableEl):
            if _table_recouvre_texte_positionne(element, elements):
                morceaux.append(_table_fond_grille_xml(element, compteur, z))
            else:
                morceaux.append(
                    table_body_xml(
                        element,
                        relations,
                        strict_geometry=True,
                        positionne=True,
                        texte_cellules=True,
                    )
                )
        elif isinstance(element, (ImageEl, RasterEl)):
            continue
        elif isinstance(element, ShapeEl):
            continue
        else:
            continue

        if page_exact_flow and participe_flux and bbox is not None:
            precedent_bas = max(precedent_bas, bbox.y1)

    if section:
        morceaux.append(_paragraphe_section_minimal_xml(section))
    return "".join(morceaux)


def _page_tableau_exacte(page: Page) -> bool:
    """Les grandes tables ne doivent jamais être laissées au flux Word."""
    if not page.elements:
        return False
    paysage = page.largeur_emu > page.hauteur_emu
    for element in page.elements:
        if not isinstance(element, TableEl):
            continue
        grande_largeur = element.bbox.largeur >= page.largeur_emu * 0.60
        grande_hauteur = element.bbox.hauteur >= page.hauteur_emu * 0.18
        if paysage or grande_largeur or grande_hauteur:
            return True
    return False


def construire_document_xml_compat(document: Document, relations) -> str:
    """Ancien writer conservé comme façade de compatibilité.

    Le chemin de production Word-native passe par ``RenderPlan`` et
    ``word_native_rewriter``. Cette fonction reste isolée pour les anciens appels
    et les documents non encore migrés; elle ne doit plus recevoir de nouvelles
    décisions de reconstruction.
    """
    morceaux = [_ENTETE]
    compteur = [0]

    for position, page in enumerate(document.pages):
        derniere = position == len(document.pages) - 1
        source_layers = any(
            isinstance(visual, (ImageEl, RasterEl, ShapeEl))
            and visual.z_index is not None
            and any(
                isinstance(text, (TextBox, FlowParagraph))
                and se_chevauchent(visual.bbox, text.bbox)
                for text in page.elements
            )
            for visual in page.elements
        )
        contient_flux = any(isinstance(element, FlowParagraph) for element in page.elements)
        contient_tableau = any(isinstance(element, TableEl) for element in page.elements)
        contient_texte_ancien = any(isinstance(element, TextBox) for element in page.elements)
        page_exacte = any(
            isinstance(element, FlowParagraph) and element.retrait_gauche_emu > 0
            for element in page.elements
        ) or _page_tableau_exacte(page)
        if page_exacte and not source_layers:
            morceaux.append(_page_absolue_xml(page, derniere, compteur, relations, document.media, document.polices))
            if derniere:
                morceaux.append(_section_xml(page))
            continue
        if not source_layers and (contient_flux or (contient_tableau and not contient_texte_ancien)):
            morceaux.append(
                _page_flux_xml(page, derniere, compteur, relations, document.media, document.polices)
            )
            if derniere:
                morceaux.append(_section_flux_xml(page))
            continue

        ancres = _ancres_de_page(page, compteur, relations, document.media, document.polices)
        paragraphe_contenu = f"<w:r>{ancres}</w:r>" if ancres else ""

        if derniere:
            # La section de la dernière page se déclare au niveau du corps, pas dans
            # les propriétés d'un paragraphe. C'est la règle OOXML.
            morceaux.append(f"<w:p>{paragraphe_contenu}</w:p>")
            morceaux.append(_section_xml(page))
        else:
            morceaux.append(
                "<w:p><w:pPr>"
                '<w:spacing w:before="0" w:after="0" w:line="1" w:lineRule="exact"/>'
                f"{_section_xml(page)}</w:pPr>{paragraphe_contenu}</w:p>"
            )

    if not document.pages:
        morceaux.append("<w:p/>")

    morceaux.append(_PIED)
    xml = "".join(morceaux)
    if "mc:AlternateContent" in xml:
        from pdfexact.render.bbox_debug import _ensure_vml_namespaces

        xml = _ensure_vml_namespaces(xml)
    return xml


def construire_document_xml(document: Document, relations) -> str:
    """Point d'entrée historique délégué au writer de compatibilité."""
    return construire_document_xml_compat(document, relations)
