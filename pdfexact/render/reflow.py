"""Préparation sémantique des éléments avant construction du RenderPlan.

Ce module est volontairement situé avant les backends DOCX. Il transforme les
fragments de texte de l'IR historique en paragraphes candidats, puis délègue les
frontières sémantiques à ``analysis.semantic``. Le renderer XML ne doit donc pas
réinventer un regroupement pendant la matérialisation.
"""
from __future__ import annotations

from dataclasses import fields, replace
from copy import deepcopy
from contextlib import contextmanager
from unicodedata import category

from pdfexact.analysis.options import AnalysisOptions
from pdfexact.analysis.provenance import source_confidence_evidence, text_fusion_errors
from pdfexact.analysis.semantic import (
    detecter_colonnes_textuelles,
    preserver_frontieres_ambigues,
    produire_flow_paragraphs,
    regrouper_frames,
    regrouper_listes,
    regrouper_paragraphes,
    text_of,
)
from pdfexact.analysis.geometry import union_many
from pdfexact.geometry import BBox, pt_vers_emu
from pdfexact.ir import FlowParagraph, Line, Span, TextBox
from pdfexact.analysis.text_geometry import TextBlockPresentation, geometry_contract_for, presentation_for


_TEXT_TYPES = (FlowParagraph, TextBox)


def _lines(element) -> list[Line]:
    lignes = list(getattr(element, "lignes", None) or [])
    if lignes:
        return lignes
    if isinstance(element, FlowParagraph) and element.texte:
        spans = list(element.spans) or [Span(element.texte, element.police, element.size_pt, element.couleur)]
        return [
            Line(
                bbox=element.bbox,
                spans=spans,
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


_SOURCE_TEXT_ATTRIBUTES = frozenset({
    "source_font_name", "source_origin", "source_size_pt", "source_alpha",
})
_LAYOUT_PRESENTATION_KEYS = frozenset({
    "paragraph_validated", "paragraph_id", "semantic_group", "line_count",
    "segmentation_owner", "segmentation_owners", "orientation_source", "page_index",
    "source_visible_line_count", "source_spacing_before_emu", "blank_separator_before",
    "boundary_before", "alignment", "source_spacing", "source_count",
}) | frozenset(field.name for field in fields(TextBlockPresentation))


def _projection_has_extra_paint(item) -> bool:
    if type(item) not in (TextBox, FlowParagraph, Line, Span):
        return True
    known = {field.name for field in fields(item)}
    if set(vars(item)) - known - {"source_page_index", "source_acquisition_index"}:
        return True
    if not isinstance(item.attributes, dict) or set(item.attributes) - _SOURCE_TEXT_ATTRIBUTES:
        return True
    presentation = getattr(item, "presentation", {})
    if not isinstance(presentation, dict) or set(presentation) - _LAYOUT_PRESENTATION_KEYS:
        return True
    return (
        any(getattr(item, name, False) for name in ("souligne", "barre", "surlignage", "curved"))
        or bool(getattr(item, "compositing", {}))
        or bool(getattr(item, "clip_ids", ()))
        or getattr(item, "opacity", 1.0) != 1.0
        or bool(getattr(item, "glyph_ids", ()))
        or getattr(item, "to_unicode_status", None) is not None
        or getattr(item, "angle_deg", 0.0) != 0.0
        or getattr(item, "orientation", "horizontal") != "horizontal"
        or getattr(item, "boundary_before", None) is not None
        or getattr(item, "boundary_after", None) is not None
    )


def render_visible_lines(element) -> list[Line]:
    """Project plain blank rows out of mixed layout, never out of the payload.

    Entirely blank blocks retain their native editable runs. Decorations,
    explicit hard breaks and unknown paint properties retain their rows too.
    This is not a source-equivalence or a non-painting proof.
    """
    lines = _lines(element)
    if not any(span.texte.strip() for line in lines for span in line.spans):
        return lines
    if _projection_has_extra_paint(element):
        return lines

    def plain_blank(line):
        if not line.spans or _projection_has_extra_paint(line):
            return False
        texts = [span.texte for span in line.spans]
        return any(texts) and all(
            not _projection_has_extra_paint(span)
            and all(char == "\t" or category(char) == "Zs" for char in span.texte)
            for span in line.spans
        )

    return [line for line in lines if not plain_blank(line)]


def _line_text(element) -> str:
    return text_of(element).strip()


def _first_span(element) -> Span | None:
    for ligne in _lines(element):
        for span in ligne.spans:
            if span.texte.strip():
                return span
    return None


def _bbox_union(items) -> BBox:
    result = union_many(item.bbox for item in items)
    if result is None:
        raise ValueError("_bbox_union exige au moins un élément")
    return result


def fusionner_flow_paragraphes(elements: list[object]) -> object:
    """Matérialise un groupe sémantique en un paragraphe éditable unique."""
    if not elements:
        raise ValueError("incompatible-text-fusion:empty-text-group")
    if len(elements) == 1:
        return elements[0]
    errors = text_fusion_errors(elements)
    if errors:
        raise ValueError("incompatible-text-fusion:" + ",".join(errors))
    lignes = [ligne for element in elements for ligne in _lines(element)]
    premier = elements[0]
    bbox = _bbox_union(elements)
    layout = {name: getattr(premier, name, None) for name in (
        "layout_frame_id", "layout_frame_bbox", "layout_frame_role", "layout_frame_strategy",
    )}
    frame_ids = {getattr(item, "layout_frame_id", None) for item in [*elements, *lignes]
                 if getattr(item, "layout_frame_id", None)}
    if len(frame_ids) > 1:
        layout.update(layout_frame_id=None, layout_frame_bbox=bbox)
        for name in ("layout_frame_role", "layout_frame_strategy"):
            values = {getattr(element, name, None) for element in elements}
            layout[name] = values.pop() if len(values) == 1 else None
    metadata = {key: deepcopy(value) for element in elements
                for key, value in (getattr(element, "presentation", {}) or {}).items()}
    source_ids = tuple(
        dict.fromkeys(
            source_id
            for element in elements
            for source_id in (
                (getattr(element, "source_id", None), *getattr(element, "source_ids", ()))
            )
            if source_id
        )
    )
    texte = " ".join(_line_text(element) for element in elements if _line_text(element))
    spans = [span for ligne in lignes for span in ligne.spans]
    interligne = max((ligne.hauteur_ligne_emu for ligne in lignes), default=pt_vers_emu(10))
    geometry_source = TextBox(bbox, lignes)
    geometry = geometry_contract_for(geometry_source)
    presentation = presentation_for(geometry_source)
    if isinstance(premier, FlowParagraph):
        result = replace(
            premier,
            bbox=bbox,
            texte=texte,
            spans=spans,
            lignes=lignes,
            interligne_emu=interligne,
            source_ids=source_ids,
            **layout,
            geometry=geometry,
            presentation={
                **metadata,
                "alignment": presentation.alignment,
                "line_spacing_emu": presentation.line_spacing_emu,
                "before_spacing_emu": presentation.before_spacing_emu,
                "after_spacing_emu": presentation.after_spacing_emu,
                "left_indent_emu": presentation.left_indent_emu,
                "right_indent_emu": presentation.right_indent_emu,
                "first_line_indent_emu": presentation.first_line_indent_emu,
                "preserve_line_boundaries": presentation.preserve_line_boundaries,
                "source": presentation.source,
            },
        )
        return _preserve_fusion_metadata(result, elements, metadata)
    first_line = lignes[0]
    first_span = next((span for line in lignes for span in line.spans), None)
    if first_span is None:
        raise ValueError("incompatible-text-fusion:missing-exact-text-spans")
    result = FlowParagraph(
        bbox=bbox,
        texte=texte,
        police=first_span.police,
        size_pt=first_span.size_pt,
        couleur=first_span.couleur,
        alignement=getattr(first_line, "alignement", "left") or "left",
        interligne_emu=interligne,
        spans=spans,
        lignes=lignes,
        **layout,
        vertical_alignement=getattr(premier, "vertical_alignement", "top"),
        source_id=getattr(premier, "source_id", None),
        source_ids=source_ids,
        angle_deg=getattr(premier, "angle_deg", 0.0),
        orientation=getattr(premier, "orientation", "horizontal"),
        baseline_points=getattr(premier, "baseline_points", ()),
        semantic_role=getattr(premier, "semantic_role", None),
        z_index=getattr(premier, "z_index", None),
        curved=getattr(premier, "curved", False),
        geometry=geometry,
        presentation={
            **metadata,
            "alignment": presentation.alignment,
            "line_spacing_emu": presentation.line_spacing_emu,
            "before_spacing_emu": presentation.before_spacing_emu,
            "after_spacing_emu": presentation.after_spacing_emu,
            "left_indent_emu": presentation.left_indent_emu,
            "right_indent_emu": presentation.right_indent_emu,
            "first_line_indent_emu": presentation.first_line_indent_emu,
            "preserve_line_boundaries": presentation.preserve_line_boundaries,
            "source": presentation.source,
        },
    )
    return _preserve_fusion_metadata(result, elements, metadata)


def _preserve_fusion_metadata(result, elements, presentation):
    computed = {
        "bbox", "texte", "lignes", "spans", "interligne_emu", "source_ids", "geometry",
        "presentation", "layout_frame_id", "layout_frame_bbox", "layout_frame_role", "layout_frame_strategy",
        "quad", "polygon", "baseline_points", "baseline",
    }
    for name, value in vars(elements[0]).items():
        if name not in computed:
            setattr(result, name, deepcopy(value))
    for name in ("quad", "polygon", "baseline_points", "baseline"):
        if hasattr(result, name):
            setattr(result, name, ())
    for name in ("evidence", "decision_history", "duplicate_candidates", "grouping_evidence"):
        values = [deepcopy(value) for element in elements for value in getattr(element, name, ())]
        if values or hasattr(result, name):
            setattr(result, name, values)
    confidences = [element.confidence for element in elements]
    result.confidence = confidences[0] if all(value == confidences[0] for value in confidences) else None
    # Keep source values even for equal aggregates that may be fused again.
    result.evidence.extend(entry for element in elements
                           if (entry := source_confidence_evidence(element)) is not None)
    result.attributes = {key: deepcopy(value) for element in elements for key, value in element.attributes.items()}
    result.presentation.update(presentation)
    if hasattr(result, "source_line_ids"):
        result.source_line_ids = tuple(dict.fromkeys(
            ident for element in elements for ident in getattr(element, "source_line_ids", ())
        ))
    return result


def _compatible_groups(group):
    """Partition every proposal at the first contract that cannot be retained."""
    current = []
    for item in group:
        if current and text_fusion_errors([*current, item]):
            yield current
            current = []
        current.append(item)
    if current:
        yield current


@contextmanager
def _source_metadata_during_analysis(elements):
    # Grouping may infer script/language on its inputs. Keep those annotations
    # local to the proposal, rather than overwriting acquired parent data.
    saved = [(item, item.script, item.language, deepcopy(item.attributes))
             for item in elements if isinstance(item, _TEXT_TYPES)]
    try:
        yield
    finally:
        for item, script, language, attributes in saved:
            item.script, item.language, item.attributes = script, language, attributes


def _apply_semantic_groups(elements: list[object], groups: list[list[object]]) -> list[object]:
    positions = {id(element): index for index, element in enumerate(elements)}
    replacements: dict[int, object] = {}
    suppressed: set[int] = set()
    consumed: set[int] = set()
    for group in groups:
        candidates = {positions[id(item)]: item for item in group
                      if isinstance(item, _TEXT_TYPES) and id(item) in positions
                      and positions[id(item)] not in consumed}
        text_items = [candidates[index] for index in sorted(candidates)]
        for compatible in _compatible_groups(text_items):
            if len(compatible) < 2:
                continue
            indices = [positions[id(item)] for item in compatible]
            first = indices[0]
            replacements[first] = fusionner_flow_paragraphes(compatible)
            suppressed.update(index for index in indices if index != first)
            consumed.update(indices)
    return [
        replacements.get(index, element)
        for index, element in enumerate(elements)
        if index not in suppressed
    ]


def _regrouper_continuations_par_frame(elements: list[object], options: AnalysisOptions) -> list[object]:
    with _source_metadata_during_analysis(elements):
        groups = regrouper_frames(elements, options)
    return _apply_semantic_groups(elements, groups)


def _regrouper_continuations_par_colonne(elements: list[object], options: AnalysisOptions) -> list[object]:
    groups = []
    with _source_metadata_during_analysis(elements):
        for column in detecter_colonnes_textuelles(elements, options):
            groups.extend(regrouper_paragraphes(column, options))
    return _apply_semantic_groups(elements, groups)


def regrouper_continuations_par_frame(
    elements: list[object], options: AnalysisOptions | None = None
) -> list[object]:
    return _regrouper_continuations_par_frame(elements, options or AnalysisOptions())


def regrouper_continuations_par_colonne(
    elements: list[object], options: AnalysisOptions | None = None
) -> list[object]:
    return _regrouper_continuations_par_colonne(elements, options or AnalysisOptions())


def prepare_page_elements(elements: list[object], options: AnalysisOptions | None = None) -> list[object]:
    """Prépare exactement la liste qui sera indexée par le RenderPlan."""
    options = options or AnalysisOptions()
    with _source_metadata_during_analysis(elements):
        groups = regrouper_paragraphes(elements, options)
        groups = preserver_frontieres_ambigues(groups, options)
    groups = [part for group in groups for part in _compatible_groups(group)]
    result = produire_flow_paragraphs(groups, fusionner=fusionner_flow_paragraphes)
    result = _regrouper_continuations_par_colonne(result, options)
    result = _regrouper_continuations_par_frame(result, options)
    return regrouper_listes(result, options)


def prepare_document_elements(document, options: AnalysisOptions | None = None) -> dict[int, list[object]]:
    """Prepare des pages isolees sans modifier ni partager les noeuds source."""
    options = options or AnalysisOptions()
    from pdfexact.analysis.text_segmentation import segmenter_page_textes

    result = {}
    for page in getattr(document, "pages", ()):
        candidate = deepcopy(page)
        text = [item for item in candidate.elements if isinstance(item, _TEXT_TYPES) and item.lignes]
        if any(len(item.lignes) > 1 and not item.presentation.get("paragraph_validated") for item in text):
            # Keep validated neighbours on the page as segmentation barriers.
            segmenter_page_textes(candidate)
        result[page.index] = prepare_page_elements(candidate.elements, options)
    return result
