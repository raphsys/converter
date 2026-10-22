"""Compréhension de mise en page avant rendu."""

from pdfexact.layout.analyzer import analyze_page, analyser_page
from pdfexact.layout.ai import (
    DEFAULT_LAYOUT_MODEL,
    DEFAULT_LAYOUT_PROVIDER,
    LayoutAIPage,
    LayoutAIZone,
    detecter_layout_ia,
)
from pdfexact.layout.classifier import classer_regions, classify_regions, detecter_regions_colonnes
from pdfexact.layout.model import LayoutBlock, LayoutPage, LayoutRegion, ProtectedZone
from pdfexact.layout.planner import (
    LayoutPlanItem,
    filtrer_elements_selon_plan,
    plan_regions,
    planifier_regions,
    zones_layout_du_plan,
    zones_ocr_du_plan,
    zones_ocr_dur_du_plan,
    zones_protegees_du_plan,
)
from pdfexact.layout.understanding import (
    EDITABLE_STRATEGIES,
    LAYOUT_PROTECTED_STRATEGIES,
    OCR_PROTECTED_STRATEGIES,
    UnderstandingElement,
    PageUnderstanding,
    UnderstandingZone,
    comprendre_page,
    filtrer_elements_selon_comprehension,
    filtrer_elements_proteges,
)
from pdfexact.layout.text_comprehension import (
    TextUnderstandingDecision,
    comprendre_groupe_lignes,
    comprendre_ligne_texte,
    comprendre_reflow_paragraphe,
)

__all__ = [
    "LayoutBlock",
    "LayoutPage",
    "LayoutPlanItem",
    "LayoutRegion",
    "ProtectedZone",
    "DEFAULT_LAYOUT_MODEL",
    "DEFAULT_LAYOUT_PROVIDER",
    "LayoutAIPage",
    "LayoutAIZone",
    "analyze_page",
    "analyser_page",
    "classer_regions",
    "classify_regions",
    "detecter_regions_colonnes",
    "detecter_layout_ia",
    "filtrer_elements_selon_plan",
    "plan_regions",
    "planifier_regions",
    "zones_layout_du_plan",
    "zones_ocr_du_plan",
    "zones_ocr_dur_du_plan",
    "zones_protegees_du_plan",
    "EDITABLE_STRATEGIES",
    "LAYOUT_PROTECTED_STRATEGIES",
    "OCR_PROTECTED_STRATEGIES",
    "PageUnderstanding",
    "UnderstandingElement",
    "UnderstandingZone",
    "comprendre_page",
    "filtrer_elements_selon_comprehension",
    "filtrer_elements_proteges",
    "TextUnderstandingDecision",
    "comprendre_groupe_lignes",
    "comprendre_ligne_texte",
    "comprendre_reflow_paragraphe",
]
