"""Compréhension géométrique et sémantique de l'orientation du texte."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass(frozen=True)
class OrientationDecision:
    kind: str
    angle_deg: float
    confidence: float
    semantic_role: str | None = None
    curved: bool = False
    evidence: tuple[str, ...] = ()
    ai_used: bool = False
    fallback_used: bool = True


OrientationProvider = Callable[
    [str, tuple[str, ...], str | None, float, tuple[tuple[float, float], ...]],
    OrientationDecision | None,
]
_PROVIDER: OrientationProvider | None = None




def normaliser_angle(angle_deg: float) -> float:
    angle = float(angle_deg or 0.0)
    while angle <= -180.0:
        angle += 360.0
    while angle > 180.0:
        angle -= 360.0
    return angle


def angle_depuis_points(points: Iterable[tuple[float, float]]) -> float:
    points = tuple(points)
    if len(points) < 2:
        return 0.0
    x0, y0 = points[0]
    x1, y1 = points[1]
    return normaliser_angle(math.degrees(math.atan2(y1 - y0, x1 - x0)))


def courbure_depuis_points(points: Iterable[tuple[float, float]]) -> float:
    """Mesure la variation maximale de direction d'une ligne de base.

    Une bbox quadrangulaire ne suffit pas à détecter un texte courbe. Les traces PDF
    et certains OCR fournissent cependant plusieurs points de base. La valeur retournée
    est exprimée en degrés et reste volontairement tolérante aux petits écarts de
    rasterisation.
    """
    points = tuple(points)
    if len(points) < 3:
        return 0.0
    angles = [
        angle_depuis_points((points[index], points[index + 1]))
        for index in range(len(points) - 1)
        if points[index] != points[index + 1]
    ]
    if len(angles) < 2:
        return 0.0
    ecarts = []
    for precedent, courant in zip(angles, angles[1:]):
        ecart = abs(normaliser_angle(courant - precedent))
        ecarts.append(min(ecart, abs(180.0 - ecart)))
    return max(ecarts, default=0.0)


def classer_orientation(
    texte: str,
    angle_deg: float = 0.0,
    *,
    semantic_role: str | None = None,
    baseline_points: Iterable[tuple[float, float]] = (),
    confidence: float = 0.0,
) -> OrientationDecision:
    points = tuple(baseline_points)
    angle = normaliser_angle(angle_deg)
    courbure = courbure_depuis_points(points)
    if courbure >= 12.0:
        kind = "curved"
    elif abs(angle) <= 7.0:
        kind = "horizontal"
    elif abs(abs(angle) - 90.0) <= 10.0:
        kind = "vertical"
    elif angle > 0:
        kind = "oblique-down"
    else:
        kind = "oblique-up"

    semantic = semantic_role
    evidence = [f"angle={angle:.2f}"]
    compact = " ".join((texte or "").split()).lower()
    if semantic is None:
        if any(marker in compact for marker in ("photo", "source", "courtesy", "copyright")):
            semantic = "credit"
            evidence.append("credit-language")
        elif any(marker in compact for marker in ("figure", "fig.", "caption", "approximately")):
            semantic = "caption"
            evidence.append("caption-language")

    decision = OrientationDecision(
        kind=kind,
        angle_deg=angle,
        confidence=max(0.0, min(1.0, max(confidence, 0.70 if abs(angle) > 7 else 0.55))),
        semantic_role=semantic,
        curved=kind == "curved",
        evidence=tuple(evidence),
    )
    if _PROVIDER is not None:
        try:
            ia = _PROVIDER(
                texte,
                (texte,),
                semantic,
                angle,
                tuple((float(x), float(y)) for x, y in points),
            )
        except Exception:  # noqa: BLE001
            ia = None
        if ia is not None and ia.confidence >= 0.50:
            return ia
    return decision
