"""Profils de capacités des lecteurs DOCX.

Les backends restent responsables de produire l'OOXML; ce module ne rend rien et
ne choisit pas un mode de reconstruction. Il décrit uniquement les risques et les
fallbacks autorisés pour un lecteur cible.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReaderProfile:
    name: str
    supports_wps: bool
    supports_vml: bool
    supports_page_anchors: bool
    supports_vertical_body: bool
    supports_text_warp: bool
    supports_negative_spacing: bool


_PROFILES = {
    "word": ReaderProfile("word", True, True, True, True, True, True),
    "libreoffice": ReaderProfile("libreoffice", True, True, True, True, False, False),
    "wps": ReaderProfile("wps", True, True, True, True, True, True),
    "strict-ooxml": ReaderProfile("strict-ooxml", False, False, True, False, False, False),
}

_FEATURES = {
    "wps": "supports_wps",
    "vml": "supports_vml",
    "page-anchors": "supports_page_anchors",
    "vertical-body": "supports_vertical_body",
    "text-warp": "supports_text_warp",
    "negative-spacing": "supports_negative_spacing",
}


def profil_lecteur(name: str | None = None) -> ReaderProfile:
    """Retourne un profil déterministe; les noms inconnus tombent sur Word."""
    return _PROFILES.get(str(name or "word").casefold(), _PROFILES["word"])


def feature_supported(profile: ReaderProfile | str, feature: str) -> bool:
    profile = profil_lecteur(profile) if isinstance(profile, str) else profile
    attribute = _FEATURES.get(str(feature).casefold())
    return bool(attribute and getattr(profile, attribute, False))


def fallback_for(profile: ReaderProfile | str, feature: str) -> str | None:
    """Retourne le fallback de lecteur sans modifier le mode du plan."""
    if feature_supported(profile, feature):
        return None
    fallbacks = {
        "wps": "vml",
        "vml": "local-raster",
        "page-anchors": "inline-flow",
        "vertical-body": "rotated-vml",
        "text-warp": "segmented-editable",
        "negative-spacing": "font-fit",
    }
    return fallbacks.get(str(feature).casefold())


def record_reader_risk(profile: ReaderProfile | str, feature: str, *, context: str = "") -> dict:
    """Produit un diagnostic sérialisable pour le rapport de rendu."""
    profile = profil_lecteur(profile) if isinstance(profile, str) else profile
    fallback = fallback_for(profile, feature)
    return {
        "reader": profile.name,
        "feature": feature,
        "supported": fallback is None,
        "fallback": fallback,
        "context": context,
    }

