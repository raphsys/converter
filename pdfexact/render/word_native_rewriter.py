"""Reconstruction Word-native guidée par les régions et les couches de la page.

Le renderer historique mélangeait le flux, les ancres et les tables de placement. Ce
module garde une distinction stricte : le texte courant devient un vrai ``w:p`` dans
``w:body`` ; un texte horizontal qui doit conserver une géométrie de page reste aussi
un vrai ``w:p`` avec ``w:framePr`` (les lignes deviennent des retours internes), et
seuls les textes réellement orientés ou courbés utilisent encore une forme Word
spécialisée ; les fonds et les objets visuels sont placés dans une couche arrière
indépendante.
"""

from dataclasses import dataclass, field, replace
import re
from statistics import median
from types import SimpleNamespace

from pdfexact.geometry import BBox, emu_vers_pt, pt_vers_emu, pt_vers_twips, quantifier_bbox
from pdfexact.analysis.geometry import bbox_area, intersection_area, overlap_ratio, union_many
from pdfexact.ir import (
    Document,
    FlowParagraph,
    ImageEl,
    Line,
    LinkZone,
    RasterEl,
    ShapeEl,
    Span,
    TableEl,
    TextBox,
)
from pdfexact.render.drawing import (
    _run_xml,
    forme_xml,
    image_xml,
    table_body_xml,
    zone_lien_xml,
)
from pdfexact.analysis.options import AnalysisOptions
from pdfexact.analysis.text_geometry import (
    block_alignment,
    geometry_kind,
    is_special_orientation,
)
from pdfexact.analysis.semantic import (
    commence_par_minuscule,
    detecter_colonnes_textuelles,
    detecter_marqueur_liste,
    est_continuation_de_ligne,
    preserver_frontieres_ambigues,
    produire_flow_paragraphs,
    regrouper_frames,
    regrouper_listes,
    regrouper_paragraphes,
)
from pdfexact.layout.text_comprehension import comprendre_reflow_paragraphe
from pdfexact.render.render_plan import (
    RenderPlan,
    build_document_render_plan,
    build_render_plan,
    build_page_render_plan,
)
from pdfexact.render.reflow import (
    fusionner_flow_paragraphes,
    prepare_page_elements,
    prepare_document_elements,
    regrouper_continuations_par_colonne,
    regrouper_continuations_par_frame,
)
from pdfexact.render.section_layout import section_xml
from pdfexact.render.compatibility import record_reader_risk


_HEADER = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:document '
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
    'xmlns:v="urn:schemas-microsoft-com:vml" '
    'xmlns:o="urn:schemas-microsoft-com:office:office" '
    'xmlns:w10="urn:schemas-microsoft-com:office:word" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'mc:Ignorable="wps w14"><w:body>'
)
_FOOTER = "</w:body></w:document>"

_GEOMETRIC_ROLES = {
    "caption",
    "credit",
    "label",
    "diagram_text",
    "annotation",
    "watermark",
    "figure_text",
}
_VISUAL_TYPES = (ImageEl, RasterEl, ShapeEl)
_TEXT_TYPES = (FlowParagraph, TextBox)


@dataclass(frozen=True)
class RewritePolicy:
    """Paramètres conservateurs de la reconstruction."""

    allow_anchored_frames: bool = True
    preserve_page_breaks: bool = True
    tolerance_emu: int = pt_vers_emu(2)
    visual_overlap_threshold: float = 0.12
    # Les labels de cartes et de schémas sont souvent extraits entre 14 et 15 pt
    # alors qu'ils sont déjà peints dans le bitmap source. Les titres éditables
    # restent protégés par leur taille ou leur rôle sémantique.
    embedded_text_max_size_pt: float = 16.0
    strict: bool = False
    reader_profile: str = "word"


@dataclass(frozen=True)
class ElementDecision:
    source_id: str
    mode: str
    reason: str
    page_index: int
    bbox: BBox
    orientation: str = "horizontal"
    region_id: str | None = None
    z_index: int = 0
    confidence: float = 1.0


@dataclass
class RewriteDiagnostics:
    pages: int = 0
    flow_paragraphs: int = 0
    positioned_flow_paragraphs: int = 0
    direct_body_paragraphs: int = 0
    inline_frames: int = 0
    anchored_frames: int = 0
    real_tables: int = 0
    anchored_images: int = 0
    anchored_shapes: int = 0
    anchored_links: int = 0
    positioned_tables: int = 0
    embedded_text_skipped: int = 0
    skipped_duplicates: int = 0
    missing_elements: list[str] = field(default_factory=list)
    out_of_page_elements: list[str] = field(default_factory=list)
    plan_errors: list[str] = field(default_factory=list)
    reader_risks: list[dict] = field(default_factory=list)
    decisions: list[ElementDecision] = field(default_factory=list)

    @property
    def conforme(self) -> bool:
        return not self.missing_elements and not self.out_of_page_elements and not self.plan_errors


@dataclass(frozen=True)
class RewriteResult:
    xml: str
    diagnostics: RewriteDiagnostics
    numbering_xml: str | None = None


class _NumberingBuilder:
    """Construit les listes OOXML necessaires aux paragraphes reconstruits."""

    _MARKERS = {
        "bullet": ("bullet", "•", "Symbol"),
        "dash": ("bullet", "–", "Calibri"),
        "decimal": ("decimal", "%1.", "Calibri"),
        "alpha": ("lowerLetter", "%1)", "Calibri"),
        "roman": ("lowerRoman", "%1)", "Calibri"),
    }

    def __init__(self, relations):
        self._relations = relations
        self._groups: dict[tuple[str, str], int] = {}
        self._abstracts: dict[str, int] = {}
        self._next_abstract = 1
        self._next_num = 1

    def num_id(self, element) -> int | None:
        kind = getattr(element, "list_marker", None)
        if not kind:
            return None
        group = str(getattr(element, "list_group_id", None) or "default")
        key = (str(kind), group)
        if key in self._groups:
            return self._groups[key]
        abstract_id = self._abstracts.get(str(kind))
        if abstract_id is None:
            abstract_id = self._next_abstract
            self._next_abstract += 1
            self._abstracts[str(kind)] = abstract_id
        num_id = self._next_num
        self._next_num += 1
        self._groups[key] = num_id
        return num_id

    def xml(self) -> str | None:
        if not self._groups:
            return None
        abstract_xml = []
        for kind, abstract_id in sorted(self._abstracts.items(), key=lambda item: item[1]):
            num_fmt, marker, font = self._MARKERS.get(kind, self._MARKERS["bullet"])
            levels = []
            for level in range(9):
                levels.append(
                    f'<w:lvl w:ilvl="{level}"><w:start w:val="1"/>'
                    f'<w:numFmt w:val="{num_fmt}"/><w:lvlText w:val="{marker}"/>'
                    '<w:lvlJc w:val="left"/><w:rPr>'
                    f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}"/>'
                    '</w:rPr></w:lvl>'
                )
            abstract_xml.append(
                f'<w:abstractNum w:abstractNumId="{abstract_id}">'
                '<w:multiLevelType w:val="hybridMultilevel"/>'
                + "".join(levels)
                + '</w:abstractNum>'
            )
        nums = [
            f'<w:num w:numId="{num_id}"><w:abstractNumId w:val="{self._abstracts[kind]}"/></w:num>'
            for (kind, _group), num_id in sorted(self._groups.items(), key=lambda item: item[1])
        ]
        self._relations.ajouter("numbering.xml", "numbering")
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            + "".join(abstract_xml)
            + "".join(nums)
            + "</w:numbering>"
        )


def _element_id(element, page_index: int, index: int) -> str:
    source_id = getattr(element, "source_id", None)
    return str(source_id or f"p{page_index + 1}-e{index + 1}")


def _area(bbox: BBox) -> int:
    return bbox_area(bbox)


def _intersection(a: BBox, b: BBox) -> int:
    return intersection_area(a, b)


def _overlap_ratio(inner: BBox, outer: BBox) -> float:
    return overlap_ratio(inner, outer)


def _inside_page(bbox: BBox, page, tolerance_emu: int = 0) -> bool:
    return (
        bbox.x0 >= -tolerance_emu
        and bbox.y0 >= -tolerance_emu
        and bbox.x1 <= page.largeur_emu + tolerance_emu
        and bbox.y1 <= page.hauteur_emu + tolerance_emu
    )


def _orientation(element) -> str:
    value = getattr(element, "orientation", "horizontal") or "horizontal"
    if value == "horizontal":
        for ligne in getattr(element, "lignes", None) or []:
            candidate = getattr(ligne, "orientation", "horizontal") or "horizontal"
            if candidate != "horizontal":
                value = candidate
                break
    return str(value).lower()


def _role(element) -> str | None:
    role = getattr(element, "semantic_role", None) or getattr(element, "layout_frame_role", None)
    if role:
        return str(role).lower()
    for ligne in getattr(element, "lignes", None) or []:
        role = getattr(ligne, "semantic_role", None)
        if role:
            return str(role).lower()
    return None


def _layout_role(element) -> str | None:
    """Retourne le rôle du conteneur avant le rôle fin d'un fragment."""
    role = getattr(element, "layout_frame_role", None)
    if role:
        return str(role).lower()
    for ligne in getattr(element, "lignes", None) or []:
        role = getattr(ligne, "layout_frame_role", None)
        if role:
            return str(role).lower()
    return _role(element)


def _lines(element) -> list[Line]:
    if isinstance(element, (TextBox, FlowParagraph)):
        lignes = list(getattr(element, "lignes", None) or [])
        if lignes:
            return lignes
    if isinstance(element, FlowParagraph) and element.texte:
        span = Span(element.texte, element.police, element.size_pt, element.couleur)
        return [
            Line(
                bbox=element.bbox,
                spans=[span],
                hauteur_ligne_emu=max(element.interligne_emu, element.bbox.hauteur),
                largeur_cible_emu=max(element.bbox.largeur, 1),
                alignement=element.alignement,
                angle_deg=element.angle_deg,
                orientation=element.orientation,
                semantic_role=element.semantic_role,
                curved=element.curved,
            )
        ]
    return []


def _is_plain_flow(element) -> bool:
    return (
        isinstance(element, _TEXT_TYPES)
        and _orientation(element) == "horizontal"
        and not getattr(element, "curved", False)
        and (_role(element) or "") not in _GEOMETRIC_ROLES
    )


def _visuals(page) -> list[tuple[int, object]]:
    return [(index, element) for index, element in enumerate(page.elements) if isinstance(element, _VISUAL_TYPES)]


def _text_elements(page) -> list[tuple[int, object]]:
    return [(index, element) for index, element in enumerate(page.elements) if isinstance(element, _TEXT_TYPES)]


def _line_text(element) -> str:
    return "".join(span.texte for ligne in _lines(element) for span in ligne.spans).strip()


def _first_span(element) -> Span | None:
    for ligne in _lines(element):
        for span in ligne.spans:
            if span.texte.strip():
                return span
    return None


def _same_text_style(left, right) -> bool:
    span_left = _first_span(left)
    span_right = _first_span(right)
    if span_left is None or span_right is None:
        return False
    return (
        span_left.police.famille == span_right.police.famille
        and span_left.police.gras == span_right.police.gras
        and span_left.police.italique == span_right.police.italique
        and abs(span_left.size_pt - span_right.size_pt) <= 1.2
        and span_left.couleur == span_right.couleur
    )


def _starts_list_item(text: str) -> bool:
    return bool(detecter_marqueur_liste(SimpleNamespace(texte=text)))


def _starts_lowercase_continuation(text: str) -> bool:
    """Reconnaît une suite de ligne sans confondre une nouvelle rubrique."""
    return commence_par_minuscule(text)


def _is_text_marker(element) -> bool:
    """Identifie une puce ou un symbole isolé à conserver séparément."""
    return _marker_kind(element) is not None


def _marker_kind(element) -> str | None:
    """Normalise les glyphes de puce PDF en une famille de liste Word."""
    return detecter_marqueur_liste(element)


def _normaliser_listes(elements: list[object]) -> list[object]:
    return regrouper_listes(elements, AnalysisOptions())


def _bbox_union(items) -> BBox:
    result = union_many(item.bbox for item in items)
    if result is None:
        raise ValueError("_bbox_union exige au moins un élément")
    return result


def _visual_text_region(element, page) -> BBox | None:
    """Retourne le support visuel qui contient un bloc de texte.

    Les PDF de brochures n'exposent pas toujours une ``layout_frame_bbox`` pour
    les paragraphes issus du texte natif. Le rectangle de fond ou l'image sous le
    texte reste alors la meilleure indication de la largeur de recomposition.
    """
    candidats = []
    for _index, visual in _visuals(page):
        if getattr(visual, "purpose", None) == "audit-background":
            continue
        # Le bbox OCR peut dépasser de quelques pixels le rectangle peint
        # (antialiasing, glyphes inclinés, crédits verticaux). On utilise donc
        # une couverture minimale de la zone texte plutôt qu'un containment strict.
        if _overlap_ratio(element.bbox, visual.bbox) < 0.55:
            continue
        if visual.bbox.largeur < element.bbox.largeur + pt_vers_emu(6):
            continue
        if visual.bbox.hauteur < min(element.bbox.hauteur + pt_vers_emu(6), page.hauteur_emu):
            continue
        candidats.append((_area(visual.bbox), visual.bbox))
    if not candidats:
        return None
    return min(candidats, key=lambda item: item[0])[1]


def _roles_compatibles_pour_region(gauche: str | None, droite: str | None) -> bool:
    """Dit si deux lignes peuvent appartenir au même conteneur de lecture."""
    if gauche and droite and gauche != droite:
        # Un titre et son contenu partagent souvent le même panneau. Les légendes,
        # crédits et annotations, eux, doivent rester exclus de la colonne voisine.
        incompatibles = {
            "caption",
            "credit",
            "label",
            "annotation",
            "diagram_text",
            "figure_text",
        }
        if gauche in incompatibles or droite in incompatibles:
            return False
    return True


def _inferred_text_region(element, page) -> BBox | None:
    """Infère la largeur éditoriale d'un bloc à partir de ses lignes voisines.

    Les extracteurs PDF donnent parfois une bbox de glyphes à chaque ligne, alors
    que la vraie largeur utile est celle du panneau ou de la colonne. Cette
    inférence reste locale : même origine horizontale, rôle compatible et proximité
    verticale. Elle évite d'étendre un bloc jusque dans une colonne étrangère.
    """
    if not isinstance(element, _TEXT_TYPES):
        return None
    role = _role(element)
    frame_id = getattr(element, "layout_frame_id", None)
    tolerance_x = max(pt_vers_emu(14), int(page.largeur_emu * 0.025))
    tolerance_y = max(pt_vers_emu(260), int(page.hauteur_emu * 0.16))
    candidats = []
    for _index, autre in _text_elements(page):
        if not _is_plain_flow(autre):
            continue
        if not _roles_compatibles_pour_region(role, _role(autre)):
            continue
        meme_frame = bool(frame_id and getattr(autre, "layout_frame_id", None) == frame_id)
        meme_colonne = abs(autre.bbox.x0 - element.bbox.x0) <= tolerance_x
        proche = abs(autre.bbox.y0 - element.bbox.y0) <= tolerance_y
        if not meme_frame and not (meme_colonne and proche):
            continue
        candidats.append(autre)
    if len(candidats) < 2:
        return None
    x0 = min(element.bbox.x0, *(item.bbox.x0 for item in candidats))
    x1 = max(element.bbox.x1, *(item.bbox.x1 for item in candidats))
    # La marge est volontairement faible : elle compense la métrique de la police
    # de remplacement sans empiéter sur une image ou une colonne adjacente.
    x0 = max(0, x0 - pt_vers_emu(2))
    x1 = min(page.largeur_emu, x1 + pt_vers_emu(8))
    if x1 - x0 <= element.bbox.largeur + pt_vers_emu(4):
        return None
    return BBox(x0, element.bbox.y0, x1, element.bbox.y1)


def _is_compact_positioned_text(element) -> bool:
    """Identifie les blocs dont la bbox est une limite de composition stricte.

    Une légende, un crédit ou un label est généralement placé dans la bande
    exacte fournie par le PDF. Lui attribuer la largeur d'une colonne voisine
    permet à Word de replier le texte dans un autre panneau. Les paragraphes
    éditoriaux ordinaires conservent, eux, l'inférence de colonne existante.
    """
    return (_role(element) or "") in {
        "caption",
        "credit",
        "label",
        "annotation",
        "diagram_text",
        "figure_text",
    }


def _line_step_emu(element) -> int:
    """Calcule un interligne source robuste à partir des positions de lignes."""
    lignes = sorted(_lines(element), key=lambda item: (item.bbox.y0, item.bbox.x0))
    if not lignes:
        return max(
            getattr(element, "interligne_emu", 0),
            pt_vers_emu(max(getattr(element, "size_pt", 10.0) * 1.12, 1.0)),
        )
    deltas = [
        courant.bbox.y0 - precedent.bbox.y0
        for precedent, courant in zip(lignes, lignes[1:])
        if courant.bbox.y0 > precedent.bbox.y0
    ]
    if deltas:
        # La médiane résiste aux lignes atypiques et aux petits écarts produits
        # par l'antialiasing ou par une ligne de légende plus haute que les autres.
        return max(pt_vers_emu(1), int(median(deltas)))
    hauteur = [ligne.bbox.hauteur for ligne in lignes if ligne.bbox.hauteur > 0]
    return max(
        pt_vers_emu(1),
        int(median(hauteur)) if hauteur else 0,
        getattr(element, "interligne_emu", 0),
        pt_vers_emu(max(getattr(element, "size_pt", 10.0) * 1.12, 1.0)),
    )


def _spans_ajustes_a_la_ligne(ligne: Line) -> list[Span]:
    """Compense une métrique de police de remplacement sans changer le corps."""
    spans = list(ligne.spans or [])
    texte = "".join(str(span.texte or "") for span in spans)
    nombre = len(texte.replace("\n", "").replace("\r", ""))
    if nombre < 2 or ligne.bbox.largeur <= 0:
        return spans
    taille = max((float(span.size_pt) for span in spans if span.texte), default=0.0)
    if taille <= 0:
        return spans
    # Estimation volontairement conservatrice : elle sert uniquement à détecter
    # un dépassement probable avant que Word ne crée une ligne supplémentaire.
    largeur_estimee_pt = sum(
        len(str(span.texte or "").replace("\n", "").replace("\r", ""))
        * float(span.size_pt)
        * (0.57 if span.police.gras else 0.53)
        for span in spans
    )
    largeur_source_pt = emu_vers_pt(ligne.bbox.largeur)
    depassement_pt = largeur_estimee_pt - largeur_source_pt
    if depassement_pt <= 0.15:
        # Les métriques C059/CMR de LibreOffice sont parfois sous-estimées par
        # l'approximation précédente, alors que la ligne occupe déjà presque
        # toute la largeur source. Une correction minimale évite qu'un dernier
        # mot bascule seul sur la ligne suivante.
        if nombre < 48:
            return spans
        correction = -2 if nombre >= 80 else -1
        return [replace(span, espacement_twips=int(span.espacement_twips or 0) + correction) for span in spans]
    # OOXML exprime l'espacement en 1/20 pt. On borne la correction pour ne pas
    # écraser les mots sur les PDF dont la bbox a été légèrement sous-détectée.
    correction = max(-8, min(0, round(-depassement_pt * 20 / max(nombre - 1, 1))))
    if correction == 0:
        return spans
    return [replace(span, espacement_twips=int(span.espacement_twips or 0) + correction) for span in spans]


def _positioned_text_region(element, page) -> BBox:
    """Retourne la contrainte de composition contractuelle du PDF.

    Les anciennes inférences de colonne sont utiles pour comprendre la page, mais
    elles ne doivent jamais changer la geometrie deja extraite au moment du rendu.
    """
    bbox = quantifier_bbox(element.bbox)
    return bbox


def _can_join_flow_lines(previous, current) -> bool:
    return isinstance(previous, _TEXT_TYPES) and isinstance(current, _TEXT_TYPES) and est_continuation_de_ligne(
        previous,
        current,
        AnalysisOptions(),
    )


def _regrouper_flow_paragraphes(elements: list[object]) -> list[object]:
    return prepare_page_elements(elements, AnalysisOptions())


def _fusionner_flow_paragraphes(elements: list[object]) -> object:
    return fusionner_flow_paragraphes(elements)


def _appliquer_groupes_semantiques(elements: list[object], groups: list[list[object]]) -> list[object]:
    """Materialise les groupes sémantiques sans reclassifier les objets."""
    positions = {id(element): index for index, element in enumerate(elements)}
    replacements: dict[int, object] = {}
    suppressed: set[int] = set()
    for group in groups:
        text_items = [item for item in group if isinstance(item, _TEXT_TYPES) and id(item) in positions]
        if len(text_items) < 2:
            continue
        indices = sorted(positions[id(item)] for item in text_items)
        first = indices[0]
        replacements[first] = _fusionner_flow_paragraphes(text_items)
        suppressed.update(index for index in indices if index != first)
    return [
        replacements.get(index, element)
        for index, element in enumerate(elements)
        if index not in suppressed
    ]


def _regrouper_continuations_par_frame(elements: list[object]) -> list[object]:
    """Rattache les fragments d'un même frame malgré l'ordre de peinture PDF.

    Un PDF peut intercaler une image, une forme ou une autre colonne entre deux
    lignes appartenant au même bloc éditorial. Le regroupement séquentiel ne peut
    alors pas les voir comme voisines. On ne réordonne pas les objets : on fusionne
    seulement les textes horizontaux du même frame, triés par position verticale,
    lorsque la suite est une continuation lexicale proche.
    """
    return regrouper_continuations_par_frame(elements, AnalysisOptions())


def _regrouper_continuations_par_colonne(elements: list[object]) -> list[object]:
    """Récupère une continuité quand l'identifiant de frame a été réécrit.

    La colonne est un filet de sécurité pour les extracteurs qui créent plusieurs
    ids pour une même zone. Il ne fusionne jamais une nouvelle puce ou un nouveau
    paragraphe commençant par une majuscule.
    """
    return regrouper_continuations_par_colonne(elements, AnalysisOptions())


def _visual_region_for_text(element, visuals, threshold: float) -> tuple[int, object] | None:
    candidates = []
    for index, visual in visuals:
        score = _overlap_ratio(element.bbox, visual.bbox)
        if score >= threshold:
            candidates.append((score, _area(visual.bbox), index, visual))
    if not candidates:
        return None
    _, _, index, visual = min(candidates, key=lambda item: (-item[0], item[1], item[2]))
    return index, visual


def _has_multiple_columns(page, texts: list[tuple[int, object]]) -> bool:
    positions = sorted({element.bbox.x0 for _, element in texts if _is_plain_flow(element)})
    if len(positions) < 4:
        return False
    seuil = page.largeur_emu * 0.14
    groupes = 1
    for precedent, courant in zip(positions, positions[1:]):
        if courant - precedent > seuil:
            groupes += 1
    return groupes > 1


def _looks_embedded_in_visual(element, visual, policy: RewritePolicy) -> bool:
    if not isinstance(visual, (ImageEl, RasterEl)):
        return False
    if getattr(visual, "purpose", None) == "audit-background":
        # Le raster de récupération a été explicitement nettoyé de ses glyphes.
        # Le texte IR doit donc rester éditable et être rendu au-dessus.
        return False
    if getattr(visual, "purpose", None) == "audit-baked-visual":
        # La récupération complète reprend volontairement les glyphes source.
        # Une seconde écriture Word créerait un doublon visuel.
        return _overlap_ratio(element.bbox, visual.bbox) >= 0.92
    if _overlap_ratio(element.bbox, visual.bbox) < 0.92:
        return False
    if getattr(element, "curved", False) or _orientation(element) != "horizontal":
        return False
    size = max(
        (span.size_pt for ligne in _lines(element) for span in ligne.spans if span.texte.strip()),
        default=0.0,
    )
    role = (_role(element) or "").lower()
    if role in {"caption", "credit", "heading", "title", "subtitle"}:
        return False
    return size <= policy.embedded_text_max_size_pt


def _decision(element, page, page_index: int, index: int, policy: RewritePolicy, multi_columns: bool) -> ElementDecision:
    identifiant = _element_id(element, page_index, index)
    bbox = quantifier_bbox(element.bbox)
    orientation = _orientation(element)
    visuals = _visuals(page)
    region = _visual_region_for_text(element, visuals, policy.visual_overlap_threshold) if isinstance(element, _TEXT_TYPES) else None
    region_id = f"p{page_index + 1}-r{region[0] + 1}" if region else None
    if isinstance(element, _TEXT_TYPES):
        if region and _looks_embedded_in_visual(element, region[1], policy):
            return ElementDecision(identifiant, "skip_embedded", "text_baked_into_visual", page_index, bbox, orientation, region_id, index)
        if _is_plain_flow(element) and region is None and not multi_columns:
            return ElementDecision(identifiant, "flow", "single_region_horizontal_flow", page_index, bbox, orientation, None, index)
        if not policy.allow_anchored_frames:
            return ElementDecision(identifiant, "skip", "anchored_frame_forbidden", page_index, bbox, orientation, region_id, index)
        reason = "text_over_visual_region" if region else "geometric_or_multi_region_text"
        return ElementDecision(identifiant, "anchored_frame", reason, page_index, bbox, orientation, region_id, index)
    if isinstance(element, TableEl):
        return ElementDecision(identifiant, "real_table", "detected_table", page_index, bbox, orientation, None, index)
    if isinstance(element, (ImageEl, RasterEl)):
        return ElementDecision(identifiant, "anchored_image", "visual_region", page_index, bbox, orientation, None, index)
    if isinstance(element, ShapeEl):
        return ElementDecision(identifiant, "anchored_shape", "visual_region", page_index, bbox, orientation, None, index)
    if isinstance(element, LinkZone):
        return ElementDecision(identifiant, "anchored_link", "positioned_link", page_index, bbox, orientation, None, index)
    return ElementDecision(identifiant, "skip", "unsupported_element", page_index, bbox, orientation, None, index)


def _flow_runs(
    element,
    relations,
    *,
    ajuster_lignes: bool = False,
    preserve_line_boundaries: bool = False,
) -> str:
    lignes = sorted(_lines(element), key=lambda item: (item.bbox.y0, item.bbox.x0))
    if not lignes:
        spans = getattr(element, "spans", None) or []
        return "".join(_run_xml(span, relations, autoriser_espacement_negatif=True) for span in spans)
    reflow = comprendre_reflow_paragraphe(
        ["".join(span.texte for span in ligne.spans) for ligne in lignes],
        frame_role=getattr(element, "layout_frame_role", None),
        frame_strategy=getattr(element, "layout_frame_strategy", None),
    )
    morceaux = []
    for index, ligne in enumerate(lignes):
        if index:
            join_action = (
                reflow.line_joins[index - 1]
                if index - 1 < len(reflow.line_joins)
                else "space"
            )
            if preserve_line_boundaries or join_action == "preserve_break":
                morceaux.append("<w:r><w:br/></w:r>")
            elif join_action == "paragraph_break":
                morceaux.append("<w:r><w:br/><w:br/></w:r>")
            else:
                previous = "".join(span.texte for span in lignes[index - 1].spans)
                current = "".join(span.texte for span in ligne.spans)
                if join_action == "hyphen_join" and morceaux:
                    morceaux[-1] = re.sub(
                        r"(?:-|¬)(</w:t></w:r>)$", r"\1", morceaux[-1]
                    )
                if (
                    join_action not in {"hyphen_join", "no_space"}
                    and previous
                    and current
                    and not previous[-1].isspace()
                    and not current[0].isspace()
                    and not previous.endswith(("-", "/"))
                    and current[0] not in ".,;:!?)]}%"
                ):
                    morceaux.append('<w:r><w:t xml:space="preserve"> </w:t></w:r>')
        if ligne.bbox.x0 - element.bbox.x0 > pt_vers_emu(3) and not getattr(element, "list_marker", None):
            morceaux.append("<w:r><w:tab/></w:r>")
        spans = _spans_ajustes_a_la_ligne(ligne) if ajuster_lignes else ligne.spans
        morceaux.extend(_run_xml(span, relations, autoriser_espacement_negatif=True) for span in spans)
    return "".join(morceaux)


def _line_slice_paragraphs(element, relations, numbering=None) -> str:
    """Rend une region horizontale irreguliere par tranches natives.

    Word ne sait pas exprimer un contour polygonal dans un seul ``w:p``. Chaque
    tranche conserve donc sa largeur et son retrait source, sans inserer de
    blancs artificiels entre les mots.
    """
    bbox = quantifier_bbox(element.bbox)
    paragraphs = []
    for line in sorted(_lines(element), key=lambda item: (item.bbox.y0, item.bbox.x0)):
        runs = "".join(
            _run_xml(span, relations, autoriser_espacement_negatif=False)
            for span in line.spans
            if span.texte
        )
        if not runs:
            continue
        left = max(pt_vers_twips(emu_vers_pt(line.bbox.x0 - bbox.x0)), 0)
        right = max(pt_vers_twips(emu_vers_pt(bbox.x1 - line.bbox.x1)), 0)
        spacing = max(pt_vers_twips(emu_vers_pt(line.hauteur_ligne_emu)), 1)
        paragraphs.append(
            '<w:p><w:pPr>'
            f'<w:ind w:left="{left}" w:right="{right}" w:firstLine="0"/>'
            f'<w:spacing w:before="0" w:after="0" w:line="{spacing}" w:lineRule="exact"/>'
            f'<w:jc w:val="{block_alignment(element)}"/><w:keepLines/></w:pPr>{runs}</w:p>'
        )
    return "".join(paragraphs)


def _list_properties_xml(element, numbering: _NumberingBuilder | None) -> str:
    if numbering is None or not getattr(element, "list_marker", None):
        return ""
    num_id = numbering.num_id(element)
    if num_id is None:
        return ""
    level = max(0, min(8, int(getattr(element, "list_level", 0) or 0)))
    marker_bbox = getattr(element, "list_marker_bbox", None)
    lines = _lines(element)
    body_x = min((line.bbox.x0 for line in lines), default=element.bbox.x0)
    left_emu = max(pt_vers_emu(6), body_x - marker_bbox.x0) if marker_bbox else 0
    left = pt_vers_twips(emu_vers_pt(left_emu)) if left_emu else 0
    hanging = left if left else 360
    indentation = f'<w:ind w:left="{left}" w:hanging="{hanging}"/>' if left else ""
    return (
        f'<w:numPr><w:ilvl w:val="{level}"/><w:numId w:val="{num_id}"/></w:numPr>'
        + indentation
    )


def _line_height(element) -> int:
    if _is_compact_positioned_text(element):
        return _line_step_emu(element)
    values = [ligne.hauteur_ligne_emu for ligne in _lines(element) if ligne.hauteur_ligne_emu]
    return max([getattr(element, "interligne_emu", 0), *values, pt_vers_emu(max(getattr(element, "size_pt", 10.0) * 1.12, 1.0))])


def _flow_paragraph_xml(element, page, before_emu: int, relations, numbering=None) -> str:
    largeur = max(page.largeur_emu - element.bbox.x1, 0)
    gauche = max(pt_vers_twips(emu_vers_pt(max(element.bbox.x0, 0))), 0)
    droite = max(pt_vers_twips(emu_vers_pt(largeur)), 0)
    avant = max(pt_vers_twips(emu_vers_pt(before_emu)), 0)
    interligne = max(pt_vers_twips(emu_vers_pt(_line_height(element))), 1)
    contenu = _flow_runs(
        element,
        relations,
        ajuster_lignes=_is_compact_positioned_text(element),
        preserve_line_boundaries=_is_compact_positioned_text(element),
    )
    if not contenu:
        return ""
    alignement = block_alignment(element)
    liste = _list_properties_xml(element, numbering)
    return (
        "<w:p><w:pPr>"
        f"{liste}"
        f'<w:spacing w:before="{avant}" w:after="0" w:line="{interligne}" w:lineRule="exact"/>'
        f'<w:ind w:left="{gauche}" w:right="{droite}" w:firstLine="0"/>'
        f'<w:jc w:val="{alignement}"/><w:keepLines/>'
        f"</w:pPr>{contenu}</w:p>"
    )


def _positioned_flow_paragraph_xml(element, page, relations, numbering=None) -> str:
    """Construit un paragraphe Word réel positionné par la page.

    ``w:framePr`` ne crée pas une zone de texte DrawingML : le contenu reste dans
    ``w:p``/``w:r`` et reste donc sélectionnable, modifiable et recomposable comme
    du texte Word. Il sert uniquement à conserver la position d'un bloc qui ne peut
    pas participer au flux linéaire global sans entrer en collision avec une autre
    colonne ou une image.
    """
    bbox = quantifier_bbox(element.bbox)
    marker_bbox = getattr(element, "list_marker_bbox", None)
    if marker_bbox is not None:
        marker_bbox = quantifier_bbox(marker_bbox)
        bbox = BBox(
            min(bbox.x0, marker_bbox.x0),
            min(bbox.y0, marker_bbox.y0),
            max(bbox.x1, marker_bbox.x1),
            max(bbox.y1, marker_bbox.y1),
        )
    region = _positioned_text_region(element, page)
    x = region.x0
    largeur_emu = region.largeur
    contenu = _flow_runs(
        element,
        relations,
        ajuster_lignes=_is_compact_positioned_text(element),
        preserve_line_boundaries=_is_compact_positioned_text(element),
    )
    if not contenu:
        return ""
    largeur = max(pt_vers_twips(emu_vers_pt(max(largeur_emu, 1))), 1)
    lignes = _lines(element)
    if _is_compact_positioned_text(element) and lignes:
        # La hauteur PDF est une contrainte de composition. On ne la remplace
        # pas par ``interligne * nombre_de_lignes`` : cette approximation ajoute
        # souvent une ligne fictive et fait chevaucher le bloc suivant.
        hauteur_emu = max(bbox.hauteur, _line_step_emu(element) * max(len(lignes) - 1, 0))
        h_rule = "exact"
    else:
        hauteur_lignes = _line_height(element) * max(len(lignes), 1) + pt_vers_emu(2)
        hauteur_emu = max(bbox.hauteur, hauteur_lignes, 1)
        h_rule = "atLeast"
    hauteur = max(pt_vers_twips(emu_vers_pt(hauteur_emu)), 1)
    x = pt_vers_twips(emu_vers_pt(max(x, 0)))
    y = pt_vers_twips(emu_vers_pt(max(bbox.y0, 0)))
    interligne = max(pt_vers_twips(emu_vers_pt(_line_height(element))), 1)
    alignement = block_alignment(element)
    liste = _list_properties_xml(element, numbering)
    return (
        "<w:p><w:pPr>"
        f'<w:framePr w:w="{largeur}" w:h="{hauteur}" w:x="{x}" w:y="{y}" '
        'w:hAnchor="page" w:vAnchor="page" w:wrap="none" w:anchorLock="0" '
        f'w:hRule="{h_rule}"/>'
        # Le PDF conserve parfois une ligne dont la largeur dépasse la métrique
        # de la police disponible localement. fitText reproduit le comportement
        # de la forme source sans transformer le paragraphe en image ou textbox.
        f'<w:fitText w:val="{largeur}"/>{liste}'
        f'<w:spacing w:before="0" w:after="0" w:line="{interligne}" w:lineRule="exact"/>'
        f'<w:jc w:val="{alignement}"/><w:keepLines/>'
        f"</w:pPr>{contenu}</w:p>"
    )


def _frame_body_properties(element) -> tuple[int, str]:
    """Retourne les proprietes du corps de texte du cadre.

    Le sens vertical est porte par ``bodyPr/@vert``, le mecanisme OOXML prevu
    pour les WordprocessingShape. La geometrie interne est transposee dans
    ``_text_frame_graphic`` afin que le moteur compose la ligne sur la longueur
    du cadre avant de l'afficher verticalement.
    """
    angle = float(getattr(element, "angle_deg", 0.0) or 0.0)
    if not angle:
        angles = [
            float(getattr(ligne, "angle_deg", 0.0) or 0.0)
            for ligne in _lines(element)
            if abs(float(getattr(ligne, "angle_deg", 0.0) or 0.0)) > 0.1
        ]
        if angles:
            angle = angles[0]
    orientation = _orientation(element)
    if orientation in {"vertical", "vertical-lr", "vertical-rl", "vertical-rtl"}:
        # +90 degres dans le repere PDF correspond a vert270 dans OOXML ; le
        # signe inverse utilise vert. On ne combine pas ce mode avec a:xfrm rot:
        # LibreOffice ignore la rotation de la forme mais respecte le flux du
        # corps de texte.
        return 0, "vert270" if angle >= 0 else "vert"
    return round(-angle * 60000) if abs(angle) > 7 else 0, "horz"


def _frame_shape_rotation(element) -> int:
    """Retourne la rotation de forme portable pour le chemin WPS.

    Pour un ``wps:wsp``, la rotation de la forme tourne aussi son cadre externe
    et decale la bbox dans LibreOffice. Le chemin WPS porte donc uniquement
    l'orientation dans ``bodyPr/@vert``; le fallback VML utilise sa propre
    rotation autour du centre.
    """
    return 0


def _text_warp(element) -> str:
    """Encode une courbure sémantique dans le corps de texte DrawingML.

    Word ne possède pas de paragraphe courbe dans le flux principal. Pour ce cas
    géométrique, le texte reste éditable dans un ``wps:txbx`` et reçoit un warp
    Word standard. Le sens est déduit de la pente de la ligne de base quand elle
    est disponible ; une courbure sans pente explicite reste en arc montant.
    """
    curved = bool(getattr(element, "curved", False)) or _orientation(element) == "curved"
    curved = curved or any(getattr(line, "curved", False) for line in _lines(element))
    if not curved:
        return ""
    points = list(getattr(element, "baseline_points", None) or ())
    if not points:
        for line in _lines(element):
            points.extend(getattr(line, "baseline_points", None) or ())
    pente = 0.0
    if len(points) >= 2:
        pente = points[-1][1] - points[0][1]
    preset = "textArchDown" if pente < 0 else "textArchUp"
    return f'<a:prstTxWarp prst="{preset}"><a:avLst/></a:prstTxWarp>'


def _vertical_text_line_spacing_twips(line_source) -> int:
    """Retourne l'avance de glyphes, pas la hauteur de la bbox verticale.

    Une ligne PDF verticale a souvent une bbox de la hauteur complete du credit
    (par exemple 130 pt) alors que chaque caractere ne fait que 8 pt. Reutiliser
    ``hauteur_ligne_emu`` comme interligne dans une textbox verticale pousse le
    paragraphe hors de la zone visible. L'interligne interne doit suivre la
    typographie; la bbox reste reservee a la geometrie externe.
    """
    tailles = [
        float(getattr(span, "size_pt", 0.0) or 0.0)
        for span in getattr(line_source, "spans", ())
        if getattr(span, "texte", "")
    ]
    taille = max(tailles, default=8.0)
    # Une avance legerement superieure au corps laisse les accents et les
    # descendantes respirer sans dependre de la metrique de la police.
    return max(pt_vers_twips(taille * 1.12), 1)


def _vertical_rotated_text_xml(element, relations) -> str:
    """Construit une vraie ligne Word qui sera tournee par DrawingML.

    Une rotation ne doit pas etre simulee par un caractere par ligne : cette
    technique inverse l'ordre de lecture et depend de la gestion des retours
    par LibreOffice/WPS. Les spans et leur ordre source sont donc preserves.
    """
    paragraphes = []
    for index, ligne_source in enumerate(_lines(element)):
        runs = "".join(
            _run_xml(span, relations, autoriser_espacement_negatif=True)
            for span in ligne_source.spans
            if span.texte
        )
        if not runs:
            continue
        if index:
            paragraphes.append('<w:r><w:br/></w:r>')
        interligne = _vertical_text_line_spacing_twips(ligne_source)
        paragraphes.append(
            f'<w:p><w:pPr><w:spacing w:before="0" w:after="0" '
            f'w:line="{interligne}" w:lineRule="exact"/><w:keepLines/></w:pPr>{runs}</w:p>'
        )
    return "".join(paragraphes)


def _text_frame_graphic(element, relations, numbering=None) -> str:
    lignes = _lines(element)
    paragraphes = []
    if _orientation(element) in {"vertical", "vertical-lr", "vertical-rl", "vertical-rtl"}:
        contenu_horizontal = ""
    else:
        # A positioned textbox is only the page-level container.  Inside it the
        # content remains one real Word paragraph and can reflow naturally.
        # Source line boxes are used to recover the line advance, never emitted
        # as artificial paragraph-per-line markup.
        if geometry_kind(element) in {"exclusion-flow", "variable-width-flow"}:
            paragraphes.append(_line_slice_paragraphs(element, relations, numbering))
        else:
            contenu_horizontal = _flow_runs(
                element,
                relations,
                ajuster_lignes=True,
                preserve_line_boundaries=False,
            )
            if contenu_horizontal:
                line = max(pt_vers_twips(emu_vers_pt(_line_step_emu(element))), 1)
                liste = _list_properties_xml(element, numbering)
                paragraphes.append(
                    f'<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="{line}" w:lineRule="exact"/>'
                    f'<w:jc w:val="{block_alignment(element)}"/><w:keepLines/>{liste}</w:pPr>{contenu_horizontal}</w:p>'
                )
    rot, vert = _frame_body_properties(element)
    warp = _text_warp(element)
    bbox = quantifier_bbox(element.bbox)
    vertical = _orientation(element) in {"vertical", "vertical-lr", "vertical-rl", "vertical-rtl"}
    contenu = _vertical_rotated_text_xml(element, relations) if vertical else "".join(paragraphes)
    body_vert = vert
    shape_rotation = _frame_shape_rotation(element)
    # Une forme tournee de 90 degres doit recevoir ses dimensions non tournees.
    # L'ancre externe garde la bbox PDF exacte ; seule la geometrie interne est
    # transposee pour que le texte ne soit pas compose dans une bande de 1 a 3 pt.
    internal_width = max(bbox.hauteur if vertical else bbox.largeur, 1)
    internal_height = max(bbox.largeur if vertical else bbox.hauteur, 1)
    return (
        '<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        '<wps:wsp><wps:cNvSpPr txBox="1"/><wps:spPr>'
        f'<a:xfrm rot="{shape_rotation}"><a:off x="0" y="0"/>'
        f'<a:ext cx="{internal_width}" cy="{internal_height}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln>'
        '</wps:spPr>'
        f'<wps:txbx><w:txbxContent>{contenu}</w:txbxContent></wps:txbx>'
        f'<wps:bodyPr rot="{rot}" vert="{body_vert}" wrap="none" vertOverflow="overflow" horzOverflow="overflow" '
        f'lIns="0" tIns="0" rIns="0" bIns="0" anchor="t">{warp}<a:noAutofit/></wps:bodyPr>'
        '</wps:wsp></a:graphicData></a:graphic>'
    )


def _frame_xml(
    element,
    identifiant: int,
    z: int,
    relations,
    *,
    behind_doc: bool = False,
    include_vml_shape_type: bool = True,
    numbering=None,
) -> str:
    bbox = quantifier_bbox(element.bbox)
    graphic = _text_frame_graphic(element, relations, numbering)
    nom = "Background" if behind_doc else "Editable text"
    drawing = (
        '<w:drawing><wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" '
        f'relativeHeight="{max(z, 1)}" behindDoc="{1 if behind_doc else 0}" locked="0" layoutInCell="0" allowOverlap="1">'
        '<wp:simplePos x="0" y="0"/>'
        f'<wp:positionH relativeFrom="page"><wp:posOffset>{max(bbox.x0, 0)}</wp:posOffset></wp:positionH>'
        f'<wp:positionV relativeFrom="page"><wp:posOffset>{max(bbox.y0, 0)}</wp:posOffset></wp:positionV>'
        f'<wp:extent cx="{max(bbox.largeur, 1)}" cy="{max(bbox.hauteur, 1)}"/>'
        '<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>'
        f'<wp:docPr id="{identifiant}" name="{nom} {identifiant}"/>'
        f'{graphic}</wp:anchor></w:drawing>'
    )
    if not is_special_orientation(element):
        return drawing
    return (
        '<mc:AlternateContent>'
        '<mc:Choice Requires="wps">'
        f'{drawing}'
        '</mc:Choice>'
        '<mc:Fallback>'
        f'{_vertical_vml_frame_xml(element, identifiant, z, relations, include_shape_type=include_vml_shape_type)}'
        '</mc:Fallback>'
        '</mc:AlternateContent>'
    )


def _vertical_vml_frame_xml(
    element,
    identifiant: int,
    z: int,
    relations,
    *,
    include_shape_type: bool = True,
) -> str:
    """Fallback de compatibilite pour LibreOffice et les moteurs sans WPS.

    Le fallback utilise la textbox VML canonique de type 202. Le texte reste
    un ``w:txbxContent`` compose de vrais paragraphes et runs; seule la forme
    porte la rotation, ce qui evite les limites de ``bodyPr/@vert``.
    """
    bbox = quantifier_bbox(element.bbox)
    largeur = max(emu_vers_pt(bbox.largeur), 1.0)
    hauteur = max(emu_vers_pt(bbox.hauteur), 1.0)
    x = emu_vers_pt(max(bbox.x0, 0))
    y = emu_vers_pt(max(bbox.y0, 0))
    _, body_vert = _frame_body_properties(element)
    # Le flux vertical VML est mal pris en charge par plusieurs importeurs.
    # Une textbox horizontale canonique, tournee autour de son centre, conserve
    # le texte et la bbox dans Word comme dans LibreOffice.
    orientation = _orientation(element)
    angle = float(getattr(element, "angle_deg", 0.0) or 0.0)
    if orientation in {"vertical", "vertical-lr", "vertical-rl", "vertical-rtl"}:
        rotation = -90 if body_vert == "vert270" else 90
        largeur_interne, hauteur_interne = hauteur, largeur
    else:
        rotation = round(-angle) if abs(angle) > 0.1 else 0
        largeur_interne, hauteur_interne = largeur, hauteur
    x_interne = x + (largeur - largeur_interne) / 2.0
    y_interne = y + (hauteur - hauteur_interne) / 2.0
    contenu = _vertical_rotated_text_xml(element, relations)
    style = (
        "position:absolute;"
        f"margin-left:{x_interne:.3f}pt;margin-top:{y_interne:.3f}pt;"
        f"width:{largeur_interne:.3f}pt;height:{hauteur_interne:.3f}pt;"
        f"rotation:{rotation};"
        f"z-index:{max(z, 1)};"
        "mso-position-horizontal:absolute;"
        "mso-position-horizontal-relative:page;"
        "mso-position-vertical:absolute;"
        "mso-position-vertical-relative:page;"
        "mso-wrap-style:none;"
        "mso-wrap-distance-left:0;mso-wrap-distance-right:0;"
        "mso-wrap-distance-top:0;mso-wrap-distance-bottom:0;"
    )
    shape_type = "_x0000_t202"
    shape_id = f"vertical_text_{identifiant}"
    type_xml = (
        '<v:shapetype id="_x0000_t202" coordsize="21600,21600" o:spt="202" '
        'path="m,l,21600r21600,l21600,xe">'
        '<v:stroke joinstyle="miter"/><v:path gradientshapeok="t" o:connecttype="rect"/>'
        '</v:shapetype>'
        if include_shape_type
        else ""
    )
    return (
        '<w:pict>'
        f'{type_xml}'
        f'<v:shape id="{shape_id}" o:spid="_x0000_s{identifiant}" '
        f'type="#{shape_type}" o:allowincell="f" filled="f" stroked="f" '
        f'style="{style}visibility:visible;">'
        '<v:textbox inset="0,0,0,0" '
        'style="mso-fit-shape-to-text:n;mso-word-wrap:off;">'
        f'<w:txbxContent>{contenu}</w:txbxContent>'
        '</v:textbox>'
        '<w10:wrap type="none"/></v:shape></w:pict>'
    )


def _host_paragraph(content: str) -> str:
    if not content:
        return ""
    return (
        '<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="1" w:lineRule="exact"/>'
        '<w:contextualSpacing/></w:pPr><w:r>'
        f"{content}</w:r></w:p>"
    )


def _shape_should_overlay(shape, page) -> bool:
    """Retourne les aplats de premier plan qui doivent recouvrir une image.

    Les PDF de brochures peignent souvent un bandeau (par exemple une barre noire)
    après une grande photographie. Les deux objets peuvent pourtant être extraits
    dans l'ordre inverse. On ne remonte que les aplats courts et larges, pas tous les
    tracés d'un schéma ou d'une carte.
    """
    if not getattr(shape, "remplissage", None):
        return False
    largeur = max(shape.bbox.largeur, 1)
    hauteur = max(shape.bbox.hauteur, 1)
    return (
        largeur >= page.largeur_emu * 0.70
        and hauteur <= pt_vers_emu(34)
        and shape.bbox.y0 <= pt_vers_emu(70)
    )


def _section_xml(page, next_page: bool) -> str:
    return section_xml(page, next_page=next_page)


def build_rewrite_render_plan(document: Document, policy: RewritePolicy | None = None) -> RenderPlan:
    """Compatibilité : délègue la construction au module RenderPlan."""
    policy = policy or RewritePolicy()
    options = AnalysisOptions(
        allow_local_raster_fallback=policy.allow_anchored_frames,
        geometry_tolerance_emu=policy.tolerance_emu,
        target_reader=policy.reader_profile,
        extra={"allow_anchored_frames": policy.allow_anchored_frames},
    )
    from copy import deepcopy
    from pdfexact.scene import capture_source_observations

    document = deepcopy(document)
    for page in document.pages:
        capture_source_observations(page, [*page.elements, *page.discarded_elements])
    prepared = deepcopy(document)
    for page in prepared.pages:
        page.elements = prepare_page_elements(page.elements, options)
    return build_render_plan(prepared, options)


def _rewrite_document_xml_legacy(
    document: Document,
    relations,
    policy: RewritePolicy | None = None,
    render_plan: RenderPlan | None = None,
) -> RewriteResult:
    """Reconstruit le DOCX en suivant les régions, l'ordre de peinture et le flux sûr."""
    policy = policy or RewritePolicy()
    diagnostics = RewriteDiagnostics(pages=len(document.pages))
    morceaux = [_HEADER]
    identifiant = 1
    seen: set[str] = set()
    numbering = _NumberingBuilder(relations)
    vml_shape_type_defined = False
    if render_plan is not None:
        diagnostics.plan_errors.extend(render_plan.validate())

    for page_index, page in enumerate(document.pages):
        # L'IR peut contenir une FlowParagraph par ligne après l'extraction PDF.
        # Le rewriter travaille sur les paragraphes reconstruits, sans modifier
        # l'IR partagé utilisé par l'audit et les autres writers.
        elements = (
            list(render_plan.elements_for_page(page.index) or [])
            if render_plan is not None and render_plan.elements_for_page(page.index) is not None
            else _regrouper_flow_paragraphes(list(page.elements))
        )
        indexed = list(enumerate(elements))
        texts = [(index, element) for index, element in indexed if isinstance(element, _TEXT_TYPES)]
        multi_columns = _has_multiple_columns(page, texts)
        # Le plan est construit sur la representation effectivement rendue, apres
        # le regroupement de compatibilite. Les indices restent donc stables.
        page_plan = (
            render_plan
            if render_plan is not None
            else build_page_render_plan(
                page,
                elements,
                AnalysisOptions(
                    allow_local_raster_fallback=policy.allow_anchored_frames,
                    geometry_tolerance_emu=policy.tolerance_emu,
                ),
            )
        )
        if render_plan is None:
            diagnostics.plan_errors.extend(page_plan.validate())
        decisions_by_index = {}
        for index, element in indexed:
            planned = page_plan.for_index(page_index, index)
            if planned is None:
                raise ValueError(f"render plan incomplete for page={page_index}, index={index}")
            universal = planned.decision
            mode_map = {
                "native-flow": "flow",
                "native-list": "flow",
                "native-table": "real_table",
                "positioned-text": "anchored_frame",
                "editable-frame": "anchored_frame",
                "locked-native-paragraph": "anchored_frame",
                "rotated-native-text": "anchored_frame",
                "curved-text": "anchored_frame",
                "anchored-image": "anchored_image",
                "anchored-shape": "anchored_shape",
                "local-raster": "anchored_image",
                "keep-both-ambiguous": "anchored_frame",
            }
            mode = mode_map[universal.mode.value]
            reason = "universal:" + ",".join(universal.reason_codes)
            if mode == "anchored_frame" and not policy.allow_anchored_frames:
                mode = "skip"
                reason = "anchored_frame_forbidden"
            decisions_by_index[index] = ElementDecision(
                source_id=planned.element.element_id,
                mode=mode,
                reason=reason,
                page_index=page_index,
                bbox=quantifier_bbox(element.bbox),
                orientation=_orientation(element),
                z_index=getattr(element, "z_index", index) or index,
                confidence=universal.confidence,
            )
        unique_ids: set[str] = set()
        for index, _element in indexed:
            decision = decisions_by_index[index]
            diagnostics.decisions.append(decision)
            if decision.source_id in seen or decision.source_id in unique_ids:
                diagnostics.skipped_duplicates += 1
                continue
            seen.add(decision.source_id)
            unique_ids.add(decision.source_id)
            if not _inside_page(decision.bbox, page, policy.tolerance_emu):
                diagnostics.out_of_page_elements.append(decision.source_id)
            if decision.mode == "skip":
                diagnostics.missing_elements.append(decision.source_id)
            elif decision.mode == "skip_embedded":
                diagnostics.embedded_text_skipped += 1

        image_parts = []
        shape_parts = []
        foreground_parts = []
        positioned_flow_parts = []
        text_frame_parts = []
        for index, element in indexed:
            decision = decisions_by_index[index]
            if decision.source_id not in unique_ids:
                continue
            if decision.mode == "anchored_image":
                media = document.media.get(element.media_ref)
                if media is None:
                    diagnostics.missing_elements.append(decision.source_id)
                    continue
                relation = relations.ajouter(f"media/{media.media_ref}.{media.extension}", "image")
                # Keep visual assets in the normal anchored layer. LibreOffice
                # can paint behindDoc anchors above later editable text, which
                # hides narrow captions placed on image edges.
                image_parts.append((getattr(element, "z_index", None) or index, image_xml(element, identifiant, 100 + len(image_parts), relation, derriere=False)))
                diagnostics.anchored_images += 1
                identifiant += 1
            elif decision.mode == "anchored_shape":
                overlay = _shape_should_overlay(element, page)
                # Un objet `behindDoc` ne peut pas toujours recouvrir une image
                # `behindDoc` dans LibreOffice, même avec un z-index supérieur.
                # Le bandeau est donc dans la couche normale, avec un z-index bas:
                # il passe devant l'image mais reste sous les cadres de texte.
                z = index + 1
                shape_parts.append((getattr(element, "z_index", None) or index, forme_xml(element, identifiant, z, derriere=not overlay)))
                diagnostics.anchored_shapes += 1
                identifiant += 1
            elif decision.mode == "anchored_link" and element.uri:
                foreground_parts.append(
                    zone_lien_xml(element, identifiant, index + 1, relations.ajouter(element.uri, "hyperlink", externe=True))
                )
                diagnostics.anchored_links += 1
                identifiant += 1
            elif decision.mode == "anchored_frame":
                # Un bloc horizontal n'a pas besoin d'un dessin WPS. On le garde
                # comme paragraphe Word direct et on transporte seulement sa bbox
                # dans w:framePr. Les orientations spéciales restent dans WPS car
                # w:p/w:r ne savent pas représenter une rotation ou une courbure.
                page_geometry_locked = "page-geometry-locked" in decision.reason
                if (
                    decision.orientation == "horizontal"
                    and not getattr(element, "curved", False)
                    and geometry_kind(element) == "rectangular-flow"
                    and not page_geometry_locked
                ):
                    # Keep the compatibility path for isolated paragraphs.
                    # Multi-region pages take the textbox path below because
                    # some readers interpret w:framePr as global body flow.
                    contenu = _positioned_flow_paragraph_xml(element, page, relations, numbering)
                    if contenu:
                        positioned_flow_parts.append(contenu)
                        diagnostics.positioned_flow_paragraphs += 1
                        diagnostics.direct_body_paragraphs += 1
                    else:
                        diagnostics.missing_elements.append(decision.source_id)
                elif decision.orientation in {"vertical", "vertical-lr", "vertical-rl", "vertical-rtl"}:
                    risk = record_reader_risk(
                        policy.reader_profile,
                        "vertical-body",
                        context=decision.source_id,
                    )
                    if not risk["supported"]:
                        diagnostics.reader_risks.append(risk)
                    # Rotated text must remain in the foreground layer. A
                    # floating table has no portable z-order in LibreOffice;
                    # the editable Word shape does, so give it the highest
                    # local paint priority while retaining real w:r content.
                    text_frame_parts.append(
                        _frame_xml(
                            element,
                            identifiant,
                            2_000_000 + index,
                            relations,
                            include_vml_shape_type=not vml_shape_type_defined,
                            numbering=numbering,
                        )
                    )
                    vml_shape_type_defined = True
                    diagnostics.anchored_frames += 1
                else:
                    if getattr(element, "curved", False):
                        risk = record_reader_risk(
                            policy.reader_profile,
                            "text-warp",
                            context=decision.source_id,
                        )
                        if not risk["supported"]:
                            diagnostics.reader_risks.append(risk)
                    if _line_text(element):
                        text_frame_parts.append(
                            _frame_xml(
                                element,
                                identifiant,
                                1000 + index,
                                relations,
                                numbering=numbering,
                            )
                        )
                        diagnostics.anchored_frames += 1
                    else:
                        diagnostics.missing_elements.append(decision.source_id)
                identifiant += 1

        # Les extracteurs rencontrent fréquemment les formes avant les images,
        # alors que le PDF les peint dans l'ordre inverse. Les images constituent
        # donc la sous-couche ; les aplats et bordures repassent au-dessus.
        background_parts = [
            xml
            for _, xml in sorted(
                [*image_parts, *shape_parts],
                key=lambda item: item[0],
            )
        ]
        if background_parts:
            morceaux.append(_host_paragraph("".join(background_parts)))
        if foreground_parts:
            morceaux.append(_host_paragraph("".join(foreground_parts)))

        flow_elements = sorted(
            ((index, element) for index, element in indexed if decisions_by_index[index].mode == "flow"),
            key=lambda item: (item[1].bbox.y0, item[1].bbox.x0, item[0]),
        )
        precedent_bas = 0
        for _index, element in flow_elements:
            avant = max(0, element.bbox.y0 - precedent_bas)
            contenu = _flow_paragraph_xml(element, page, avant, relations, numbering)
            if contenu:
                morceaux.append(contenu)
                diagnostics.flow_paragraphs += 1
                diagnostics.direct_body_paragraphs += 1
            precedent_bas = max(precedent_bas, element.bbox.y1)

        if positioned_flow_parts:
            morceaux.extend(positioned_flow_parts)

        if text_frame_parts:
            morceaux.append(_host_paragraph("".join(text_frame_parts)))

        for index, element in indexed:
            if decisions_by_index[index].mode != "real_table":
                continue
            morceaux.append(
                table_body_xml(
                    element,
                    relations,
                    strict_geometry=True,
                    positionne=True,
                    indentation_emu=element.bbox.x0,
                    texte_cellules=True,
                )
            )
            diagnostics.real_tables += 1
            diagnostics.positioned_tables += 1

        if policy.preserve_page_breaks:
            morceaux.append(f'<w:p><w:pPr>{_section_xml(page, page_index < len(document.pages) - 1)}</w:pPr></w:p>')

    morceaux.append(_FOOTER)
    return RewriteResult("".join(morceaux), diagnostics, numbering.xml())


def rewrite_document_xml(document, relations, policy=None, render_plan=None) -> RewriteResult:
    """Materialize an already compiled plan; direct calls prepare it first."""
    from pdfexact.render.text_backend import render_flow, render_positioned, render_frame

    policy = policy or RewritePolicy()
    plan = render_plan if render_plan is not None else build_rewrite_render_plan(document, policy)
    errors = plan.validate(document)
    expected_pages = {page.index for page in document.pages}
    if set(plan.pages) != expected_pages:
        errors = [*errors, "incomplete-plan-pages"]
    if errors and render_plan is not None:
        raise ValueError("invalid render plan: " + "; ".join(errors))
    if render_plan is not None and not policy.allow_anchored_frames and plan.options.extra.get("allow_anchored_frames") is not False:
        raise ValueError("render-policy-mismatch:allow_anchored_frames")
    diagnostics = RewriteDiagnostics(pages=len(document.pages))
    diagnostics.plan_errors.extend(errors)
    parts = [_HEADER]
    numbering = _NumberingBuilder(relations)
    identifiant = 1
    vml_defined = False
    mode_names = {"flow": "flow", "positioned": "anchored_frame", "dml-frame": "anchored_frame", "layered-frame": "anchored_frame", "image": "anchored_image", "shape": "anchored_shape", "table": "real_table", "link": "anchored_link", "unsupported": "skip"}
    for position, page in enumerate(document.pages):
        for item in plan.for_page(page.index):
            instruction = item.materialization.fragments[0]
            decision = ElementDecision(
                item.element.element_id, mode_names[instruction.container], "universal:" + ",".join(item.decision.reason_codes),
                page.index, quantifier_bbox(item.decision.expected_bbox), item.decision.expected_orientation,
                z_index=item.decision.expected_z_order, confidence=item.decision.confidence,
            )
            diagnostics.decisions.append(decision)
            if not _inside_page(decision.bbox, page, plan.options.geometry_tolerance_emu):
                diagnostics.out_of_page_elements.append(decision.source_id)
        owners = {id(instruction): item.element.element_id for item in plan.for_page(page.index) for instruction in item.materialization.fragments}
        for instruction in plan.instructions_for_page(page.index):
            element, container, anchor = instruction.element, instruction.container, instruction.anchor
            source_id = owners[id(instruction)]
            content = ""
            if container == "image":
                media = document.media.get(element.media_ref)
                if media is not None:
                    rel_id = relations.ajouter(f"media/{media.media_ref}.{media.extension}", "image")
                    content = image_xml(element, identifiant, anchor.z, rel_id, derriere=anchor.behind_doc, planned=True)
                    diagnostics.anchored_images += 1
            elif container == "shape":
                content = forme_xml(element, identifiant, anchor.z, derriere=anchor.behind_doc, planned=True)
                diagnostics.anchored_shapes += 1
            elif container == "link":
                if element.uri:
                    content = zone_lien_xml(element, identifiant, anchor.z, relations.ajouter(element.uri, "hyperlink", externe=True))
                    diagnostics.anchored_links += 1
            elif container == "flow":
                content = render_flow(instruction.text, element, page, instruction.before_emu, relations, numbering)
                if content:
                    diagnostics.flow_paragraphs += 1
                    diagnostics.direct_body_paragraphs += 1
            elif container == "positioned":
                content = render_positioned(instruction.text, element, relations, numbering)
                if content:
                    diagnostics.positioned_flow_paragraphs += 1
                    diagnostics.direct_body_paragraphs += 1
            elif container in {"dml-frame", "layered-frame"}:
                text = instruction.text
                if text.native_runs or text.frame_runs or any(tokens for _, tokens in text.vertical_lines):
                    content = render_frame(text, element, identifiant, anchor.z, relations, numbering, layered=container == "layered-frame", include_vml_shape_type=not vml_defined, behind_doc=anchor.behind_doc)
                    vml_defined = vml_defined or text.orientation.special
                    diagnostics.anchored_frames += 1
                    feature = "vertical-body" if text.orientation.vertical else "text-warp" if text.orientation.warp else None
                    if feature:
                        risk = record_reader_risk(plan.options.target_reader, feature, context=source_id)
                        if not risk["supported"]:
                            diagnostics.reader_risks.append(risk)
            elif container == "table":
                content = table_body_xml(element, relations, strict_geometry=True, positionne=True, indentation_emu=element.bbox.x0, texte_cellules=True)
                diagnostics.real_tables += 1
                diagnostics.positioned_tables += 1
            if not content:
                diagnostics.missing_elements.append(source_id)
            elif container in {"image", "shape", "link", "dml-frame", "layered-frame"}:
                parts.append(_host_paragraph(content))
            else:
                parts.append(content)
            identifiant += 1
        if policy.preserve_page_breaks:
            parts.append(f'<w:p><w:pPr>{_section_xml(page, position < len(document.pages) - 1)}</w:pPr></w:p>')
    parts.append(_FOOTER)
    return RewriteResult("".join(parts), diagnostics, numbering.xml())
