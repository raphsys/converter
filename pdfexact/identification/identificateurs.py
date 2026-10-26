"""Built-in identificateurs: the AIs decide, Python only translates and combines.

No layout heuristic lives here (no font-size ratio, page band, aspect ratio…): documents
are too diverse. Sources, in cascade order:
- native PDF facts (link annotations, native tables);
- PP-DocLayout_plus-L zones (PP-StructureV3), computed by the segmentation;
- SmolVLM vision (``vision.py``), then PP-FormulaNet (``formulenet.py``), added by the pipeline.
"""
from __future__ import annotations

from dataclasses import replace

from pdfexact.identification.base import Candidat, ContextePage, Decision, Registre, consulter, decider
from pdfexact.ir import FlowParagraph, ImageEl, LinkZone, RasterEl, ShapeEl, TableEl, TextBox

__all__ = ["Candidat", "contexte_page", "decider", "decider_element", "nature", "registre_par_defaut", "texte"]

# An element and a zone describe the same content when this share of the smaller lies in the other.
RECOUVREMENT_ZONE = 0.5
CONFIANCE_ZONE_INCONNUE = 0.7
SCORE_FAIT_NATIF = 0.9

# Translation of the PP-DocLayout labels: for a text inside the zone...
LABEL_TEXTE = {
    "doc_title": "titre_document", "paragraph_title": "intertitre", "text": "paragraphe", "abstract": "resume",
    "content": "entree_sommaire", "reference": "entree_bibliographique", "reference_content": "entree_bibliographique",
    "footnote": "note_bas_page", "header": "en_tete", "footer": "pied_de_page", "number": "numero_page",
    "figure_title": "legende", "table_title": "legende", "chart_title": "legende", "aside_text": "note_marginale",
    "algorithm": "bloc_code", "formula": "formule_bloc", "formula_number": "numero_formule", "table": "cellule",
    "image": "etiquette", "chart": "etiquette", "seal": "etiquette",
}
# ...and for a visual inside the zone: (type, weight). A generic "image" zone only
# establishes the family, its precise type is left to the vision.
LABEL_VISUEL = {
    "image": ("image_generique", 0.6), "figure": ("image_generique", 0.6), "chart": ("graphique", 1.0),
    "seal": ("sceau", 1.0), "table": ("tableau", 1.0), "formula": ("formule_bloc", 1.0),
}


def nature(element) -> str | None:
    if isinstance(element, (TextBox, FlowParagraph)):
        return "text"
    if isinstance(element, (ImageEl, RasterEl)):
        return "image"
    if isinstance(element, ShapeEl):
        return "shape"
    if isinstance(element, TableEl):
        return "table"
    if isinstance(element, LinkZone):
        return "link"
    return None


def texte(element) -> str:
    """Text of a text element, lines joined by a newline (as in the catalogue)."""
    return "\n".join("".join(span.texte for span in ligne.spans) for ligne in getattr(element, "lignes", ()))


def _intersection(a, b) -> int:
    return max(0, min(a.x1, b.x1) - max(a.x0, b.x0)) * max(0, min(a.y1, b.y1) - max(a.y0, b.y0))


def _aire(boite) -> int:
    return max(boite.largeur, 0) * max(boite.hauteur, 0)


def zone_de(element, page, zones=None):
    """The layout zone sharing most area with the element, when one of the two lies mostly in the other.

    Boxes differ by nature: a text box includes the line leading, an image box its white
    margins, a zone hugs the detected content.
    """
    zones = getattr(page, "zones_layout", ()) if zones is None else zones
    meilleure = max(zones or (), key=lambda z: _intersection(element.bbox, z.bbox), default=None)
    if meilleure is None:
        return None
    plus_petite = min(_aire(element.bbox), _aire(meilleure.bbox)) or 1
    return meilleure if _intersection(element.bbox, meilleure.bbox) / plus_petite >= RECOUVREMENT_ZONE else None


def contexte_page(page, premiere_page: bool = False) -> ContextePage:
    return ContextePage(page=page, premiere_page=premiere_page)


class FaitsNatifs:
    """What the PDF itself declares: a native table, a link annotation."""

    nom = "faits-natifs"
    natures = frozenset({"table", "link"})

    def candidats(self, element, contexte):
        if isinstance(element, TableEl):
            return [Candidat("tableau", SCORE_FAIT_NATIF, "tableau natif du PDF")]
        if element.page_cible is not None or (element.uri or "").startswith("#"):
            return [Candidat("renvoi", SCORE_FAIT_NATIF, "annotation de lien interne")]
        return [Candidat("lien", SCORE_FAIT_NATIF, "annotation de lien externe")]


def candidats_zone(element, zone, source: str) -> list[Candidat]:
    """What a PP-DocLayout zone says of the element lying in it, scored by the zone's confidence."""
    if zone is None:
        return []
    confiance = zone.confidence if zone.confidence is not None else CONFIANCE_ZONE_INCONNUE
    label = str(zone.label).casefold()
    if nature(element) == "text":
        type_, poids = LABEL_TEXTE.get(label), 1.0
    else:
        type_, poids = LABEL_VISUEL.get(label, (None, 0.0))
    return [Candidat(type_, confiance * poids, f"{source}:{label}")] if type_ else []


class ZonesLayout:
    """PP-DocLayout_plus-L (PP-StructureV3): the zone of the element gives its role."""

    nom = "pp-doclayout"
    natures = frozenset({"text", "image", "shape"})

    def candidats(self, element, contexte):
        return candidats_zone(element, zone_de(element, contexte.page), self.nom)


def registre_par_defaut(*supplements) -> Registre:
    """Native facts and PP-DocLayout zones, then the given sources (vision, formulas…)."""
    return Registre([FaitsNatifs(), ZonesLayout(), *(s for s in supplements if s is not None)])


def decider_element(element, page, contexte: ContextePage, registre: Registre | None = None) -> Decision:
    """Ask, in cascade, every source handling the element's nature, then decide."""
    nat, echecs = nature(element), []
    candidats = consulter((registre or registre_par_defaut()).pour(nat or ""), element, contexte, echecs)
    decision = decider(candidats, repli="image_generique" if nat == "image" else "inconnu")
    return replace(decision, indices=(*decision.indices, *echecs)) if echecs else decision
