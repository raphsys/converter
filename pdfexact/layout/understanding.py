"""Compréhension légère des structures de page.

Cette couche est volontairement native à pdfexact : elle reprend les idées utiles de
Vysi (frames, zones protégées, classification par rôle), mais elle reste branchée sur
l'IR du convertisseur. Elle ne rend rien ; elle décide quelles zones peuvent être
converties en Word et quelles zones doivent être protégées.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from pdfexact.geometry import BBox, pt_vers_emu, se_chevauchent, union
from pdfexact.analysis.geometry import bbox_area, center_in, clip_bbox_nonempty, intersection_area, overlap_ratio
from pdfexact.analysis.provenance import expliquer_filtrage
from pdfexact.ir import FlowParagraph, ImageEl, RasterEl, ShapeEl, TableEl, TextBox
from pdfexact.layout.classifier import detecter_regions_colonnes
from pdfexact.layout.ai import LayoutAIZone


OCR_PROTECTED_STRATEGIES = frozenset(
    {
        "word-table",
        "raster-immutable",
        "raster-image",
    }
)
LAYOUT_PROTECTED_STRATEGIES = OCR_PROTECTED_STRATEGIES
EDITABLE_STRATEGIES = frozenset(
    {
        "word-text",
        "word-table",
    }
)


@dataclass(frozen=True)
class UnderstandingZone:
    kind: str
    bbox: BBox
    source: str
    confidence: float = 1.0
    protect_ocr: bool = False
    protect_layout: bool = False


@dataclass(frozen=True)
class UnderstandingElement:
    """Decision documentaire pour un element de page.

    Une zone protegee dit seulement "ne pas OCR ici". Un element explique ce que la
    zone represente et comment elle doit etre rendue. C'est la couche de comprehension
    qui evite que OCR, find_tables() ou les heuristiques vectorielles decident seuls.
    """

    kind: str
    bbox: BBox
    source: str
    role: str
    strategy: str
    editable: bool
    confidence: float = 1.0
    context: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


@dataclass
class PageUnderstanding:
    page_width: int
    page_height: int
    zones: list[UnderstandingZone] = field(default_factory=list)
    elements: list[UnderstandingElement] = field(default_factory=list)
    profiles: set[str] = field(default_factory=set)

    def add(
        self,
        kind: str,
        bbox: BBox,
        source: str,
        *,
        confidence: float = 1.0,
        protect_ocr: bool = False,
        protect_layout: bool = False,
    ) -> None:
        bbox = _clip_bbox(bbox, self.page_width, self.page_height)
        if bbox.largeur <= 0 or bbox.hauteur <= 0:
            return
        self.zones.append(
            UnderstandingZone(
                kind=kind,
                bbox=bbox,
                source=source,
                confidence=confidence,
                protect_ocr=protect_ocr,
                protect_layout=protect_layout,
            )
        )

    def add_element(
        self,
        kind: str,
        bbox: BBox,
        source: str,
        *,
        role: str,
        strategy: str,
        editable: bool,
        confidence: float = 1.0,
        reasons: Iterable[str] = (),
    ) -> None:
        bbox = _clip_bbox(bbox, self.page_width, self.page_height)
        if bbox.largeur <= 0 or bbox.hauteur <= 0:
            return
        self.elements.append(
            UnderstandingElement(
                kind=kind,
                bbox=bbox,
                source=source,
                role=role,
                strategy=strategy,
                editable=editable,
                confidence=confidence,
                context=tuple(sorted(self.profiles)),
                reasons=tuple(reasons),
            )
        )

    @property
    def zones_ocr(self) -> list[BBox]:
        return _fusionner_zones(
            [
                *(zone.bbox for zone in self.zones if zone.protect_ocr),
                *(
                    element.bbox
                    for element in self.elements
                    if element.strategy in OCR_PROTECTED_STRATEGIES
                ),
            ]
        )

    @property
    def zones_layout(self) -> list[BBox]:
        return _fusionner_zones(
            [
                *(zone.bbox for zone in self.zones if zone.protect_layout or zone.protect_ocr),
                *(
                    element.bbox
                    for element in self.elements
                    if element.strategy in LAYOUT_PROTECTED_STRATEGIES
                ),
            ]
        )

    @property
    def elements_editables(self) -> list[UnderstandingElement]:
        return [
            element
            for element in self.elements
            if element.editable or element.strategy in EDITABLE_STRATEGIES
        ]

    @property
    def elements_immuables(self) -> list[UnderstandingElement]:
        return [
            element
            for element in self.elements
            if not element.editable and element.strategy not in EDITABLE_STRATEGIES
        ]

    def zones_strategie(self, *strategies: str) -> list[BBox]:
        selection = set(strategies)
        return _fusionner_zones(
            element.bbox for element in self.elements if element.strategy in selection
        )

    def resume(self) -> str:
        comptes: dict[str, int] = {}
        for zone in self.zones:
            comptes[zone.kind] = comptes.get(zone.kind, 0) + 1
        morceaux = [f"{cle}={valeur}" for cle, valeur in sorted(comptes.items())]
        decisions: dict[str, int] = {}
        for element in self.elements:
            decisions[element.role] = decisions.get(element.role, 0) + 1
        if decisions:
            resume_decisions = ",".join(
                f"{cle}={valeur}" for cle, valeur in sorted(decisions.items())
            )
            morceaux.append(f"elements[{resume_decisions}]")
        profils = ",".join(sorted(self.profiles)) if self.profiles else "standard"
        return f"layout: profils={profils}; " + ", ".join(morceaux)


def comprendre_page(
    *,
    largeur_emu: int,
    hauteur_emu: int,
    tableaux: list[TableEl],
    images: list[ImageEl | RasterEl],
    formes: list[ShapeEl],
    zones_rasterisees: list[BBox],
    lignes_natives: list[BBox] | None = None,
    zones_ia: list[LayoutAIZone] | tuple[LayoutAIZone, ...] | None = None,
) -> PageUnderstanding:
    """Construit une carte décisionnelle de la page."""
    comprehension = PageUnderstanding(largeur_emu, hauteur_emu)
    aire_page = max(largeur_emu * hauteur_emu, 1)

    for tableau in tableaux:
        dense = _table_dense(tableau)
        raisons = ["pdf-table"]
        raisons.append("table-has-text" if _table_a_du_texte(tableau) else "table-empty")
        if dense:
            raisons.append("dense")
            comprehension.profiles.add("dense-table")
        comprehension.add(
            "table",
            tableau.bbox,
            "pdf-table",
            confidence=0.95,
            protect_ocr=True,
            protect_layout=True,
        )
        comprehension.add_element(
            "table",
            tableau.bbox,
            "pdf-table",
            role="real-table",
            strategy="word-table",
            editable=True,
            confidence=0.95,
            reasons=raisons,
        )

    for image in images:
        kind = "fullpage-image" if _aire(image.bbox) / aire_page > 0.82 else "image"
        if kind == "fullpage-image":
            comprehension.profiles.add("scanned-or-image-page")
        comprehension.add(
            kind,
            image.bbox,
            "pdf-image",
            protect_ocr=True,
            protect_layout=True,
        )
        comprehension.add_element(
            kind,
            image.bbox,
            "pdf-image",
            role="scanned-page" if kind == "fullpage-image" else "image",
            strategy="raster-image",
            editable=False,
            confidence=0.90,
            reasons=[kind],
        )

    for zone in zones_rasterisees:
        kind = "formula-or-vector" if _zone_formula_like(zone) else "raster-zone"
        comprehension.add(
            kind,
            zone,
            "vector-raster",
            confidence=0.85,
            protect_ocr=True,
            protect_layout=True,
        )
        comprehension.add_element(
            kind,
            zone,
            "vector-raster",
            role="formula-or-complex-vector" if kind == "formula-or-vector" else "raster-zone",
            strategy="raster-immutable",
            editable=False,
            confidence=0.85,
            reasons=[kind],
        )

    for zone in _zones_vectorielles_complexes(
        formes,
        largeur_emu,
        hauteur_emu,
        comprehension.zones_ocr,
        [image.bbox for image in images],
    ):
        comprehension.add(
            "complex-vector-zone",
            zone,
            "vector-cluster",
            confidence=0.80,
            protect_ocr=True,
            protect_layout=True,
        )
        comprehension.profiles.add("complex-vector")
        comprehension.add_element(
            "complex-vector-zone",
            zone,
            "vector-cluster",
            role="figure-or-diagram",
            strategy="raster-immutable",
            editable=False,
            confidence=0.80,
            reasons=["dense-vector-cluster"],
        )

    zones_ia_effectives = [
        zone_ia
        for zone_ia in zones_ia or ()
        if not _zone_ia_deja_decrite_par_source(
            zone_ia,
            images,
            zones_rasterisees,
            formes,
            largeur_emu,
            hauteur_emu,
        )
    ]
    for zone_ia in zones_ia_effectives:
        role, strategy, editable = _decision_zone_ia(zone_ia)
        if role == "ignore":
            continue
        if role in {"text-column", "heading", "list"} and _dans_zone_bloquante_texte(
            zone_ia.bbox,
            _zones_visuelles_bloquantes(comprehension),
        ):
            continue
        if role in {"text-column", "caption", "heading", "list"}:
            comprehension.profiles.add("layout-ai")
        comprehension.add_element(
            "ai-zone",
            zone_ia.bbox,
            zone_ia.source,
            role=role,
            strategy=strategy,
            editable=editable,
            confidence=zone_ia.confidence if zone_ia.confidence is not None else 0.66,
            reasons=[f"ai-label:{zone_ia.label}", f"ai-role:{zone_ia.role}"],
        )

    if lignes_natives:
        zones_preservation_texte = [
            *_zones_visuelles_protegees(comprehension),
            *_zones_tables_bandeaux_avec_texte(comprehension, lignes_natives),
            *_zones_bandeaux_couleur_formes_avec_texte(
                formes,
                lignes_natives,
                largeur_emu,
                hauteur_emu,
            ),
        ]
        lignes_visuelles = _lignes_dans_zones_visuelles_protegees(
            lignes_natives,
            zones_preservation_texte,
        )
        for ligne in lignes_visuelles:
            comprehension.add_element(
                "text-in-visual",
                ligne,
                "native-text-in-protected-visual",
                role="text-column",
                strategy="word-text",
                editable=True,
                confidence=0.74,
                reasons=["native-text-inside-protected-visual"],
            )
        lignes_formes = _lignes_dans_formes_simples(
            lignes_natives,
            formes,
            largeur_emu,
            hauteur_emu,
            _zones_vectorielles_bloquantes(comprehension),
        )
        for ligne in lignes_formes:
            comprehension.add_element(
                "text-in-shape",
                ligne,
                "native-text-in-shape",
                role="text-column",
                strategy="word-text",
                editable=True,
                confidence=0.78,
                reasons=["native-text-inside-simple-shape"],
            )
        if lignes_visuelles or lignes_formes:
            comprehension.profiles.add("layout-ai" if zones_ia else "shape-text")

    for forme in formes:
        if not forme.remplissage:
            continue
        ratio = _aire(forme.bbox) / aire_page
        if ratio < 0.00025:
            continue
        if _is_page_border(forme.bbox, largeur_emu, hauteur_emu):
            comprehension.add("page-border", forme.bbox, "vector", confidence=0.75)
            comprehension.add_element(
                "page-border",
                forme.bbox,
                "vector",
                role="page-border",
                strategy="shape",
                editable=False,
                confidence=0.75,
                reasons=["thin-near-page-edge"],
            )
            continue
        if _is_color_band(forme.bbox, largeur_emu, hauteur_emu):
            comprehension.profiles.add("colored-bands")
            comprehension.add(
                "color-band",
                forme.bbox,
                "vector-fill",
                confidence=0.85,
                protect_layout=True,
            )
            comprehension.add_element(
                "color-band",
                forme.bbox,
                "vector-fill",
                role="section-band",
                strategy="shape-background",
                editable=False,
                confidence=0.85,
                reasons=["wide-colored-fill"],
            )

    if lignes_natives:
        regions_colonnes = detecter_regions_colonnes(lignes_natives, largeur_emu, hauteur_emu)
        if len(regions_colonnes) >= 3:
            comprehension.profiles.add("multi-column-3plus")
        elif len(regions_colonnes) == 2:
            comprehension.profiles.add("two-column")
        for index, colonne in enumerate(regions_colonnes):
            comprehension.add_element(
                "text-column",
                colonne,
                "native-lines",
                role="text-column",
                strategy="word-text",
                editable=True,
                confidence=0.70,
                reasons=[f"column-{index + 1}/{len(regions_colonnes)}"],
            )

    if largeur_emu > hauteur_emu:
        comprehension.profiles.add("landscape")
    if len(tableaux) >= 2:
        comprehension.profiles.add("table-heavy")

    return comprehension


def _decision_zone_ia(zone: LayoutAIZone) -> tuple[str, str, bool]:
    label = zone.label.casefold().replace(" ", "_").replace("-", "_")
    role = zone.role
    if role == "caption" or "caption" in label or "figure_title" in label or "table_title" in label:
        return "caption", "word-text", True
    if "title" in label:
        return "heading", "word-text", True
    if "list" in label:
        return "list", "word-text", True
    if role == "text" or "text" in label or "content" in label:
        return "text-column", "word-text", True
    if role == "table" or "table" in label:
        return "real-table", "word-table", True
    if role == "formula" or "formula" in label or "equation" in label:
        return "formula-or-complex-vector", "raster-immutable", False
    if role == "visual" or "figure" in label or "image" in label or "chart" in label:
        return "figure-or-diagram", "raster-image", False
    return "ignore", "ignore", False


def filtrer_elements_proteges(elements: list, zones_protegees: list[BBox]) -> list:
    """Supprime les fuites OCR dans des zones déjà reconstruites autrement."""
    if not zones_protegees:
        return elements
    filtres = []
    for element in elements:
        bbox = getattr(element, "bbox", None)
        if bbox is None:
            filtres.append(element)
            continue
        if isinstance(element, (TextBox, FlowParagraph)) and _touche_zone(bbox, zones_protegees):
            expliquer_filtrage(element, "protected-by-understanding-zone")
            continue
        filtres.append(element)
    return filtres


def filtrer_elements_selon_comprehension(
    elements: list,
    comprehension: PageUnderstanding,
) -> list:
    """Applique le plan de comprehension aux elements OCR.

    Le filtrage ne dépend plus d'une liste de boîtes passée au hasard par l'appelant :
    il est dérivé des stratégies d'éléments. Un `word-table`, une image immuable ou une
    formule rasterisée protègent leur zone ; un bandeau de section ne bloque pas l'OCR.
    """
    return filtrer_elements_proteges(elements, comprehension.zones_ocr)


def _aire(bbox: BBox) -> int:
    return bbox_area(bbox)


def _intersection(a: BBox, b: BBox) -> int:
    return intersection_area(a, b)


def _recouvrement_source(a: BBox, b: BBox) -> float:
    return overlap_ratio(a, b)


def _zone_ia_deja_decrite_par_source(
    zone: LayoutAIZone,
    images: list[ImageEl | RasterEl],
    zones_rasterisees: list[BBox],
    formes: list[ShapeEl],
    largeur_emu: int,
    hauteur_emu: int,
) -> bool:
    """Ignore une boîte IA visuelle qui englobe déjà des composants natifs."""
    if zone.role not in {"visual", "figure", "image", "chart"}:
        return False
    aire_page = max(largeur_emu * hauteur_emu, 1)
    aire_zone = max(_aire(zone.bbox), 1)
    if aire_zone / aire_page < 0.08:
        return False

    # Une boîte IA plus large qu'une image PDF déjà extraite est une composition,
    # pas une nouvelle image à rendre. Les petits écarts de détection sont tolérés.
    composants = [image.bbox for image in images] + list(zones_rasterisees)
    for composant in composants:
        if (
            _recouvrement_source(zone.bbox, composant) >= 0.55
            and _recouvrement_source(composant, zone.bbox) >= 0.80
        ):
            return True

    # Plusieurs grands dessins indépendants sont une seconde preuve de composition
    # lorsque la page ne contient pas d'image raster source.
    grandes_formes = [
        forme.bbox
        for forme in formes
        if _aire(forme.bbox) / aire_page >= 0.01
        and _recouvrement_source(forme.bbox, zone.bbox) >= 0.55
    ]
    preuves: list[BBox] = []
    for forme in grandes_formes:
        if any(_recouvrement_source(forme, preuve) >= 0.65 for preuve in preuves):
            continue
        preuves.append(forme)
    return len(preuves) >= 2 and aire_zone / aire_page >= 0.15


def _clip_bbox(bbox: BBox, largeur: int, hauteur: int) -> BBox:
    return clip_bbox_nonempty(bbox, largeur, hauteur)


def _fusionner_zones(zones: Iterable[BBox]) -> list[BBox]:
    result: list[BBox] = []
    marge = pt_vers_emu(1.5)
    for zone in sorted(zones, key=lambda item: (item.y0, item.x0)):
        etendue = BBox(zone.x0 - marge, zone.y0 - marge, zone.x1 + marge, zone.y1 + marge)
        fusion = None
        for index, existante in enumerate(result):
            if se_chevauchent(etendue, existante):
                fusion = index
                break
        if fusion is None:
            result.append(zone)
        else:
            result[fusion] = union(result[fusion], zone)
    return sorted(result, key=lambda item: (item.y0, item.x0))


def _touche_zone(bbox: BBox, zones: list[BBox], seuil: float = 0.12) -> bool:
    aire = max(_aire(bbox), 1)
    for zone in zones:
        if _centre_dans(bbox, zone):
            return True
        if _intersection(bbox, zone) / aire >= seuil:
            return True
    return False


def _centre_dans(bbox: BBox, zone: BBox) -> bool:
    return center_in(bbox, zone)


def _lignes_dans_formes_simples(
    lignes: list[BBox],
    formes: list[ShapeEl],
    largeur_emu: int,
    hauteur_emu: int,
    zones_deja_protegees: list[BBox],
) -> list[BBox]:
    """Préserve les libellés natifs posés dans des boîtes vectorielles éditables."""
    formes_simples = [
        forme.bbox
        for forme in formes
        if forme.remplissage
        and _forme_simple_texte(forme.bbox, largeur_emu, hauteur_emu)
    ]
    if not formes_simples:
        return []
    gardees: list[BBox] = []
    marge = pt_vers_emu(2)
    for ligne in lignes:
        if ligne.largeur < pt_vers_emu(6) or ligne.hauteur < pt_vers_emu(4):
            continue
        if _dans_zone_bloquante_texte(ligne, zones_deja_protegees):
            continue
        for forme in formes_simples:
            etendue = BBox(forme.x0 - marge, forme.y0 - marge, forme.x1 + marge, forme.y1 + marge)
            if _centre_dans(ligne, etendue) and _intersection(ligne, etendue) / max(_aire(ligne), 1) >= 0.55:
                gardees.append(ligne)
                break
    return _fusionner_zones(gardees)


def _zones_visuelles_protegees(comprehension: PageUnderstanding) -> list[BBox]:
    return _fusionner_zones(
        element.bbox
        for element in comprehension.elements
        if element.strategy in OCR_PROTECTED_STRATEGIES
        and element.role
        not in {
            "real-table",
            "image",
            "scanned-page",
            "figure-or-diagram",
            "formula-or-complex-vector",
            "raster-zone",
        }
    )


def _zones_tables_bandeaux_avec_texte(
    comprehension: PageUnderstanding,
    lignes_natives: list[BBox],
) -> list[BBox]:
    zones: list[BBox] = []
    for element in comprehension.elements:
        if element.role != "real-table" or element.strategy != "word-table":
            continue
        if element.source == "pdf-table" and "table-has-text" in element.reasons:
            continue
        if element.bbox.y0 > comprehension.page_height * 0.25:
            continue
        if element.bbox.hauteur > pt_vers_emu(90):
            continue
        lignes_dans_zone = [
            ligne
            for ligne in lignes_natives
            if _centre_dans(ligne, element.bbox)
            or _intersection(ligne, element.bbox) / max(_aire(ligne), 1) >= 0.55
        ]
        if 1 <= len(lignes_dans_zone) <= 8:
            zones.append(element.bbox)
    return _fusionner_zones(zones)


def _zones_bandeaux_couleur_formes_avec_texte(
    formes: list[ShapeEl],
    lignes_natives: list[BBox],
    largeur_emu: int,
    hauteur_emu: int,
) -> list[BBox]:
    zones: list[BBox] = []
    for forme in formes:
        if not forme.remplissage:
            continue
        if not _is_color_band(forme.bbox, largeur_emu, hauteur_emu):
            continue
        if forme.bbox.hauteur > pt_vers_emu(80):
            continue
        lignes_dans_zone = [
            ligne
            for ligne in lignes_natives
            if _centre_dans(ligne, forme.bbox)
            or _intersection(ligne, forme.bbox) / max(_aire(ligne), 1) >= 0.55
        ]
        if lignes_dans_zone:
            zones.append(forme.bbox)
    return _fusionner_zones(zones)


def _zones_visuelles_bloquantes(comprehension: PageUnderstanding) -> list[BBox]:
    return _fusionner_zones(
        element.bbox
        for element in comprehension.elements
        if element.strategy in OCR_PROTECTED_STRATEGIES
        and element.role
        in {
            "image",
            "scanned-page",
            "figure-or-diagram",
            "formula-or-complex-vector",
            "raster-zone",
        }
    )


def _zones_vectorielles_bloquantes(comprehension: PageUnderstanding) -> list[BBox]:
    return _fusionner_zones(
        element.bbox
        for element in comprehension.elements
        if element.strategy in OCR_PROTECTED_STRATEGIES
        and element.source in {"vector-cluster", "vector-raster"}
        and element.role in {"figure-or-diagram", "formula-or-complex-vector", "raster-zone"}
    )


def _dans_zone_bloquante_texte(bbox: BBox, zones: list[BBox]) -> bool:
    aire = max(_aire(bbox), 1)
    for zone in zones:
        ratio = _intersection(bbox, zone) / aire
        if ratio >= 0.85:
            return True
        if ratio >= 0.60 and _centre_dans(bbox, zone):
            return True
    return False


def _lignes_dans_zones_visuelles_protegees(
    lignes: list[BBox],
    zones_visuelles: list[BBox],
) -> list[BBox]:
    if not lignes or not zones_visuelles:
        return []
    gardees: list[BBox] = []
    for ligne in lignes:
        if ligne.largeur < pt_vers_emu(5) or ligne.hauteur < pt_vers_emu(3):
            continue
        if ligne.hauteur > pt_vers_emu(48):
            continue
        aire_ligne = max(_aire(ligne), 1)
        for zone in zones_visuelles:
            if _centre_dans(ligne, zone) or _intersection(ligne, zone) / aire_ligne >= 0.55:
                gardees.append(ligne)
                break
    return _fusionner_zones(gardees)


def _forme_simple_texte(bbox: BBox, largeur_emu: int, hauteur_emu: int) -> bool:
    if _is_page_border(bbox, largeur_emu, hauteur_emu) or _is_color_band(bbox, largeur_emu, hauteur_emu):
        return False
    largeur_pt = bbox.largeur / 12700
    hauteur_pt = bbox.hauteur / 12700
    if largeur_pt < 18 or hauteur_pt < 10:
        return False
    if largeur_pt > 190 or hauteur_pt > 70:
        return False
    return (_aire(bbox) / max(largeur_emu * hauteur_emu, 1)) <= 0.08


def _recouvrement_source(a: BBox, b: BBox) -> float:
    return overlap_ratio(a, b)


def _table_dense(tableau: TableEl) -> bool:
    cellules = sum(len(row.cells) for row in tableau.rows)
    return cellules >= 80 or len(tableau.rows) >= 28


def _table_a_du_texte(tableau: TableEl) -> bool:
    return any(cell.texte.strip() for row in tableau.rows for cell in row.cells)


def _zone_formula_like(bbox: BBox) -> bool:
    largeur_pt = bbox.largeur / 12700
    hauteur_pt = bbox.hauteur / 12700
    return hauteur_pt <= 90 and largeur_pt >= 35


def _is_color_band(bbox: BBox, largeur: int, hauteur: int) -> bool:
    largeur_ratio = bbox.largeur / max(largeur, 1)
    hauteur_pt = bbox.hauteur / 12700
    return largeur_ratio >= 0.25 and 4 <= hauteur_pt <= 80


def _is_page_border(bbox: BBox, largeur: int, hauteur: int) -> bool:
    mince = min(bbox.largeur, bbox.hauteur) <= pt_vers_emu(2)
    proche_bord = (
        bbox.x0 <= pt_vers_emu(4)
        or bbox.y0 <= pt_vers_emu(4)
        or bbox.x1 >= largeur - pt_vers_emu(4)
        or bbox.y1 >= hauteur - pt_vers_emu(4)
    )
    return mince and proche_bord


def _zones_vectorielles_complexes(
    formes: list[ShapeEl],
    largeur_emu: int,
    hauteur_emu: int,
    zones_deja_protegees: list[BBox],
    zones_images: list[BBox] | None = None,
) -> list[BBox]:
    """Repère les schémas/formules/graphiques vectoriels trop complexes pour l'OCR.

    L'objectif n'est pas de rendre ces zones comme images par défaut : c'est d'empêcher
    l'OCR d'y inventer des mots. Le rendu vectoriel/tableau existant reste prioritaire.
    """
    aire_page = max(largeur_emu * hauteur_emu, 1)
    zones_images = zones_images or []
    zones: list[BBox] = _zones_conteneurs_visuels(
        formes,
        largeur_emu,
        hauteur_emu,
        zones_deja_protegees,
        zones_images,
    )
    candidates: list[BBox] = []
    for forme in formes:
        bbox = forme.bbox
        if bbox.largeur <= 0 or bbox.hauteur <= 0:
            continue
        if _is_page_border(bbox, largeur_emu, hauteur_emu):
            continue
        if _is_color_band(bbox, largeur_emu, hauteur_emu):
            continue
        if _aire(bbox) / aire_page > 0.35:
            continue
        if any(_recouvrement_source(bbox, zone) >= 0.60 for zone in zones_deja_protegees):
            continue
        if min(bbox.largeur, bbox.hauteur) < pt_vers_emu(0.25):
            continue
        candidates.append(bbox)

    for cluster in _clusteriser(candidates, marge_pt=9.0):
        if len(cluster) < 4:
            continue
        bbox = cluster[0]
        for autre in cluster[1:]:
            bbox = union(bbox, autre)
        aire_zone = _aire(bbox)
        if aire_zone < pt_vers_emu(18) * pt_vers_emu(10):
            continue
        if aire_zone / aire_page > 0.50:
            continue
        formes_fines = sum(1 for item in cluster if min(item.largeur, item.hauteur) <= pt_vers_emu(2.5))
        densite = len(cluster) / max((bbox.largeur / pt_vers_emu(1)) * (bbox.hauteur / pt_vers_emu(1)), 1.0)
        if formes_fines >= 3 or densite >= 0.00045:
            marge = pt_vers_emu(2)
            zones.append(
                _clip_bbox(
                    BBox(bbox.x0 - marge, bbox.y0 - marge, bbox.x1 + marge, bbox.y1 + marge),
                    largeur_emu,
                    hauteur_emu,
                )
            )
    return _fusionner_zones(zones)


def _zones_conteneurs_visuels(
    formes: list[ShapeEl],
    largeur_emu: int,
    hauteur_emu: int,
    zones_deja_protegees: list[BBox],
    zones_images: list[BBox],
) -> list[BBox]:
    """Détecte les panneaux/figures dont le cadre externe porte la sémantique.

    Beaucoup de PDF éditoriaux dessinent un graphique sous forme d'un grand rectangle
    blanc puis ajoutent axes, courbes, barres et labels par dessus. Si on ne protège
    que les petits traits internes, l'OCR reconstruit du texte à travers le graphique.
    La règle ici reste générale : un grand conteneur devient immuable seulement s'il
    contient déjà une image ou suffisamment d'indices vectoriels internes.
    """
    aire_page = max(largeur_emu * hauteur_emu, 1)
    zones: list[BBox] = []
    for forme in formes:
        bbox = forme.bbox
        aire = _aire(bbox)
        if aire <= 0:
            continue
        largeur_pt = bbox.largeur / 12700
        hauteur_pt = bbox.hauteur / 12700
        ratio_page = aire / aire_page
        if largeur_pt < 58 or hauteur_pt < 42:
            continue
        if ratio_page > 0.62:
            continue
        if _is_page_border(bbox, largeur_emu, hauteur_emu):
            continue
        if _is_color_band(bbox, largeur_emu, hauteur_emu):
            continue
        if any(_recouvrement_source(bbox, zone) >= 0.78 for zone in zones_deja_protegees):
            continue

        enfants = [autre for autre in formes if autre is not forme and _centre_dans(autre.bbox, bbox)]
        images_internes = [zone for zone in zones_images if _recouvrement_source(zone, bbox) >= 0.55]
        traits_fins = sum(
            1
            for enfant in enfants
            if min(enfant.bbox.largeur, enfant.bbox.hauteur) <= pt_vers_emu(2.5)
            and max(enfant.bbox.largeur, enfant.bbox.hauteur) >= pt_vers_emu(18)
        )
        formes_colorees = sum(
            1
            for enfant in enfants
            if enfant.remplissage
            and enfant.remplissage.upper() not in {"FFFFFF", "FEFFFF", "FFFFFE"}
        )
        long_traits = sum(
            1
            for enfant in enfants
            if min(enfant.bbox.largeur, enfant.bbox.hauteur) <= pt_vers_emu(1.5)
            and max(enfant.bbox.largeur, enfant.bbox.hauteur) >= min(bbox.largeur, bbox.hauteur) * 0.35
        )

        est_panneau_colore = (
            bool(forme.remplissage)
            and forme.remplissage.upper() not in {"FFFFFF", "FEFFFF", "FFFFFE"}
            and largeur_pt >= 90
            and hauteur_pt >= 110
            and ratio_page <= 0.30
        )
        est_conteneur_blanc = (
            forme.remplissage is None
            or forme.remplissage.upper() in {"FFFFFF", "FEFFFF", "FFFFFE"}
        )
        contient_figure = (
            bool(images_internes)
            or traits_fins >= 3
            or long_traits >= 2
            or formes_colorees >= 2
            or len(enfants) >= 8
        )
        if est_panneau_colore or (est_conteneur_blanc and contient_figure):
            marge = pt_vers_emu(2)
            zones.append(
                _clip_bbox(
                    BBox(bbox.x0 - marge, bbox.y0 - marge, bbox.x1 + marge, bbox.y1 + marge),
                    largeur_emu,
                    hauteur_emu,
                )
            )
    return zones


def _clusteriser(boites: list[BBox], marge_pt: float) -> list[list[BBox]]:
    marge = pt_vers_emu(marge_pt)
    clusters: list[list[BBox]] = []
    enveloppes: list[BBox] = []
    for boite in sorted(boites, key=lambda item: (item.y0, item.x0)):
        etendue = BBox(boite.x0 - marge, boite.y0 - marge, boite.x1 + marge, boite.y1 + marge)
        cible = None
        for index, enveloppe in enumerate(enveloppes):
            if se_chevauchent(etendue, enveloppe):
                cible = index
                break
        if cible is None:
            clusters.append([boite])
            enveloppes.append(boite)
        else:
            clusters[cible].append(boite)
            enveloppes[cible] = union(enveloppes[cible], boite)
    return clusters


def _detecter_colonnes(lignes: list[BBox], largeur_page: int) -> int:
    return len(detecter_regions_colonnes(lignes, largeur_page, 0))


def _detecter_regions_colonnes(lignes: list[BBox], largeur_page: int, hauteur_page: int = 0) -> list[BBox]:
    return detecter_regions_colonnes(lignes, largeur_page, hauteur_page)
