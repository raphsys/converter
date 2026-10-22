"""Universal semantic grouping independent of the renderer.

This module accepts canonical scene records and legacy IR objects by duck typing.
It does not import Word, XML, or a document writer.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from statistics import median
from typing import Sequence

from pdfexact.analysis.geometry import axis_overlap_ratio, gap, union_many
from pdfexact.analysis.options import AnalysisOptions
from pdfexact.scene import ElementRecord
from pdfexact.layout.text_comprehension import (
    ambiguous_short_labels,
    contexte_lignes_texte,
    hard_line_break,
    unicode_text_units,
)




_LIST_MARKER_RE = re.compile(
    r"^\s*(?:[-*+\u2022\u25aa\u25ab\u25e6\u2023\u25a0\u25cf\u25cb\u25c9]|\d+[.)]|[^\W\d_][.)]|[ivxlcdmIVXLCDM]+[.)])(?:\s+|$)"
)
_CJK_MARKER_RE = re.compile(r"^\s*(?:[一二三四五六七八九十百]+[、.)）]|[（(][一二三四五六七八九十百\d]+[）)])")
_NUMBERED_MARKER_RE = re.compile(r"^\s*\d+[.)](?:\s+|$)")
_ALPHA_MARKER_RE = re.compile(r"^\s*[^\W\d_][.)](?:\s+|$)")
_ROMAN_MARKER_RE = re.compile(r"^\s*[ivxlcdmIVXLCDM]+[.)](?:\s+|$)")
_BULLET_CHARS = {"•", "▪", "▫", "◦", "‣", "■", "●", "○", "◉", "*", "o", "O"}
_DASH_CHARS = {"-", "–", "—", "−"}
_GEOMETRIC_ROLES = {"caption", "credit", "label", "diagram_text", "annotation", "watermark", "figure_text"}
_TITLE_ROLES = {"title", "subtitle", "heading", "header"}


@dataclass(frozen=True)
class ContinuityFeatures:
    horizontal_gap: int
    vertical_gap: int
    same_role: bool
    same_script: bool
    compatible_style: bool
    starts_list: bool
    ends_sentence: bool
    confidence: float
    same_frame: bool = False
    same_column: bool = False
    same_orientation: bool = True
    horizontal_overlap: float = 0.0
    line_gap_ratio: float = 0.0
    indent_delta: int = 0
    boundary_reason: str | None = None
    previous_script: str = "unknown"
    current_script: str = "unknown"


def _text_value(element) -> str:
    if isinstance(element, ElementRecord):
        return str(element.text or "")
    text = getattr(element, "texte", None)
    if text is not None:
        return str(text or "")
    direct_spans = getattr(element, "spans", None)
    if direct_spans is not None:
        return "".join(str(getattr(span, "texte", "") or "") for span in direct_spans)
    parts = []
    for line in getattr(element, "lignes", None) or []:
        parts.append("".join(str(getattr(span, "texte", "") or "") for span in getattr(line, "spans", []) or []))
    return " ".join(parts)


def text_of(element) -> str:
    return " ".join(_text_value(element).replace("\u00ad", "").split())


def _bbox_of(element):
    return getattr(element, "bbox", None)


def _role_of(element) -> str:
    role = getattr(element, "role", None) or getattr(element, "semantic_role", None)
    role = role or getattr(element, "layout_frame_role", None)
    if not role:
        for line in getattr(element, "lignes", None) or []:
            role = getattr(line, "semantic_role", None) or getattr(line, "layout_frame_role", None)
            if role:
                break
    return str(role or "unknown").casefold()


def _container_role_of(element) -> str:
    role = getattr(element, "layout_frame_role", None)
    if role:
        return str(role).casefold()
    for line in getattr(element, "lignes", None) or []:
        role = getattr(line, "layout_frame_role", None)
        if role:
            return str(role).casefold()
    return _role_of(element)


def _orientation_of(element) -> str:
    value = str(getattr(element, "orientation", "horizontal") or "horizontal").casefold()
    if value == "horizontal":
        for line in getattr(element, "lignes", None) or []:
            candidate = str(getattr(line, "orientation", "horizontal") or "horizontal").casefold()
            if candidate != "horizontal":
                return candidate
    return value


def _frame_of(element) -> str | None:
    value = getattr(element, "layout_frame_id", None)
    return str(value) if value else None


def _style_key_of(element):
    explicit = getattr(element, "style", None)
    if explicit is not None:
        return repr(explicit)
    attributes = getattr(element, "attributes", None) or {}
    if attributes.get("style_key") is not None:
        return attributes["style_key"]
    spans = getattr(element, "spans", None) or [
        span
        for line in getattr(element, "lignes", None) or []
        for span in getattr(line, "spans", None) or []
    ]
    weights = Counter()
    for span in spans:
        text = str(getattr(span, "texte", "") or "")
        if not text.strip():
            continue
        font = getattr(span, "police", None)
        weights[(
            getattr(font, "famille", None),
            bool(getattr(font, "gras", False)),
            bool(getattr(font, "italique", False)),
            round(float(getattr(span, "size_pt", 0.0) or 0.0), 1),
            getattr(span, "couleur", None),
        )] += len(text.strip())
    return weights.most_common(1)[0][0] if weights else None


def styles_compatibles(left, right) -> bool:
    """Compare les attributs de style utiles au regroupement."""
    first = _style_key_of(left)
    second = _style_key_of(right)
    if first is None or second is None or first == second:
        return True
    # Wrapped emphasis is compatible with prose; a font/size/color change is not.
    if isinstance(first, tuple) and isinstance(second, tuple) and len(first) == len(second) == 5:
        emphasis_only = (first[0], first[3:]) == (second[0], second[3:])
        initial = _first_alpha(text_of(right))
        return (
            emphasis_only
            and _role_of(left) not in _TITLE_ROLES
            and _role_of(right) not in _TITLE_ROLES
            and not ends_sentence(text_of(left))
            and bool(initial)
            and (initial.islower() or initial.lower() == initial.upper())
        )
    return False


def _first_alpha(text: str) -> str:
    return next((char for char in text if char.isalpha()), "")


def _infer_script(text: str) -> str:
    counts: dict[str, int] = {}
    for char in text:
        if not char.isalpha():
            continue
        name = unicodedata.name(char, "")
        if "LATIN" in name:
            script = "latin"
        elif "CYRILLIC" in name:
            script = "cyrillic"
        elif "ARABIC" in name:
            script = "arabic"
        elif "HEBREW" in name:
            script = "hebrew"
        elif "GREEK" in name:
            script = "greek"
        elif "DEVANAGARI" in name:
            script = "devanagari"
        elif "HANGUL" in name:
            script = "hangul"
        elif "CJK" in name or "IDEOGRAPH" in name or "HIRAGANA" in name or "KATAKANA" in name:
            script = "cjk"
        elif "THAI" in name:
            script = "thai"
        else:
            script = "other"
        counts[script] = counts.get(script, 0) + 1
    if not counts:
        return "unknown"
    ordered = sorted(counts.items(), key=lambda pair: pair[1], reverse=True)
    if len(ordered) > 1 and ordered[1][1] >= max(1, ordered[0][1] // 2):
        return "mixed"
    return ordered[0][0]


def normaliser_script_et_langue(element):
    """Infer and attach script/language without overwriting explicit values."""
    script = str(getattr(element, "script", "") or "").casefold()
    if not script or script == "auto":
        script = _infer_script(text_of(element))
        try:
            setattr(element, "script", script)
        except (AttributeError, TypeError):
            pass
    language = getattr(element, "language", None) or getattr(element, "langue", None) or "auto"
    try:
        setattr(element, "language", language)
    except (AttributeError, TypeError):
        pass
    attributes = getattr(element, "attributes", None)
    if isinstance(attributes, dict):
        attributes.setdefault("script", script)
        attributes.setdefault("language", language)
    return element


def starts_list_marker(text: str) -> str | None:
    value = " ".join(str(text or "").replace("\ufeff", "").split())
    match = (_LIST_MARKER_RE.match(value) or _CJK_MARKER_RE.match(value)) if value else None
    return value[: match.end()].strip() if match else None


def detecter_marqueur_liste(element) -> str | None:
    text = text_of(element).strip()
    if not text:
        return None
    span = next(
        (
            span
            for line in getattr(element, "lignes", None) or []
            for span in getattr(line, "spans", None) or []
            if str(getattr(span, "texte", "") or "").strip()
        ),
        None,
    )
    font_id = str(getattr(getattr(span, "police", None), "font_id", "") or "").casefold()
    if len(text) <= 2 and any(ord(char) >= 0xE000 for char in text):
        return "bullet" if "wingdings" in font_id or "symbol" in font_id else None
    if text in _BULLET_CHARS:
        return "bullet"
    if text in _DASH_CHARS:
        return "dash"
    if _NUMBERED_MARKER_RE.fullmatch(text + " "):
        return "decimal"
    if _ALPHA_MARKER_RE.fullmatch(text + " "):
        return "alpha"
    if _ROMAN_MARKER_RE.fullmatch(text + " "):
        return "roman"
    marker = starts_list_marker(text)
    if marker:
        if _NUMBERED_MARKER_RE.fullmatch(marker + " "):
            return "decimal"
        if _ALPHA_MARKER_RE.fullmatch(marker + " "):
            return "alpha"
        if _ROMAN_MARKER_RE.fullmatch(marker + " "):
            return "roman"
        return "dash" if marker in _DASH_CHARS else "bullet"
    return None


def est_texte_de_corps(text: str) -> bool:
    """Signal de texte courant utilise pour proteger les regroupements ambigus."""
    words = unicode_text_units(str(text or ""))
    if len(words) < 4:
        return False
    letters = [char for char in str(text or "") if char.isalpha()]
    if not letters or len(letters) / max(len(str(text)), 1) < 0.45:
        return False
    tokens = re.findall(r"\b[A-Z]\d+|\b\d+[A-Z]\b|[A-Z]-\d+|\d+-\d+", str(text or ""))
    return len(tokens) < max(2, len(words) // 3)


def ends_sentence(text: str) -> bool:
    return text.rstrip().endswith((".", "!", "?", ":", ";", "»", '"', "\u201d", "。", "！", "？", "：", "；", "」", "』"))


def commence_par_minuscule(text: str) -> bool:
    """Signal lexical neutre pour les adaptateurs historiques."""
    return next((char for char in str(text or "") if char.isalpha()), "").islower()


def _line_height(element) -> int:
    bbox = _bbox_of(element)
    values = [
        getattr(line, "hauteur_ligne_emu", 0) or getattr(line.bbox, "hauteur", 0)
        for line in getattr(element, "lignes", None) or []
        if any(str(span.texte).strip() for span in getattr(line, "spans", ()))
    ]
    if values:
        return max(int(median(values)), 1)
    return max(getattr(element, "interligne_emu", 0) or getattr(bbox, "hauteur", 0), 1)


def _paragraph_id(element):
    saved = getattr(element, "presentation", None) or getattr(element, "attributes", None) or {}
    return saved.get("paragraph_id") if saved.get("paragraph_validated") else None


def _option(options: AnalysisOptions | None, name: str, default):
    if options is None:
        return default
    if name in options.extra:
        return options.extra[name]
    value = getattr(options, name, None)
    return value if value is not None else default


def calculer_features_continuite(previous, current, options: AnalysisOptions | None = None) -> ContinuityFeatures:
    """Calculate continuity signals before taking a merge decision."""
    previous_bbox = _bbox_of(previous)
    current_bbox = _bbox_of(current)
    if previous_bbox is None or current_bbox is None:
        return ContinuityFeatures(0, 0, False, False, False, False, False, 0.0, boundary_reason="missing-bbox")
    horizontal_gap, vertical_gap = gap(previous_bbox, current_bbox)
    previous_role = _role_of(previous)
    current_role = _role_of(current)
    previous_container = _container_role_of(previous)
    current_container = _container_role_of(current)
    same_frame = bool(_frame_of(previous) and _frame_of(previous) == _frame_of(current))
    same_role = previous_role == current_role or (
        same_frame and previous_container == current_container and previous_container not in _GEOMETRIC_ROLES
    )
    previous_script = str(getattr(previous, "script", "unknown") or "unknown").casefold()
    current_script = str(getattr(current, "script", "unknown") or "unknown").casefold()
    if previous_script in {"unknown", "auto"}:
        previous_script = _infer_script(text_of(previous))
    if current_script in {"unknown", "auto"}:
        current_script = _infer_script(text_of(current))
    same_script = previous_script == current_script or "unknown" in {previous_script, current_script}
    same_style = styles_compatibles(previous, current)
    same_orientation = _orientation_of(previous) == _orientation_of(current) == "horizontal"
    overlap_x = axis_overlap_ratio(previous_bbox, current_bbox, "x")
    height = max(_line_height(previous), _line_height(current), 1)
    line_gap_ratio = (current_bbox.y0 - previous_bbox.y1) / height
    marker = detecter_marqueur_liste(current)
    confidence = 1.0
    reason = None
    if not same_role:
        confidence -= 0.35
        reason = "role-change"
    if not same_style:
        confidence -= 0.20
        reason = reason or "style-change"
    if not same_script:
        confidence -= 0.20
        reason = reason or "script-change"
    if not same_orientation:
        confidence -= 0.60
        reason = reason or "orientation-change"
    if line_gap_ratio > float(_option(options, "semantic_vertical_gap_factor", 1.8)):
        confidence -= 0.25
        reason = reason or "vertical-gap"
    if marker:
        confidence -= 0.45
        reason = "list-marker"
    if ends_sentence(text_of(previous)):
        confidence -= 0.20
        reason = reason or "sentence-end"
    return ContinuityFeatures(
        horizontal_gap=horizontal_gap,
        vertical_gap=vertical_gap,
        same_role=same_role,
        same_script=same_script,
        compatible_style=same_style,
        starts_list=marker is not None,
        ends_sentence=ends_sentence(text_of(previous)),
        confidence=max(0.0, min(1.0, confidence)),
        same_frame=same_frame,
        same_column=overlap_x >= float(_option(options, "semantic_column_overlap_min", 0.35)),
        same_orientation=same_orientation,
        horizontal_overlap=overlap_x,
        line_gap_ratio=line_gap_ratio,
        indent_delta=abs(current_bbox.x0 - previous_bbox.x0),
        boundary_reason=reason,
        previous_script=previous_script,
        current_script=current_script,
    )


def _obstacle_between(previous, current, obstacles) -> bool:
    first, second = _bbox_of(previous), _bbox_of(current)
    if first is None or second is None:
        return True
    from pdfexact.geometry import BBox

    same_row = axis_overlap_ratio(first, second, "y") >= 0.55
    left, right = sorted((first, second), key=lambda bbox: bbox.x0)
    corridor = (
        (left.x1, max(left.y0, right.y0), right.x0, min(left.y1, right.y1)) if same_row
        else (max(first.x0, second.x0), first.y1, min(first.x1, second.x1), second.y0)
    )
    for obstacle in obstacles:
        bbox = getattr(obstacle, "bbox", obstacle)
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            bbox = BBox(*bbox)
        if bbox is None:
            continue
        if all(bbox.x0 <= item.x0 and item.x1 <= bbox.x1
               and bbox.y0 <= item.y0 and item.y1 <= bbox.y1 for item in (first, second)):
            continue
        if (min(corridor[2], bbox.x1) > max(corridor[0], bbox.x0)
                and min(corridor[3], bbox.y1) > max(corridor[1], bbox.y0)):
            return True
    return False


def frontiere_de_paragraphe_source(
    previous, current, options: AnalysisOptions | None = None, *, obstacles=(),
) -> bool:
    """Check source boundaries without consulting a provider or mutating observations."""
    if _option(options, "preserve_line_boundaries", "auto") == "always":
        return True
    if previous is None or current is None or not text_of(previous) or not text_of(current):
        return True
    if _obstacle_between(previous, current, obstacles):
        return True
    if _orientation_of(previous) != "horizontal" or _orientation_of(current) != "horizontal":
        return True
    if getattr(previous, "curved", False) or getattr(current, "curved", False):
        return True
    if getattr(previous, "angle_deg", 0) != getattr(current, "angle_deg", 0):
        return True
    previous_saved = getattr(previous, "presentation", None) or getattr(previous, "attributes", None) or {}
    current_saved = getattr(current, "presentation", None) or getattr(current, "attributes", None) or {}
    previous_line = (getattr(previous, "lignes", None) or (previous,))[-1]
    current_line = (getattr(current, "lignes", None) or (current,))[0]
    if hard_line_break(_text_value(previous_line), _text_value(current_line)):
        return True
    known_obstacles = [*(previous_saved.get("obstacles") or ()), *(current_saved.get("obstacles") or ())]
    if known_obstacles and _obstacle_between(previous, current, known_obstacles):
        return True
    if (getattr(previous_line, "boundary_after", None) or getattr(current_line, "boundary_before", None)
            or previous_saved.get("boundary_after") or current_saved.get("boundary_before")
            or current_saved.get("blank_separator_before")):
        return True
    previous_id, current_id = _paragraph_id(previous), _paragraph_id(current)
    if (previous_id or current_id) and previous_id != current_id:
        return True
    features = calculer_features_continuite(previous, current, options)
    if features.confidence < float(_option(options, "semantic_group_min_confidence", 0.72)):
        return True
    # A model decision must not erase already established geometric boundaries.
    if features.starts_list or not features.same_script or not features.same_orientation:
        return True
    if features.line_gap_ratio > float(_option(options, "semantic_vertical_gap_factor", 1.8)):
        return True
    if features.horizontal_overlap < float(_option(options, "semantic_column_overlap_min", 0.35)):
        return True
    if _role_of(previous) == "label" or _role_of(current) == "label":
        return True
    if not bool(_option(options, "semantic_ignore_frame_id", False)):
        previous_frame = _frame_of(previous)
        current_frame = _frame_of(current)
        if previous_frame and current_frame and previous_frame != current_frame:
            cross_frame_continuation = (
                features.compatible_style
                and not features.ends_sentence
                and commence_par_minuscule(text_of(current))
                and features.line_gap_ratio <= float(_option(options, "semantic_cross_frame_gap_factor", 1.75))
            )
            if not cross_frame_continuation:
                return True
    if features.starts_list or not features.same_script or not features.compatible_style:
        return True
    if getattr(previous_line, "alignement", None) != getattr(current_line, "alignement", None):
        return True
    previous_role = _role_of(previous)
    current_role = _role_of(current)
    if previous_role in _TITLE_ROLES or current_role in _TITLE_ROLES:
        return previous_role != current_role
    if not features.same_role and not features.same_frame:
        return True
    role_boundary = not features.same_role
    if features.same_frame and _container_role_of(previous) == _container_role_of(current):
        role_boundary = False
    if role_boundary:
        return True
    if features.line_gap_ratio < -float(_option(options, "semantic_overlap_gap_factor", 0.35)):
        return True
    if features.line_gap_ratio > float(_option(options, "semantic_vertical_gap_factor", 1.8)):
        return True
    if features.horizontal_overlap < float(_option(options, "semantic_column_overlap_min", 0.35)) and not features.same_frame:
        return True
    height = max(_line_height(previous), _line_height(current), 1)
    if (_bbox_of(current).x0 - _bbox_of(previous).x0 > height * 0.6
            and features.ends_sentence):
        return True
    if text_of(previous).rstrip().endswith("-"):
        return False
    first = _first_alpha(text_of(current))
    if features.ends_sentence and first.isupper() and features.line_gap_ratio > float(_option(options, "semantic_sentence_gap_factor", 0.55)):
        return True
    if text_of(current).lstrip().startswith((")", "]", "}")):
        return True
    return False


def est_frontiere_de_paragraphe(previous, current, options: AnalysisOptions | None = None) -> bool:
    """Allow model advice only after every independent source boundary passes."""
    if frontiere_de_paragraphe_source(previous, current, options):
        return True
    if (ambiguous_short_labels((text_of(previous), text_of(current)))
            and not (_role_of(previous) == _role_of(current) == "body")):
        return True
    if _option(options, "semantic_ai", True) is False:
        # Geometric pre-grouping: paragraphs are decided later, once per zone.
        return False
    from pdfexact.layout.text_comprehension import comprendre_groupe_lignes

    context = contexte_lignes_texte((previous, current))
    decision = comprendre_groupe_lignes(
        tuple(row["text"] for row in context["lines"]),
        frame_role=_container_role_of(previous),
        frame_strategy=getattr(previous, "layout_frame_strategy", None),
        metadonnees=context,
    )
    return bool(decision.ai_used and not decision.fallback_used
                and decision.action in {"preserve-line", "preserve-lines"})


def est_continuation_de_ligne(previous, current, options: AnalysisOptions | None = None) -> bool:
    return not est_frontiere_de_paragraphe(previous, current, options)






def _is_textual(element) -> bool:
    return bool(_bbox_of(element) is not None and (_text_value(element).strip() or getattr(element, "lignes", None)))


def regrouper_paragraphes(elements: Sequence[object], options: AnalysisOptions | None = None) -> list[list[object]]:
    """Build source groups and keep non-text intercalaries visible."""
    options = options or AnalysisOptions()
    ordered = list(elements)
    obstacles = [item for item in ordered if not _is_textual(item) and _bbox_of(item) is not None]
    groups: list[list[object]] = []
    current: list[object] = []
    pending: list[object] = []
    last_text = None
    for element in ordered:
        if not _is_textual(element):
            if current:
                pending.append(element)
            else:
                groups.append([element])
            continue
        can_join = bool(last_text is not None
                        and not _obstacle_between(last_text, element, obstacles)
                        and est_continuation_de_ligne(last_text, element, options))
        if pending:
            can_join = can_join and bool(_frame_of(last_text) and _frame_of(last_text) == _frame_of(element))
        if can_join:
            current.extend(pending)
            pending = []
            current.append(element)
        else:
            if current:
                groups.append(current)
                groups.extend([[item] for item in pending])
            elif pending:
                groups.extend([[item] for item in pending])
            current = [element]
            pending = []
        last_text = element
    if current:
        groups.append(current)
        groups.extend([[item] for item in pending])
    elif pending:
        groups.extend([[item] for item in pending])
    return groups


def _replace_list_metadata(element, marker, marker_kind):
    from copy import deepcopy

    element = deepcopy(element)
    try:
        source_ids = tuple(dict.fromkeys(
            source_id for item in (element, marker)
            for source_id in (*getattr(item, "source_ids", ()), getattr(item, "source_id", None)) if source_id
        ))
        setattr(element, "source_ids", source_ids)
        setattr(element, "replaces", tuple(dict.fromkeys((*getattr(element, "replaces", ()), *source_ids))))
        setattr(element, "transformation", "list-marker-attachment")
        setattr(element, "list_marker_source", deepcopy(marker))
        setattr(element, "list_marker", marker_kind)
        setattr(element, "list_marker_bbox", getattr(marker, "bbox", None))
        bbox = _bbox_of(element)
        setattr(element, "list_group_id", _frame_of(element) or f"{_container_role_of(element)}:{getattr(bbox, 'x0', 0)}")
        marker_bbox = getattr(marker, "bbox", None)
        if bbox is not None and marker_bbox is not None:
            merged = union_many((bbox, marker_bbox))
            if merged is not None:
                setattr(element, "bbox", merged)
    except (AttributeError, TypeError):
        pass
    return element


def regrouper_listes(elements: Sequence[object], options: AnalysisOptions | None = None) -> list[object]:
    """Attach isolated markers using symbol, indentation, frame and alignment."""
    values = list(elements)
    markers = [
        (index, element, detecter_marqueur_liste(element))
        for index, element in enumerate(values)
        if _is_textual(element) and detecter_marqueur_liste(element)
    ]
    if not markers:
        return values
    removed: set[int] = set()
    associated: dict[int, tuple[object, str]] = {}
    for marker_index, marker, kind in markers:
        marker_bbox = _bbox_of(marker)
        if marker_bbox is None:
            continue
        candidates = []
        for body_index, body in enumerate(values):
            if body_index == marker_index or body_index in removed or not _is_textual(body):
                continue
            if detecter_marqueur_liste(body) or _orientation_of(body) != "horizontal" or getattr(body, "curved", False):
                continue
            body_bbox = _bbox_of(body)
            if body_bbox is None or body_bbox.x0 < marker_bbox.x0:
                continue
            gap_x = body_bbox.x0 - marker_bbox.x1
            gap_y = abs(body_bbox.y0 - marker_bbox.y0)
            tolerance_y = max(marker_bbox.hauteur, body_bbox.hauteur, 1) * float(_option(options, "semantic_list_y_factor", 1.6))
            if gap_x < 0 or gap_x > _option(options, "semantic_list_x_gap_emu", 30 * 12700) or gap_y > tolerance_y:
                continue
            marker_frame = _frame_of(marker)
            body_frame = _frame_of(body)
            if marker_frame and body_frame and marker_frame != body_frame:
                continue
            candidates.append((0 if marker_frame and marker_frame == body_frame else 1, gap_y, gap_x, body_index, body))
        if not candidates:
            continue
        _score, _gy, _gx, body_index, body = min(candidates, key=lambda item: item[:4])
        associated[body_index] = (marker, str(kind))
        removed.add(marker_index)
    result = []
    for index, element in enumerate(values):
        if index not in removed:
            association = associated.get(index)
            result.append(_replace_list_metadata(element, *association) if association else element)
    return result


def detecter_colonnes_textuelles(elements: Sequence[object], options: AnalysisOptions | None = None) -> list[list[object]]:
    """Group text by x bands while respecting role and frame compatibility."""
    options = options or AnalysisOptions()
    columns: list[list[object]] = []
    textual = sorted(
        (item for item in elements if _is_textual(item)),
        key=lambda item: (getattr(_bbox_of(item), "x0", 0), getattr(_bbox_of(item), "y0", 0)),
    )
    for element in textual:
        bbox = _bbox_of(element)
        best_index = None
        best_score = 0.0
        for index, column in enumerate(columns):
            column_box = union_many(_bbox_of(item) for item in column if _bbox_of(item) is not None)
            if column_box is None:
                continue
            score = axis_overlap_ratio(column_box, bbox, "x")
            compatible = _container_role_of(column[0]) == _container_role_of(element) or _frame_of(column[0]) == _frame_of(element)
            if compatible and score > best_score:
                best_index, best_score = index, score
        if best_index is None or best_score < float(_option(options, "semantic_column_overlap_min", 0.35)):
            columns.append([element])
        else:
            columns[best_index].append(element)
    return [
        sorted(column, key=lambda item: (getattr(_bbox_of(item), "y0", 0), getattr(_bbox_of(item), "x0", 0)))
        for column in sorted(columns, key=lambda column: getattr(_bbox_of(column[0]), "x0", 0))
    ]


def regrouper_frames(elements: Sequence[object], options: AnalysisOptions | None = None) -> list[list[object]]:
    options = options or AnalysisOptions()
    obstacles = [item for item in elements if not _is_textual(item) and _bbox_of(item) is not None]
    frames: dict[str, list[object]] = {}
    for element in elements:
        frame = _frame_of(element)
        if frame and _is_textual(element) and _orientation_of(element) == "horizontal" and not getattr(element, "curved", False):
            frames.setdefault(frame, []).append(element)
    groups: list[list[object]] = []
    for values in frames.values():
        ordered = sorted(values, key=lambda item: (getattr(_bbox_of(item), "y0", 0), getattr(_bbox_of(item), "x0", 0)))
        # Frames are layout regions, not paragraph identities. Reuse the same
        # boundary decision as the first pass instead of bypassing it here.
        current: list[object] = []
        previous = None
        for item in ordered:
            compatible = (
                previous is not None
                and _orientation_of(previous) == _orientation_of(item) == "horizontal"
                and not getattr(previous, "curved", False)
                and not getattr(item, "curved", False)
                and not detecter_marqueur_liste(item)
                and not detecter_marqueur_liste(previous)
                and styles_compatibles(previous, item)
                and not _obstacle_between(previous, item, obstacles)
                and not est_frontiere_de_paragraphe(previous, item, options)
            )
            if current and not compatible:
                groups.append(current)
                current = []
            current.append(item)
            previous = item
        if current:
            groups.append(current)
    return [group for group in groups if any(_is_textual(item) for item in group)]


def preserver_frontieres_ambigues(groups: Sequence[Sequence[object]], options: AnalysisOptions | None = None) -> list[list[object]]:
    options = options or AnalysisOptions()
    result: list[list[object]] = []
    for group in groups:
        obstacles = [item for item in group if not _is_textual(item) and _bbox_of(item) is not None]
        current: list[object] = []
        previous = None
        for item in group:
            if not _is_textual(item):
                current.append(item)
                continue
            if previous is not None and frontiere_de_paragraphe_source(previous, item, options, obstacles=obstacles):
                if current:
                    result.append(current)
                current = []
            current.append(item)
            previous = item
        if current:
            result.append(current)
    return result


def produire_flow_paragraphs(groups: Sequence[Sequence[object]], fusionner=None) -> list[object]:
    """Materialize groups through a factory supplied by the renderer."""
    result: list[object] = []
    for group in groups:
        text_items = [item for item in group if _is_textual(item)]
        others = [item for item in group if not _is_textual(item)]
        if fusionner is not None and len(text_items) > 1:
            result.append(fusionner(text_items))
        else:
            result.extend(text_items)
        result.extend(others)
    return result


def valider_groupe_semantique(group: Sequence[object], options: AnalysisOptions | None = None) -> list[str]:
    options = options or AnalysisOptions()
    textual = [item for item in group if _is_textual(item)]
    if not textual:
        return ["empty-text-group"]
    errors = []
    for previous, current in zip(textual, textual[1:]):
        features = calculer_features_continuite(previous, current, options)
        if est_frontiere_de_paragraphe(previous, current, options):
            errors.append(features.boundary_reason or "paragraph-boundary")
    if any(detecter_marqueur_liste(item) for item in textual):
        errors.append("contains-list-marker")
    return list(dict.fromkeys(errors))




        # Recognition and semantic confidence measure different things. Merely
        # observing text or a FlowParagraph must not manufacture either score.


# ASCII alias for callers that cannot encode accents.
preserver_frontieres_ambiguës = preserver_frontieres_ambigues
