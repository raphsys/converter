"""Table-of-contents entries, whatever their layout.

Every table of contents (contents, figures, tables, index-like lists) pairs a
title with a page reference. The reference is what identifies an entry:

- after leader dots, middle dots, ellipses or underscores: always an entry;
- otherwise set apart from the title by a tab or a blank wider than a space,
  at the end (right-aligned) or at the start of the row (left-aligned), and
  aligned with the reference of another row of the same zone;
- without any page reference, entries open with the same label and changing
  markers (Appendix A, Appendix B).

Justified prose may end on a number, but never set apart and aligned like a
column of page references. A wrapped title row carries no reference, so it
stays with the row that ends the entry.
"""
from __future__ import annotations

import re
from statistics import median

# Page reference: arabic number or range, or roman numeral, optionally "p."/"page".
_REF = r"(?:(?:p\.|pp\.|page|pages)\s*)?(?:\d{1,4}(?:\s*[-–—]\s*\d{1,4})?|[ivxlcdm]{1,7})"
_LEADER_FIN = re.compile(r"(?:[.·…_]\s?){3,}\s*" + _REF + r"\s*$", re.IGNORECASE)
_TAB_FIN = re.compile(r"\S\s*\t\s*" + _REF + r"\s*$", re.IGNORECASE)
_TAB_DEBUT = re.compile(r"^\s*" + _REF + r"\s*\t\s*\S", re.IGNORECASE)
_REF_SEULE = re.compile(r"^\s*" + _REF + r"\s*$", re.IGNORECASE)
# Label then enumerator opening a row: "Appendix A.", "Table 2:", "Chapitre IV".
_LIBELLE = re.compile(r"^\s*([^\W\d_]{3,})\s+(\d{1,3}(?:\.\d{1,3})*|[A-Z]|[IVXLC]{1,6})(?:[.:)\-–—]|\s)")
# Blank between title and reference, in line heights: wider than a word space.
_BLANC_MIN = 0.8
# Alignment tolerance of a reference column, in line heights.
_ALIGNEMENT = 0.6


def fin_par_points_de_suite(text: str) -> bool:
    """A row ending with leader dots and a page reference."""
    return _LEADER_FIN.search(str(text)) is not None


def _reference(line):
    """('end'|'start', reference edge x) when the row sets a page reference apart."""
    text = "".join(span.texte for span in line.spans)
    spans = [span for span in line.spans if span.texte.strip()]
    if not spans:
        return None
    if _TAB_FIN.search(text):
        return "end", spans[-1].bbox.x1
    if _TAB_DEBUT.search(text):
        return "start", spans[0].bbox.x0
    if len(spans) < 2:
        return None
    blanc = _BLANC_MIN * max(line.bbox.hauteur, 1)
    if _REF_SEULE.match(spans[-1].texte) and spans[-1].bbox.x0 - spans[-2].bbox.x1 >= blanc:
        return "end", spans[-1].bbox.x1
    if _REF_SEULE.match(spans[0].texte) and spans[1].bbox.x0 - spans[0].bbox.x1 >= blanc:
        return "start", spans[0].bbox.x0
    return None


def _libelle(text):
    """(label, marker) of a row opening with a label and an enumerator."""
    found = _LIBELLE.match(str(text))
    return (found.group(1).casefold(), found.group(2).casefold()) if found else None


def marquer_entrees_de_sommaire(units) -> None:
    """Mark rows ending ('end') or starting ('start') a table-of-contents entry."""
    candidats: dict[tuple, list] = {}
    libelles: dict[tuple, list] = {}
    for unit in units:
        line = unit.lignes[-1]
        if fin_par_points_de_suite("".join(span.texte for span in line.spans)):
            unit.presentation["toc_entry"] = "end"
            continue
        opening = _libelle("".join(span.texte for span in unit.lignes[0].spans))
        if opening is not None:
            libelles.setdefault((unit.layout_frame_id, opening[0]), []).append((opening[1], unit))
        found = _reference(line)
        if found is not None:
            side, edge = found
            candidats.setdefault((unit.layout_frame_id, side), []).append((edge, unit))
    # Entries without page reference: the same label with changing markers
    # (Appendix A, Appendix B; Table 1, Table 2). The same marker twice is prose.
    for rows in libelles.values():
        if len({marker for marker, _ in rows}) >= 2:
            for _, unit in rows:
                unit.presentation.setdefault("toc_entry", "start")
    for (_, side), rows in candidats.items():
        if len(rows) < 2:
            continue
        tolerance = _ALIGNEMENT * median(unit.lignes[-1].bbox.hauteur for _, unit in rows)
        for edge, unit in rows:
            # The row itself counts once: another aligned reference is required.
            if sum(abs(edge - other) <= tolerance for other, _ in rows) >= 2:
                unit.presentation["toc_entry"] = side
