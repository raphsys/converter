"""Contrats universels de geometrie et de presentation du texte.

Ce module ne depend d'aucun backend DOCX. Il transforme les lignes PDF en
contraintes de composition reutilisables par le plan, le writer et l'audit.
"""
from __future__ import annotations

from dataclasses import dataclass

from pdfexact.analysis.geometry import resolve_text_orientation
from pdfexact.geometry import BBox, pt_vers_emu, quantifier_bbox


SPECIAL_ORIENTATIONS = frozenset(
    {
        "vertical",
        "vertical-lr",
        "vertical-rl",
        "vertical-rtl",
        "rotated",
        "oblique-up",
        "oblique-down",
        "curved",
    }
)
GEOMETRIC_ROLES = frozenset(
    {"caption", "credit", "label", "annotation", "diagram_text", "figure_text", "footer"}
)
HEADING_ROLES = frozenset({"title", "subtitle", "heading", "header"})


@dataclass(frozen=True)
class TextBlockPresentation:
    alignment: str = "left"
    line_spacing_emu: int = 0
    before_spacing_emu: int = 0
    after_spacing_emu: int = 0
    left_indent_emu: int = 0
    right_indent_emu: int = 0
    first_line_indent_emu: int = 0
    preserve_line_boundaries: bool = False
    source: str = "extracted"


def line_has_text(line) -> bool:
    """A blank positioning row is spacing evidence, not visible text geometry."""
    return any(str(getattr(span, "texte", "") or "").strip() for span in getattr(line, "spans", ()))


def line_has_whitespace_paint(line) -> bool:
    """Recognize recorded visible decorations, not arbitrary whitespace glyphs."""
    if getattr(line, "opacity", 1.0) == 0:
        return False
    for span in getattr(line, "spans", ()):
        text = getattr(span, "texte", "")
        if not text or not text.isspace() or getattr(span, "invisible", False):
            continue
        if getattr(span, "opacity", 1.0) == 0 or (getattr(span, "attributes", {}) or {}).get("source_alpha") == 0:
            continue
        if any(getattr(span, name, False) for name in ("souligne", "barre", "surlignage")):
            return True
    return False


def line_needs_paint_geometry(line) -> bool:
    return line_has_text(line) or line_has_whitespace_paint(line)


def _lines(element):
    return [line for line in (getattr(element, "lignes", ()) or ()) if line_has_text(line)]


def paragraph_bbox_from_lines(lines, fallback: BBox | None = None) -> BBox | None:
    """Construit l'enveloppe d'un paragraphe depuis ses lignes reelles.

    La bbox est l'enveloppe technique Word, tandis que ``line_bboxes`` conserve
    la forme composee. Aucun padding arbitraire n'est ajoute : les bords viennent
    exclusivement des lignes qui appartiennent au paragraphe.
    """
    lignes = [line for line in lines if getattr(line, "bbox", None) is not None and line_needs_paint_geometry(line)]
    if not lignes:
        return quantifier_bbox(fallback) if fallback is not None else None
    bboxes = [line.bbox for line in lignes]
    return quantifier_bbox(
        BBox(
            min(bbox.x0 for bbox in bboxes),
            min(bbox.y0 for bbox in bboxes),
            max(bbox.x1 for bbox in bboxes),
            max(bbox.y1 for bbox in bboxes),
        )
    )


def orientation_of(element) -> str:
    return str(resolve_text_orientation(element)["orientation"] or "horizontal").casefold()


def is_special_orientation(element) -> bool:
    return (
        orientation_of(element) in SPECIAL_ORIENTATIONS
        or bool(resolve_text_orientation(element)["angle_deg"])
        or bool(getattr(element, "curved", False))
        or any(bool(getattr(line, "curved", False)) for line in _lines(element))
    )


def geometry_kind(element) -> str:
    """Détermine la forme de composition sans remplacer la bbox historique."""
    if is_special_orientation(element):
        return "oriented"
    lines = _lines(element)
    if len(lines) < 2:
        return "rectangular-flow"
    non_final = lines[:-1]
    # Le retrait d'une première ligne est précisément l'information à garder;
    # seule la largeur de la dernière ligne peut être naturellement courte.
    x0_values = [line.bbox.x0 for line in lines]
    x1_values = [line.bbox.x1 for line in non_final]
    tolerance = pt_vers_emu(3.0)
    if x0_values and max(x0_values) - min(x0_values) > tolerance:
        return "exclusion-flow"
    if x1_values and max(x1_values) - min(x1_values) > tolerance:
        return "variable-width-flow"
    return "rectangular-flow"


def _text(element) -> str:
    direct = getattr(element, "texte", None)
    if direct:
        return str(direct)
    return " ".join(
        "".join(str(getattr(span, "texte", "") or "") for span in line.spans)
        for line in _lines(element)
    ).strip()


def _max_size(element) -> float:
    return max(
        (float(getattr(span, "size_pt", 0.0) or 0.0) for line in _lines(element) for span in line.spans),
        default=float(getattr(element, "size_pt", 0.0) or 0.0),
    )


def block_alignment(element) -> str:
    """Retourne l'alignement du bloc, jamais une justification globale."""
    saved = getattr(element, "presentation", None) or {}
    saved_alignment = str(saved.get("alignment", "") or "").casefold() if isinstance(saved, dict) else ""
    if saved_alignment in {"left", "center", "right", "both"}:
        return saved_alignment
    explicit = str(getattr(element, "alignement", "left") or "left").casefold()
    lines = _lines(element)
    values = [str(getattr(line, "alignement", "left") or "left").casefold() for line in lines]
    meaningful = [value for value in values if value != "left"]
    if meaningful and len(set(meaningful)) == 1:
        return meaningful[0]
    role = str(
        getattr(element, "semantic_role", None)
        or getattr(element, "layout_frame_role", None)
        or ""
    ).casefold()
    words = len(_text(element).split())
    if explicit in {"center", "right", "both", "justify"}:
        return "both" if explicit == "justify" else explicit
    if role in GEOMETRIC_ROLES or role in HEADING_ROLES:
        return "left"
    # Un bloc court ou compose en grand corps est typographiquement un titre,
    # meme lorsque le PDF ne porte pas de role semantique exploitable.
    if _max_size(element) >= 16.0 or (len(lines) <= 5 and words <= 12):
        return "left"
    non_final = lines[:-1]
    if len(non_final) >= 2:
        bbox = getattr(element, "bbox", None)
        tolerance = pt_vers_emu(2.0)
        full = [
            line for line in non_final
            if bbox is not None
            and line.bbox.x0 <= bbox.x0 + tolerance
            and line.bbox.x1 >= bbox.x1 - tolerance
        ]
        tracking = [
            line for line in non_final
            if any(int(getattr(span, "espacement_twips", 0) or 0) > 0 for span in line.spans)
        ]
        if len(full) >= max(2, len(non_final) // 2) or len(tracking) >= max(2, len(non_final) // 2):
            return "both"
    return "left"


def presentation_for(element) -> TextBlockPresentation:
    lines = _lines(element)
    return TextBlockPresentation(
        alignment=block_alignment(element),
        line_spacing_emu=max(
            [int(getattr(element, "interligne_emu", 0) or 0)]
            + [int(getattr(line, "hauteur_ligne_emu", 0) or 0) for line in lines]
            + [0]
        ),
        before_spacing_emu=int(getattr(element, "espace_avant_emu", 0) or 0),
        after_spacing_emu=int(getattr(element, "espace_apres_emu", 0) or 0),
        left_indent_emu=int(getattr(element, "retrait_gauche_emu", 0) or 0),
        right_indent_emu=int(getattr(element, "retrait_droite_emu", 0) or 0),
        first_line_indent_emu=int(getattr(element, "retrait_premiere_ligne_emu", 0) or 0),
        preserve_line_boundaries=(
            geometry_kind(element) != "rectangular-flow"
            or str(getattr(element, "semantic_role", "") or "").casefold() in GEOMETRIC_ROLES
        ),
    )


def geometry_contract_for(element):
    """Construit le contrat geometrique apres une fusion de lignes."""
    from pdfexact.ir import TextGeometry

    lines = [line for line in (getattr(element, "lignes", ()) or ()) if line_needs_paint_geometry(line)]
    bbox = getattr(element, "bbox", None)
    exclusions: list[BBox] = []
    if bbox is not None and not is_special_orientation(element):
        tolerance = pt_vers_emu(2.0)
        for line in lines:
            # Un retrait de ligne par rapport a la bbox n'est pas un simple
            # effet de reflow: il reserve une zone a un objet voisin (lettrine,
            # image ou forme). Cette zone doit voyager avec le paragraphe.
            if line.bbox.x0 > bbox.x0 + tolerance:
                candidate = BBox(bbox.x0, line.bbox.y0, line.bbox.x0, line.bbox.y1)
                if candidate.largeur > 0 and candidate.hauteur > 0:
                    if not any(
                        candidate.x0 == previous.x0
                        and candidate.y0 == previous.y0
                        and candidate.x1 == previous.x1
                        and candidate.y1 == previous.y1
                        for previous in exclusions
                    ):
                        exclusions.append(candidate)
    return TextGeometry(
        kind=geometry_kind(element),
        line_bboxes=tuple(line.bbox for line in lines),
        line_quads=tuple(tuple(getattr(line, "quad", ()) or ()) for line in lines),
        baselines=tuple(tuple(getattr(line, "baseline_points", ()) or ()) for line in lines),
        exclusion_bboxes=tuple(exclusions),
    )
