"""Socle extensible de l'identification : candidats, décision, identificateurs, registre.

Ajouter une identité : déclarer le type dans le référentiel, puis enregistrer un
``Identificateur`` qui propose ce type (``Registre.enregistrer``). Le cœur ne change pas.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from pdfexact.identification.referentiel import famille

# Status thresholds of a decision.
SEUIL_IDENTIFIE = 0.6
ECART_IDENTIFIE = 0.15
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
    """What rules may know about the page of an element."""

    page: object
    premiere_page: bool
    corps_pt: float
    taille_max_pt: float
    boites_texte: tuple = ()
    boites_ocr: tuple = ()
    extra: dict = field(default_factory=dict)


@runtime_checkable
class Identificateur(Protocol):
    """A source of identification: proposes candidate types for some natures of objects.

    ``natures``: the object natures it handles ("text", "image", "shape", "table", "link").
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


def decider(candidats: list[Candidat], repli: str = "inconnu") -> Decision:
    """Combine the scores of each type (1 - Π(1 - s)) and settle the status."""
    for candidat in candidats:
        famille(candidat.type)
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
