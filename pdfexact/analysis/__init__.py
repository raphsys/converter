"""Contrats et algorithmes universels de l'analyse PDF.

Les imports sont paresseux : ``scene`` utilise lui-même les primitives de ce
package et ne doit pas dependre de l'ordre dans lequel l'appelant importe les
modules.
"""

__all__ = [
    "AnalysisOptions",
    "ElementKind",
    "ElementRecord",
    "PageScene",
    "RenderDecision",
    "RenderMode",
    "SceneDocument",
    "decider_mode_universel",
    "verifier_decision",
    "decision_is_lossless",
    "normaliser_script_et_langue",
    "calculer_features_continuite",
    "est_frontiere_de_paragraphe",
    "est_continuation_de_ligne",
    "detecter_marqueur_liste",
    "regrouper_paragraphes",
    "regrouper_listes",
    "regrouper_frames",
    "detecter_colonnes_textuelles",
    "produire_flow_paragraphs",
    "valider_groupe_semantique",
]


def __getattr__(name: str):
    if name == "AnalysisOptions":
        from pdfexact.analysis.options import AnalysisOptions

        return AnalysisOptions
    if name in {"ElementKind", "ElementRecord", "PageScene", "SceneDocument"}:
        from pdfexact.scene import ElementKind, ElementRecord, PageScene, SceneDocument

        return {
            "ElementKind": ElementKind,
            "ElementRecord": ElementRecord,
            "PageScene": PageScene,
            "SceneDocument": SceneDocument,
        }[name]
    if name in {"RenderDecision", "RenderMode", "decider_mode_universel", "verifier_decision", "decision_is_lossless"}:
        from pdfexact.analysis.decisions import (
            RenderDecision,
            RenderMode,
            decider_mode_universel,
            decision_is_lossless,
            verifier_decision,
        )

        return {
            "RenderDecision": RenderDecision,
            "RenderMode": RenderMode,
            "decider_mode_universel": decider_mode_universel,
            "verifier_decision": verifier_decision,
            "decision_is_lossless": decision_is_lossless,
        }[name]
    if name in {
        "normaliser_script_et_langue",
        "calculer_features_continuite",
        "est_frontiere_de_paragraphe",
        "est_continuation_de_ligne",
        "detecter_marqueur_liste",
        "regrouper_paragraphes",
        "regrouper_listes",
        "regrouper_frames",
        "detecter_colonnes_textuelles",
        "produire_flow_paragraphs",
        "valider_groupe_semantique",
    }:
        from pdfexact.analysis import semantic

        return getattr(semantic, name)
    raise AttributeError(name)
