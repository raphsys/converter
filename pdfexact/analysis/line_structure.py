"""Typographic structure of source lines, independent of any renderer.

Three facts are read from geometry and text only:

* a leader row ("Title ........ 12") always ends its line and is never
  justified text: its width comes from the leader, not from word spacing;
* a line that stops before its column edge while the next line's first word
  would have fitted there was broken on purpose (a reflowing composer would
  have pulled that word up);
* lines sharing a right edge (or a centre) but not a left edge are right
  aligned (or centred).
"""
from __future__ import annotations

import re

from pdfexact.geometry import emu_vers_pt, pt_vers_emu

LEADER_RE = re.compile(
    r"^(?P<label>.+?)\s*(?P<leader>(?:[-._]\s*){6,})\s*(?P<page>-?\d{1,4}|[ivxlcdm]{1,8})\s*$",
    re.IGNORECASE,
)
_LEADER_NAMES = {".": "dot", "-": "hyphen", "_": "underscore"}
# Average advance of a Latin glyph, in em, when no font metrics are available.
_ESTIMATED_GLYPH_EM = 0.55
_ESTIMATED_SPACE_EM = 0.28


def _text(line) -> str:
    return "".join(str(getattr(span, "texte", "") or "") for span in getattr(line, "spans", ()))


def _size(line) -> float:
    return max((float(getattr(span, "size_pt", 0) or 0) for span in getattr(line, "spans", ())), default=10.0) or 10.0


def split_leader(text: str):
    """Return (label, page, leader name) for a leader row, else None."""
    match = LEADER_RE.match(str(text or ""))
    if match is None:
        return None
    leader = match.group("leader").replace(" ", "")
    return match.group("label").rstrip(), match.group("page"), _LEADER_NAMES.get(leader[:1], "dot")


def is_leader_line(line) -> bool:
    return split_leader(_text(line)) is not None


def _first_word_width_pt(line, measure=None) -> float:
    words = _text(line).split()
    if not words:
        return 0.0
    size = _size(line)
    measured = measure(line, words[0]) if measure is not None else None
    word = measured if measured is not None else len(words[0]) * size * _ESTIMATED_GLYPH_EM
    return word + size * _ESTIMATED_SPACE_EM


def hard_break_reason(previous, current, right_edge, *, measure=None) -> str | None:
    """Why the source broke the line between two rows, or None if it reflowed."""
    if is_leader_line(previous):
        return "leader-row"
    if right_edge is None:
        return None
    free_pt = emu_vers_pt(right_edge - previous.bbox.x1)
    if free_pt > _first_word_width_pt(current, measure):
        return "short-line"
    return None


def geometric_alignment(lines) -> str | None:
    """Right or centre alignment proven by the rows' edges; None otherwise."""
    lines = [line for line in lines if _text(line).strip()]
    if len(lines) < 2 or any(is_leader_line(line) for line in lines):
        return None
    # PDF row boxes include trailing spaces: edges match within half an em.
    tolerance = max(pt_vers_emu(2.0), pt_vers_emu(0.5 * max(_size(line) for line in lines)))

    def spread(values):
        return max(values) - min(values)

    if spread([line.bbox.x0 for line in lines]) <= tolerance:
        return None
    if spread([line.bbox.x1 for line in lines]) <= tolerance:
        return "right"
    if spread([(line.bbox.x0 + line.bbox.x1) / 2 for line in lines]) <= tolerance:
        return "center"
    return None
