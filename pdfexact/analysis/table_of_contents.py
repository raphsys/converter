"""Table-of-contents entries inside zones the layout AI labels as contents.

The layout model decides which zone is a table of contents (role
"table-of-contents"), whatever its layout or language. Inside such a zone each
row is an entry, unless it continues the previous row: the previous row carried
no page reference while the zone's entries do carry references (a wrapped title).
"""
from __future__ import annotations

import re

ROLE = "table-of-contents"
# Page reference: arabic number or range, or a well-formed roman numeral in one case.
_NOMBRE = (r"(?:\d{1,4}(?:\s*[-–—]\s*\d{1,4})?"
           r"|(?-i:(?=[ivxlc])x{0,3}(?:ix|iv|v?i{0,3})|(?=[IVXLC])X{0,3}(?:IX|IV|V?I{0,3})))")
# Set apart from the title by a leader, a tab or a wide blank: "Phase 2" or
# "Annex C" ending a wrapped title is not a reference.
_REFERENCE = re.compile(r"(?:(?:[.·…_]\s?){3,}|\t|\s{2,})\s*" + _NOMBRE + r"\s*$")
_SEULE = re.compile(r"^\s*" + _NOMBRE + r"\s*$")


def _a_une_reference(unit) -> bool:
    spans = [span for span in unit.lignes[-1].spans if span.texte.strip()]
    if not spans:
        return False
    # A reference in its own span is set apart by the layout itself.
    if len(spans) > 1 and _SEULE.match(spans[-1].texte):
        return True
    return _REFERENCE.search("".join(span.texte for span in unit.lignes[-1].spans)) is not None


def marquer_entrees_de_sommaire(units) -> None:
    """Mark each row of a contents zone that ends an entry ('end')."""
    zones: dict[object, list] = {}
    for unit in units:
        if unit.semantic_role == ROLE:
            zone = unit.layout_frame_id or f"owner:{unit.presentation.get('segmentation_owner')}"
            zones.setdefault(zone, []).append(unit)
    for rows in zones.values():
        references = [_a_une_reference(unit) for unit in rows]
        for unit, reference in zip(rows, references):
            # Without any reference in the zone, every row is its own entry.
            if reference or not any(references):
                unit.presentation["toc_entry"] = "end"
