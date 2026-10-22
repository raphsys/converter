"""Représentation intermédiaire — le contrat entre extraction et rendu.

Les extracteurs produisent ces objets, le writer les consomme. Aucun des deux côtés ne
connaît l'autre. Toutes les dimensions sont en EMU, à l'exception de Span.size_pt, en
points, parce que Word exprime les corps de police en demi-points.
"""
from copy import deepcopy
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path as CheminFichier
from typing import Union

from pdfexact.geometry import BBox

# Attention : `Path` désigne ici un tracé vectoriel, pas un chemin de fichier — d'où
# l'import de pathlib sous le nom CheminFichier.
# Une commande de chemin : un opérateur et ses points, en EMU absolus.
# Opérateurs : "move", "line", "cubic", "quad", "close".
PathCommand = tuple[str, tuple[tuple[int, int], ...]]
Path = list[PathCommand]


@dataclass(frozen=True)
class FontAsset:
    """Une police du document, embarquée ou substituée par une police système.

    `font_id` est le nom PostScript relevé dans le PDF : c'est le seul point de jonction
    avec les spans, dont le dictionnaire ne porte aucun xref.
    """

    font_id: str
    famille: str
    donnees: bytes | None
    extension: str
    embarquee: bool
    # Fichier de police retrouvé par la bibliothèque. C'est lui qui fournit les métriques
    # réelles ; sans lui, on ne peut que retomber sur une approximation.
    chemin: CheminFichier | None = None
    reconnue: bool = False
    mode_resolution: str = "manquante"
    confiance_resolution: float = 0.0
    alias_resolution: str | None = None
    metriques: dict[str, float] = field(default_factory=dict)
    unicode_coverage: tuple[int, ...] = ()
    validated_equivalence: str | None = None
    substitution_source: str | None = None
    font_confidence: float | None = None
    metrics_confidence: float | None = None


@dataclass(frozen=True)
class FontRef:
    """Référence d'un span vers une police, avec son style."""

    font_id: str
    famille: str
    gras: bool
    italique: bool
    script: str = "auto"
    language: str = "auto"
    typographic_role: str | None = None
    canonical_id: str | None = None


@dataclass(frozen=True)
class VisualContract:
    """Contraintes visuelles immuables transportees jusqu'au rendu et a l'audit."""

    bbox: BBox
    quad: tuple[tuple[int, int], ...] = ()
    baseline: tuple[tuple[int, int], ...] = ()
    z_order: int = 0
    orientation: str = "horizontal"
    angle_deg: float = 0.0
    opacity: float = 1.0
    clipping: tuple[str, ...] = ()
    style: tuple[tuple[str, str], ...] = ()
    source_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TextGeometry:
    """Geometry fine d'un bloc texte, au-dela de sa bbox englobante.

    La bbox reste l'interface historique des renderers. Les lignes, quads et
    zones d'exclusion transportent la forme réelle de la composition PDF.
    """

    kind: str = "rectangular-flow"
    line_bboxes: tuple[BBox, ...] = ()
    line_quads: tuple[tuple[tuple[int, int], ...], ...] = ()
    baselines: tuple[tuple[tuple[int, int], ...], ...] = ()
    exclusion_bboxes: tuple[BBox, ...] = ()


@dataclass(frozen=True)
class MediaItem:
    """Un binaire à écrire dans word/media/."""

    media_ref: str
    donnees: bytes
    extension: str
    native_width: int | None = None
    native_height: int | None = None
    color_mode: str | None = None
    alpha: bool | None = None
    content_hash: str | None = None
    source_ids: tuple[str, ...] = ()
    dpi: tuple[float, float] | None = None
    media_kind: str = "unknown"


@dataclass
class Span:
    texte: str
    police: FontRef
    size_pt: float
    couleur: str
    espacement_twips: int = 0
    lien: str | None = None
    invisible: bool = False
    souligne: bool = False
    barre: bool = False
    capitales: bool = False
    exposant: bool = False
    indice: bool = False
    surlignage: str | None = None
    bbox: BBox | None = None
    quad: tuple[tuple[int, int], ...] = ()
    source_id: str | None = None
    angle_deg: float = 0.0
    orientation: str = "horizontal"
    baseline_points: tuple[tuple[int, int], ...] = ()
    semantic_role: str | None = None
    curved: bool = False
    z_index: int | None = None
    source_kind: str | None = None
    source_ids: tuple[str, ...] = ()
    language: str = "auto"
    script: str = "auto"
    confidence: float | None = None
    glyph_ids: tuple[int, ...] = ()
    to_unicode_status: str | None = None
    font_metrics: dict[str, float] = field(default_factory=dict)
    evidence: list[object] = field(default_factory=list)
    decision_history: list[dict[str, object]] = field(default_factory=list)
    attributes: dict[str, object] = field(default_factory=dict)
    baseline: tuple[tuple[int, int], ...] = ()
    z_order: int | None = None

    def __post_init__(self):
        if self.baseline and not self.baseline_points:
            self.baseline_points = self.baseline
        elif self.baseline_points and not self.baseline:
            self.baseline = self.baseline_points
        if self.z_order is not None and self.z_index is None:
            self.z_index = self.z_order
        elif self.z_index is not None and self.z_order is None:
            self.z_order = self.z_index


@dataclass
class Line:
    """Une ligne de texte. Devient une zone de texte OOXML à elle seule."""

    bbox: BBox
    spans: list[Span]
    hauteur_ligne_emu: int
    largeur_cible_emu: int
    alignement: str = "left"
    layout_frame_id: str | None = None
    layout_frame_role: str | None = None
    layout_frame_strategy: str | None = None
    layout_frame_bbox: BBox | None = None
    source_id: str | None = None
    angle_deg: float = 0.0
    orientation: str = "horizontal"
    baseline_points: tuple[tuple[int, int], ...] = ()
    semantic_role: str | None = None
    z_index: int | None = None
    curved: bool = False
    quad: tuple[tuple[int, int], ...] = ()
    source_kind: str | None = None
    source_ids: tuple[str, ...] = ()
    reading_direction: str | None = None
    language: str = "auto"
    script: str = "auto"
    segmentation_score: float | None = None
    boundary_before: str | None = None
    boundary_after: str | None = None
    boundary_before_confidence: float | None = None
    boundary_after_confidence: float | None = None
    confidence: float | None = None
    evidence: list[object] = field(default_factory=list)
    decision_history: list[dict[str, object]] = field(default_factory=list)
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass
class TextBox:
    """Bloc logique de texte. Regroupement seulement — le writer rend ligne par ligne."""

    bbox: BBox
    lignes: list[Line]
    layout_frame_id: str | None = None
    layout_frame_role: str | None = None
    layout_frame_strategy: str | None = None
    layout_frame_bbox: BBox | None = None
    source_id: str | None = None
    source_ids: tuple[str, ...] = ()
    angle_deg: float = 0.0
    orientation: str = "horizontal"
    semantic_role: str | None = None
    curved: bool = False
    list_marker: str | None = None
    list_level: int = 0
    list_group_id: str | None = None
    list_marker_bbox: BBox | None = None
    geometry: TextGeometry | None = None
    presentation: dict[str, object] = field(default_factory=dict)
    z_index: int | None = None
    group_id: str | None = None
    grouping_evidence: list[object] = field(default_factory=list)
    source_kind: str | None = None
    language: str = "auto"
    script: str = "auto"
    confidence: float | None = None
    extraction_confidence: float | None = None
    role_confidence: float | None = None
    geometry_confidence: float | None = None
    semantic_confidence: float | None = None
    quad: tuple[tuple[int, int], ...] = ()
    polygon: tuple[tuple[int, int], ...] = ()
    baseline_points: tuple[tuple[int, int], ...] = ()
    clip_ids: tuple[str, ...] = ()
    opacity: float = 1.0
    parent_group_id: str | None = None
    compositing: dict[str, object] = field(default_factory=dict)
    evidence: list[object] = field(default_factory=list)
    decision_history: list[dict[str, object]] = field(default_factory=list)
    duplicate_candidates: list[dict[str, object]] = field(default_factory=list)
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass
class FlowParagraph:
    """Paragraphe Word réel, dans le flux, reconstruit depuis des lignes OCR."""

    bbox: BBox
    texte: str
    police: FontRef
    size_pt: float
    couleur: str
    alignement: str = "left"
    retrait_gauche_emu: int = 0
    retrait_droite_emu: int = 0
    retrait_premiere_ligne_emu: int = 0
    espace_avant_emu: int = 0
    espace_apres_emu: int = 0
    interligne_emu: int = 0
    souligne: bool = False
    barre: bool = False
    capitales: bool = False
    surlignage: str | None = None
    espacement_twips: int = 0
    spans: list[Span] = field(default_factory=list)
    lignes: list[Line] = field(default_factory=list)
    layout_frame_id: str | None = None
    layout_frame_role: str | None = None
    layout_frame_strategy: str | None = None
    layout_frame_bbox: BBox | None = None
    vertical_alignement: str = "top"
    source_id: str | None = None
    source_ids: tuple[str, ...] = ()
    angle_deg: float = 0.0
    orientation: str = "horizontal"
    baseline_points: tuple[tuple[int, int], ...] = ()
    semantic_role: str | None = None
    z_index: int | None = None
    curved: bool = False
    list_marker: str | None = None
    list_level: int = 0
    list_group_id: str | None = None
    list_marker_bbox: BBox | None = None
    geometry: TextGeometry | None = None
    presentation: dict[str, object] = field(default_factory=dict)
    paragraph_confidence: float | None = None
    source_line_ids: tuple[str, ...] = ()
    render_decision_id: str | None = None
    source_kind: str | None = None
    language: str = "auto"
    script: str = "auto"
    confidence: float | None = None
    extraction_confidence: float | None = None
    role_confidence: float | None = None
    geometry_confidence: float | None = None
    semantic_confidence: float | None = None
    quad: tuple[tuple[int, int], ...] = ()
    polygon: tuple[tuple[int, int], ...] = ()
    clip_ids: tuple[str, ...] = ()
    opacity: float = 1.0
    parent_group_id: str | None = None
    compositing: dict[str, object] = field(default_factory=dict)
    evidence: list[object] = field(default_factory=list)
    decision_history: list[dict[str, object]] = field(default_factory=list)
    duplicate_candidates: list[dict[str, object]] = field(default_factory=list)
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass
class ImageEl:
    bbox: BBox
    media_ref: str
    # Placement PDF complet conserve pour l'audit et les cas XObject/matrices.
    placement_id: str | None = None
    source_xref: int | None = None
    quad: tuple[tuple[int, int], ...] = ()
    transform: tuple[float, ...] = ()
    alpha_preserved: bool = True
    z_index: int | None = None
    clip_bbox: BBox | None = None
    paint_group_id: str | None = None
    source_id: str | None = None
    source_ids: tuple[str, ...] = ()
    source_kind: str | None = None
    opacity: float = 1.0
    parent_group_id: str | None = None
    clip_ids: tuple[str, ...] = ()
    compositing: dict[str, object] = field(default_factory=dict)
    confidence: float | None = None
    evidence: list[object] = field(default_factory=list)
    decision_history: list[dict[str, object]] = field(default_factory=list)
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass
class ShapeEl:
    bbox: BBox
    chemins: list[Path]
    remplissage: str | None
    contour: str | None
    epaisseur_emu: int
    pointilles: str | None = None
    alpha: float = 1.0
    z_index: int | None = None
    source_id: str | None = None
    source_ids: tuple[str, ...] = ()
    source_kind: str | None = None
    clip_bbox: BBox | None = None
    clip_ids: tuple[str, ...] = ()
    parent_group_id: str | None = None
    paint_group_id: str | None = None
    compositing: dict[str, object] = field(default_factory=dict)
    confidence: float | None = None
    evidence: list[object] = field(default_factory=list)
    decision_history: list[dict[str, object]] = field(default_factory=list)
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass
class RasterEl:
    """Région rastérisée en repli ou composition locale d'un objet visuel."""

    bbox: BBox
    media_ref: str
    purpose: str | None = None
    source_placements: tuple[str, ...] = ()
    source_xrefs: tuple[int, ...] = ()
    z_index: int | None = None
    paint_group_id: str | None = None
    paint_sequences: tuple[int, ...] = ()
    source_id: str | None = None
    source_ids: tuple[str, ...] = ()
    source_kind: str | None = None
    source_component_ids: tuple[str, ...] = ()
    fallback_reason: str | None = None
    clip_bbox: BBox | None = None
    clip_ids: tuple[str, ...] = ()
    opacity: float = 1.0
    parent_group_id: str | None = None
    compositing: dict[str, object] = field(default_factory=dict)
    confidence: float | None = None
    evidence: list[object] = field(default_factory=list)
    decision_history: list[dict[str, object]] = field(default_factory=list)
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass
class TableBorder:
    couleur: str = "000000"
    sz: int = 4
    visible: bool = True
    source_ids: tuple[str, ...] = ()
    confidence: float | None = None


@dataclass
class TableCell:
    bbox: BBox
    texte: str
    col_span: int = 1
    fond: str | None = None
    spans: list[Span] = field(default_factory=list)
    alignement: str = "center"
    bordures: dict[str, TableBorder] = field(default_factory=dict)
    direction_texte: str | None = None
    v_merge: str | None = None
    source_id: str | None = None
    source_ids: tuple[str, ...] = ()
    confidence: float | None = None
    grid_evidence: list[object] = field(default_factory=list)
    text_source_ids: tuple[str, ...] = ()


@dataclass
class TableRow:
    bbox: BBox
    cells: list[TableCell]
    source_id: str | None = None
    source_ids: tuple[str, ...] = ()
    confidence: float | None = None
    grid_evidence: list[object] = field(default_factory=list)


@dataclass
class TableEl:
    bbox: BBox
    rows: list[TableRow]
    col_widths_emu: list[int]
    police: FontRef
    size_pt: float
    couleur: str = "000000"
    bordure_couleur: str = "000000"
    bordure_sz: int = 4
    bordures_globales: bool = True
    source_id: str | None = None
    source_ids: tuple[str, ...] = ()
    source_kind: str | None = None
    confidence: float | None = None
    grid_evidence: list[object] = field(default_factory=list)
    semantic_table: bool | None = None
    z_index: int | None = None
    evidence: list[object] = field(default_factory=list)
    decision_history: list[dict[str, object]] = field(default_factory=list)
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass
class LinkZone:
    """Lien couvrant une zone sans texte. Les liens sur du texte vivent dans Span.lien."""

    bbox: BBox
    uri: str | None = None
    page_cible: int | None = None
    source_id: str | None = None
    source_ids: tuple[str, ...] = ()
    source_kind: str | None = None
    associated_text: str | None = None
    z_index: int | None = None
    confidence: float | None = None
    evidence: list[object] = field(default_factory=list)
    decision_history: list[dict[str, object]] = field(default_factory=list)
    attributes: dict[str, object] = field(default_factory=dict)


Element = Union[TextBox, FlowParagraph, ImageEl, ShapeEl, RasterEl, TableEl, LinkZone]


@dataclass
class Page:
    index: int
    largeur_emu: int
    hauteur_emu: int
    elements: list[Element] = field(default_factory=list)
    # Objets écartés par une étape historique, conservés pour la provenance et
    # l'audit. Ils ne sont pas rendus une seconde fois.
    discarded_elements: list[Element] = field(default_factory=list)
    # Contrat de repere : toutes les bboxes de cette page sont deja dans cet espace.
    coordinate_space: str = "page-visible-canonical"
    orientation: str = "portrait"
    format_name: str | None = None
    rotation_pdf: int = 0
    native_width_pt: float | None = None
    native_height_pt: float | None = None
    scene_id: str | None = None
    source_pdf_id: str | None = None
    options_snapshot: dict[str, object] = field(default_factory=dict)
    diagnostics: list[object] = field(default_factory=list)
    element_registry: object | None = None
    source_inventory: dict[str, object] = field(default_factory=dict)
    source_transformations: list[dict[str, object]] = field(default_factory=list)


@dataclass
class Document:
    pages: list[Page] = field(default_factory=list)
    media: dict[str, MediaItem] = field(default_factory=dict)
    polices: dict[str, FontAsset] = field(default_factory=dict)
    # Vue canonique optionnelle. Elle est construite après l'extraction pour
    # observer le pipeline historique sans imposer encore sa représentation au
    # renderer de compatibilité.
    scene: object | None = None
    scene_id: str | None = None
    source_pdf_id: str | None = None
    options_snapshot: dict[str, object] = field(default_factory=dict)
    diagnostics: list[object] = field(default_factory=list)
    element_registry: object | None = None


def iter_elements(document, *, include_discarded=True, include_observations=False):
    """Iterate page elements without hiding discarded source observations."""
    seen = set()
    for page in document.pages:
        elements = list(page.elements)
        if include_discarded:
            elements.extend(getattr(page, "discarded_elements", ()))
        if include_observations:
            elements.extend(getattr(page, "source_inventory", {}).values())
        for element in elements:
            if id(element) not in seen:
                seen.add(id(element))
                yield element


def element_text(element):
    text = getattr(element, "text", None)
    if text is not None:
        return str(text)
    text = getattr(element, "texte", None)
    if text is not None:
        return str(text)
    if hasattr(element, "rows"):
        return "\n".join("\t".join(element_text(cell) for cell in row.cells) for row in element.rows)
    if hasattr(element, "cells"):
        return "\t".join(element_text(cell) for cell in element.cells)
    if getattr(element, "lignes", None):
        return "\n".join(element_text(line) for line in element.lignes)
    return "".join(element_text(span) for span in getattr(element, "spans", ()))


def element_source_ids(element):
    result = list(getattr(element, "source_ids", ()) or ())
    result.extend(value for value in (getattr(element, "source_id", None),) if value)
    result.extend(getattr(element, "source_component_ids", ()) or ())
    for name in ("lignes", "spans", "rows", "cells"):
        for child in getattr(element, name, ()) or ():
            result.extend(element_source_ids(child))
    marker = getattr(element, "list_marker_source", None)
    if marker is not None:
        result.extend(element_source_ids(marker))
    return tuple(dict.fromkeys(str(value) for value in result if value))


def element_geometry(element):
    """Return geometry without reducing quads, paths or baselines to a bbox."""
    return {name: deepcopy(getattr(element, name, None)) for name in (
        "bbox", "quad", "polygon", "baseline_points", "baseline", "angle_deg",
        "orientation", "chemins", "path", "clip_bbox", "clip_ids", "geometry",
    ) if hasattr(element, name)}


def clone_element_with_metadata(element, **changes):
    """Clone declared and dynamically attached metadata, including frozen types."""
    result = deepcopy(element)
    for name, value in changes.items():
        if is_dataclass(result) and name not in {item.name for item in fields(result)} and not hasattr(result, name):
            raise TypeError(f"unknown-element-field:{name}")
        object.__setattr__(result, name, value)
    return result


def validate_document_ir(document):
    errors = []
    for page in document.pages:
        if page.largeur_emu <= 0 or page.hauteur_emu <= 0:
            errors.append(f"invalid-page-size:{page.index}")
        if page.coordinate_space != "page-visible-canonical":
            errors.append(f"invalid-coordinate-space:{page.index}")
        seen = set()
        for element in page.elements:
            source_id = getattr(element, "source_id", None)
            if not source_id:
                errors.append(f"missing-source-id:{page.index}")
            elif source_id in seen:
                errors.append(f"duplicate-source-id:{source_id}")
            seen.add(source_id)
            bbox = getattr(element, "bbox", None)
            if bbox is None or bbox.largeur < 0 or bbox.hauteur < 0:
                errors.append(f"invalid-bbox:{source_id}")
            if isinstance(element, RasterEl) and element.purpose not in {"shading", "source-image"}:
                if not (element.fallback_reason or element.purpose):
                    errors.append(f"missing-fallback-reason:{source_id}")
                if not element.source_component_ids and not element.source_placements:
                    errors.append(f"missing-raster-sources:{source_id}")
    return errors
