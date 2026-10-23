"""Decision de regroupement textuel basee sur le role de layout et le contenu."""

from __future__ import annotations

import logging
import math
import re
import unicodedata
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Iterator


@dataclass(frozen=True)
class TextUnderstandingDecision:
    """Decision appliquee aux lignes natives avant rendu Word."""

    kind: str
    action: str
    confidence: float
    evidence: tuple[str, ...] = ()
    line_joins: tuple[str, ...] = ()
    ai_used: bool = False
    fallback_used: bool = True
    line_groups: tuple[tuple[int, ...], ...] = ()


TextUnderstandingMetadata = dict[str, Any] | list[dict[str, Any]]
TextUnderstandingContext = str | TextUnderstandingMetadata | None
TextUnderstandingProvider = Callable[
    [str, tuple[str, ...], str | None, TextUnderstandingContext],
    TextUnderstandingDecision | None,
]

_WORD_RE = re.compile(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*", re.UNICODE)
_CODE_RE = re.compile(r"\b[A-Z]{1,4}[-–]?\d+[A-Z]?\b|\b\d+[A-Z]\b|\b[A-Z]\d+[-–][A-Z]?\d+\b")
_BULLET_RE = re.compile(r"^\s*(?:[\-\u2022*]|\(?[0-9A-Za-z]{1,3}[.)])\s+")
_CAPTION_RE = re.compile(r"^\s*(?:fig(?:ure)?|table|tab\.?|below|above|source|note)\b", re.I)
_NUMERIC_RECORD_RE = re.compile(
    r"^(?P<label>.*?\S)(?P<separator>\s*[:=]\s*|[ \t]+)"
    r"(?:[$\u00a3\u20ac]\s*)?[+-]?\d(?:[\d., \u00a0]*\d)?%?$"
)
_LOGGER = logging.getLogger(__name__)


@dataclass
class _AnalysisState:
    provider: TextUnderstandingProvider | None = None
    warning_keys: set[tuple[str, str]] = field(default_factory=set)
    events: list[dict] = field(default_factory=list)
    acceptance_reported: bool = False


_ANALYSE: ContextVar[_AnalysisState | None] = ContextVar("text_understanding_analysis", default=None)


def _etat_analyse() -> _AnalysisState:
    state = _ANALYSE.get()
    if state is None:
        # Import only on first use: the HTTP provider imports these contracts.
        from pdfexact.layout.text_comprehension_ai import creer_fournisseur_comprehension_texte_ai

        state = _AnalysisState(creer_fournisseur_comprehension_texte_ai())
        _ANALYSE.set(state)
    return state


def configurer_fournisseur_comprehension_texte(
    provider: TextUnderstandingProvider | None,
    *,
    annoncer: bool = False,
) -> None:
    """Configure le fournisseur et renouvelle les diagnostics de l'analyse."""

    _ANALYSE.set(_AnalysisState(provider))
    if annoncer:
        if provider is None:
            _signaler_diagnostic("missing-provider", "analysis", (), _FOURNISSEUR_ABSENT)
        elif getattr(provider, "diagnostics", {}).get("availability") == "absent":
            _signaler_diagnostic("missing-provider", "analysis", (), "missing-bundle")
        else:
            _LOGGER.info("Text understanding status=configured; awaiting provider results")


@contextmanager
def contexte_comprehension_texte() -> Iterator[None]:
    """Isole une conversion et restaure le fournisseur de son appelant."""

    token = _ANALYSE.set(None)
    try:
        yield
    finally:
        state = _ANALYSE.get()
        finish = getattr(state.provider, "finaliser_sans_entree", None) if state else None
        try:
            if callable(finish):
                finish()
        finally:
            _ANALYSE.reset(token)




def diagnostics_comprehension_texte() -> tuple[dict, ...]:
    """Return detached observations, including the conversion provider's history."""
    state = _etat_analyse()
    events = list(getattr(state.provider, "history", ()))
    current = getattr(state.provider, "diagnostics", None)
    if isinstance(current, dict) and current not in events:
        events.append(current)
    events.extend(event for event in state.events if event not in events)
    return deepcopy(tuple(events))


def contexte_lignes_texte(elements_or_lines, *, metadonnees=None) -> dict:
    """Project actual selected lines, without inheriting parent/sibling IDs."""
    context = deepcopy(metadonnees) if isinstance(metadonnees, dict) else {}
    if hasattr(elements_or_lines, "lignes") or hasattr(elements_or_lines, "spans"):
        elements_or_lines = (elements_or_lines,)
    rows = []
    page_index = strategy = None
    for element in elements_or_lines:
        attributes = getattr(element, "attributes", {}) or {}
        presentation = {**(attributes.get("presentation") or {}),
                        **(getattr(element, "presentation", {}) or {})}
        for key in ("neighbors", "obstacles"):
            supplied = presentation.get(key, attributes.get(key))
            if key not in context and supplied is not None:
                context[key] = deepcopy(supplied)
        if page_index is None:
            page_index = getattr(element, "page_index", None)
            if page_index is None:
                page_index = getattr(element, "source_page_index", None)
            if page_index is None:
                page_index = presentation.get("page_index", attributes.get("page_index"))
        if strategy is None:
            strategy = getattr(element, "layout_frame_strategy", None) or attributes.get("layout_frame_strategy")
        selected = getattr(element, "lignes", None)
        selected = tuple(selected) if selected is not None else (element,)
        for position, line in enumerate(selected):
            if isinstance(line, dict):
                row = deepcopy(line)
                if "index" in row:
                    row.setdefault("source_index", row["index"])
                row["index"] = len(rows)
                rows.append(row)
                continue
            spans = getattr(line, "spans", ())
            bbox = getattr(line, "bbox", None)
            line_attributes = getattr(line, "attributes", {}) or {}
            if page_index is None:
                page_index = getattr(line, "page_index", None)
                if page_index is None:
                    page_index = getattr(line, "source_page_index", None)
            local = {**attributes, **presentation}
            # Container separators surround the block, not every child line.
            if position:
                for key in ("boundary_before", "blank_separator_before", "source_spacing_before_emu"):
                    local.pop(key, None)
            if position < len(selected) - 1:
                local.pop("boundary_after", None)
            local.update(line_attributes)
            local.update(getattr(line, "presentation", {}) or {})
            styles = []
            weighted = []
            for span in spans:
                font = getattr(span, "police", None)
                style = {"font": getattr(font, "famille", None),
                         "size_pt": getattr(span, "size_pt", None),
                         "bold": getattr(font, "gras", None),
                         "italic": getattr(font, "italique", None),
                         "color": getattr(span, "couleur", None)}
                styles.append(style)
                weighted.append((len(getattr(span, "texte", "").strip()), style))
            if not spans:
                source_style = getattr(line, "style", {}) or {}
                styles = [{key: deepcopy(value) for key, value in source_style.items()
                           if key in {"font", "font_family", "font_name", "font_id", "source_fontname",
                                      "size_pt", "bold", "italic", "color", "alignement"}
                           and (value is None or isinstance(value, (str, int, float, bool)))}]
                if "font" not in styles[0]:
                    styles[0]["font"] = styles[0].get("font_family")
            def known(name):
                return (getattr(line, name, None) or line_attributes.get(name)
                        or getattr(element, name, None) or attributes.get(name))

            ids = getattr(line, "source_ids", None)
            if not ids and getattr(line, "source_id", None):
                ids = (line.source_id,)
            row = {
                "index": len(rows), "text": ("".join(span.texte for span in spans) if spans
                                               else getattr(line, "text", getattr(line, "texte", ""))),
                "bbox": [bbox.x0, bbox.y0, bbox.x1, bbox.y1] if bbox is not None else None,
                "source_ids": list(ids) if ids else None,
                "layout_frame_id": known("layout_frame_id"),
                "layout_role": known("layout_frame_role"),
                "semantic_role": known("semantic_role") or getattr(line, "role", None),
                "orientation": getattr(line, "orientation", None),
                "angle_deg": getattr(line, "angle_deg", None),
                "alignment": getattr(line, "alignement", None) or (getattr(line, "style", {}) or {}).get("alignement"),
                "styles": styles,
                "dominant_style": max(weighted, key=lambda pair: sum(
                    weight for weight, style in weighted if style == pair[1]
                ))[1] if weighted else (styles[0] if styles else None),
                "spacing_before_emu": local.get("source_spacing_before_emu"),
                "blank_separator_before": local.get("blank_separator_before"),
                "boundary_before": getattr(line, "boundary_before", None) or local.get("boundary_before"),
                "boundary_after": getattr(line, "boundary_after", None) or local.get("boundary_after"),
                "segmentation_owner": local.get("segmentation_owner"),
            }
            rows.append(row)
    context.setdefault("page_index", page_index)
    context.setdefault("frame_strategy", strategy)
    context.setdefault("coordinate_system", {"origin": "top-left", "units": "EMU"})
    context["lines"] = rows
    return deepcopy(context)


_FOURNISSEUR_ABSENT = (
    "no text-understanding endpoint configured (--text-understanding-url or "
    "PDFEXACT_TEXT_UNDERSTANDING_URL); segmentation is geometric"
)


def _signaler_diagnostic(
    status: str,
    kind: str,
    lignes: tuple[str, ...],
    detail: str,
    *,
    contexte: TextUnderstandingContext = None,
) -> None:
    state = _etat_analyse()
    key = (status, detail)
    provider_keys = getattr(state.provider, "warning_keys", state.warning_keys)
    if key in state.warning_keys or key in provider_keys:
        return
    state.warning_keys.add(key)
    provider_keys.add(key)
    diagnostic = getattr(state.provider, "diagnostics", {})
    if isinstance(diagnostic, dict) and diagnostic.get("status") == status and diagnostic.get("reason") == detail:
        state.events.append(deepcopy(diagnostic))
    else:
        state.events.append({"status": status, "reason": detail})
    page = ""
    if isinstance(contexte, dict) and "page_index" in contexte:
        page = f" page_index={contexte['page_index']}"
    _LOGGER.warning(
        "Text understanding status=%s kind=%s lines=%d%s: %s; "
        "using geometric/heuristic fallback",
        status, kind, len(lignes), page, detail,
    )


def comprendre_ligne_texte(
    texte: str,
    *,
    frame_role: str | None,
    frame_strategy: str | None = None,
    metadonnees: TextUnderstandingMetadata | None = None,
) -> TextUnderstandingDecision:
    """Classe une ligne isolee pour savoir si elle peut entrer dans un paragraphe."""

    normalise = " ".join(texte.split())
    if not normalise:
        return TextUnderstandingDecision("empty", "preserve-line", 1.0, ("empty",))
    decision_ia = _decision_ia(
        "line",
        (texte,),
        frame_role=frame_role,
        frame_strategy=metadonnees if metadonnees is not None else frame_strategy,
    )
    if decision_ia is not None:
        return decision_ia
    if frame_strategy and frame_strategy != "word-text":
        return TextUnderstandingDecision("protected", "preserve-line", 0.98, ("non-word-text-frame",))
    if frame_role != "text-column":
        return TextUnderstandingDecision(frame_role or "unframed", "preserve-line", 0.96, ("not-text-column",))

    if _est_ligne_non_paragraphe(normalise):
        return TextUnderstandingDecision("label", "preserve-line", 0.90, ("non-prose-line",))
    if _score_prose([normalise]) >= 0.58:
        return TextUnderstandingDecision("paragraph-line", "candidate-paragraph-line", 0.78, ("prose-line",))
    return TextUnderstandingDecision("uncertain", "preserve-line", 0.55, ("weak-prose-signal",))


def comprendre_groupe_lignes(
    textes: Iterable[str],
    *,
    frame_role: str | None,
    frame_strategy: str | None = None,
    metadonnees: TextUnderstandingMetadata | None = None,
) -> TextUnderstandingDecision:
    """Decide si plusieurs lignes natives representent un vrai paragraphe."""

    lignes = tuple(str(t) for t in textes)
    if len(lignes) < 2:
        return TextUnderstandingDecision("single-line", "preserve-lines", 0.99, ("line-count<2",))
    decision_ia = _decision_ia(
        "group",
        lignes,
        frame_role=frame_role,
        frame_strategy=metadonnees if metadonnees is not None else frame_strategy,
    )
    if decision_ia is not None:
        return decision_ia
    if frame_strategy and frame_strategy != "word-text":
        return TextUnderstandingDecision("protected", "preserve-lines", 0.98, ("non-word-text-frame",))
    if frame_role != "text-column":
        return TextUnderstandingDecision(frame_role or "unframed", "preserve-lines", 0.97, ("not-text-column",))

    prose = _score_prose(lignes)
    label = _score_label_ou_schema(lignes)
    evidence: list[str] = [f"prose={prose:.2f}", f"label={label:.2f}"]

    if label >= 0.58 and label >= prose:
        evidence.append("diagram-or-label-language")
        return TextUnderstandingDecision("label-group", "preserve-lines", min(0.95, label), tuple(evidence))
    if prose >= 0.62 and prose - label >= 0.14:
        evidence.append("paragraph-language")
        return TextUnderstandingDecision("paragraph", "merge-paragraph", min(0.96, prose), tuple(evidence))
    return TextUnderstandingDecision("uncertain", "preserve-lines", 0.60, tuple(evidence + ["no-semantic-majority"]))


def comprendre_reflow_paragraphe(
    textes: Iterable[str],
    *,
    frame_role: str | None,
    frame_strategy: str | None = None,
    metadonnees: TextUnderstandingMetadata | None = None,
) -> TextUnderstandingDecision:
    """Décide comment joindre les lignes à l'intérieur d'une seule bbox."""
    lignes = tuple(str(texte) for texte in textes)
    if len(lignes) < 2:
        return TextUnderstandingDecision(
            "single-line", "paragraph-reflow", 1.0, ("line-count<2",), ()
        )

    decision_ia = _decision_ia(
        "paragraph-reflow",
        lignes,
        frame_role=frame_role,
        frame_strategy=metadonnees if metadonnees is not None else frame_strategy,
    )
    if decision_ia is not None:
        joins = tuple(
            "preserve_break" if hard_line_break(left, right) else action
            for left, right, action in zip(lignes, lignes[1:], decision_ia.line_joins)
        )
        return replace(decision_ia, line_joins=joins)

    structured_rows = _est_bloc_lignes_structurees(lignes)
    joins = []
    rows = _lignes_contexte(metadonnees, lignes)
    for index, (precedente, courant) in enumerate(zip(lignes, lignes[1:])):
        if (hard_line_break(precedente, courant) or not precedente.strip() or not courant.strip()
                or (rows and _frontiere_contexte(rows[index], rows[index + 1]))):
            joins.append("preserve_break")
        elif precedente.rstrip().endswith(("-", "¬")) and courant.lstrip()[:1].islower():
            joins.append("hyphen_join")
        elif structured_rows:
            joins.append("preserve_break")
        else:
            joins.append("no_space" if cjk_join_without_space(precedente, courant) else "space")
    return TextUnderstandingDecision(
        "paragraph-reflow-fallback",
        "paragraph-reflow",
        0.60,
        ("deterministic-line-join",) + (("structured-row-breaks",) if structured_rows else ()),
        tuple(joins),
    )


def _est_bloc_lignes_structurees(lignes: tuple[str, ...]) -> bool:
    """Reconnaissance prudente de lignes autonomes, sans decouper le paragraphe."""
    if len(lignes) < 2 or any(len(ligne.split()) > 10 or len(ligne) > 96 for ligne in lignes):
        return False
    if any(
        ligne.endswith((",", ";", ":", "-", "\u00ac", "\u2013", "\u2014", "/", "(", "["))
        for ligne in lignes[:-1]
    ):
        return False

    records = []
    for ligne in lignes:
        record = _NUMERIC_RECORD_RE.fullmatch(ligne)
        # Decimal values are data; sentence punctuation in labels is prose.
        label = record.group("label") if record is not None else ligne
        if any(mark in label for mark in ".!?;"):
            return False
        if record is not None and any(char.isalpha() for char in label):
            records.append(record)

    if len(records) == len(lignes):
        explicit_separators = [
            any(char in record.group("separator") for char in ":=\t")
            or len(record.group("separator")) >= 2
            for record in records
        ]
        if all(explicit_separators) or (len(lignes) >= 3 and not any(explicit_separators)):
            return True
    return len(lignes) >= 3 and all(ligne and (ligne[0].isupper() or ligne[0].isdigit()) for ligne in lignes)


def comprendre_segmentation_page(
    textes: Iterable[str],
    *,
    metadonnees: TextUnderstandingMetadata | None = None,
) -> TextUnderstandingDecision | None:
    """Demande une segmentation globale des lignes textuelles de la page.

    ``line_groups`` est volontairement distinct de ``line_joins`` : le service
    peut ainsi décider qu'un même bloc PDF contient deux, trois ou davantage
    d'éléments sémantiques indépendants (par exemple un libellé et un numéro de
    page). Le fallback reste déterministe dans ``text_segmentation``.
    """
    lignes = tuple(str(texte) for texte in textes)
    if not lignes:
        return None
    return _decision_ia(
        "page-segmentation",
        lignes,
        frame_role="page",
        frame_strategy=metadonnees,
    )


def _decision_ia(
    kind: str,
    lignes: tuple[str, ...],
    *,
    frame_role: str | None,
    frame_strategy: TextUnderstandingContext,
) -> TextUnderstandingDecision | None:
    state = _etat_analyse()
    provider = state.provider
    if provider is None:
        _signaler_diagnostic(
            "missing-provider", kind, lignes, _FOURNISSEUR_ABSENT, contexte=frame_strategy
        )
        return None
    event_count = len(state.events)
    try:
        decision = provider(kind, lignes, frame_role, deepcopy(frame_strategy))
    except Exception as exc:  # noqa: BLE001
        _signaler_diagnostic(
            "provider-error", kind, lignes, f"{type(exc).__name__}: {exc}",
            contexte=frame_strategy,
        )
        return None
    if decision is None:
        diagnostic = getattr(provider, "diagnostics", {})
        if isinstance(diagnostic, dict) and diagnostic.get("status"):
            _signaler_diagnostic(diagnostic["status"], kind, lignes,
                                diagnostic.get("reason", "provider abstained"), contexte=frame_strategy)
        elif len(state.events) == event_count:
            _signaler_diagnostic("empty-response", kind, lignes, "provider returned no decision", contexte=frame_strategy)
        return None
    if isinstance(decision, TextUnderstandingDecision) and decision.action == "abstain":
        _signaler_diagnostic("model-abstention", kind, lignes,
                            "; ".join(decision.evidence), contexte=frame_strategy)
        return None
    reason = _raison_decision_invalide(decision)
    if reason is not None:
        _signaler_diagnostic("invalid-response", kind, lignes, reason, contexte=frame_strategy)
        return None
    if decision.confidence < 0.50:
        _signaler_diagnostic(
            "low-confidence", kind, lignes, f"confidence={decision.confidence:.3f} below 0.50",
            contexte=frame_strategy,
        )
        return None
    reason = _raison_action_invalide(decision, kind, len(lignes))
    if reason is not None:
        _signaler_diagnostic("invalid-response", kind, lignes, reason, contexte=frame_strategy)
        return None
    reason = source_decision_conflict(decision, kind, lignes, context=frame_strategy)
    if reason is not None:
        _signaler_diagnostic("source-conflict", kind, lignes, reason, contexte=frame_strategy)
        if kind == "page-segmentation" and reason.startswith("source-"):
            return TextUnderstandingDecision(
                "source-conflict-fallback", "segment-page", 1.0,
                ("source-conflict", reason, "deterministic-source-line-partition"),
                line_groups=tuple((index,) for index in range(len(lignes))),
            )
        return None
    if not state.acceptance_reported:
        state.acceptance_reported = True
        _LOGGER.info(
            "Text understanding status=accepted kind=%s lines=%d confidence=%.3f",
            kind, len(lignes), decision.confidence,
        )
    return replace(
        decision,
        ai_used=True,
        fallback_used=False,
        evidence=tuple(decision.evidence) + ("ai-decision-accepted",),
    )


def _raison_decision_invalide(decision: Any) -> str | None:
    if not isinstance(decision, TextUnderstandingDecision):
        return f"expected TextUnderstandingDecision, received {type(decision).__name__}"
    confidence = decision.confidence
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0.0 <= confidence <= 1.0
        or not math.isfinite(confidence)
    ):
        return "confidence must be a finite number between 0 and 1"
    if not isinstance(decision.kind, str) or not decision.kind:
        return "kind must be a nonempty string"
    if not isinstance(decision.action, str) or decision.action not in {
        "segment-page", "candidate-paragraph-line", "merge-paragraph",
        "preserve-line", "preserve-lines", "paragraph-reflow",
    }:
        return f"unsupported action: {decision.action!r}"
    if not isinstance(decision.evidence, (tuple, list)) or not all(
        isinstance(item, str) for item in decision.evidence
    ):
        return "evidence must be a sequence of strings"
    if not isinstance(decision.line_joins, (tuple, list)) or not all(
        isinstance(item, str) and item in {
            "space", "no_space", "hyphen_join", "preserve_break", "paragraph_break"
        }
        for item in decision.line_joins
    ):
        return "line_joins contains invalid transitions"
    if not isinstance(decision.line_groups, (tuple, list)) or not all(
        isinstance(group, (tuple, list)) and group
        and all(type(index) is int for index in group)
        for group in decision.line_groups
    ):
        return "line_groups must contain nonempty sequences of integer indices"
    return None


def _raison_action_invalide(
    decision: TextUnderstandingDecision, kind: str, line_count: int
) -> str | None:
    actions = {
        "page-segmentation": {"segment-page"},
        "paragraph-reflow": {"paragraph-reflow"},
        "line": {"candidate-paragraph-line", "preserve-line"},
        "group": {"merge-paragraph", "preserve-lines"},
    }
    if decision.action not in actions.get(kind, {decision.action}):
        return f"action {decision.action!r} is incompatible with request {kind!r}"
    if kind == "page-segmentation" and not decision.line_groups:
        return "segment-page response has no line_groups"
    if kind == "paragraph-reflow" and len(decision.line_joins) != line_count - 1:
        return f"expected {line_count - 1} line_joins, received {len(decision.line_joins)}"
    return None


def ambiguous_short_labels(lines: tuple[str, ...]) -> bool:
    """Short independent-looking lines need evidence beyond model confidence."""
    return len(lines) > 1 and all(
        0 < len(unicode_text_units(line)) <= 2
        and not any(char in line for char in ".!?。！？,，;；")
        for line in lines
    )


def _lignes_contexte(context, lines):
    rows = context.get("lines") if isinstance(context, dict) else context
    if not isinstance(rows, list) or len(rows) != len(lines):
        return None
    if not all(isinstance(row, dict) and (row.get("text") is None or row["text"] == text)
               for row, text in zip(rows, lines)):
        return None
    return rows


def _frontiere_contexte(left, right):
    if right.get("blank_separator_before") or right.get("boundary_before") or left.get("boundary_after"):
        return "source-separator"
    for key in ("alignment", "angle_deg"):
        if left.get(key) is not None and right.get(key) is not None and left[key] != right[key]:
            return f"{key}-change"
    titles = {"title", "subtitle", "heading", "header"}
    a, b = left.get("semantic_role"), right.get("semantic_role")
    if a != b and (a in titles or b in titles):
        return "role-change"
    if left.get("orientation") and right.get("orientation") and left["orientation"] != right["orientation"]:
        return "orientation-change"
    first, second = left.get("bbox"), right.get("bbox")
    if not (isinstance(first, (list, tuple)) and isinstance(second, (list, tuple))
            and len(first) == len(second) == 4
            and all(isinstance(value, (int, float)) and math.isfinite(value) for value in (*first, *second))):
        return None
    height = max(first[3] - first[1], second[3] - second[1], 1)
    overlap = max(0, min(first[2], second[2]) - max(first[0], second[0]))
    width = max(min(first[2] - first[0], second[2] - second[0]), 1)
    if second[1] >= first[3] and overlap / width < 0.1:
        return "column-change"
    if second[1] - first[3] > height * 0.85:
        return "vertical-gap"
    from pdfexact.analysis.semantic import ends_sentence

    if second[0] - first[0] > height * 0.6 and ends_sentence(left.get("text", "")):
        return "paragraph-indent"
    def dominant(row):
        if isinstance(row.get("dominant_style"), dict):
            return row["dominant_style"]
        styles = row.get("styles")
        return styles[0] if isinstance(styles, list) and len(styles) == 1 else {}

    style_a, style_b = dominant(left), dominant(right)
    size_a, size_b = style_a.get("size_pt"), style_b.get("size_pt")
    if (isinstance(size_a, (int, float)) and isinstance(size_b, (int, float))
            and abs(size_a - size_b) > max(size_a, size_b) * 0.15):
        return "block-style-change"
    return None


def source_decision_conflict(
    decision: TextUnderstandingDecision, kind: str, lines: tuple[str, ...], context=None,
) -> str | None:
    rows = _lignes_contexte(context, lines)
    if isinstance(context, dict) and "lines" in context and rows is None:
        return "source-context-misaligned:line-count/order/text"
    if kind == "group" and decision.action == "merge-paragraph" and ambiguous_short_labels(lines):
        return "ambiguous-short-lines: model confidence alone cannot justify merging labels"
    merged = set()
    if kind == "group" and decision.action == "merge-paragraph":
        merged.update(range(len(lines) - 1))
    elif kind == "page-segmentation":
        partition = [index for group in decision.line_groups for index in group]
        if partition != list(range(len(lines))):
            return "invalid-partition:coverage/order/duplicates"
        merged.update(index for group in decision.line_groups for index in group[:-1])
    elif kind == "paragraph-reflow":
        merged.update(index for index, join in enumerate(decision.line_joins)
                      if join not in {"preserve_break", "paragraph_break"})
    for index in merged:
        left, right = lines[index:index + 2]
        if hard_line_break(left, right) or not left.strip() or not right.strip():
            return f"source-hard-break-conflict:after={index}"
        if rows and (reason := _frontiere_contexte(rows[index], rows[index + 1])):
            return f"source-context-conflict:after={index}; {reason}"
    if kind == "paragraph-reflow":
        for index, (left, right, join) in enumerate(zip(lines, lines[1:], decision.line_joins)):
            if hard_line_break(left, right) and join not in {"preserve_break", "paragraph_break"}:
                return f"source-hard-break-conflict:after={index}"
            if cjk_join_without_space(left, right) and join == "space":
                return f"source-script-spacing-conflict:after={index}; verified Unicode characters, no language inferred"
    return None


def _est_ligne_non_paragraphe(texte: str) -> bool:
    mots = unicode_text_units(texte)
    if len(mots) < 4:
        return True
    from pdfexact.analysis.semantic import starts_list_marker
    if _BULLET_RE.match(texte) or starts_list_marker(texte) or _CAPTION_RE.match(texte):
        return True
    codes = _CODE_RE.findall(texte)
    if len(codes) >= max(2, len(mots) // 3):
        return True
    lettres = [car for car in texte if car.isalpha()]
    if not lettres:
        return True
    if sum(1 for car in lettres if car.isupper()) / len(lettres) > 0.82:
        return True
    if _ratio_alphabetique(texte) < 0.42:
        return True
    return False


def _score_prose(lignes: tuple[str, ...] | list[str]) -> float:
    texte = " ".join(lignes)
    mots = unicode_text_units(texte)
    if not mots:
        return 0.0
    score = 0.0
    if len(mots) >= 12:
        score += 0.26
    elif len(mots) >= 7:
        score += 0.14
    minuscules = sum(1 for mot in mots if any(car.islower() for car in mot))
    if any(is_cjk_character(char) for char in texte) and not any(char.isupper() or char.islower() for char in texte):
        minuscules = len(mots)  # Case is not a prose signal in uncased scripts.
    score += min(0.22, 0.22 * minuscules / max(len(mots), 1))
    mots_longs = sum(1 for mot in mots if len(mot) >= 5)
    if sum(is_cjk_character(char) for char in texte) >= 12:
        mots_longs = len(mots)
    score += min(0.18, 0.18 * mots_longs / max(len(mots), 1))
    ponctuation_phrase = sum(1 for car in texte if car in ".,;:!?。！？、，；：")
    score += min(0.14, ponctuation_phrase * 0.035)
    fins_internes = sum(1 for ligne in lignes[:-1] if ligne.rstrip().endswith((".", "!", "?", ":")))
    if fins_internes >= max(2, len(lignes) // 2):
        score -= 0.18
    if _ratio_alphabetique(texte) >= 0.50:
        score += 0.16
    return max(0.0, min(1.0, score))


def _score_label_ou_schema(lignes: tuple[str, ...] | list[str]) -> float:
    texte = " ".join(lignes)
    mots = unicode_text_units(texte)
    if not mots:
        return 1.0
    score = 0.0
    lignes_courtes = sum(1 for ligne in lignes if len(unicode_text_units(ligne)) <= 4)
    score += min(0.22, 0.22 * lignes_courtes / max(len(lignes), 1))
    codes = _CODE_RE.findall(texte)
    score += min(0.28, 0.07 * len(codes))
    if any(_BULLET_RE.match(ligne) for ligne in lignes):
        score += 0.18
    if any(_CAPTION_RE.match(ligne) for ligne in lignes):
        score += 0.20
    lettres = [car for car in texte if car.isalpha()]
    if lettres and sum(1 for car in lettres if car.isupper()) / len(lettres) > 0.60:
        score += 0.14
    if len(mots) < 12:
        score += 0.12
    if _ratio_alphabetique(texte) < 0.42:
        score += 0.18
    return max(0.0, min(1.0, score))


def _ratio_alphabetique(texte: str) -> float:
    significatifs = [car for car in texte if not car.isspace()]
    if not significatifs:
        return 0.0
    return sum(1 for car in significatifs if car.isalpha()) / len(significatifs)


def is_cjk_character(char: str) -> bool:
    name = unicodedata.name(char, "")
    return any(part in name for part in ("CJK", "IDEOGRAPH", "HIRAGANA", "KATAKANA"))


def unicode_text_units(text: str) -> list[str]:
    """Lexical proxies, not language identification or linguistic tokenization."""
    units = []
    word = ""
    for char in str(text):
        if is_cjk_character(char):
            if word:
                units.append(word)
                word = ""
            units.append(char)
        elif unicodedata.category(char)[0] in {"L", "M"} or (word and char in "'’-"):
            word += char
        elif word:
            units.append(word)
            word = ""
    if word:
        units.append(word)
    return units


def hard_line_break(previous: str, current: str) -> bool:
    return previous.rstrip(" \t").endswith(("\n", "\r")) or current.lstrip(" \t").startswith(("\n", "\r"))



def cjk_join_without_space(previous: str, current: str) -> bool:
    if not previous or not current or previous[-1].isspace() or current[0].isspace():
        return False
    punctuation = "。！？、，；：）」』】》〉"
    return ((is_cjk_character(previous[-1]) and (is_cjk_character(current[0]) or current[0] in punctuation))
            or (previous[-1] in punctuation and is_cjk_character(current[0])))
