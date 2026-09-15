"""Decision de regroupement textuel basee sur le role de layout et le contenu."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass(frozen=True)
class TextUnderstandingDecision:
    """Decision appliquee aux lignes natives avant rendu Word."""

    kind: str
    action: str
    confidence: float
    evidence: tuple[str, ...] = ()


TextUnderstandingProvider = Callable[
    [str, tuple[str, ...], str | None, str | None],
    TextUnderstandingDecision | None,
]

_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’-]*")
_CODE_RE = re.compile(r"\b[A-Z]{1,4}[-–]?\d+[A-Z]?\b|\b\d+[A-Z]\b|\b[A-Z]\d+[-–][A-Z]?\d+\b")
_BULLET_RE = re.compile(r"^\s*(?:[\-\u2022*]|\(?[0-9A-Za-z]{1,3}[.)])\s+")
_CAPTION_RE = re.compile(r"^\s*(?:fig(?:ure)?|table|tab\.?|below|above|source|note)\b", re.I)
_FOURNISSEUR_COMPREHENSION_TEXTE: TextUnderstandingProvider | None = None


def configurer_fournisseur_comprehension_texte(
    provider: TextUnderstandingProvider | None,
) -> None:
    """Branche une compréhension IA optionnelle, avec fallback heuristique."""

    global _FOURNISSEUR_COMPREHENSION_TEXTE
    _FOURNISSEUR_COMPREHENSION_TEXTE = provider


def comprendre_ligne_texte(
    texte: str,
    *,
    frame_role: str | None,
    frame_strategy: str | None = None,
) -> TextUnderstandingDecision:
    """Classe une ligne isolee pour savoir si elle peut entrer dans un paragraphe."""

    normalise = " ".join(texte.split())
    if not normalise:
        return TextUnderstandingDecision("empty", "preserve-line", 1.0, ("empty",))
    decision_ia = _decision_ia(
        "line",
        (normalise,),
        frame_role=frame_role,
        frame_strategy=frame_strategy,
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
) -> TextUnderstandingDecision:
    """Decide si plusieurs lignes natives representent un vrai paragraphe."""

    lignes = tuple(" ".join(t.split()) for t in textes if " ".join(t.split()))
    if len(lignes) < 2:
        return TextUnderstandingDecision("single-line", "preserve-lines", 0.99, ("line-count<2",))
    decision_ia = _decision_ia(
        "group",
        lignes,
        frame_role=frame_role,
        frame_strategy=frame_strategy,
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


def _decision_ia(
    kind: str,
    lignes: tuple[str, ...],
    *,
    frame_role: str | None,
    frame_strategy: str | None,
) -> TextUnderstandingDecision | None:
    provider = _FOURNISSEUR_COMPREHENSION_TEXTE
    if provider is None:
        return None
    try:
        decision = provider(kind, lignes, frame_role, frame_strategy)
    except Exception:  # noqa: BLE001
        return None
    if decision is None or decision.confidence < 0.50:
        return None
    return decision


def _est_ligne_non_paragraphe(texte: str) -> bool:
    mots = _WORD_RE.findall(texte)
    if len(mots) < 4:
        return True
    if _BULLET_RE.match(texte) or _CAPTION_RE.match(texte):
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
    mots = _WORD_RE.findall(texte)
    if not mots:
        return 0.0
    score = 0.0
    if len(mots) >= 12:
        score += 0.26
    elif len(mots) >= 7:
        score += 0.14
    minuscules = sum(1 for mot in mots if any(car.islower() for car in mot))
    score += min(0.22, 0.22 * minuscules / max(len(mots), 1))
    mots_longs = sum(1 for mot in mots if len(mot) >= 5)
    score += min(0.18, 0.18 * mots_longs / max(len(mots), 1))
    ponctuation_phrase = sum(1 for car in texte if car in ".,;:!?")
    score += min(0.14, ponctuation_phrase * 0.035)
    fins_internes = sum(1 for ligne in lignes[:-1] if ligne.rstrip().endswith((".", "!", "?", ":")))
    if fins_internes >= max(2, len(lignes) // 2):
        score -= 0.18
    if _ratio_alphabetique(texte) >= 0.50:
        score += 0.16
    return max(0.0, min(1.0, score))


def _score_label_ou_schema(lignes: tuple[str, ...] | list[str]) -> float:
    texte = " ".join(lignes)
    mots = _WORD_RE.findall(texte)
    if not mots:
        return 1.0
    score = 0.0
    lignes_courtes = sum(1 for ligne in lignes if len(_WORD_RE.findall(ligne)) <= 4)
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
