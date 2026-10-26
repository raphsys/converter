"""Expressions inside a text, located by characters.

The AI finds them (GLiNER, ``gliner.py``); the PDF itself flags note calls (superscript).
Extensible: a ``DetecteurExpression`` finds spans of one or more types in the text of an
element; ``RegistreExpressions.enregistrer`` plugs a new one in.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pdfexact.identification.referentiel import famille


@dataclass(frozen=True)
class Trouvaille:
    debut: int
    fin: int
    type: str
    confiance: float
    indice: str


@runtime_checkable
class DetecteurExpression(Protocol):
    nom: str

    def trouver(self, element, texte: str) -> list[Trouvaille]: ...


class RegistreExpressions:
    def __init__(self, detecteurs=()):
        self._detecteurs: list[DetecteurExpression] = []
        for detecteur in detecteurs:
            self.enregistrer(detecteur)

    def enregistrer(self, detecteur: DetecteurExpression) -> None:
        if not isinstance(detecteur, DetecteurExpression):
            raise TypeError(f"pas un détecteur d'expressions : {detecteur!r}")
        if any(existant.nom == detecteur.nom for existant in self._detecteurs):
            raise ValueError(f"détecteur déjà enregistré : {detecteur.nom}")
        self._detecteurs.append(detecteur)

    def __iter__(self):
        return iter(self._detecteurs)

    @property
    def noms(self) -> tuple[str, ...]:
        return tuple(d.nom for d in self._detecteurs)


def _spans_positionnes(element):
    """(start, end, span, line) of every span in the element text."""
    position = 0
    for numero, ligne in enumerate(getattr(element, "lignes", ())):
        if numero:
            position += 1  # the newline joining lines
        for span in ligne.spans:
            yield position, position + len(span.texte), span, ligne
            position += len(span.texte)


class DetecteurAppelsNote:
    """A span the PDF flags as superscript is a note call (a native fact, not a size rule)."""

    nom = "appels-note"

    def trouver(self, element, texte):
        resultat = []
        for debut, fin, span, _ligne in _spans_positionnes(element):
            contenu = span.texte.strip()
            if span.exposant and contenu:
                gauche = len(span.texte) - len(span.texte.lstrip())
                resultat.append(Trouvaille(debut + gauche, debut + gauche + len(contenu), "appel_de_note", 0.9,
                                           "exposant du PDF"))
        return resultat


def detecteurs_par_defaut(model_root=None, *, gliner="auto") -> RegistreExpressions:
    """GLiNER when the model is present (or the given detector), then the native note calls."""
    if gliner == "auto":
        from pdfexact.identification.gliner import creer_detecteur_gliner

        gliner = creer_detecteur_gliner(model_root)
    return RegistreExpressions([d for d in (gliner, DetecteurAppelsNote()) if d is not None])


def _texte(element) -> str:
    return "\n".join("".join(span.texte for span in ligne.spans) for ligne in getattr(element, "lignes", ()))


def trouver(element, registre: RegistreExpressions) -> list[Trouvaille]:
    """Every expression of the element; where two overlap, the longest wins."""
    texte = _texte(element)
    candidates = [t for detecteur in registre for t in detecteur.trouver(element, texte) if t.fin > t.debut]
    candidates.sort(key=lambda t: (-(t.fin - t.debut), -t.confiance, t.debut))
    gardees: list[Trouvaille] = []
    for candidate in candidates:
        if all(candidate.fin <= g.debut or candidate.debut >= g.fin for g in gardees):
            famille(candidate.type)
            gardees.append(candidate)
    return sorted(gardees, key=lambda t: t.debut)
