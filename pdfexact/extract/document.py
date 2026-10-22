"""Ouverture du PDF et assemblage du Document.

La superposition suit l'ordre total des peintures source, avec l'ordre d'acquisition
pour les sequences egales. L'ordre de lecture du texte reste distinct.
"""
import pymupdf
import re
import sys
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

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
from pdfexact.extract.ocr import (
    extraire_ocr,
    extraire_rapidocr,
    extraire_textes_natifs_zones,
    extraire_tesseract_lignes_absentes,
)
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
    extraire_zones_shading,
    nettoyer_images_fond_texte_positionne,
    nettoyer_tuiles_page_depuis_source,
    page_a_des_degrades,
    rasteriser_region,
    rasteriser_region_sans_texte,
    rasteriser_regions_segmentees_sans_texte,
    resserrer_ancres_visuelles,
    segmenter_elements_visuels_page,
    verify_media_crop_partition,
)
from pdfexact.geometry import (
    BBox,
    PageGeometry,
    emu_vers_pt,
    pt_vers_emu,
    se_chevauchent,
    union,
)
from pdfexact.analysis.geometry import (
    bbox_area,
    intersection_area,
    intersection_over_min_area,
    overlap_ratio,
)
from pdfexact.analysis.provenance import Evidence, expliquer_filtrage
from pdfexact.analysis.options import AnalysisOptions
from pdfexact.analysis.semantic import regrouper_paragraphes
from pdfexact.ir import (
    Document,
    FlowParagraph,
    FontRef,
    ImageEl,
    Line,
    LinkZone,
    Page,
    RasterEl,
    ShapeEl,
    Span,
    TableEl,
    TextBox,
    clone_element_with_metadata,
    element_source_ids,
)
from pdfexact.scene import capture_source_observations, ensure_source_identity, record_source_transformation
from pdfexact.layout import (
    analyser_page,
    classer_regions,
    comprendre_page,
    detecter_layout_ia,
    filtrer_elements_selon_plan,
    planifier_regions,
    zones_ocr_dur_du_plan,
    zones_layout_du_plan,
    zones_ocr_du_plan,
)
from pdfexact.report import DiagnosticElement, DiagnosticLayout, PageDegradee, Rapport


def _aire(bbox: BBox) -> int:
    return bbox_area(bbox)


def _intersection(a: BBox, b: BBox) -> int:
    return intersection_area(a, b)


def _recouvrement_min(a: BBox, b: BBox) -> float:
    return intersection_over_min_area(a, b)


def _recouvrement_source(a: BBox, b: BBox) -> float:
    return overlap_ratio(a, b)


def _zone_deja_couverte(zone: BBox, zones: list[BBox], seuil: float = 0.70) -> bool:
    return any(_recouvrement_min(zone, existante) >= seuil for existante in zones)


def _bbox_intersecte_page(bbox: BBox, page: Page) -> bool:
    return (
        min(bbox.x1, page.largeur_emu) > max(bbox.x0, 0)
        and min(bbox.y1, page.hauteur_emu) > max(bbox.y0, 0)
    )


def _zone_source_deja_couverte(zone: BBox, zones: list[BBox], seuil: float = 0.75) -> bool:
    return any(_recouvrement_source(zone, existante) >= seuil for existante in zones)


def _journaliser_elements_rejetes(page: Page, avant: list, apres: list, reason: str) -> None:
    """Conserve les objets écartés par une heuristique pour la scène d'audit."""
    capture_source_observations(page, avant)
    ids_apres = {id(element) for element in apres}
    for output in apres:
        observations = getattr(output, "_source_observations", ())
        if observations:
            capture_source_observations(page, observations)
            record_source_transformation(page, observations, [output], reason,
                                         removed_source_ids=output.attributes.get("removed_source_ids", ()))
    for element in avant:
        if id(element) in ids_apres or any(element is item for item in page.discarded_elements):
            continue
        page.discarded_elements.append(element)
        expliquer_filtrage(element, reason)
        record_source_transformation(page, [element], [], reason)


def _appliquer_filtre_page(page: Page, filtre, *args, reason: str, **kwargs) -> list:
    avant = list(page.elements)
    capture_source_observations(page, avant)
    apres = filtre(avant, *args, **kwargs)
    _journaliser_elements_rejetes(page, avant, apres, reason)
    page.elements = apres
    return apres


def _clone_apres_filtrage(element, *, children_name, children, bbox):
    ensure_source_identity(element, getattr(element, "source_page_index", 0))
    child_ids = tuple(source_id for child in children for source_id in element_source_ids(child))
    digest = sha256("|".join(child_ids).encode()).hexdigest()[:16]
    clone = clone_element_with_metadata(element, bbox=bbox, **{children_name: children})
    clone.source_id = f"{element.source_id}:filtered:{digest}"
    clone.source_ids = (clone.source_id, *dict.fromkeys(child_ids))
    removed = tuple(source_id for source_id in element_source_ids(element)
                    if source_id != element.source_id and source_id not in child_ids)
    clone.attributes.update({"replaces": (element.source_id,), "transformation": "protected-zone-span-filter",
                             "original_source_ids": element_source_ids(element), "removed_source_ids": removed})
    clone.decision_history.append({"event": "transformed", "reason_code": "protected-zone-span-filter",
                                   "source_ids": element_source_ids(element), "removed_source_ids": removed})
    clone._source_observations = [clone_element_with_metadata(element)]
    for child in children:
        clone._source_observations.extend(getattr(child, "_source_observations", ()))
    return clone


def _zone_ia_ecrase_objet_natif(
    item,
    plan,
    zones_existantes: list[BBox],
    page: Page,
) -> bool:
    """Refuse une zone IA composite qui remplacerait des objets déjà extraits.

    Paddlex voit parfois une composition entière (photo + carte + vecteurs + texte)
    comme une seule image. Cette boîte ne doit pas devenir une autorité de rendu :
    dès qu'elle recouvre fortement un objet natif ou une zone vectorielle déjà
    protégée, on conserve les composants plus précis et on laisse l'IA guider
    uniquement le classement/OCR.
    """
    aire_page = max(_aire(BBox(0, 0, page.largeur_emu, page.hauteur_emu)), 1)
    aire_zone = max(_aire(item.bbox), 1)
    ratio_page = aire_zone / aire_page
    if ratio_page < 0.08:
        return False

    # Une image source ou une zone vectorielle déjà extraite est une preuve forte
    # qu'une boîte IA plus large est composite. On exige une extension visible de
    # la boîte IA pour ne pas perturber le cas trivial « IA == image source ».
    for existante in zones_existantes:
        couverture_zone = _recouvrement_source(item.bbox, existante)
        couverture_existante = _recouvrement_source(existante, item.bbox)
        if couverture_zone < 0.55 or couverture_existante < 0.80:
            continue
        if aire_zone > _aire(existante) * 1.10:
            return True

    # Deux preuves indépendantes dans la boîte sont suffisantes même si aucune
    # n'occupe seule une grande partie de la zone : c'est le cas typique d'une
    # page composée de colonnes, photos et formes vectorielles.
    preuves: list[BBox] = []
    for autre in plan:
        if autre is item:
            continue
        source = str(getattr(autre.region, "style_hints", {}).get("source", ""))
        if source == "paddlex":
            continue
        if _recouvrement_source(autre.bbox, item.bbox) < 0.55:
            continue
        if any(_recouvrement_min(autre.bbox, preuve) >= 0.65 for preuve in preuves):
            continue
        preuves.append(autre.bbox)
    return len(preuves) >= 2


def _zone_rasterisable(zone: BBox, page: Page) -> bool:
    largeur = max(0, min(zone.x1, page.largeur_emu) - max(zone.x0, 0))
    hauteur = max(0, min(zone.y1, page.hauteur_emu) - max(zone.y0, 0))
    if largeur < pt_vers_emu(1.0) or hauteur < pt_vers_emu(1.0):
        return False
    return largeur * hauteur >= pt_vers_emu(2.0) * pt_vers_emu(2.0)


def _page_image_pleine_sans_texte_natif(
    zones_images_source: list[BBox],
    lignes_natives: list[BBox],
    page: Page,
) -> bool:
    # Une page qui contient déjà du texte PDF natif n'est pas une page scannée,
    # même si ses images couvrent presque toute sa surface. Elle doit conserver
    # ses objets source et suivre le chemin natif mixte.
    if lignes_natives:
        return False

    # La région peut être découpée en tuiles : on mesure alors la couverture totale,
    # pas la taille d'une tuile isolée.
    aire_page = max(page.largeur_emu * page.hauteur_emu, 1)
    if not zones_images_source:
        return False
    x0 = min(zone.x0 for zone in zones_images_source)
    y0 = min(zone.y0 for zone in zones_images_source)
    x1 = max(zone.x1 for zone in zones_images_source)
    y1 = max(zone.y1 for zone in zones_images_source)
    couverture = sum(_aire(zone) for zone in zones_images_source) / aire_page
    return (
        couverture >= 0.72
        and x1 - x0 >= page.largeur_emu * 0.80
        and y1 - y0 >= page.hauteur_emu * 0.80
    )




def _page_pdf_natif_mixe(
    lignes_natives: list[BBox],
    zones_images_source: list[BBox],
    page: Page,
) -> bool:
    """Détecte toute page combinant texte PDF et contenu bitmap.

    Le nombre de lignes n'est pas un critère fiable : une couverture peut n'avoir que
    trois lignes, tandis qu'une brochure en comporte des dizaines. Dès qu'un texte
    natif et une image coexistent, le fond doit suivre le même traitement page-exact
    afin d'éviter une seconde couche textuelle dans l'image.
    """
    return bool(
        lignes_natives
        and zones_images_source
    )


def _extraire_texte_pdf_natif_word_native(
    page_pdf,
    polices: dict,
    plan_layout,
    zones_images: list[BBox],
    zones_textes_visuelles_natives: list[BBox],
    page_ir: Page,
    document: Document,
    zones_ia=None,
    *,
    geometrie: PageGeometry | None = None,
) -> list[FlowParagraph]:
    if geometrie is None:
        elements_natifs = extraire_texte(page_pdf, polices)
    else:
        elements_natifs = extraire_texte(page_pdf, polices, geometrie=geometrie)
    capture_source_observations(page_ir, elements_natifs, source_kind="pdf-native")
    if plan_layout:
        elements_natifs = _attacher_frames_texte(
            elements_natifs,
            plan_layout,
            zones_ia=zones_ia,
        )
        avant = elements_natifs
        elements_natifs = filtrer_elements_selon_plan(
            elements_natifs,
            plan_layout,
            preserver_texte_natif=True,
        )
        _journaliser_elements_rejetes(page_ir, avant, elements_natifs, "native-plan-filter")
        lignes_texte = [ligne.bbox for element in elements_natifs for ligne in element.lignes]
        avant = elements_natifs
        elements_natifs = _filtrer_textes_intersectant_zones(
            elements_natifs,
            _zones_formules_du_plan(plan_layout, lignes_texte, page_ir),
        )
        _journaliser_elements_rejetes(page_ir, avant, elements_natifs, "native-protected-zone-filter")
    paragraphes = []
    for element in elements_natifs:
        for ligne in element.lignes:
            texte = "".join(span.texte for span in ligne.spans).strip()
            if not texte:
                continue
            style = next((span for span in ligne.spans if span.texte.strip()), ligne.spans[0])
            paragraphes.append(
                FlowParagraph(
                    bbox=ligne.bbox,
                    texte=texte,
                    police=style.police,
                    size_pt=style.size_pt,
                    couleur=style.couleur,
                    alignement=ligne.alignement,
                    retrait_gauche_emu=max(0, ligne.bbox.x0),
                    retrait_droite_emu=max(0, page_ir.largeur_emu - ligne.bbox.x1),
                    interligne_emu=max(ligne.hauteur_ligne_emu, ligne.bbox.hauteur),
                    souligne=style.souligne,
                    barre=style.barre,
                    surlignage=style.surlignage,
                    spans=list(ligne.spans),
                    lignes=[ligne],
                    **{name: getattr(ligne, name) if getattr(ligne, name) is not None else getattr(element, name)
                       for name in ("layout_frame_id", "layout_frame_role", "layout_frame_strategy", "layout_frame_bbox")},
                    angle_deg=ligne.angle_deg,
                    orientation=ligne.orientation,
                    baseline_points=ligne.baseline_points,
                    semantic_role=ligne.semantic_role,
                    curved=ligne.curved,
                    source_id=f"{ligne.source_id}:paragraph",
                    source_ids=element_source_ids(ligne),
                    source_line_ids=(ligne.source_id,),
                    source_kind=ligne.source_kind,
                    language=ligne.language,
                    script=ligne.script,
                    confidence=ligne.confidence,
                    quad=ligne.quad,
                    z_index=ligne.z_index,
                    attributes={"replaces": (ligne.source_id,), "source_block_id": element.source_id,
                                "transformation": "native-line-paragraph-adapter"},
                )
            )
        outputs = [item for item in paragraphes if item.attributes.get("source_block_id") == element.source_id]
        record_source_transformation(page_ir, [element], outputs, "native-line-paragraph-adapter")
    return paragraphes


def _zones_formules_du_plan(
    plan,
    lignes_natives: list[BBox] | None = None,
    page: Page | None = None,
) -> list[BBox]:
    if not plan:
        return []
    return [
        item.bbox
        for item in plan
        if item.kind in {"formula", "formula-or-complex-vector"}
        and item.strategy in {"raster-immutable", "raster-image"}
        and not _zone_formule_inline_dans_texte(item.bbox, lignes_natives or [], page)
    ]


def _zone_formule_inline_dans_texte(
    zone: BBox,
    lignes_natives: list[BBox],
    page: Page | None,
) -> bool:
    if not lignes_natives or page is None:
        return False
    if zone.largeur >= page.largeur_emu * 0.18:
        return False
    centre_y = (zone.y0 + zone.y1) // 2
    centre_x = (zone.x0 + zone.x1) // 2
    for ligne in lignes_natives:
        if not (ligne.y0 - pt_vers_emu(2) <= centre_y <= ligne.y1 + pt_vers_emu(2)):
            continue
        if not (ligne.x0 - pt_vers_emu(2) <= centre_x <= ligne.x1 + pt_vers_emu(2)):
            continue
        if ligne.largeur < page.largeur_emu * 0.22:
            continue
        if zone.largeur <= ligne.largeur * 0.35:
            return True
    return False


def _preparer_ocr_visible_page_image(elements: list) -> int:
    lignes = 0
    for element in elements:
        if not isinstance(element, (TextBox, FlowParagraph)):
            continue
        if isinstance(element, TextBox):
            setattr(element, "preserve_as_textbox", True)
        for ligne in getattr(element, "lignes", []):
            if any(span.texte.strip() for span in ligne.spans):
                lignes += 1
            for span in ligne.spans:
                span.invisible = False
                span.couleur = span.couleur or "000000"
    return lignes


def _styliser_ocr_depuis_image_scanee(page_pdf, elements: list, geometrie: PageGeometry) -> None:
    for element in elements:
        if not isinstance(element, (TextBox, FlowParagraph)):
            continue
        for ligne in getattr(element, "lignes", []):
            couleur = _couleur_texte_depuis_rendu(page_pdf, ligne.bbox, geometrie)
            for span in ligne.spans:
                span.couleur = couleur
                if span.size_pt >= 18:
                    span.police = FontRef(span.police.font_id, span.police.famille, True, span.police.italique)


def _couleur_texte_depuis_rendu(page_pdf, bbox: BBox, geometrie: PageGeometry) -> str:
    rect_affiche = pymupdf.Rect(
        emu_vers_pt(bbox.x0),
        emu_vers_pt(bbox.y0),
        emu_vers_pt(bbox.x1),
        emu_vers_pt(bbox.y1),
    ).intersect(pymupdf.Rect(0, 0, geometrie.largeur_pt, geometrie.hauteur_pt))
    if rect_affiche.is_empty:
        return "000000"
    pix = page_pdf.get_pixmap(
        matrix=pymupdf.Matrix(1, 1),
        clip=geometrie.rect_affiche_vers_natif(rect_affiche),
        alpha=False,
    )
    if pix.width <= 1 or pix.height <= 1:
        return "000000"

    samples = pix.samples
    pas = pix.n
    bord: list[float] = []
    tous: list[float] = []
    for y in range(pix.height):
        for x in range(pix.width):
            offset = (y * pix.width + x) * pas
            r, g, b = samples[offset], samples[offset + 1], samples[offset + 2]
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            tous.append(lum)
            if x < 2 or y < 2 or x >= pix.width - 2 or y >= pix.height - 2:
                bord.append(lum)
    if not tous:
        return "000000"
    reference = _mediane(bord or tous)
    sombres = sum(1 for lum in tous if lum < 80) / len(tous)
    clairs = sum(1 for lum in tous if lum > 205) / len(tous)
    if reference < 170 and clairs >= 0.01:
        return "FFFFFF"
    if reference < 145 and clairs >= 0.004:
        return "FFFFFF"
    if reference < 120 and sombres < 0.35:
        return "FFFFFF"
    return "000000"


def _mediane(valeurs: list[float]) -> float:
    valeurs = sorted(valeurs)
    return valeurs[len(valeurs) // 2]


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
    filtres = []
    for tableau in tableaux:
        if _tableau_confirme_par_layout_ia(tableau, zones_ia, largeur_page_emu, hauteur_page_emu):
            filtres.append(tableau)
        else:
            expliquer_filtrage(tableau, "layout-ai-contradicts-table", source="layout-ai")
    return filtres


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
    filtres = []
    for element in elements:
        if isinstance(element, ShapeEl) and _forme_couverte_par_zone(element, zones):
            expliquer_filtrage(element, "covered-by-raster-zone")
            continue
        filtres.append(element)
    return filtres


def _element_visuel_couvert_par_zone(element, zones: list[BBox], seuil: float = 0.70) -> bool:
    if not isinstance(element, (ShapeEl, ImageEl, RasterEl)):
        return False
    return any(_recouvrement_source(element.bbox, zone) >= seuil for zone in zones)


def _filtrer_elements_visuels_couverts(elements: list, zones: list[BBox]) -> list:
    if not zones:
        return elements
    filtres = []
    for element in elements:
        if _element_visuel_couvert_par_zone(element, zones):
            expliquer_filtrage(element, "covered-by-visual-zone")
            continue
        filtres.append(element)
    return filtres






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
    filtres = []
    for element in elements:
        if isinstance(element, TextBox):
            lignes = []
            for ligne in element.lignes:
                ligne_filtre = _ligne_sans_spans_intersectant_zones(ligne, zones)
                if ligne_filtre is not None:
                    lignes.append(ligne_filtre)
            if lignes:
                if len(lignes) == len(element.lignes) and all(a is b for a, b in zip(lignes, element.lignes)):
                    filtres.append(element)
                    continue
                bbox = lignes[0].bbox
                for ligne in lignes[1:]:
                    bbox = union(bbox, ligne.bbox)
                filtres.append(_clone_apres_filtrage(element, children_name="lignes", children=lignes, bbox=bbox))
            continue
        if not _element_texte_intersecte_zone(element, zones):
            filtres.append(element)
        else:
            expliquer_filtrage(element, "text-intersects-protected-zone")
    return filtres


def _ligne_sans_spans_intersectant_zones(ligne: Line, zones: list[BBox]) -> Line | None:
    spans_avec_bbox = [span for span in ligne.spans if span.bbox is not None]
    if not spans_avec_bbox:
        return None if _bbox_texte_intersecte_zone(ligne.bbox, ligne.spans, zones) else ligne
    spans = [
        span
        for span in ligne.spans
        if span.bbox is None or not _bbox_texte_intersecte_zone(span.bbox, [span], zones)
    ]
    if not spans:
        return None
    if len(spans) == len(ligne.spans):
        return ligne
    bboxes = [span.bbox for span in spans if span.bbox is not None]
    bbox = bboxes[0] if bboxes else ligne.bbox
    for boite in bboxes[1:]:
        bbox = union(bbox, boite)
    return _clone_apres_filtrage(ligne, children_name="spans", children=spans, bbox=bbox)


def _bbox_texte_intersecte_zone(bbox: BBox, spans: list[Span], zones: list[BBox]) -> bool:
    bboxes = [span.bbox for span in spans if span.bbox is not None]
    if not bboxes:
        bboxes = [bbox]
    aire_totale = sum(max(_aire(boite), 1) for boite in bboxes)
    aire_couverte = 0
    for boite in bboxes:
        centre_x = (boite.x0 + boite.x1) // 2
        centre_y = (boite.y0 + boite.y1) // 2
        for zone in zones:
            intersection = _intersection(boite, zone)
            aire_couverte += intersection
            if zone.x0 <= centre_x <= zone.x1 and zone.y0 <= centre_y <= zone.y1:
                aire_couverte += max(_aire(boite), 1)
                break
    return (aire_couverte / max(aire_totale, 1)) >= 0.35


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
        if _zone_ia_ecrase_objet_natif(item, plan, zones_existantes + zones, page):
            continue
        if _zone_source_deja_couverte(item.bbox, zones_existantes + zones, seuil=0.75):
            continue
        zones.append(item.bbox)
    return zones


def _zones_formules_a_rasteriser(
    plan,
    zones_existantes: list[BBox],
    lignes_natives: list[BBox] | None = None,
    page: Page | None = None,
) -> list[BBox]:
    zones: list[BBox] = []
    for zone in _zones_formules_du_plan(plan, lignes_natives, page):
        if _zone_source_deja_couverte(zone, zones_existantes + zones, seuil=0.75):
            continue
        zones.append(zone)
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














def _securiser_elements_visuels_page(page: Page, media: dict) -> None:
    avant = list(page.elements)
    capture_source_observations(page, avant)
    apres = []
    for source in avant:
        fragments = segmenter_elements_visuels_page([source], media, page.largeur_emu, page.hauteur_emu)
        crop_proofs = [dict(evidence.details).get("proof")
                       for fragment in fragments for evidence in getattr(fragment, "evidence", ())
                       if isinstance(evidence, Evidence) and evidence.kind == "media-crop-partition"]
        proof = next((proof for proof in crop_proofs if isinstance(proof, dict)
                      and proof.get("source", {}).get("source_id") == source.source_id), None)
        if proof is not None:
            acquired = page.source_inventory[source.source_id]
            errors = verify_media_crop_partition(acquired, fragments, media, proof)
            if errors:
                source.attributes["crop_unverified_reasons"] = errors
                apres.append(source)
                continue
            apres.extend(fragments)
            record_source_transformation(page, [source], fragments, "source-media-segmentation", proof=proof)
            continue
        if any(fragment is not source for fragment in fragments) and (
            getattr(source, "quad", ()) or getattr(source, "transform", ()) or getattr(source, "clip_bbox", None) is not None
        ):
            source.attributes["crop_unverified_reasons"] = ["missing-producer-crop-proof"]
            apres.append(source)
            continue
        outputs = []
        for fragment in fragments:
            if fragment is source:
                outputs.append(source)
                continue
            output = clone_element_with_metadata(source, bbox=fragment.bbox, media_ref=fragment.media_ref)
            digest = sha256(str((fragment.bbox.x0, fragment.bbox.y0, fragment.bbox.x1, fragment.bbox.y1)).encode()).hexdigest()[:16]
            output.source_id = f"{source.source_id}:media-crop:{digest}"
            output.source_ids = tuple(dict.fromkeys((output.source_id, *element_source_ids(source))))
            output.attributes.update({"replaces": (source.source_id,), "transformation": "source-media-pixel-crop",
                                      "source_media_ref": source.media_ref, "source_bbox": source.bbox,
                                      "crop_unverified_reasons": ["missing-producer-crop-proof"]})
            if isinstance(output, RasterEl):
                output.source_component_ids = tuple(dict.fromkeys((source.source_id, *source.source_component_ids)))
                output.fallback_reason = source.fallback_reason or "source-media-segmentation"
            outputs.append(output)
        apres.extend(outputs)
        if any(output is not source for output in outputs):
            record_source_transformation(page, [source], outputs, "source-media-segmentation",
                                         proof={"capture_method": "source-media-pixel-crop", "source_media_ref": source.media_ref,
                                                "output_ids": tuple(output.source_id for output in outputs),
                                                "source_bbox": _bbox_report(source.bbox),
                                                "output_bboxes": tuple(_bbox_report(output.bbox) for output in outputs),
                                                "pixel_equivalence_verified": False,
                                                "reasons": ["missing-producer-crop-proof"]})
    _journaliser_elements_rejetes(page, avant, apres, "segmented-or-replaced-visual")
    page.elements = apres


def _lier_composants_raster(page: Page, raster: RasterEl, sources: list, reason: str, *, dpi: int) -> None:
    capture_source_observations(page, sources)
    raster.source_kind = "inferred"
    raster.source_component_ids = tuple(source.source_id for source in sources)
    raster.source_ids = tuple(dict.fromkeys(source_id for source in sources for source_id in element_source_ids(source)))
    raster.fallback_reason = reason
    raster.attributes.update({"source_component_ids": raster.source_component_ids,
                              "replaces": raster.source_component_ids, "transformation": "raster-composition"})
    ensure_source_identity(raster, page.index, source_pdf_id=page.source_pdf_id or "")
    proof = {"reason": reason, "source_ids": raster.source_component_ids, "output_id": raster.source_id,
             "dpi": dpi, "raster_bbox": _bbox_report(raster.bbox), "producer": "pdfexact.extract.document",
             "capture_method": "source-page-region-render", "pixel_equivalence_verified": False}
    raster.evidence.append(Evidence(kind="raster-replacement", source="pdfexact.extract.document", confidence=None,
                                    details=tuple(proof.items())))
    record_source_transformation(page, sources, [raster], reason, source_component_ids=raster.source_component_ids,
                                 proof=proof)


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


def _attacher_frames_texte(elements: list, plan, zones_ia=None) -> list:
    """Associe chaque ligne native au frame de compréhension qui la contient."""
    if not plan and not zones_ia:
        return elements
    frames = [
        (index, item)
        for index, item in enumerate(plan)
        if item.strategy == "word-text"
        and item.kind in {"text-column", "caption", "heading", "list", "ai-zone"}
        and item.region is not None
    ]
    # Le plan final peut ne retenir qu'une partie des zones IA. Les en-tetes,
    # titres et textes detectes directement par le modele restent des conteneurs
    # utiles pour la reconstruction native.
    for zone_index, zone in enumerate(zones_ia or ()):
        if zone.role == "caption" or zone.label == "figure_title":
            role = "caption"
        elif zone.label in {"header", "doc_title", "paragraph_title"}:
            role = "heading"
        else:
            role = "text-column"
        if zone.role not in {"text", "caption"} and zone.label not in {
            "header",
            "doc_title",
            "paragraph_title",
            "text",
            "figure_title",
        }:
            continue
        frames.append(
            (
                len(plan or []) + zone_index,
                SimpleNamespace(
                    bbox=zone.bbox,
                    kind=role,
                    strategy="word-text",
                    region=zone,
                ),
            )
        )
    cadres_uniques = []
    vus = set()
    for frame_index, item in frames:
        cle = (
            item.kind,
            item.strategy,
            item.bbox.x0,
            item.bbox.y0,
            item.bbox.x1,
            item.bbox.y1,
        )
        if cle in vus:
            continue
        vus.add(cle)
        cadres_uniques.append((frame_index, item))
    frames = cadres_uniques
    if not frames:
        return elements

    # Frame inference is a layout view, not a new acquisition of native rows.
    source_lines = {}
    views = []
    for element in elements:
        if isinstance(element, (TextBox, FlowParagraph)) and any(
            hasattr(line, "source_acquisition_index") for line in element.lignes
        ):
            view = clone_element_with_metadata(element)
            source_lines.update((id(copied), source) for copied, source in zip(view.lignes, element.lignes)
                                if hasattr(source, "source_acquisition_index"))
            views.append(view)
        else:
            views.append(element)
    elements = views
    lignes_sans_frame: list[Line] = []
    for element in elements:
        if not isinstance(element, (TextBox, FlowParagraph)):
            continue
        lignes = element.lignes if isinstance(element, FlowParagraph) else element.lignes
        frame_lignes = []
        lignes_non_attachees = []
        for ligne in lignes:
            if ligne.semantic_role is None:
                ligne.semantic_role = _role_semantique_zone(ligne.bbox, zones_ia)
            meilleur = _meilleur_frame_ligne(ligne.bbox, frames)
            if meilleur is None:
                lignes_non_attachees.append(ligne)
                continue
            frame_index, item = meilleur
            role = item.kind
            frame_id = f"{frame_index}:{role}:{item.bbox.x0}:{item.bbox.y0}:{item.bbox.x1}:{item.bbox.y1}"
            ligne.layout_frame_id = frame_id
            ligne.layout_frame_role = role
            ligne.layout_frame_strategy = item.strategy
            ligne.layout_frame_bbox = item.bbox
            frame_lignes.append((frame_id, role, item.strategy, item.bbox))
        lignes_sans_frame.extend(lignes_non_attachees)
        roles = {ligne.semantic_role for ligne in lignes}
        if len(roles) == 1 and element.semantic_role is None:
            element.semantic_role = roles.pop()
        if frame_lignes and len({frame[0] for frame in frame_lignes}) == 1 and not lignes_non_attachees:
            frame_id, role, strategy, bbox = frame_lignes[0]
            element.layout_frame_id = frame_id
            element.layout_frame_role = role
            element.layout_frame_strategy = strategy
            element.layout_frame_bbox = bbox
        else:
            # A source PDF block can span several semantic regions.
            element.layout_frame_id = None
            element.layout_frame_role = None
            element.layout_frame_strategy = None
            element.layout_frame_bbox = None

    # Le plan IA ne couvre pas toujours les textes PDF natifs (titres, sous-titres,
    # en-têtes, petits panneaux). Ils ne doivent pas rester des lignes orphelines :
    # sans conteneur, le writer les place dans des bandes indépendantes et Word peut
    # rogner leur hauteur. On reconstruit donc des blocs de lecture par continuité
    # géométrique et cohérence typographique, sans inventer de texte.
    for index, groupe in enumerate(_regrouper_lignes_sans_frame(lignes_sans_frame)):
        if not groupe:
            continue
        role = _role_frame_inferre(groupe)
        bbox = groupe[0].bbox
        for ligne in groupe[1:]:
            bbox = union(bbox, ligne.bbox)
        marge = pt_vers_emu(1)
        bbox = BBox(
            max(0, bbox.x0 - marge),
            max(0, bbox.y0 - marge),
            bbox.x1 + marge,
            bbox.y1 + marge,
        )
        frame_id = f"inferred:{index}:{role}:{bbox.x0}:{bbox.y0}:{bbox.x1}:{bbox.y1}"
        for ligne in groupe:
            ligne.layout_frame_id = frame_id
            ligne.layout_frame_role = role
            ligne.layout_frame_strategy = "word-text"
            ligne.layout_frame_bbox = bbox
    return _materialiser_vues_frames_texte(elements, source_lines)


def _role_semantique_zone(bbox, zones_ia):
    """Semantic role of the layout-AI zone holding most of a line, if any."""
    from pdfexact.layout.ai import role_semantique_etiquette

    area = max(bbox.largeur * bbox.hauteur, 1)
    best, best_ratio = None, 0.5
    for zone in zones_ia or ():
        ratio = intersection_area(bbox, zone.bbox) / area
        if ratio > best_ratio:
            best, best_ratio = zone, ratio
    return role_semantique_etiquette(best.label) if best is not None else None


def _materialiser_vues_frames_texte(elements, source_lines):
    """Keep derived frames on owners and restore their exact acquired rows."""
    names = ("layout_frame_id", "layout_frame_role", "layout_frame_strategy", "layout_frame_bbox", "semantic_role")
    result = []
    for element in elements:
        if not any(id(line) in source_lines for line in getattr(element, "lignes", ())):
            result.append(element)
            continue
        groups = []
        for line in element.lignes:
            layout = tuple(getattr(line, name) for name in names)
            if not groups or groups[-1][0] != layout:
                groups.append((layout, []))
            groups[-1][1].append(source_lines.get(id(line), line))
        for index, (layout, lines) in enumerate(groups):
            owner = clone_element_with_metadata(element, lignes=lines, **dict(zip(names, layout)))
            if len(groups) > 1:
                owner.bbox = BBox(min(line.bbox.x0 for line in lines), min(line.bbox.y0 for line in lines),
                                  max(line.bbox.x1 for line in lines), max(line.bbox.y1 for line in lines))
                owner.geometry = None
                owner.source_id = f"{element.source_id}:frame-view:{index}" if element.source_id else None
                owner.source_ids = tuple(dict.fromkeys(
                    ident for ident in (element.source_id, *(ident for line in lines for ident in element_source_ids(line)))
                    if ident is not None
                ))
            if isinstance(owner, FlowParagraph):
                owner.spans = [span for line in lines for span in line.spans]
                owner.texte = " ".join("".join(span.texte for span in line.spans) for line in lines)
                owner.source_line_ids = tuple(line.source_id for line in lines if line.source_id is not None)
            result.append(owner)
    return result


def _regrouper_lignes_sans_frame(lignes: list[Line]) -> list[list[Line]]:
    """Regroupe les lignes non couvertes par le plan en blocs de lecture locaux.

    Le regroupement reste volontairement géométrique : il ne dépend ni de la langue
    ni d'un vocabulaire particulier. Une ligne ne rejoint un bloc que si elle est
    proche verticalement, partage une colonne horizontale et conserve une typographie
    compatible. Les grands écarts, changements de colonne et changements de style
    créent naturellement un nouveau conteneur.
    """
    options = AnalysisOptions(
        extra={
            "semantic_vertical_gap_factor": 2.4,
            "semantic_column_overlap_min": 0.18,
            # Reading blocks only: comprehension decides paragraphs once per zone
            # afterwards; asking the model for every row pair here was redundant.
            "semantic_ai": False,
        }
    )
    return [
        [item for item in group if isinstance(item, Line)]
        for group in regrouper_paragraphes(lignes, options)
        if any(isinstance(item, Line) for item in group)
    ]


def _style_ligne_texte(ligne: Line) -> tuple[float, bool, bool] | None:
    span = next((span for span in ligne.spans if span.texte.strip()), None)
    if span is None:
        return None
    return float(span.size_pt), bool(span.police.gras), bool(span.police.italique)


def _role_frame_inferre(lignes: list[Line]) -> str:
    styles = [_style_ligne_texte(ligne) for ligne in lignes]
    styles = [style for style in styles if style is not None]
    if not styles:
        return "text-column"
    taille_max = max(style[0] for style in styles)
    texte = " ".join("".join(span.texte for span in ligne.spans).strip() for ligne in lignes)
    prose = len(re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]{2,}", texte)) >= 8
    if taille_max >= 16 and len(lignes) <= 6:
        return "heading"
    if any(re.match(r"^\s*(?:[•▪◦*]|\d+[.)])\s+", "".join(span.texte for span in ligne.spans)) for ligne in lignes):
        return "list"
    if all(style[2] for style in styles) and taille_max <= 14 and len(lignes) <= 4 and not prose:
        return "caption"
    return "text-column"


def _meilleur_frame_ligne(bbox: BBox, frames) -> tuple[int, object] | None:
    centre_x = (bbox.x0 + bbox.x1) // 2
    centre_y = (bbox.y0 + bbox.y1) // 2
    aire_ligne = max(bbox.largeur * bbox.hauteur, 1)
    candidats = []
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
        candidats.append(
            (contient, aire_frame, -couverture, -score, frame_index, item)
        )
    if not candidats:
        return None
    # Quand plusieurs cadres contiennent la meme ligne, le plus petit cadre est
    # le conteneur semantique le plus precis. Cela evite qu'un cadre de colonne
    # englobant absorbe un titre ou une legende detectee plus finement par l'IA.
    contenus = [candidat for candidat in candidats if candidat[0]]
    choix = min(contenus, key=lambda candidat: (candidat[1], candidat[2], candidat[4])) if contenus else min(
        candidats,
        key=lambda candidat: (candidat[3], candidat[1], candidat[4]),
    )
    return choix[4], choix[5]


def _dedoublonner_textes_positionnes(page: Page) -> None:
    capture_source_observations(page, page.elements)
    text_types = (TextBox, FlowParagraph)
    candidats: list[tuple[int, object, Line, str]] = []
    for index, element in enumerate(page.elements):
        if not isinstance(element, text_types) or len(element.lignes) != 1:
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
            if not _preuve_doublon_texte(ligne_a, ligne_b) or any(
                getattr(element_a, name, None) != getattr(element_b, name, None)
                for name in ("source_kind", "z_index", "opacity", "alpha", "clip_ids", "clip_bbox", "compositing")
            ):
                continue
            gagnant = _meilleur_texte_duplique(element_a, ligne_a, element_b, ligne_b)
            perdant = element_b if gagnant is element_a else element_a
            supprimer.add(index_b if gagnant is element_a else index_a)
            perdant.attributes.update({"duplicate_of": gagnant.source_id, "duplicate_verified": True})
            gagnant.source_ids = tuple(dict.fromkeys((*element_source_ids(gagnant), *element_source_ids(perdant))))
            page.discarded_elements.append(perdant)
            record_source_transformation(page, [perdant], [gagnant], "duplicate-positioned-text",
                                         duplicate_of=gagnant.source_id, duplicate_verified=True,
                                         proof="identical-text-style-and-glyph-geometry")
            expliquer_filtrage(
                perdant,
                "duplicate-positioned-text",
                kept_id=str(getattr(gagnant, "source_id", None) or "unknown"),
            )
            if gagnant is element_b:
                break
    if supprimer:
        page.elements = [element for index, element in enumerate(page.elements) if index not in supprimer]


def _preuve_doublon_texte(a: Line, b: Line) -> bool:
    if a.bbox != b.bbox or a.angle_deg != b.angle_deg or a.quad != b.quad or a.baseline_points != b.baseline_points:
        return False
    fields = ("texte", "police", "size_pt", "couleur", "bbox", "quad", "angle_deg", "baseline_points",
              "souligne", "barre", "surlignage", "espacement_twips", "invisible", "capitales", "exposant", "indice",
              "source_kind", "z_index", "alpha", "opacity", "clip_ids", "clip_bbox", "compositing")
    if any(getattr(a, name, None) != getattr(b, name, None) for name in fields[18:]):
        return False
    return len(a.spans) == len(b.spans) and all(
        all(getattr(left, name, None) == getattr(right, name, None) for name in fields)
        for left, right in zip(a.spans, b.spans)
    )


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
    ocr_language="auto",
    ocr_model_root=None,
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
    # Une page qui possède déjà des glyphes PDF ne doit pas être reconstruite par
    # les tuiles IA : ces tuiles peuvent réinclure le texte natif dans leur bitmap.
    page_pdf_natif_candidat = False

    # L'analyse de structure est une étape obligatoire du pipeline universel.
    # ``layout_ai`` reste dans la signature pour compatibilité avec les anciens
    # appelants, mais ne peut plus supprimer cette étape : les modes spans,
    # glyphs et OCR doivent partager le même repère sémantique de page.
    analyse_layout = analyser_page(page_pdf, geometrie=geometrie)
    lignes_natives = analyse_layout.native_line_bboxes()
    page_pdf_natif_candidat = bool(lignes_natives)
    page_layout_ai = detecter_layout_ia(
        page_pdf,
        analyse_layout,
        provider=layout_provider,
        model=layout_model,
        model_root=layout_model_root,
        device=layout_device,
        required=False,
    )
    if page_layout_ai.warnings:
        print(
            "      avertissement layout IA: "
            + ",".join(page_layout_ai.warnings)
            + "; repli géométrique actif",
            file=sys.stderr,
        )
    if verbose:
        print(
            f"      layout IA: {page_layout_ai.status}, zones={len(page_layout_ai.zones)}",
            file=sys.stderr,
        )

    if text_mode == "rapidocr" and ocr_layout in {"hybrid", "word-native"}:
        tableaux_bruts = extraire_tableaux(page_pdf, polices, geometrie=geometrie)
        tableaux_listing = extraire_tableaux_listing(page_pdf, polices, geometrie=geometrie)
        capture_source_observations(page_ir, [*tableaux_bruts, *tableaux_listing], source_kind="pdf-native")
        for tableau_listing in tableaux_listing:
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
        _journaliser_elements_rejetes(page_ir, [*tableaux_bruts, *tableaux_listing], tableaux_detectes,
                                     "historical-table-recognition-filter")

    formes_pdf = extraire_vectoriel(page_pdf, geometrie=geometrie)
    capture_source_observations(page_ir, formes_pdf, source_kind="vector")
    formes_a_regrouper: list[ShapeEl] = []
    for forme in formes_pdf:
        if _forme_bordure_page_clusterisante(forme, page_ir):
            if text_mode != "rapidocr" or ocr_layout in {"hybrid", "word-native"}:
                page_ir.elements.append(forme)
                formes_vectorielles.append(forme)
            else:
                _journaliser_elements_rejetes(page_ir, [forme], [], "historical-page-border-filter")
            continue
        formes_a_regrouper.append(forme)
    for cluster in regrouper(formes_a_regrouper):
        boite_cluster = boite_du_cluster(cluster)
        if not _bbox_intersecte_page(boite_cluster, page_ir):
            record_source_transformation(page_ir, cluster, [], "outside-visible-page",
                                         outside_page={"source_bbox": _bbox_report(boite_cluster),
                                                       "page_bbox": _bbox_report(BBox(0, 0, page_ir.largeur_emu, page_ir.hauteur_emu)),
                                                       "intersection_area": 0})
            continue
        if page_pdf_natif_candidat:
            page_ir.elements.extend(cluster)
            formes_vectorielles.extend(cluster)
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
            _lier_composants_raster(page_ir, raster, cluster, "complex-vector-cluster", dpi=dpi)
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
            else:
                _journaliser_elements_rejetes(page_ir, cluster, [], "historical-vector-significance-filter")
            continue
        else:
            page_ir.elements.extend(cluster)
            formes_vectorielles.extend(cluster)

    # Les shadings sont des opérations de peinture locales, pas une propriété
    # qui doit forcer tous les aplats vectoriels de la page à devenir des images.
    # On les conserve comme petites couches raster indépendantes, sous le texte,
    # tandis que les formes simples restent natives.
    for zone_shading in extraire_zones_shading(doc, page_pdf, geometrie):
        if _zone_deja_couverte(zone_shading, zones_rasterisees, seuil=0.92):
            continue
        page_ir.elements.append(
            rasteriser_region(
                page_pdf,
                zone_shading,
                document.media,
                dpi=dpi,
                purpose="shading",
            )
        )

    if page_pdf_natif_candidat:
        images = extraire_images(
            page_pdf,
            doc,
            document.media,
            geometrie=geometrie,
        )
        images_inline = extraire_images_inline(
            page_pdf,
            document.media,
            deja_posees=images,
            geometrie=geometrie,
        )
    elif text_mode == "rapidocr" and ocr_layout in {"reflow", "hybrid", "word-native"}:
        images = extraire_images_rasterisees(
            page_pdf,
            doc,
            document.media,
            dpi=dpi,
            geometrie=geometrie,
            supprimer_texte_natif=ocr_layout == "word-native" and not page_pdf_natif_candidat,
        )
        images_inline = extraire_images_inline_rasterisees(
            page_pdf,
            document.media,
            deja_posees=images,
            dpi=dpi,
            geometrie=geometrie,
            supprimer_texte_natif=ocr_layout == "word-native" and not page_pdf_natif_candidat,
        )
    else:
        images = extraire_images(page_pdf, doc, document.media, geometrie=geometrie)
        images_inline = extraire_images_inline(
            page_pdf,
            document.media,
            deja_posees=images,
            geometrie=geometrie,
        )
    capture_source_observations(page_ir, [*images, *images_inline], source_kind="image")
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
            sources = [tableau for tableau in tableaux_bruts if tableau.bbox == zone]
            _lier_composants_raster(page_ir, raster, sources, "rejected-graph-table-raster", dpi=dpi)
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
    plan_layout = None
    if text_mode == "rapidocr" and ocr_layout in {"hybrid", "word-native"}:
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
            if not page_pdf_natif_candidat
            and item.region.style_hints.get("source") == "vector-cluster"
            and item.strategy == "raster-immutable"
            and _zone_rasterisable(item.bbox, page_ir)
            and not _zone_deja_couverte(item.bbox, zones_rasterisees)
            and not _zone_deja_couverte(item.bbox, [tableau.bbox for tableau in tableaux], seuil=0.55)
            and not _zone_touche_tableau(item.bbox, tableaux)
        ]
        if zones_vectorielles_complexes:
            sources_vectorielles = list(page_ir.elements)
            _appliquer_filtre_page(
                page_ir,
                _filtrer_formes_couvertes,
                zones_vectorielles_complexes,
                reason="covered-by-vector-raster-zone",
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
                components = [item for item in sources_vectorielles if isinstance(item, ShapeEl) and overlap_ratio(item.bbox, zone) == 1.0]
                _lier_composants_raster(page_ir, raster, components, "layout-vector-cluster-raster", dpi=dpi)
                zones_rasterisees.append(raster.bbox)
                rapport.clusters_rasterises += 1
            if verbose:
                print(
                    f"      zones vectorielles complexes rastérisées: {len(zones_vectorielles_complexes)}",
                    file=sys.stderr,
                )
        zones_visuelles_ia = [] if page_pdf_natif_candidat else _zones_visuelles_ia_a_rasteriser(
            plan_layout,
            zones_rasterisees + zones_images_source + [tableau.bbox for tableau in tableaux],
            page_ir,
        )
        zones_visuelles_ia = [
            zone for zone in zones_visuelles_ia if not _zone_touche_tableau(zone, tableaux)
        ]
        if zones_visuelles_ia:
            sources_visuelles = list(page_ir.elements)
            _appliquer_filtre_page(
                page_ir,
                _filtrer_elements_visuels_couverts,
                zones_visuelles_ia,
                reason="covered-by-layout-ai-visual-zone",
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
                components = [item for item in sources_visuelles if isinstance(item, (ShapeEl, ImageEl, RasterEl))
                              and overlap_ratio(item.bbox, zone) == 1.0]
                _lier_composants_raster(page_ir, raster, components, "layout-visual-region-raster", dpi=dpi)
                zones_rasterisees.append(raster.bbox)
                rapport.clusters_rasterises += 1
            if verbose:
                print(
                    f"      zones IA visuelles rastérisées: {len(zones_visuelles_ia)}",
                    file=sys.stderr,
                )
        zones_formules = _zones_formules_a_rasteriser(
            plan_layout,
            zones_images_source + [tableau.bbox for tableau in tableaux],
            lignes_natives,
            page_ir,
        )
        if zones_formules:
            sources_formules = list(page_ir.elements)
            _appliquer_filtre_page(
                page_ir,
                _filtrer_elements_visuels_couverts,
                zones_formules,
                reason="covered-by-formula-zone",
            )
            for zone in zones_formules:
                raster = rasteriser_region(
                    page_pdf,
                    zone,
                    document.media,
                    dpi=dpi,
                    purpose="formula",
                )
                page_ir.elements.append(raster)
                components = [item for item in sources_formules if overlap_ratio(item.bbox, zone) == 1.0]
                _lier_composants_raster(page_ir, raster, components, "layout-formula-raster", dpi=dpi)
                zones_rasterisees.append(raster.bbox)
                rapport.clusters_rasterises += 1
            if verbose:
                print(
                    f"      zones formules rastérisées: {len(zones_formules)}",
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
        zones_ocr_interdites = zones_ocr_dur_du_plan(plan_layout)
        if verbose:
            print(f"      {comprehension.resume()}", file=sys.stderr)
        if ocr_layout == "word-native" and _page_image_pleine_sans_texte_natif(
            zones_images_source,
            lignes_natives,
            page_ir,
        ):
            ocr_visible = extraire_rapidocr(
                page_pdf,
                polices,
                dpi=max(dpi, 300),
                verbose=False,
                granularite=ocr_granularity,
                layout=ocr_layout,
                zones_ignorees=[],
                media=None,
                layout_map=None,
                geometrie=geometrie,
                observation_page=page_ir,
                language=ocr_language,
                model_root=ocr_model_root,
            )
            # An English-only rescue would add Latin hallucinations to a
            # multilingual scan. Keep that legacy supplement explicitly Latin.
            ocr_visible += extraire_tesseract_lignes_absentes(
                page_pdf,
                polices,
                ocr_visible,
                dpi=max(dpi, 300),
                geometrie=geometrie,
            ) if ocr_language in {"en", "eng"} else []
            capture_source_observations(page_ir, ocr_visible, source_kind="ocr")
            lignes_visibles = _preparer_ocr_visible_page_image(ocr_visible)
            _styliser_ocr_depuis_image_scanee(page_pdf, ocr_visible, geometrie)
            nettoyes = nettoyer_tuiles_page_depuis_source(
                page_pdf,
                page_ir.elements,
                ocr_visible,
                document.media,
                dpi=max(dpi, 300),
                geometrie=geometrie,
            )
            nettoyes += nettoyer_images_fond_texte_positionne(
                page_ir.elements,
                ocr_visible,
                document.media,
            )
            nettoyes += resserrer_ancres_visuelles(page_ir.elements, document.media)
            page_ir.elements.extend(ocr_visible)
            if verbose:
                print(
                    "      page image pleine: fond inpainté + "
                    f"OCR Word visible={lignes_visibles}, image(s) nettoyée(s)={nettoyes}",
                    file=sys.stderr,
                )
            return
        if ocr_layout == "word-native" and _page_pdf_natif_mixe(
            lignes_natives,
            zones_images_source,
            page_ir,
        ):
            textes_natifs = _extraire_texte_pdf_natif_word_native(
                page_pdf,
                polices,
                plan_layout,
                zones_images,
                zones_textes_visuelles_natives,
                page_ir,
                document,
                zones_ia=page_layout_ai.zones if page_layout_ai else None,
                geometrie=geometrie,
            )
            page_ir.elements.extend(textes_natifs)
            # Une page native mixte contient souvent du texte imprimé dans ses
            # images. Le chemin natif ne peut pas le voir : on lance donc une
            # OCR locale uniquement dans les images, en excluant les lignes PDF
            # déjà récupérées pour éviter les doublons.
            zones_natives = [ligne.bbox for element in textes_natifs for ligne in element.lignes]
            # Les images source restent des objets visuels. L'OCR ne peut être
            # lancé que sur les zones explicitement classées comme texte-image par
            # le plan, jamais sur toute la page graphique.
            zones_ocr_images = list(zones_images)
            if zones_ocr_images:
                textes_images = extraire_rapidocr(
                    page_pdf,
                    polices,
                    dpi=max(dpi, 200),
                    verbose=False,
                    granularite=ocr_granularity,
                    layout="word-native",
                    zones_ignorees=zones_natives,
                    layout_map=None,
                    geometrie=geometrie,
                    zones_cibles=zones_ocr_images,
                    observation_page=page_ir,
                    language=ocr_language,
                    model_root=ocr_model_root,
                )
                page_ir.elements.extend(textes_images)
            else:
                textes_images = []
            # The native-mixed path returns before the generic OCR cleanup.  It
            # still needs the same duplicate/isolated-fragment pass, otherwise
            # a second extraction of a caption can survive into the DOCX.
            _dedoublonner_textes_positionnes(page_ir)
            if verbose:
                lignes_texte = sum(len(element.lignes) for element in textes_natifs)
                print(
                    "      page PDF native: texte PDF conservé + "
                    f"OCR images={len(textes_images)}, lignes Word={lignes_texte}",
                    file=sys.stderr,
                )
            return

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
        page_ir.elements.extend(
            extraire_glyphes_images(
                page_pdf,
                document.media,
                dpi=dpi,
                geometrie=geometrie,
            )
        )
        return

    if text_mode == "rapidocr":
        elements_ocr = extraire_rapidocr(
            page_pdf,
            polices,
            dpi=dpi,
            verbose=verbose,
            granularite=ocr_granularity,
            layout=ocr_layout,
            zones_ignorees=zones_ocr_interdites,
            media=document.media,
            layout_map=layout_map,
            geometrie=geometrie,
            observation_page=page_ir,
            language=ocr_language,
            model_root=ocr_model_root,
        )
        capture_source_observations(page_ir, elements_ocr)
        if comprehension is not None:
            elements_ocr_avant_plan = list(elements_ocr)
            elements_ocr = _attacher_frames_texte(elements_ocr, plan_layout)
            elements_ocr = filtrer_elements_selon_plan(
                elements_ocr,
                plan_layout,
                preserver_texte_natif=ocr_layout == "word-native",
            )
            _journaliser_elements_rejetes(
                page_ir,
                elements_ocr_avant_plan,
                elements_ocr,
                "filtered-by-layout-plan",
            )
        if zones_textes_visuelles_natives and ocr_layout == "word-native":
            elements_ocr_avant_zone = list(elements_ocr)
            elements_ocr = _filtrer_textes_intersectant_zones(elements_ocr, zones_textes_visuelles_natives)
            _journaliser_elements_rejetes(
                page_ir,
                elements_ocr_avant_zone,
                elements_ocr,
                "text-intersects-native-visual-zone",
            )
        if ocr_layout == "word-native":
            page_ir.elements.extend(
                _fonds_synthetiques_texte_inverse(page_pdf, elements_ocr, page_ir, geometrie)
            )
            nettoyer_images_fond_texte_positionne(page_ir.elements, elements_ocr, document.media)
            resserrer_ancres_visuelles(page_ir.elements, document.media)
        page_ir.elements.extend(elements_ocr)
        if zones_textes_visuelles_natives and ocr_layout == "word-native":
            layout_map_natif_visuel = layout_map_natif_visuel or construire_layout_map(
                page_pdf,
                geometrie=geometrie,
                observation_page=page_ir,
            )
            capture_source_observations(page_ir, textes_visuels, source_kind="pdf-native")
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

    # Les modes spans/glyphs doivent eux aussi disposer d'une compréhension de
    # page et d'un plan de cadres. Ils ne déclenchent pas les filtres OCR, mais
    # leurs textes natifs reçoivent le même contexte spatial et sémantique.
    if comprehension is None:
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
            _diagnostic_layout(
                page_ir.index,
                analyse_layout.resume(),
                comprehension,
                plan_layout,
                page_layout_ai,
            )
        )

    blocs = (
        extraire_texte_glyphes(page_pdf, polices, geometrie=geometrie)
        if text_mode == "glyphs"
        else extraire_texte(page_pdf, polices, geometrie=geometrie)
    )
    capture_source_observations(page_ir, blocs, source_kind="pdf-native")
    # Le chemin spans/glyphs ne passait historiquement jamais par le plan de
    # lecture. Les zones IA restent pourtant utiles ici : elles déterminent le
    # conteneur sémantique de chaque ligne sans convertir le texte en image.
    # Le writer recevra donc les mêmes cadres que les chemins OCR.
    if page_layout_ai is not None:
        blocs = _attacher_frames_texte(blocs, plan_layout or [], page_layout_ai.zones)
    page_ir.elements.extend(blocs)
    page_ir.elements.extend(appliquer_liens(page_pdf, blocs, geometrie=geometrie))


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
    layout_ai: bool = True,
    layout_provider: str | None = None,
    layout_model: str | None = None,
    layout_model_root: str | None = None,
    layout_device: str | None = None,
    verbose: bool = False,
    rapport: Rapport | None = None,
    ai_models_root=None,
    ocr_language: str = "auto",
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

        document = Document(polices=polices, source_pdf_id=sha256(Path(chemin_pdf).read_bytes()).hexdigest(),
                            options_snapshot={"dpi": dpi, "text_mode": text_mode, "ocr_layout": ocr_layout,
                                              "ocr_granularity": ocr_granularity, "rasteriser_pages": rasteriser_pages,
                                              "layout_ai": layout_ai, "seuil_raster": seuil_raster})
        document.options_snapshot.update({"ocr_language": ocr_language,
                                          "ai_models_root": str(ai_models_root) if ai_models_root is not None else None})
        document.scene_id = document.source_pdf_id

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
                coordinate_space=geometrie.repere,
                orientation=geometrie.orientation,
                format_name=geometrie.format_nom,
                rotation_pdf=geometrie.rotation,
                source_pdf_id=document.source_pdf_id,
                scene_id=f"{document.source_pdf_id}:page:{index}",
                options_snapshot=dict(document.options_snapshot),
                native_width_pt=(
                    geometrie.coordinate_system.media_width_pt
                    if geometrie.coordinate_system is not None
                    else None
                ),
                native_height_pt=(
                    geometrie.coordinate_system.media_height_pt
                    if geometrie.coordinate_system is not None
                    else None
                ),
            )

            if rasteriser_pages:
                if verbose:
                    print("    rasterisation page segmentée", file=sys.stderr)
                page_ir.elements.extend(
                    rasteriser_regions_segmentees_sans_texte(
                        page_pdf,
                        BBox(0, 0, page_ir.largeur_emu, page_ir.hauteur_emu),
                        document.media,
                        dpi=dpi,
                        geometrie=geometrie,
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
                            observation_page=page_ir,
                        )
                    )
                _securiser_elements_visuels_page(page_ir, document.media)
                capture_source_observations(page_ir, page_ir.elements)
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
                    ocr_language=ocr_language,
                    ocr_model_root=ai_models_root if ai_models_root is not None else layout_model_root,
                )
            except Exception as erreur:  # noqa: BLE001 — une page ne fait jamais tout échouer
                if strict:
                    raise
                elements_avant_degradation = list(page_ir.elements)
                capture_source_observations(page_ir, elements_avant_degradation)
                page_ir.elements = rasteriser_regions_segmentees_sans_texte(
                    page_pdf,
                    BBox(0, 0, page_ir.largeur_emu, page_ir.hauteur_emu),
                    document.media,
                    dpi=dpi,
                    geometrie=geometrie,
                )
                _journaliser_elements_rejetes(
                    page_ir,
                    elements_avant_degradation,
                    page_ir.elements,
                    "page-degraded-to-raster-fallback",
                )
                for raster in page_ir.elements:
                    components = [item for item in elements_avant_degradation
                                  if overlap_ratio(item.bbox, raster.bbox) == 1.0]
                    _lier_composants_raster(page_ir, raster, components, f"page-extraction-error:{type(erreur).__name__}", dpi=dpi)
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
                        observation_page=page_ir,
                    )
                )

            _securiser_elements_visuels_page(page_ir, document.media)
            capture_source_observations(page_ir, page_ir.elements)
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

        # Phase 0 : exposer une scène canonique d'observation après la construction
        # historique de l'IR. Cette vue ne filtre ni ne remplace aucun élément et
        # permet de comparer les prochaines phases à la sortie existante.
        from pdfexact.scene import scene_from_legacy_document

        document.scene = scene_from_legacy_document(document)

        return document
    finally:
        doc.close()
