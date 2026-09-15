"""Ouverture du PDF et assemblage du Document.

L'ordre de construction des éléments d'une page fixe leur superposition : vectoriel et
zones rastérisées d'abord — ce sont les fonds —, puis les images, puis le texte, qui doit
rester au-dessus et lisible en toute circonstance.
"""
import pymupdf
import re
import sys

from pdfexact.extract.fonts import collecter_polices
from pdfexact.extract.glyph_images import extraire_glyphes_images
from pdfexact.extract.images import (
    extraire_images,
    extraire_images_inline,
    extraire_images_inline_rasterisees,
    extraire_images_rasterisees,
)
from pdfexact.extract.links import appliquer_liens
from pdfexact.extract.layout_map import construire_layout_map
from pdfexact.extract.ocr import extraire_ocr, extraire_rapidocr, extraire_textes_natifs_zones
from pdfexact.extract.tables import extraire_tableaux, extraire_tableaux_listing
from pdfexact.extract.text import extraire_texte, extraire_texte_glyphes
from pdfexact.extract.vector import (
    SEUIL_CHEMINS_PAR_DEFAUT,
    boite_du_cluster,
    doit_rasteriser,
    extraire_vectoriel,
    regrouper,
)
from pdfexact.fallback.rasterize import (
    nettoyer_images_fond_texte_positionne,
    page_a_des_degrades,
    rasteriser_region,
    rasteriser_region_sans_texte,
)
from pdfexact.geometry import (
    BBox,
    PageGeometry,
    emu_vers_pt,
    pt_vers_emu,
    quantifier_bbox,
    quantifier_coord,
    se_chevauchent,
    union,
)
from pdfexact.ir import (
    Document,
    FlowParagraph,
    ImageEl,
    Line,
    LinkZone,
    Page,
    RasterEl,
    ShapeEl,
    Span,
    TableEl,
    TextBox,
)
from pdfexact.layout import (
    analyser_page,
    classer_regions,
    comprendre_page,
    detecter_layout_ia,
    filtrer_elements_selon_plan,
    planifier_regions,
    zones_layout_du_plan,
    zones_ocr_du_plan,
)
from pdfexact.report import DiagnosticElement, DiagnosticLayout, PageDegradee, Rapport


def _aire(bbox: BBox) -> int:
    return max(0, bbox.largeur) * max(0, bbox.hauteur)


def _intersection(a: BBox, b: BBox) -> int:
    x0 = max(a.x0, b.x0)
    y0 = max(a.y0, b.y0)
    x1 = min(a.x1, b.x1)
    y1 = min(a.y1, b.y1)
    return max(0, x1 - x0) * max(0, y1 - y0)


def _recouvrement_min(a: BBox, b: BBox) -> float:
    return _intersection(a, b) / max(min(_aire(a), _aire(b)), 1)


def _recouvrement_source(a: BBox, b: BBox) -> float:
    return _intersection(a, b) / max(_aire(a), 1)


def _zone_deja_couverte(zone: BBox, zones: list[BBox], seuil: float = 0.70) -> bool:
    return any(_recouvrement_min(zone, existante) >= seuil for existante in zones)


def _bbox_intersecte_page(bbox: BBox, page: Page) -> bool:
    return (
        min(bbox.x1, page.largeur_emu) > max(bbox.x0, 0)
        and min(bbox.y1, page.hauteur_emu) > max(bbox.y0, 0)
    )


def _zone_source_deja_couverte(zone: BBox, zones: list[BBox], seuil: float = 0.75) -> bool:
    return any(_recouvrement_source(zone, existante) >= seuil for existante in zones)


def _zone_touche_tableau(zone: BBox, tableaux: list[TableEl], seuil: float = 0.04) -> bool:
    for tableau in tableaux:
        if _intersection(zone, tableau.bbox) <= 0:
            continue
        if _recouvrement_min(zone, tableau.bbox) >= seuil:
            return True
    return False


def _tableau_ressemble_graphe(tableau: TableEl) -> bool:
    cellules = [cell for row in tableau.rows for cell in row.cells]
    if len(cellules) < 4:
        return False
    textes = [cell.texte.strip() for cell in cellules]
    non_vides = [texte for texte in textes if texte]
    if not non_vides:
        return False

    vides_ratio = 1.0 - (len(non_vides) / max(len(cellules), 1))
    texte_total = " ".join(non_vides).lower()
    mots_table = ("data", "percent", "number", "missing", "refused", "blank", "substance")
    if (
        len(tableau.rows) >= 3
        and len(tableau.col_widths_emu) >= 4
        and vides_ratio <= 0.35
        and sum(1 for mot in mots_table if mot in texte_total) >= 2
    ):
        return False
    chiffres_total = sum(c.isdigit() for c in texte_total)
    lettres_total = sum(c.isalpha() for c in texte_total)
    densite_numerique = chiffres_total >= 8 and chiffres_total >= lettres_total * 0.55
    marqueurs_graphe = sum(
        1
        for marqueur in (
            "energy",
            "ev",
            "states",
            "atom",
            "pdos",
            "kev",
            "groups",
            "gpa",
            "radius",
            "temperature",
            "pressure",
            "mm",
            "∂",
            "partial",
            "t,k",
            "p/gpa",
            "k/gpa",
        )
        if marqueur in texte_total
    )
    courts_ou_numeriques = 0
    longs_libelles = 0
    for texte in non_vides:
        compact = texte.replace("|", " ").replace("\n", " ")
        morceaux = [m for m in compact.split() if m]
        if len(morceaux) <= 3 and sum(c.isdigit() for c in compact) >= sum(c.isalpha() for c in compact):
            courts_ou_numeriques += 1
        if len(morceaux) >= 8:
            longs_libelles += 1
    ratio_axes = courts_ou_numeriques / max(len(non_vides), 1)
    if marqueurs_graphe >= 2 and densite_numerique:
        return True
    if longs_libelles >= 2:
        return False
    return marqueurs_graphe >= 1 and (
        vides_ratio >= 0.25
        or ratio_axes >= 0.35
        or len(tableau.rows) <= 3
        or len(tableau.col_widths_emu) >= 4
    )


def _tableau_ressemble_bandeau_entete(
    tableau: TableEl,
    lignes_natives: list[BBox],
    hauteur_page_emu: int,
) -> bool:
    if tableau.bbox.y0 > hauteur_page_emu * 0.25:
        return False
    if tableau.bbox.hauteur > pt_vers_emu(90):
        return False
    lignes = [
        ligne
        for ligne in lignes_natives
        if _intersection(ligne, tableau.bbox) / max(_aire(ligne), 1) >= 0.45
    ]
    return 1 <= len(lignes) <= 8


def _filtrer_tableaux_contredits_par_ia(
    tableaux: list[TableEl],
    zones_ia,
    largeur_page_emu: int,
    hauteur_page_emu: int,
    *,
    actif: bool,
) -> list[TableEl]:
    if not actif or not zones_ia:
        return tableaux
    return [
        tableau
        for tableau in tableaux
        if _tableau_confirme_par_layout_ia(tableau, zones_ia, largeur_page_emu, hauteur_page_emu)
    ]


def _tableau_confirme_par_layout_ia(
    tableau: TableEl,
    zones_ia,
    largeur_page_emu: int,
    hauteur_page_emu: int,
) -> bool:
    aire_page = max(largeur_page_emu * hauteur_page_emu, 1)
    ratio_page = _aire(tableau.bbox) / aire_page
    cellules = [cell for row in tableau.rows for cell in row.cells]
    dense = len(cellules) >= 80 or len(tableau.rows) >= 28 or (
        len(tableau.rows) >= 12 and len(tableau.col_widths_emu) >= 5
    )
    if dense:
        return True

    zones_table = [zone for zone in zones_ia if getattr(zone, "role", None) == "table"]
    if any(
        _recouvrement_min(tableau.bbox, zone.bbox) >= 0.55
        or _recouvrement_source(tableau.bbox, zone.bbox) >= 0.45
        for zone in zones_table
    ):
        return True

    touche_visuel_ia = any(
        getattr(zone, "role", None) in {"visual", "formula"}
        and _recouvrement_min(zone.bbox, tableau.bbox) >= 0.50
        for zone in zones_ia
    )
    if ratio_page >= 0.30 and touche_visuel_ia:
        return False
    if ratio_page >= 0.45 and not zones_table:
        return False
    return True


def _forme_couverte_par_zone(forme: ShapeEl, zones: list[BBox], seuil: float = 0.55) -> bool:
    return any(_recouvrement_source(forme.bbox, zone) >= seuil for zone in zones)


def _filtrer_formes_couvertes(elements: list, zones: list[BBox]) -> list:
    if not zones:
        return elements
    return [
        element
        for element in elements
        if not (isinstance(element, ShapeEl) and _forme_couverte_par_zone(element, zones))
    ]


def _element_visuel_couvert_par_zone(element, zones: list[BBox], seuil: float = 0.70) -> bool:
    if not isinstance(element, (ShapeEl, ImageEl, RasterEl)):
        return False
    return any(_recouvrement_source(element.bbox, zone) >= seuil for zone in zones)


def _filtrer_elements_visuels_couverts(elements: list, zones: list[BBox]) -> list:
    if not zones:
        return elements
    return [
        element
        for element in elements
        if not _element_visuel_couvert_par_zone(element, zones)
    ]


def _element_texte_couvert_par_zone(element, zones: list[BBox], seuil: float = 0.22) -> bool:
    if not isinstance(element, (TextBox, FlowParagraph)):
        return False
    bbox = getattr(element, "bbox", None)
    if bbox is None:
        return False
    centre_x = (bbox.x0 + bbox.x1) // 2
    centre_y = (bbox.y0 + bbox.y1) // 2
    for zone in zones:
        if zone.x0 <= centre_x <= zone.x1 and zone.y0 <= centre_y <= zone.y1:
            return True
        if _recouvrement_source(bbox, zone) >= seuil:
            return True
    return False


def _filtrer_textes_couverts(elements: list, zones: list[BBox]) -> list:
    if not zones:
        return elements
    return [
        element
        for element in elements
        if not _element_texte_couvert_par_zone(element, zones)
    ]


def _bbox_texte_elementaires(element) -> list[BBox]:
    bboxes: list[BBox] = []
    if isinstance(element, (TextBox, FlowParagraph)):
        for ligne in element.lignes:
            bboxes.append(ligne.bbox)
            bboxes.extend(span.bbox for span in ligne.spans if span.bbox is not None)
        if isinstance(element, FlowParagraph):
            bboxes.extend(span.bbox for span in element.spans if span.bbox is not None)
    bbox = getattr(element, "bbox", None)
    if bbox is not None:
        bboxes.append(bbox)
    return bboxes


def _element_texte_intersecte_zone(element, zones: list[BBox]) -> bool:
    if not isinstance(element, (TextBox, FlowParagraph)):
        return False
    for bbox in _bbox_texte_elementaires(element):
        centre_x = (bbox.x0 + bbox.x1) // 2
        centre_y = (bbox.y0 + bbox.y1) // 2
        for zone in zones:
            if zone.x0 <= centre_x <= zone.x1 and zone.y0 <= centre_y <= zone.y1:
                return True
            if _intersection(bbox, zone) / max(_aire(bbox), 1) >= 0.05:
                return True
    return False


def _filtrer_textes_intersectant_zones(elements: list, zones: list[BBox]) -> list:
    if not zones:
        return elements
    return [
        element
        for element in elements
        if not _element_texte_intersecte_zone(element, zones)
    ]


def _zone_contient_lignes_natives(zone: BBox, lignes_natives: list[BBox], minimum: int = 2) -> bool:
    touches = 0
    for ligne in lignes_natives:
        if _intersection(zone, ligne) <= 0:
            continue
        centre_x = (ligne.x0 + ligne.x1) // 2
        centre_y = (ligne.y0 + ligne.y1) // 2
        if zone.x0 <= centre_x <= zone.x1 and zone.y0 <= centre_y <= zone.y1:
            touches += 1
        elif _recouvrement_source(ligne, zone) >= 0.45:
            touches += 1
        if touches >= minimum:
            return True
    return False


def _filtrer_zones_images_avec_texte_natif(
    zones_ignorees: list[BBox],
    zones_images_source: list[BBox],
    lignes_natives: list[BBox],
) -> list[BBox]:
    if not zones_ignorees or not zones_images_source or not lignes_natives:
        return zones_ignorees
    zones_filtrees: list[BBox] = []
    for zone in zones_ignorees:
        zone_image = any(_recouvrement_min(zone, image) >= 0.55 for image in zones_images_source)
        if zone_image and _zone_contient_lignes_natives(zone, lignes_natives):
            continue
        zones_filtrees.append(zone)
    return zones_filtrees


def _zones_images_lisibles_ocr(zones_images_source: list[BBox], page: Page) -> list[BBox]:
    """Grandes images de page pouvant contenir du texte à reconstruire en Word natif."""
    if not zones_images_source:
        return []
    aire_page = max(page.largeur_emu * page.hauteur_emu, 1)
    lisibles: list[BBox] = []
    for zone in zones_images_source:
        ratio = _aire(zone) / aire_page
        large = zone.largeur >= page.largeur_emu * 0.35
        haute = zone.hauteur >= page.hauteur_emu * 0.08
        if ratio >= 0.08 and large and haute:
            lisibles.append(zone)
    return _dedoublonner_cadres_lecture(lisibles)


def _filtrer_zones_lisibles_ocr(zones_ignorees: list[BBox], zones_lisibles: list[BBox]) -> list[BBox]:
    if not zones_ignorees or not zones_lisibles:
        return zones_ignorees
    return [
        zone
        for zone in zones_ignorees
        if not _zone_deja_couverte(zone, zones_lisibles, seuil=0.82)
    ]


def _zones_visuelles_ia_a_rasteriser(plan, zones_existantes: list[BBox], page: Page) -> list[BBox]:
    zones: list[BBox] = []
    aire_page = max(page.largeur_emu * page.hauteur_emu, 1)
    for item in plan:
        source = str(item.region.style_hints.get("source", ""))
        if source != "paddlex":
            continue
        if item.strategy not in {"raster-image", "raster-immutable"}:
            continue
        if item.kind not in {"image", "scanned-page", "figure-or-diagram", "formula-or-complex-vector"}:
            continue
        if _aire(item.bbox) / aire_page < 0.018:
            continue
        if _zone_source_deja_couverte(item.bbox, zones_existantes + zones, seuil=0.75):
            continue
        zones.append(item.bbox)
    return zones


def _texte_blanc_sur_fond(paragraphe: FlowParagraph) -> bool:
    if (paragraphe.couleur or "").upper() not in {"FFFFFF", "FEFFFF", "FFFFFE"}:
        return False
    return emu_vers_pt(paragraphe.bbox.largeur) >= 80 and emu_vers_pt(paragraphe.bbox.hauteur) <= 42


def _couleur_int_vers_rgb(couleur: int | None) -> tuple[int, int, int]:
    valeur = int(couleur or 0)
    return (valeur >> 16) & 255, (valeur >> 8) & 255, valeur & 255


def _couleur_presque_blanche(couleur: int | None) -> bool:
    r, g, b = _couleur_int_vers_rgb(couleur)
    return r >= 244 and g >= 244 and b >= 244


def _zone_contient_texte_blanc_natif(
    page_pdf,
    zone: BBox,
    geometrie: PageGeometry,
) -> tuple[int, float]:
    rect_zone = pymupdf.Rect(
        emu_vers_pt(zone.x0),
        emu_vers_pt(zone.y0),
        emu_vers_pt(zone.x1),
        emu_vers_pt(zone.y1),
    )
    caracteres = 0
    taille_max = 0.0
    for bloc in page_pdf.get_text("dict").get("blocks", []):
        if bloc.get("type") != 0:
            continue
        for ligne in bloc.get("lines", []):
            for span in ligne.get("spans", []):
                texte = span.get("text", "").strip()
                if not texte or not _couleur_presque_blanche(span.get("color")):
                    continue
                rect_span = pymupdf.Rect(span.get("bbox", ligne.get("bbox", (0, 0, 0, 0))))
                bbox_span = geometrie.bbox_depuis_rect_natif(rect_span)
                rect_affiche = pymupdf.Rect(
                    emu_vers_pt(bbox_span.x0),
                    emu_vers_pt(bbox_span.y0),
                    emu_vers_pt(bbox_span.x1),
                    emu_vers_pt(bbox_span.y1),
                )
                if rect_affiche.intersect(rect_zone).is_empty:
                    continue
                caracteres += len(texte)
                taille_max = max(taille_max, float(span.get("size", 0) or 0))
    return caracteres, taille_max


def _ratio_fond_colore_sombre(page_pdf, zone: BBox, geometrie: PageGeometry) -> float:
    rect = pymupdf.Rect(
        emu_vers_pt(zone.x0),
        emu_vers_pt(zone.y0),
        emu_vers_pt(zone.x1),
        emu_vers_pt(zone.y1),
    ).intersect(pymupdf.Rect(0, 0, geometrie.largeur_pt, geometrie.hauteur_pt))
    if rect.is_empty:
        return 0.0
    pix = page_pdf.get_pixmap(
        matrix=pymupdf.Matrix(0.25, 0.25),
        clip=geometrie.rect_affiche_vers_natif(rect),
        alpha=False,
    )
    if pix.width <= 0 or pix.height <= 0:
        return 0.0
    total = pix.width * pix.height
    actifs = 0
    pas = pix.n
    samples = pix.samples
    for offset in range(0, len(samples), pas):
        r, g, b = samples[offset], samples[offset + 1], samples[offset + 2]
        luminosite = 0.299 * r + 0.587 * g + 0.114 * b
        saturation = max(r, g, b) - min(r, g, b)
        if luminosite < 210 and saturation >= 35:
            actifs += 1
    return actifs / max(total, 1)


def _zone_visuelle_garde_texte_original(
    page_pdf,
    zone: BBox,
    page: Page,
    geometrie: PageGeometry,
) -> bool:
    aire_page = max(page.largeur_emu * page.hauteur_emu, 1)
    if _aire(zone) / aire_page < 0.012:
        return False
    caracteres_blancs, taille_max = _zone_contient_texte_blanc_natif(page_pdf, zone, geometrie)
    if caracteres_blancs < 8 or taille_max < 14:
        return False
    return _ratio_fond_colore_sombre(page_pdf, zone, geometrie) >= 0.28


def _bande_fond_depuis_rendu(page_pdf, bbox: BBox, geometrie: PageGeometry) -> tuple[BBox, str] | None:
    import pymupdf

    y0 = max(emu_vers_pt(bbox.y0) - 4, 0)
    y1 = min(emu_vers_pt(bbox.y1) + 4, geometrie.hauteur_pt)
    rect_affiche = pymupdf.Rect(0, y0, geometrie.largeur_pt, y1)
    pix = page_pdf.get_pixmap(
        matrix=pymupdf.Matrix(1, 1),
        clip=geometrie.rect_affiche_vers_natif(rect_affiche),
        alpha=False,
    )
    if pix.width <= 1 or pix.height <= 1:
        return None

    samples = pix.samples
    colonnes: list[bool] = []
    couleurs: list[tuple[int, int, int]] = []
    for x in range(pix.width):
        sombres = 0
        rs = gs = bs = 0
        for y in range(pix.height):
            offset = (y * pix.width + x) * pix.n
            r, g, b = samples[offset], samples[offset + 1], samples[offset + 2]
            if 0.299 * r + 0.587 * g + 0.114 * b < 235:
                sombres += 1
                rs += r
                gs += g
                bs += b
        colonnes.append(sombres / max(pix.height, 1) >= 0.35)
        if sombres:
            couleurs.append((rs // sombres, gs // sombres, bs // sombres))

    centre = max(0, min(round(emu_vers_pt((bbox.x0 + bbox.x1) // 2)), len(colonnes) - 1))
    if not colonnes[centre]:
        actifs = [i for i, actif in enumerate(colonnes) if actif and abs(i - centre) < 80]
        if not actifs:
            return None
        centre = min(actifs, key=lambda item: abs(item - centre))

    gauche = centre
    while gauche > 0 and colonnes[gauche - 1]:
        gauche -= 1
    droite = centre
    while droite + 1 < len(colonnes) and colonnes[droite + 1]:
        droite += 1

    if droite - gauche < emu_vers_pt(bbox.largeur) * 0.8:
        return None
    if not couleurs:
        return None

    r = round(sum(c[0] for c in couleurs) / len(couleurs))
    g = round(sum(c[1] for c in couleurs) / len(couleurs))
    b = round(sum(c[2] for c in couleurs) / len(couleurs))
    if 0.299 * r + 0.587 * g + 0.114 * b > 230:
        return None

    bande = BBox(pt_vers_emu(gauche), pt_vers_emu(y0), pt_vers_emu(droite + 1), pt_vers_emu(y1))
    return bande, f"{r:02X}{g:02X}{b:02X}"


def _fonds_synthetiques_texte_inverse(
    page_pdf,
    elements_ocr: list,
    page_ir: Page,
    geometrie: PageGeometry,
) -> list[ShapeEl]:
    fonds_existants = [
        element.bbox
        for element in page_ir.elements
        if isinstance(element, ShapeEl)
        and element.remplissage
        and element.remplissage.upper() not in {"FFFFFF", "FEFEFE"}
    ]
    fonds: list[ShapeEl] = []
    for element in elements_ocr:
        if not isinstance(element, FlowParagraph) or not _texte_blanc_sur_fond(element):
            continue
        if any(se_chevauchent(element.bbox, fond) for fond in fonds_existants + [fond.bbox for fond in fonds]):
            continue
        detecte = _bande_fond_depuis_rendu(page_pdf, element.bbox, geometrie)
        if detecte is None:
            continue
        bbox, couleur = detecte
        fonds.append(ShapeEl(bbox=bbox, chemins=[], remplissage=couleur, contour=None, epaisseur_emu=0))
    return fonds


def _limiter_bbox_page(bbox: BBox, page: Page) -> BBox:
    x0 = max(0, min(bbox.x0, page.largeur_emu - 1))
    y0 = max(0, min(bbox.y0, page.hauteur_emu - 1))
    x1 = max(x0 + 1, min(bbox.x1, page.largeur_emu))
    y1 = max(y0 + 1, min(bbox.y1, page.hauteur_emu))
    return BBox(x0, y0, x1, y1)


def _qbbox(bbox: BBox, page: Page) -> BBox:
    return _limiter_bbox_page(quantifier_bbox(bbox), page)


def _quantifier_span(span: Span, page: Page) -> None:
    if span.bbox is not None:
        span.bbox = _qbbox(span.bbox, page)


def _quantifier_ligne(ligne: Line, page: Page) -> None:
    ligne.bbox = _qbbox(ligne.bbox, page)
    ligne.hauteur_ligne_emu = max(1, quantifier_coord(ligne.hauteur_ligne_emu))
    ligne.largeur_cible_emu = max(1, quantifier_coord(ligne.largeur_cible_emu))
    for span in ligne.spans:
        _quantifier_span(span, page)


def _quantifier_element(element, page: Page) -> None:
    if hasattr(element, "bbox"):
        element.bbox = _qbbox(element.bbox, page)
    if isinstance(element, TextBox):
        for ligne in element.lignes:
            _quantifier_ligne(ligne, page)
    elif isinstance(element, FlowParagraph):
        for ligne in element.lignes:
            _quantifier_ligne(ligne, page)
        element.retrait_gauche_emu = max(0, quantifier_coord(element.retrait_gauche_emu))
        element.retrait_droite_emu = max(0, quantifier_coord(element.retrait_droite_emu))
        element.retrait_premiere_ligne_emu = quantifier_coord(element.retrait_premiere_ligne_emu)
        element.espace_avant_emu = max(0, quantifier_coord(element.espace_avant_emu))
        element.espace_apres_emu = max(0, quantifier_coord(element.espace_apres_emu))
        element.interligne_emu = max(0, quantifier_coord(element.interligne_emu))
        for span in element.spans:
            _quantifier_span(span, page)
    elif isinstance(element, TableEl):
        element.col_widths_emu = [max(1, quantifier_coord(largeur)) for largeur in element.col_widths_emu]
        for row in element.rows:
            row.bbox = _qbbox(row.bbox, page)
            for cell in row.cells:
                cell.bbox = _qbbox(cell.bbox, page)
                for span in cell.spans:
                    _quantifier_span(span, page)
    elif isinstance(element, ShapeEl):
        element.epaisseur_emu = max(0, quantifier_coord(element.epaisseur_emu))
        element.chemins = [
            [
                (
                    commande,
                    tuple(
                        (quantifier_coord(x), quantifier_coord(y))
                        for x, y in points
                    ),
                )
                for commande, points in chemin
            ]
            for chemin in element.chemins
        ]


def _quantifier_page(page: Page) -> None:
    for element in page.elements:
        _quantifier_element(element, page)


def _cadres_lecture_depuis_comprehension(comprehension) -> list[BBox]:
    if comprehension is None:
        return []
    return [
        element.bbox
        for element in comprehension.elements
        if element.strategy == "word-text"
        and element.role in {"text-column", "caption", "heading", "list"}
    ]


def _cadres_lecture_depuis_plan(plan) -> list[BBox]:
    cadres_natifs: list[BBox] = []
    cadres_fallback: list[BBox] = []
    cadres_structurels: list[BBox] = []
    cadres_preservation: list[BBox] = []

    for item in plan:
        style_hints = getattr(item.region, "style_hints", {}) or {}
        source = str(style_hints.get("source", ""))
        table_ia = item.strategy == "word-table" and source != "pdf-table"
        if not table_ia and (
            item.strategy != "word-text"
            or item.kind not in {"text-column", "caption", "heading", "list", "ai-zone"}
        ):
            continue
        reasons = {str(reason) for reason in style_hints.get("reasons", [])}
        if table_ia:
            cadres_fallback.append(item.bbox)
        elif source in {"native-text-in-protected-visual", "native-text-in-shape"} or reasons & {
            "native-text-inside-protected-visual",
            "native-text-inside-shape",
        }:
            cadres_preservation.append(item.bbox)
        elif item.kind == "text-column" and source == "native-lines":
            cadres_natifs.append(item.bbox)
        elif item.kind == "text-column":
            cadres_fallback.append(item.bbox)
        else:
            cadres_structurels.append(item.bbox)

    cadres_principaux = _fusionner_cadres_lecture(cadres_natifs) if cadres_natifs else []
    if not cadres_principaux:
        cadres_principaux = _fusionner_cadres_lecture(cadres_fallback)
    else:
        cadres_structurels.extend(_cadres_hors_couverture(_fusionner_cadres_lecture(cadres_fallback), cadres_principaux))

    cadres = cadres_principaux + _cadres_hors_couverture(cadres_structurels, cadres_principaux)
    cadres.extend(_cadres_hors_couverture(cadres_preservation, cadres))
    return _dedoublonner_cadres_lecture(cadres)


def _fusionner_cadres_lecture(cadres: list[BBox]) -> list[BBox]:
    if not cadres:
        return []
    largeur_min = pt_vers_emu(20)
    hauteur_min = pt_vers_emu(10)
    clusters: list[BBox] = []
    for cadre in sorted(cadres, key=lambda bbox: (bbox.x0, bbox.y0, bbox.x1)):
        if cadre.largeur < largeur_min or cadre.hauteur < hauteur_min:
            continue
        meilleur_index: int | None = None
        meilleur_score = 0.0
        for index, cluster in enumerate(clusters):
            score = _score_meme_cadre_lecture(cadre, cluster)
            if score > meilleur_score:
                meilleur_index = index
                meilleur_score = score
        if meilleur_index is None or meilleur_score < 1.0:
            clusters.append(cadre)
        else:
            clusters[meilleur_index] = union(clusters[meilleur_index], cadre)
    return sorted(clusters, key=lambda bbox: (bbox.x0, bbox.y0))


def _score_meme_cadre_lecture(a: BBox, b: BBox) -> float:
    largeur_min = max(min(a.largeur, b.largeur), 1)
    chevauchement_x = max(0, min(a.x1, b.x1) - max(a.x0, b.x0))
    ratio_x = chevauchement_x / largeur_min
    tolerance_ancrage = pt_vers_emu(18)
    meme_gauche = abs(a.x0 - b.x0) <= tolerance_ancrage
    meme_droite = abs(a.x1 - b.x1) <= tolerance_ancrage
    centres_proches = abs(((a.x0 + a.x1) // 2) - ((b.x0 + b.x1) // 2)) <= max(
        pt_vers_emu(42),
        largeur_min // 2,
    )
    if ratio_x >= 0.45:
        return 2.0 + ratio_x
    if ratio_x >= 0.25 and (meme_gauche or meme_droite or centres_proches):
        return 1.5 + ratio_x
    if meme_gauche and meme_droite:
        return 1.25
    if meme_gauche and centres_proches:
        return 1.1
    return 0.0


def _cadres_hors_couverture(cadres: list[BBox], reference: list[BBox]) -> list[BBox]:
    if not reference:
        return cadres
    return [cadre for cadre in cadres if not any(_recouvrement_source(cadre, ref) >= 0.80 for ref in reference)]


def _dedoublonner_cadres_lecture(cadres: list[BBox]) -> list[BBox]:
    resultat: list[BBox] = []
    for cadre in sorted(cadres, key=lambda bbox: (bbox.y0, bbox.x0, -bbox.largeur * bbox.hauteur)):
        if any(_recouvrement_min(cadre, existant) >= 0.92 for existant in resultat):
            continue
        resultat.append(cadre)
    return sorted(resultat, key=lambda bbox: (bbox.x0, bbox.y0))


def _attacher_frames_texte(elements: list, plan) -> list:
    """Associe chaque ligne native au frame de compréhension qui la contient."""
    if not plan:
        return elements
    frames = [
        (index, item)
        for index, item in enumerate(plan)
        if item.strategy == "word-text"
        and item.kind in {"text-column", "caption", "heading", "list", "ai-zone"}
        and item.region is not None
    ]
    if not frames:
        return elements

    for element in elements:
        if not isinstance(element, (TextBox, FlowParagraph)):
            continue
        lignes = element.lignes if isinstance(element, FlowParagraph) else element.lignes
        frame_lignes = []
        for ligne in lignes:
            meilleur = _meilleur_frame_ligne(ligne.bbox, frames)
            if meilleur is None:
                continue
            frame_index, item = meilleur
            role = item.kind
            frame_id = f"{frame_index}:{role}:{item.bbox.x0}:{item.bbox.y0}:{item.bbox.x1}:{item.bbox.y1}"
            ligne.layout_frame_id = frame_id
            ligne.layout_frame_role = role
            ligne.layout_frame_strategy = item.strategy
            ligne.layout_frame_bbox = item.bbox
            frame_lignes.append((frame_id, role, item.strategy, item.bbox))
        if frame_lignes:
            frame_id, role, strategy, bbox = frame_lignes[0]
            element.layout_frame_id = frame_id
            element.layout_frame_role = role
            element.layout_frame_strategy = strategy
            element.layout_frame_bbox = bbox
    return elements


def _meilleur_frame_ligne(bbox: BBox, frames) -> tuple[int, object] | None:
    centre_x = (bbox.x0 + bbox.x1) // 2
    centre_y = (bbox.y0 + bbox.y1) // 2
    aire_ligne = max(bbox.largeur * bbox.hauteur, 1)
    meilleur = None
    meilleur_score = 0.0
    for frame_index, item in frames:
        frame = item.bbox
        contient = frame.x0 <= centre_x <= frame.x1 and frame.y0 <= centre_y <= frame.y1
        if not contient and not se_chevauchent(bbox, frame):
            continue
        x0 = max(bbox.x0, frame.x0)
        y0 = max(bbox.y0, frame.y0)
        x1 = min(bbox.x1, frame.x1)
        y1 = min(bbox.y1, frame.y1)
        couverture = max(0, x1 - x0) * max(0, y1 - y0) / aire_ligne
        if not contient and couverture < 0.45:
            continue
        role = item.kind
        role_bonus = 0.35 if role == "text-column" else 0.15
        aire_frame = max(frame.largeur * frame.hauteur, 1)
        precision = min(1.0, aire_ligne / aire_frame)
        score = couverture + (0.75 if contient else 0.0) + role_bonus + precision * 0.08
        if score > meilleur_score:
            meilleur = (frame_index, item)
            meilleur_score = score
    return meilleur


def _dedoublonner_textes_positionnes(page: Page) -> None:
    candidats: list[tuple[int, TextBox, Line, str]] = []
    for index, element in enumerate(page.elements):
        if not isinstance(element, TextBox) or len(element.lignes) != 1:
            continue
        ligne = element.lignes[0]
        texte = _compact_textbox_line(ligne)
        if texte:
            candidats.append((index, element, ligne, texte))
    if len(candidats) < 2:
        return

    supprimer: set[int] = set()
    for i, (index_a, element_a, ligne_a, texte_a) in enumerate(candidats):
        if index_a in supprimer:
            continue
        for index_b, element_b, ligne_b, texte_b in candidats[i + 1 :]:
            if index_b in supprimer or texte_a != texte_b:
                continue
            if not _lignes_dupliquees(ligne_a.bbox, ligne_b.bbox):
                continue
            gagnant = _meilleur_texte_duplique(element_a, ligne_a, element_b, ligne_b)
            supprimer.add(index_b if gagnant is element_a else index_a)
            if gagnant is element_b:
                break
    if supprimer:
        page.elements = [element for index, element in enumerate(page.elements) if index not in supprimer]


def _compact_textbox_line(ligne: Line) -> str:
    texte = "".join(span.texte for span in ligne.spans).strip().casefold()
    return re.sub(r"\s+", " ", texte)


def _lignes_dupliquees(a: BBox, b: BBox) -> bool:
    if se_chevauchent(a, b) and _recouvrement_min(a, b) >= 0.55:
        return True
    dx = abs(((a.x0 + a.x1) // 2) - ((b.x0 + b.x1) // 2))
    dy = abs(((a.y0 + a.y1) // 2) - ((b.y0 + b.y1) // 2))
    return dx <= pt_vers_emu(3) and dy <= pt_vers_emu(3)


def _meilleur_texte_duplique(a: TextBox, ligne_a: Line, b: TextBox, ligne_b: Line) -> TextBox:
    return a if _score_texte_positionne(a, ligne_a) >= _score_texte_positionne(b, ligne_b) else b


def _score_texte_positionne(element: TextBox, ligne: Line) -> float:
    score = 0.0
    if getattr(element, "preserve_as_textbox", False):
        score += 3.0
    if ligne.layout_frame_id:
        score += 1.0
    if ligne.spans and all(getattr(span, "bbox", None) is not None for span in ligne.spans if span.texte.strip()):
        score += 0.5
    score -= (ligne.bbox.largeur * ligne.bbox.hauteur) / max(pt_vers_emu(500) * pt_vers_emu(500), 1)
    return score


def _diagnostic_layout(index: int, resume_analyse: str, comprehension, plan, layout_ai=None) -> DiagnosticLayout:
    elements: dict[str, int] = {}
    for element in comprehension.elements:
        elements[element.role] = elements.get(element.role, 0) + 1
    strategies: dict[str, int] = {}
    for item in plan:
        strategies[item.strategy] = strategies.get(item.strategy, 0) + 1
    inventory = _inventaire_layout(comprehension, plan)
    return DiagnosticLayout(
        index=index,
        resume=f"{resume_analyse}; {comprehension.resume()}",
        profiles=sorted(comprehension.profiles),
        elements=elements,
        strategies=strategies,
        inventory=inventory,
        zones_ocr=len(zones_ocr_du_plan(plan)),
        zones_layout=len(zones_layout_du_plan(plan)),
        layout_ai=layout_ai.to_report() if layout_ai is not None else {},
    )


def _bbox_report(bbox: BBox) -> dict[str, int]:
    return {"x0": bbox.x0, "y0": bbox.y0, "x1": bbox.x1, "y1": bbox.y1}


def _inventaire_layout(comprehension, plan) -> list[DiagnosticElement]:
    inventaire: list[DiagnosticElement] = []
    vus: set[tuple] = set()

    def ajouter(kind, role, source, strategy, bbox, editable, confidence, reasons):
        cle = (kind, role, source, strategy, bbox.x0, bbox.y0, bbox.x1, bbox.y1)
        if cle in vus:
            return
        vus.add(cle)
        inventaire.append(
            DiagnosticElement(
                kind=kind,
                role=role,
                source=source,
                strategy=strategy,
                bbox=_bbox_report(bbox),
                editable=bool(editable),
                confidence=round(float(confidence), 4),
                reasons=[str(reason) for reason in reasons],
            )
        )

    for element in comprehension.elements:
        ajouter(
            element.kind,
            element.role,
            element.source,
            element.strategy,
            element.bbox,
            element.editable,
            element.confidence,
            element.reasons,
        )

    for item in plan:
        hints = getattr(item.region, "style_hints", {}) or {}
        ajouter(
            item.kind,
            item.kind,
            str(hints.get("source", "layout-plan")),
            item.strategy,
            item.bbox,
            item.editable,
            item.confidence,
            hints.get("reasons", []),
        )

    return sorted(inventaire, key=lambda item: (item.bbox["y0"], item.bbox["x0"], item.kind, item.role))


def _fond_vectoriel_significatif(cluster: list[ShapeEl], aire_page: int, flux_word: bool = False) -> bool:
    """Garde les grands aplats utiles au layout, pas les artefacts de glyphes/traits."""
    min_dimension = pt_vers_emu(4)
    min_aire = max(int(aire_page * 0.001), pt_vers_emu(8) * pt_vers_emu(8))
    for element in cluster:
        if not isinstance(element, ShapeEl) or not element.remplissage:
            continue
        couleur = element.remplissage.upper()
        if couleur in {"FFFFFF", "FEFEFE"}:
            continue
        if flux_word and couleur in {"000000", "010101", "020202", "808080", "C0C0C0"}:
            continue
        if element.bbox.largeur < min_dimension or element.bbox.hauteur < min_dimension:
            continue
        if _aire(element.bbox) >= min_aire:
            return True
    return False


def _vectoriel_structurel_significatif(cluster: list[ShapeEl], page: Page) -> bool:
    """Garde traits, cadres et courbes utiles sans reprendre les micro-glyphes."""
    largeur_page = max(page.largeur_emu, 1)
    hauteur_page = max(page.hauteur_emu, 1)
    for element in cluster:
        if not isinstance(element, ShapeEl):
            continue
        if not element.contour or element.epaisseur_emu <= 0:
            continue
        largeur = max(element.bbox.largeur, 1)
        hauteur = max(element.bbox.hauteur, 1)
        long_horizontal = hauteur <= pt_vers_emu(3) and largeur >= max(pt_vers_emu(32), largeur_page * 0.08)
        long_vertical = largeur <= pt_vers_emu(3) and hauteur >= max(pt_vers_emu(32), hauteur_page * 0.06)
        cadre_ou_courbe = largeur >= pt_vers_emu(24) and hauteur >= pt_vers_emu(12) and len(element.chemins) <= 80
        if long_horizontal or long_vertical or cadre_ou_courbe:
            return True
    return False


def _forme_bordure_page_clusterisante(forme: ShapeEl, page: Page) -> bool:
    if forme.remplissage or not forme.contour:
        return False
    aire_page = max(page.largeur_emu * page.hauteur_emu, 1)
    ratio = (forme.bbox.largeur * forme.bbox.hauteur) / aire_page
    if ratio < 0.55:
        return False
    return forme.epaisseur_emu <= pt_vers_emu(2)


def _remplir_page(
    page_ir,
    page_pdf,
    doc,
    document,
    polices,
    dpi,
    seuil_raster,
    rapport,
    text_mode,
    ocr_granularity,
    ocr_layout,
    layout_ai,
    layout_provider,
    layout_model,
    layout_model_root,
    layout_device,
    verbose,
):
    """Construit les éléments d'une page, dans l'ordre de superposition."""
    geometrie = PageGeometry.depuis_page(page_pdf)
    degrades = page_a_des_degrades(doc, page_pdf)
    zones_visuelles: list[BBox] = []
    formes_vectorielles: list[ShapeEl] = []
    zones_rasterisees: list[BBox] = []
    aire_page = max(page_ir.largeur_emu * page_ir.hauteur_emu, 1)
    tableaux_detectes: list[TableEl] = []
    zones_tableaux: list[BBox] = []
    zones_faux_tableaux: list[BBox] = []
    zones_textes_visuelles_natives: list[BBox] = []
    zones_images_lisibles: list[BBox] = []
    layout_map_natif_visuel = None
    analyse_layout = None
    page_layout_ai = None
    lignes_natives: list[BBox] = []

    if text_mode == "rapidocr" and ocr_layout in {"hybrid", "word-native"}:
        analyse_layout = analyser_page(page_pdf, geometrie=geometrie)
        lignes_natives = analyse_layout.native_line_bboxes()
        if layout_ai:
            page_layout_ai = detecter_layout_ia(
                page_pdf,
                analyse_layout,
                provider=layout_provider,
                model=layout_model,
                model_root=layout_model_root,
                device=layout_device,
            )
            if verbose:
                suffixe = f", avertissements={','.join(page_layout_ai.warnings)}" if page_layout_ai.warnings else ""
                print(
                    f"      layout IA: {page_layout_ai.status}, zones={len(page_layout_ai.zones)}{suffixe}",
                    file=sys.stderr,
                )

    if text_mode == "rapidocr" and ocr_layout in {"hybrid", "word-native"}:
        tableaux_bruts = extraire_tableaux(page_pdf, polices, geometrie=geometrie)
        for tableau_listing in extraire_tableaux_listing(page_pdf, polices, geometrie=geometrie):
            if not _zone_deja_couverte(tableau_listing.bbox, [tableau.bbox for tableau in tableaux_bruts], seuil=0.55):
                tableaux_bruts.append(tableau_listing)
        for tableau in tableaux_bruts:
            if _tableau_ressemble_graphe(tableau):
                zones_faux_tableaux.append(tableau.bbox)
            elif _tableau_ressemble_bandeau_entete(tableau, lignes_natives, page_ir.hauteur_emu):
                continue
            else:
                tableaux_detectes.append(tableau)
        if page_layout_ai is not None:
            tableaux_detectes = _filtrer_tableaux_contredits_par_ia(
                tableaux_detectes,
                page_layout_ai.zones,
                page_ir.largeur_emu,
                page_ir.hauteur_emu,
                actif=page_layout_ai.status == "layout_ai_detected",
            )
        zones_tableaux = [tableau.bbox for tableau in tableaux_detectes]

    formes_pdf = extraire_vectoriel(page_pdf, geometrie=geometrie)
    formes_a_regrouper: list[ShapeEl] = []
    for forme in formes_pdf:
        if _forme_bordure_page_clusterisante(forme, page_ir):
            if text_mode != "rapidocr" or ocr_layout in {"hybrid", "word-native"}:
                page_ir.elements.append(forme)
                formes_vectorielles.append(forme)
            continue
        formes_a_regrouper.append(forme)
    for cluster in regrouper(formes_a_regrouper):
        boite_cluster = boite_du_cluster(cluster)
        if not _bbox_intersecte_page(boite_cluster, page_ir):
            continue
        if doit_rasteriser(cluster, degrades, seuil_raster):
            if _zone_visuelle_garde_texte_original(page_pdf, boite_cluster, page_ir, geometrie):
                raster = rasteriser_region_sans_texte(
                    page_pdf,
                    boite_cluster,
                    document.media,
                    dpi=dpi,
                    geometrie=geometrie,
                )
                zones_textes_visuelles_natives.append(raster.bbox)
            else:
                raster = rasteriser_region(page_pdf, boite_cluster, document.media, dpi=dpi)
            page_ir.elements.append(raster)
            zones_rasterisees.append(raster.bbox)
            aire_cluster = max(raster.bbox.largeur, 0) * max(raster.bbox.hauteur, 0)
            if aire_cluster / aire_page <= 0.18:
                zones_visuelles.append(raster.bbox)
            rapport.clusters_rasterises += 1
        elif text_mode == "rapidocr" and ocr_layout in {"reflow", "hybrid", "word-native"}:
            # En reflow, le texte devient un vrai flux Word. Les petits traits PDF
            # se décorrèlent des paragraphes. En hybrid/word-native page-exact, on garde
            # les aplats significatifs en coordonnées absolues.
            if (
                ocr_layout in {"hybrid", "word-native"}
                and (
                    _fond_vectoriel_significatif(cluster, aire_page, flux_word=False)
                    or _vectoriel_structurel_significatif(cluster, page_ir)
                )
                and not any(_recouvrement_min(boite_cluster, zone) > 0.18 for zone in zones_tableaux)
            ):
                page_ir.elements.extend(cluster)
                formes_vectorielles.extend(cluster)
            continue
        else:
            page_ir.elements.extend(cluster)
            formes_vectorielles.extend(cluster)

    if text_mode == "rapidocr" and ocr_layout in {"reflow", "hybrid", "word-native"}:
        images = extraire_images_rasterisees(
            page_pdf,
            doc,
            document.media,
            dpi=dpi,
            geometrie=geometrie,
            supprimer_texte_natif=ocr_layout == "word-native",
        )
        images_inline = extraire_images_inline_rasterisees(
            page_pdf,
            document.media,
            deja_posees=images,
            dpi=dpi,
            geometrie=geometrie,
            supprimer_texte_natif=ocr_layout == "word-native",
        )
    else:
        images = extraire_images(page_pdf, doc, document.media, geometrie=geometrie)
        images_inline = extraire_images_inline(
            page_pdf,
            document.media,
            deja_posees=images,
            geometrie=geometrie,
        )
    page_ir.elements.extend(images)
    page_ir.elements.extend(images_inline)
    zones_images_source = [image.bbox for image in images + images_inline]
    if ocr_layout == "word-native":
        for zone_image in zones_images_source:
            if _zone_visuelle_garde_texte_original(page_pdf, zone_image, page_ir, geometrie):
                zones_textes_visuelles_natives.append(zone_image)
    if ocr_layout == "word-native":
        zones_images_lisibles = _zones_images_lisibles_ocr(zones_images_source, page_ir)
    for zone in zones_faux_tableaux:
        zones_visuelles.append(zone)
        if not _zone_deja_couverte(zone, zones_rasterisees + zones_images_source, seuil=0.55):
            raster = rasteriser_region(page_pdf, zone, document.media, dpi=dpi)
            page_ir.elements.append(raster)
            zones_rasterisees.append(raster.bbox)
            rapport.clusters_rasterises += 1
    zones_images = zones_visuelles + zones_images_source
    if verbose and images_inline:
        print(f"      images inline: {len(images_inline)} bloc(s)", file=sys.stderr)
    if verbose and zones_visuelles:
        print(f"      zones vectorielles immuables: {len(zones_visuelles)}", file=sys.stderr)

    tableaux = []
    if text_mode == "rapidocr" and ocr_layout in {"hybrid", "word-native"}:
        tableaux = tableaux_detectes
        if tableaux:
            page_ir.elements.extend(tableaux)
            zones_images.extend(tableau.bbox for tableau in tableaux)
            if verbose:
                print(f"      tableaux Word: {len(tableaux)}", file=sys.stderr)

    comprehension = None
    if text_mode == "rapidocr" and ocr_layout in {"hybrid", "word-native"}:
        if analyse_layout is None:
            analyse_layout = analyser_page(page_pdf, geometrie=geometrie)
            lignes_natives = analyse_layout.native_line_bboxes()
        if ocr_layout == "hybrid":
            carte_preview = construire_layout_map(
                page_pdf,
                zones_visuelles=zones_images,
                dpi=dpi,
                geometrie=geometrie,
            )
            lignes_natives = [ligne.bbox for ligne in carte_preview.lignes_visuelles_natives()]
        comprehension = comprendre_page(
            largeur_emu=page_ir.largeur_emu,
            hauteur_emu=page_ir.hauteur_emu,
            tableaux=tableaux,
            images=images + images_inline,
            formes=formes_pdf,
            zones_rasterisees=zones_rasterisees,
            lignes_natives=lignes_natives,
            zones_ia=page_layout_ai.zones if page_layout_ai else None,
        )
        plan_layout = planifier_regions(classer_regions(analyse_layout, comprehension))
        rapport.diagnostics_layout.append(
            _diagnostic_layout(page_ir.index, analyse_layout.resume(), comprehension, plan_layout, page_layout_ai)
        )
        zones_vectorielles_complexes = [
            item.bbox
            for item in plan_layout
            if item.region.style_hints.get("source") == "vector-cluster"
            and item.strategy == "raster-immutable"
            and not _zone_deja_couverte(item.bbox, zones_rasterisees)
            and not _zone_deja_couverte(item.bbox, [tableau.bbox for tableau in tableaux], seuil=0.55)
            and not _zone_touche_tableau(item.bbox, tableaux)
        ]
        if zones_vectorielles_complexes:
            page_ir.elements = _filtrer_formes_couvertes(
                page_ir.elements,
                zones_vectorielles_complexes,
            )
            formes_vectorielles = [
                forme
                for forme in formes_vectorielles
                if not _forme_couverte_par_zone(forme, zones_vectorielles_complexes)
            ]
            for zone in zones_vectorielles_complexes:
                if _zone_visuelle_garde_texte_original(page_pdf, zone, page_ir, geometrie):
                    zones_textes_visuelles_natives.append(zone)
                    raster = rasteriser_region_sans_texte(
                        page_pdf,
                        zone,
                        document.media,
                        dpi=dpi,
                        geometrie=geometrie,
                    )
                else:
                    zones_textes_visuelles_natives.append(zone)
                    raster = rasteriser_region_sans_texte(
                        page_pdf,
                        zone,
                        document.media,
                        dpi=dpi,
                        geometrie=geometrie,
                    )
                page_ir.elements.append(raster)
                zones_rasterisees.append(raster.bbox)
                rapport.clusters_rasterises += 1
            if verbose:
                print(
                    f"      zones vectorielles complexes rastérisées: {len(zones_vectorielles_complexes)}",
                    file=sys.stderr,
                )
        zones_visuelles_ia = _zones_visuelles_ia_a_rasteriser(
            plan_layout,
            zones_rasterisees + zones_images_source + [tableau.bbox for tableau in tableaux],
            page_ir,
        )
        zones_visuelles_ia = [
            zone for zone in zones_visuelles_ia if not _zone_touche_tableau(zone, tableaux)
        ]
        if zones_visuelles_ia:
            page_ir.elements = _filtrer_elements_visuels_couverts(
                page_ir.elements,
                zones_visuelles_ia,
            )
            formes_vectorielles = [
                forme
                for forme in formes_vectorielles
                if not _element_visuel_couvert_par_zone(forme, zones_visuelles_ia)
            ]
            for zone in zones_visuelles_ia:
                if _zone_visuelle_garde_texte_original(page_pdf, zone, page_ir, geometrie):
                    zones_textes_visuelles_natives.append(zone)
                    raster = rasteriser_region_sans_texte(
                        page_pdf,
                        zone,
                        document.media,
                        dpi=dpi,
                        geometrie=geometrie,
                    )
                else:
                    zones_textes_visuelles_natives.append(zone)
                    raster = rasteriser_region_sans_texte(
                        page_pdf,
                        zone,
                        document.media,
                        dpi=dpi,
                        geometrie=geometrie,
                    )
                page_ir.elements.append(raster)
                zones_rasterisees.append(raster.bbox)
                rapport.clusters_rasterises += 1
            if verbose:
                print(
                    f"      zones IA visuelles rastérisées: {len(zones_visuelles_ia)}",
                    file=sys.stderr,
                )
        zones_images = zones_ocr_du_plan(plan_layout)
        if ocr_layout == "word-native":
            zones_images = _filtrer_zones_images_avec_texte_natif(
                zones_images,
                zones_images_source,
                lignes_natives,
            )
            zones_images = _filtrer_zones_lisibles_ocr(zones_images, zones_images_lisibles)
        if verbose:
            print(f"      {comprehension.resume()}", file=sys.stderr)

    layout_map = None
    if text_mode == "rapidocr" and ocr_layout in {"hybrid", "word-native"}:
        layout_map = construire_layout_map(
            page_pdf,
            zones_visuelles=(zones_ocr_du_plan(plan_layout) if comprehension else zones_images),
            cadres_lecture=(
                _dedoublonner_cadres_lecture(
                    _cadres_lecture_depuis_plan(plan_layout) + zones_images_lisibles
                )
                if comprehension
                else _dedoublonner_cadres_lecture(
                    _cadres_lecture_depuis_comprehension(comprehension) + zones_images_lisibles
                )
            ),
            dpi=dpi,
            geometrie=geometrie,
        )

    if text_mode == "glyph-images":
        page_ir.elements.extend(extraire_glyphes_images(page_pdf, document.media, dpi=dpi))
        return

    if text_mode == "rapidocr":
        elements_ocr = extraire_rapidocr(
            page_pdf,
            polices,
            dpi=dpi,
            verbose=verbose,
            granularite=ocr_granularity,
            layout=ocr_layout,
            zones_ignorees=zones_images,
            media=document.media,
            layout_map=layout_map,
            geometrie=geometrie,
        )
        if comprehension is not None:
            elements_ocr = _attacher_frames_texte(elements_ocr, plan_layout)
            elements_ocr = filtrer_elements_selon_plan(
                elements_ocr,
                plan_layout,
                preserver_texte_natif=ocr_layout == "word-native",
            )
        if zones_textes_visuelles_natives and ocr_layout == "word-native":
            elements_ocr = _filtrer_textes_intersectant_zones(elements_ocr, zones_textes_visuelles_natives)
        if ocr_layout == "word-native":
            page_ir.elements.extend(
                _fonds_synthetiques_texte_inverse(page_pdf, elements_ocr, page_ir, geometrie)
            )
            nettoyer_images_fond_texte_positionne(page_ir.elements, elements_ocr, document.media)
        page_ir.elements.extend(elements_ocr)
        if zones_textes_visuelles_natives and ocr_layout == "word-native":
            layout_map_natif_visuel = layout_map_natif_visuel or construire_layout_map(
                page_pdf,
                geometrie=geometrie,
            )
            textes_visuels = extraire_textes_natifs_zones(
                page_pdf,
                polices,
                zones_textes_visuelles_natives,
                layout_map_natif_visuel,
                geometrie=geometrie,
            )
            nettoyer_images_fond_texte_positionne(page_ir.elements, textes_visuels, document.media)
            page_ir.elements.extend(_attacher_frames_texte(textes_visuels, plan_layout))
            _dedoublonner_textes_positionnes(page_ir)
        return

    blocs = extraire_texte_glyphes(page_pdf, polices) if text_mode == "glyphs" else extraire_texte(page_pdf, polices)
    page_ir.elements.extend(blocs)
    page_ir.elements.extend(appliquer_liens(page_pdf, blocs))


def extraire(
    chemin_pdf,
    pages=None,
    bibliotheque=None,
    dpi: int = 300,
    seuil_raster: int = SEUIL_CHEMINS_PAR_DEFAUT,
    strict: bool = False,
    rasteriser_pages: bool = False,
    text_mode: str = "spans",
    ocr_layer: bool = False,
    ocr_lang: str = "eng",
    ocr_visible: bool = False,
    ocr_granularity: str = "word",
    ocr_layout: str = "blocks",
    layout_ai: bool = False,
    layout_provider: str | None = None,
    layout_model: str | None = None,
    layout_model_root: str | None = None,
    layout_device: str | None = None,
    verbose: bool = False,
    rapport: Rapport | None = None,
) -> Document:
    """Construit l'IR complet à partir d'un PDF.

    Aucune page ne peut faire échouer la conversion : une page en erreur est remplacée
    par son rendu raster et signalée dans le rapport. `strict` renverse ce comportement.
    """
    rapport = rapport if rapport is not None else Rapport()

    doc = pymupdf.open(chemin_pdf)
    try:
        polices = {} if rasteriser_pages else collecter_polices(doc, bibliotheque)
        rapport.polices_reconnues = [
            a.font_id
            for a in polices.values()
            if a.reconnue and a.mode_resolution in {"exact", "famille_style"}
        ]
        rapport.polices_substituees = [
            f"{a.font_id} -> {a.alias_resolution} ({a.mode_resolution}, {a.confiance_resolution:.2f})"
            for a in polices.values()
            if a.reconnue and a.mode_resolution not in {"exact", "famille_style"}
        ]
        rapport.polices_non_reconnues = [
            a.font_id for a in polices.values() if not a.reconnue
        ]

        if pages is None:
            indices = list(range(doc.page_count))
        else:
            indices = list(pages)
            hors_bornes = [i + 1 for i in indices if not 0 <= i < doc.page_count]
            if hors_bornes:
                raise ValueError(
                    f"page(s) {', '.join(map(str, hors_bornes))} absente(s) : "
                    f"le document en compte {doc.page_count}"
                )

        document = Document(polices=polices)

        for position, index in enumerate(indices, start=1):
            if verbose:
                modes = []
                if rasteriser_pages:
                    modes.append("raster-page")
                else:
                    modes.append(f"texte={text_mode}")
                if ocr_layer:
                    modes.append(f"ocr={ocr_lang}{'/visible' if ocr_visible else ''}")
                print(
                    f"  page {position}/{len(indices)} (PDF {index + 1}) - {', '.join(modes)}",
                    file=sys.stderr,
                )
            page_pdf = doc[index]
            geometrie = PageGeometry.depuis_page(page_pdf)
            page_ir = Page(
                index=index,
                largeur_emu=geometrie.largeur_emu,
                hauteur_emu=geometrie.hauteur_emu,
            )

            if rasteriser_pages:
                if verbose:
                    print("    rasterisation pleine page", file=sys.stderr)
                page_ir.elements.append(
                    rasteriser_region(
                        page_pdf,
                        BBox(0, 0, page_ir.largeur_emu, page_ir.hauteur_emu),
                        document.media,
                        dpi=dpi,
                    )
                )
                if ocr_layer:
                    if verbose:
                        print("    OCR Tesseract", file=sys.stderr)
                    page_ir.elements.extend(
                        extraire_ocr(
                            page_pdf,
                            dpi=dpi,
                            langue=ocr_lang,
                            visible=ocr_visible,
                            verbose=verbose,
                        )
                    )
                _quantifier_page(page_ir)
                document.pages.append(page_ir)
                continue

            try:
                if verbose:
                    print("    extraction éléments PDF", file=sys.stderr)
                _remplir_page(
                    page_ir,
                    page_pdf,
                    doc,
                    document,
                    polices,
                    dpi,
                    seuil_raster,
                    rapport,
                    text_mode,
                    ocr_granularity,
                    ocr_layout,
                    layout_ai,
                    layout_provider,
                    layout_model,
                    layout_model_root,
                    layout_device,
                    verbose,
                )
            except Exception as erreur:  # noqa: BLE001 — une page ne fait jamais tout échouer
                if strict:
                    raise
                page_ir.elements = [
                    rasteriser_region(
                        page_pdf,
                        BBox(0, 0, page_ir.largeur_emu, page_ir.hauteur_emu),
                        document.media,
                        dpi=dpi,
                    )
                ]
                rapport.pages_degradees.append(
                    PageDegradee(index=index, motif=f"{type(erreur).__name__}: {erreur}")
                )

            if ocr_layer:
                if verbose:
                    print("    OCR Tesseract", file=sys.stderr)
                page_ir.elements.extend(
                    extraire_ocr(
                        page_pdf,
                        dpi=dpi,
                        langue=ocr_lang,
                        visible=ocr_visible,
                        verbose=verbose,
                    )
                )

            _quantifier_page(page_ir)
            document.pages.append(page_ir)

        rapport.pages_totales = len(document.pages)
        for page in document.pages:
            for element in page.elements:
                if isinstance(element, (ImageEl, RasterEl)):
                    rapport.images += 1
                elif isinstance(element, ShapeEl):
                    rapport.formes += 1
                elif isinstance(element, TableEl):
                    rapport.tableaux += 1
                elif isinstance(element, LinkZone):
                    rapport.liens += 1
        rapport.liens += sum(
            1
            for page in document.pages
            for element in page.elements
            if isinstance(element, TextBox)
            for ligne in element.lignes
            for span in ligne.spans
            if span.lien
        )

        return document
    finally:
        doc.close()
