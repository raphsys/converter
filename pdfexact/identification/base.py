"""Socle extensible de l'identification : candidats, décision, identificateurs, registre.

Ajouter une identité : déclarer le type dans le référentiel, puis enregistrer un
``Identificateur`` qui propose ce type (``Registre.enregistrer``). Le cœur ne change pas.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from pdfexact.identification.referentiel import famille

logger = logging.getLogger(__name__)

# Status thresholds of a decision.
SEUIL_IDENTIFIE = 0.6
ECART_IDENTIFIE = 0.15
# Candidates below this score are noise: they never impose a type.
SCORE_MIN = 0.15
ALTERNATIVES_MAX = 3


@dataclass(frozen=True)
class Candidat:
    type: str
    score: float
    indice: str


@dataclass(frozen=True)
class Decision:
    type: str
    famille: str
    statut: str
    confiance: float
    alternatives: tuple[tuple[str, float], ...]
    indices: tuple[str, ...]


@dataclass(frozen=True)
class ContextePage:
    """The page of an element, and what the pipeline lends the sources (renderers…)."""

    page: object
    premiere_page: bool = False
    extra: dict = field(default_factory=dict)


@runtime_checkable
class Identificateur(Protocol):
    """A source of identification: proposes candidate types for some natures of objects.

    ``natures``: the object natures it handles ("text", "image", "shape", "table", "link").
    Sources complement each other in a cascade: an identificateur may define
    ``pertinent(element, contexte, candidats) -> bool``; it is then consulted only when
    the candidates already proposed by the sources before it leave it work to do.
    """

    nom: str
    natures: frozenset[str]

    def candidats(self, element, contexte: ContextePage) -> list[Candidat]: ...


class Registre:
    """Ordered set of identificateurs; new identities plug in here."""

    def __init__(self, identificateurs=()):
        self._identificateurs: list[Identificateur] = []
        for identificateur in identificateurs:
            self.enregistrer(identificateur)

    def enregistrer(self, identificateur: Identificateur) -> None:
        if not isinstance(identificateur, Identificateur):
            raise TypeError(f"pas un identificateur : {identificateur!r}")
        if any(existant.nom == identificateur.nom for existant in self._identificateurs):
            raise ValueError(f"identificateur déjà enregistré : {identificateur.nom}")
        self._identificateurs.append(identificateur)

    def pour(self, nature: str) -> list[Identificateur]:
        return [i for i in self._identificateurs if nature in i.natures]

    @property
    def noms(self) -> tuple[str, ...]:
        return tuple(i.nom for i in self._identificateurs)


def consulter(identificateurs, element, contexte: ContextePage, echecs: list[str] | None = None) -> list[Candidat]:
    """Run the identificateurs in order; each sees what the previous ones proposed.

    A source failing on an element is logged and noted in ``echecs``; the others go on.
    """
    candidats: list[Candidat] = []
    for identificateur in identificateurs:
        try:
            pertinent = getattr(identificateur, "pertinent", None)
            if pertinent is not None and not pertinent(element, contexte, tuple(candidats)):
                continue
            candidats.extend(identificateur.candidats(element, contexte))
        except Exception as erreur:
            logger.warning("identification : source %s en échec sur %s (page %s) : %s", identificateur.nom,
                           type(element).__name__, getattr(contexte.page, "index", "?"), erreur, exc_info=True)
            if echecs is not None:
                echecs.append(f"{identificateur.nom} en échec : {erreur}")
    return candidats


def decider(candidats: list[Candidat], repli: str = "inconnu") -> Decision:
    """Combine the scores of each type (1 - Π(1 - s)) and settle the status."""
    for candidat in candidats:
        famille(candidat.type)
    candidats = [c for c in candidats if c.score >= SCORE_MIN]
    if not candidats:
        return Decision(repli, famille(repli), "non_identifie", 0.0, (), ())
    restes: dict[str, float] = {}
    for candidat in candidats:
        restes[candidat.type] = restes.get(candidat.type, 1.0) * (1.0 - min(max(candidat.score, 0.0), 1.0))
    scores = sorted(((t, round(1.0 - r, 3)) for t, r in restes.items()), key=lambda item: -item[1])
    meilleur, score = scores[0]
    second = scores[1][1] if len(scores) > 1 else 0.0
    statut = "identifie" if score >= SEUIL_IDENTIFIE and score - second >= ECART_IDENTIFIE else "ambigu"
    indices = tuple(f"{c.type}: {c.indice} ({c.score:.2f})" for c in candidats)
    return Decision(meilleur, famille(meilleur), statut, score, tuple(scores[1:1 + ALTERNATIVES_MAX]), indices)
