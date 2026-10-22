"""Plan de composition Word pour un bloc texte PDF.

Ce module separe la decision sémantique, la mesure typographique et le rendu
OOXML. Les renderers consomment le meme plan et ne redecident plus des retours.
"""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass
import math

from pdfexact.geometry import BBox, emu_vers_pt, pt_vers_emu, pt_vers_twips
from pdfexact.analysis.semantic import frontiere_de_paragraphe_source
from pdfexact.layout.text_comprehension import (
    comprendre_reflow_paragraphe,
    contexte_lignes_texte,
)


_JONCTIONS_VALIDES = frozenset(
    {"space", "no_space", "hyphen_join", "preserve_break", "paragraph_break"}
)


@dataclass(frozen=True)
class ParagraphLayoutPlan:
    """Decision complete de composition pour un seul bloc texte."""

    joins: tuple[str, ...]
    line_spacing_twips: tuple[int, ...]
    line_width_scale_percent: tuple[int, ...]
    preserve_lines: bool
    estimated_line_count: int
    evidence: tuple[str, ...] = ()

    def action_between(self, index: int) -> str:
        if self.preserve_lines:
            return "preserve_break"
        if 0 <= index < len(self.joins):
            return self.joins[index]
        return "space"


def lignes_du_bloc(element) -> tuple:
    """Retourne les lignes textuelles dans un ordre stable de lecture."""
    return tuple(
        sorted(
            (
                line
                for line in (getattr(element, "lignes", ()) or ())
                if any(span.texte for span in line.spans)
            ),
            key=lambda line: (line.bbox.y0, line.bbox.x0),
        )
    )


def _textes(element) -> tuple[str, ...]:
    return tuple(
        "".join(span.texte for span in line.spans)
        for line in lignes_du_bloc(element)
    )


def _police_largeur(text: str, spans, polices) -> float | None:
    if not polices or not text:
        return None
    try:
        from pdfexact.extract.fonts import mesurer_largeur_pt
    except Exception:  # noqa: BLE001
        return None
    largeur = 0.0
    for span in spans:
        asset = polices.get(span.police.font_id)
        if asset is None:
            return None
        largeur += mesurer_largeur_pt(span.texte, asset, span.size_pt)
    return largeur


def _espacement_pour_ligne(line, polices) -> int:
    """Retourne seulement la correction necessaire pour eviter un wrap Word."""
    spans = [span for span in line.spans if span.texte]
    if not spans:
        return 0
    mesure = _police_largeur("".join(span.texte for span in spans), spans, polices)
    if mesure is None:
        return 0
    cible = emu_vers_pt(line.bbox.largeur) * 0.985
    if mesure <= cible + 0.25:
        return 0
    caracteres = max(sum(len(span.texte) for span in spans) - 1, 1)
    correction = round(pt_vers_twips((cible - mesure) / caracteres))
    # Le tracking est un ajustement de secours, borne pour rester lisible.
    return max(-32, min(0, correction))


def _largeur_ligne_pt(line, polices) -> float | None:
    spans = [span for span in line.spans if span.texte]
    if not spans:
        return None
    return _police_largeur("".join(span.texte for span in spans), spans, polices)


def _est_composition_affichee(element, textes: tuple[str, ...]) -> bool:
    role = str(
        getattr(element, "semantic_role", None)
        or getattr(element, "layout_frame_role", None)
        or ""
    ).casefold()
    if role in {"title", "subtitle", "heading", "header", "label"}:
        return True
    if len(textes) <= 1 or len(textes) > 6:
        return False
    mots = len(" ".join(textes).split())
    tailles = [
        float(span.size_pt or 0.0)
        for line in lignes_du_bloc(element)
        for span in line.spans
        if span.texte
    ]
    if not tailles or mots > 14:
        return False
    # Une composition courte et nettement plus grande que le texte courant est
    # un affichage : ses retours sont intentionnels, mais doivent etre verifies.
    return max(tailles) >= 16.0


_RUPTURES = frozenset({"preserve_break", "paragraph_break"})
# A row wider than its available width is condensed to 98 % of it (2 % of
# renderer rounding); a row narrower than 90 % of its source width is widened
# back to 98 % of it. Rows in between keep their natural width.
_MARGE_ARRONDI = 0.98
_ZONE_NEUTRE_BASSE = 0.90
_ECHELLE_MIN, _ECHELLE_MAX = 50, 200


def _mesure_premier_mot(polices):
    if not polices:
        return None
    from dataclasses import replace

    def mesure(line, word):
        spans = [span for span in line.spans if span.texte]
        return _police_largeur(word, [replace(spans[0], texte=word)], polices) if spans else None

    return mesure


def _largeur_utile_pt(line, polices) -> float | None:
    """Width a row needs once rendered: a leader becomes a tab, not glyphs."""
    from pdfexact.analysis.line_structure import split_leader

    parts = split_leader("".join(span.texte for span in line.spans))
    if parts is None:
        return _largeur_ligne_pt(line, polices)
    spans = [span for span in line.spans if span.texte]
    if not spans or not polices:
        return None
    from dataclasses import replace

    label, page, _ = parts
    return _police_largeur(f"{label}   {page}", [replace(spans[0], texte=f"{label}   {page}")], polices)


def _echelle(mesure, largeur_pt, disponible_pt=None, *, agrandir=True) -> int:
    """Horizontal scale of a row rendered with a substitute face.

    A row is condensed only when it would not fit the width available in its
    frame (it would wrap or leave the box); it is widened back towards its
    source width when the substitute is clearly narrower. Matching metrics
    are left untouched."""
    if not mesure or largeur_pt <= 0:
        return 100
    disponible_pt = max(disponible_pt or largeur_pt, largeur_pt)
    if mesure > disponible_pt:
        return max(_ECHELLE_MIN, round(disponible_pt * _MARGE_ARRONDI / mesure * 100))
    if agrandir and mesure < largeur_pt * _ZONE_NEUTRE_BASSE:
        return min(_ECHELLE_MAX, round(largeur_pt * _MARGE_ARRONDI / mesure * 100))
    return 100


def planifier_paragraphe(element, polices=None, column_right=None) -> ParagraphLayoutPlan:
    """Construit le plan unique consomme par tous les renderers Word.

    ``column_right`` is the right edge of the text column holding the block;
    a row stopping before it while the next word would fit was broken on
    purpose. It defaults to the block's own edge."""
    from pdfexact.analysis.line_structure import geometric_alignment, hard_break_reason, is_leader_line

    textes = _textes(element)
    if not textes:
        return ParagraphLayoutPlan((), (), (), False, 0, ("empty",))

    role = getattr(element, "layout_frame_role", None)
    strategy = getattr(element, "layout_frame_strategy", None)
    lignes = lignes_du_bloc(element)
    owner = copy(element)
    owner.lignes = list(lignes)
    context = contexte_lignes_texte((owner,))
    source_indices = {id(line): index for index, line in enumerate(element.lignes)}
    for line, row in zip(lignes, context["lines"]):
        row.setdefault("source_index", source_indices[id(line)])
    reflow = comprendre_reflow_paragraphe(
        textes,
        frame_role=role,
        frame_strategy=strategy,
        metadonnees=context,
    )
    display = _est_composition_affichee(element, textes)
    joins = tuple(
        join if join in _JONCTIONS_VALIDES else "space"
        for join in reflow.line_joins
    )
    joins = tuple(
        "preserve_break" if frontiere_de_paragraphe_source(
            previous, current, obstacles=context.get("obstacles", ()),
        ) else join
        for previous, current, join in zip(lignes, lignes[1:], joins)
    )
    right_edge = max(column_right or 0, element.bbox.x1)
    mesure_mot = _mesure_premier_mot(polices)
    joins = tuple(
        "preserve_break" if join not in _RUPTURES and hard_break_reason(
            previous, current, right_edge, measure=mesure_mot,
        ) else join
        for previous, current, join in zip(lignes, lignes[1:], joins)
    )
    # Ragged-left and centred rows are compositions: each break is authored.
    display = display or geometric_alignment(lignes) in {"right", "center"}
    dernier = len(lignes) - 1
    figees = tuple(
        display or len(lignes) == 1 or (
            (index == 0 or joins[index - 1] in _RUPTURES)
            and (index == dernier or joins[index] in _RUPTURES)
        )
        for index in range(len(lignes))
    )
    mesures = tuple(_largeur_utile_pt(line, polices) for line in lignes)
    # A fixed row keeps its own source width, whatever the substitute font:
    # it must neither leave its box (wider face) nor shrink (narrower face).
    line_width_scale = [
        _echelle(mesure, emu_vers_pt(line.bbox.largeur), emu_vers_pt(element.bbox.x1 - line.bbox.x0),
                 agrandir=not is_leader_line(line)) if figee else 100
        for line, mesure, figee in zip(lignes, mesures, figees)
    ]
    reflowed = [index for index, figee in enumerate(figees) if not figee]
    if reflowed and all(mesures[index] for index in reflowed):
        # Reflowed rows share one scale so the block keeps its row count.
        source = sum(emu_vers_pt(lignes[index].bbox.largeur) for index in reflowed)
        commune = _echelle(sum(mesures[index] for index in reflowed), source, agrandir=False)
        for index in reflowed:
            line_width_scale[index] = commune
    line_width_scale = tuple(line_width_scale)
    line_spacing = tuple(
        0 if scale != 100 else _espacement_pour_ligne(line, polices)
        for line, scale in zip(lignes, line_width_scale)
    )
    if display or all(join in _RUPTURES for join in joins):
        estimated = len(textes)
        evidence = ("display-composition" if display else "source-line-structure", *reflow.evidence)
    else:
        largeur = max(float(getattr(element.bbox, "largeur", 0) or 0), 1.0)
        total = 0.0
        for line in lignes_du_bloc(element):
            spans = [span for span in line.spans if span.texte]
            mesure = _police_largeur("".join(span.texte for span in spans), spans, polices)
            total += mesure if mesure is not None else emu_vers_pt(line.bbox.largeur)
        estimated = (
            1
            if len(textes) == 1
            else max(len(textes), int(math.ceil(total / emu_vers_pt(largeur))))
        )
        evidence = ("natural-flow", *reflow.evidence)
    return ParagraphLayoutPlan(
        joins=joins,
        line_spacing_twips=line_spacing,
        line_width_scale_percent=line_width_scale,
        preserve_lines=display,
        estimated_line_count=max(1, estimated),
        evidence=tuple(evidence),
    )


def ajuster_bboxes_mono_ligne(document, marge_pt: float = 4.0) -> None:
    """Elargit les bboxes mono-ligne seulement dans l'espace libre de la page.

    Une police de remplacement peut etre plus large que la police PDF. Le cadre
    Word ne doit alors ni provoquer un faux retour ni recouvrir le bloc voisin.
    La bbox et sa ligne sont ajustees ensemble afin que le DOCX et le diagnostic
    PDF gardent la meme geometrie.
    """
    marge = pt_vers_emu(marge_pt)
    for page in getattr(document, "pages", ()):
        elements = [
            element
            for element in getattr(page, "elements", ())
            if getattr(element, "bbox", None) is not None
        ]
        for element in elements:
            lignes = lignes_du_bloc(element)
            if len(lignes) != 1 or getattr(element, "orientation", "horizontal") != "horizontal":
                continue
            mesure = _largeur_ligne_pt(lignes[0], getattr(document, "polices", None))
            if mesure is None:
                continue
            bbox = element.bbox
            # Les métriques de la police résolue restent une approximation du
            # moteur Word/LibreOffice. Une marge proportionnelle absorbe cet
            # écart sans modifier le corps de police.
            besoin = pt_vers_emu(max(mesure + marge_pt * 2, mesure * 1.20))
            if besoin <= bbox.largeur:
                continue
            limite = getattr(page, "largeur_emu", bbox.x1)
            for voisin in elements:
                if voisin is element or voisin.bbox.x0 <= bbox.x0:
                    continue
                recouvrement_y = min(bbox.y1, voisin.bbox.y1) - max(bbox.y0, voisin.bbox.y0)
                if recouvrement_y > 0:
                    limite = min(limite, voisin.bbox.x0 - marge)
            nouvelle_largeur = min(besoin, max(bbox.largeur, limite - bbox.x0))
            if nouvelle_largeur <= bbox.largeur:
                continue
            element.bbox = BBox(bbox.x0, bbox.y0, bbox.x0 + nouvelle_largeur, bbox.y1)
            ligne = lignes[0]
            ligne.bbox = BBox(ligne.bbox.x0, ligne.bbox.y0, ligne.bbox.x0 + nouvelle_largeur, ligne.bbox.y1)
            ligne.largeur_cible_emu = nouvelle_largeur
