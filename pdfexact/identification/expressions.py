"""Expressions inside a text, located by characters (formulas, protected tokens, note calls).

Extensible: a ``DetecteurExpression`` finds spans of one or more types in the text of an
element; ``RegistreExpressions.enregistrer`` plugs a new one in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pdfexact.identification.formules import formules_en_ligne
from pdfexact.identification.referentiel import famille

# A text with more capital letters than this is written in capitals: no acronyms there.
RATIO_CAPITALES = 0.6
# A note call is smaller than its line's body.
RATIO_TAILLE_APPEL = 0.75
RATIO_MONOSPACE_TEXTE = 0.6
_MONOSPACE = ("mono", "courier", "consolas", "menlo", "code")


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


class DetecteurMotif:
    """One regular expression, one type."""

    def __init__(self, nom: str, type_: str, motif: str, confiance: float, drapeaux: int = 0):
        famille(type_)
        self.nom, self.type, self.confiance = nom, type_, confiance
        self._motif = re.compile(motif, drapeaux)

    def trouver(self, element, texte):
        return [Trouvaille(m.start(), m.end(), self.type, self.confiance, self.nom) for m in self._motif.finditer(texte)]


class DetecteurFormules:
    nom = "formules"

    def trouver(self, element, texte):
        return [Trouvaille(a, b, "formule_en_ligne", 0.75, "symboles mathématiques ou espèce chimique")
                for a, b in formules_en_ligne(texte)]


class DetecteurAcronymes:
    nom = "acronymes"
    _motif = re.compile(r"\b[A-Z][A-Z0-9]{1,6}s?\b")
    _romain = re.compile(r"^[IVXLCDM]+$")

    def trouver(self, element, texte):
        lettres = [c for c in texte if c.isalpha()]
        if lettres and sum(c.isupper() for c in lettres) / len(lettres) > RATIO_CAPITALES:
            return []
        return [Trouvaille(m.start(), m.end(), "acronyme", 0.6, "mot en capitales")
                for m in self._motif.finditer(texte) if not self._romain.match(m.group(0))]


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
    nom = "appels-note"
    _motif = re.compile(r"^\s*(\d{1,3}|[*†‡§])\s*$")

    def trouver(self, element, texte):
        resultat = []
        for debut, fin, span, ligne in _spans_positionnes(element):
            if not self._motif.match(span.texte):
                continue
            corps = max((s.size_pt for s in ligne.spans if s.texte.strip()), default=span.size_pt)
            if span.exposant or span.size_pt <= RATIO_TAILLE_APPEL * corps:
                gauche = len(span.texte) - len(span.texte.lstrip())
                droite = len(span.texte) - len(span.texte.rstrip())
                resultat.append(Trouvaille(debut + gauche, fin - droite, "appel_de_note", 0.75, "chiffre en exposant"))
        return resultat


class DetecteurCodeEnLigne:
    nom = "code-en-ligne"

    def trouver(self, element, texte):
        spans = list(_spans_positionnes(element))
        mono = [(d, f, s) for d, f, s, _ in spans if any(m in s.police.famille.casefold() for m in _MONOSPACE)]
        total = sum(len(s.texte.strip()) for _, _, s, _ in spans) or 1
        if not mono or sum(len(s.texte.strip()) for _, _, s in mono) / total >= RATIO_MONOSPACE_TEXTE:
            return []
        resultat = []
        for debut, fin, span in mono:
            gauche = len(span.texte) - len(span.texte.lstrip())
            droite = len(span.texte) - len(span.texte.rstrip())
            if fin - droite > debut + gauche:
                resultat.append(Trouvaille(debut + gauche, fin - droite, "code_en_ligne", 0.65, "police à chasse fixe"))
        return resultat


_MOIS = (r"(?:janv|févr|fevr|mars|avr|mai|juin|juil|août|aout|sept|oct|nov|déc|dec|jan|feb|mar|apr|may|jun|jul|aug|sep)"
         r"[a-zéû]*\.?")
_UNITES = ["km/h", "m/s", "mph", "km²", "m²", "m³", "cm²", "km", "cm", "mm", "µm", "nm", "kg", "mg", "min", "kHz", "MHz",
           "GHz", "Hz", "kW", "MW", "kV", "mV", "mA", "kJ", "kPa", "MPa", "hPa", "Pa", "mL", "ml", "kB", "MB", "GB", "TB",
           "ft", "mi", "ha", "mbar", "bar", "ppm", "dB", "m", "g", "h", "W", "V", "A", "J", "N", "L", "l"]
_GRANDEUR = (r"(?<![\w.])\d+(?:[.,]\d+)*(?:\s?(?:%|‰|°\s?[CF])|\s?(?:"
             + "|".join(re.escape(u) for u in _UNITES) + r")(?![\w]))")


def detecteurs_par_defaut() -> RegistreExpressions:
    return RegistreExpressions([
        DetecteurMotif("url", "url", r"\b(?:https?://|www\.)[^\s<>()\"']*[^\s<>()\"'.,;:!?]", 0.95),
        DetecteurMotif("email", "email", r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b", 0.95),
        DetecteurMotif("doi", "identifiant", r"\b10\.\d{4,9}/[^\s\"'<>]*[^\s\"'<>.,;:]", 0.9),
        DetecteurMotif("isbn", "identifiant", r"\bISBN(?:-1[03])?:?\s*\d[\d -]{8,15}[\dXx]\b", 0.9),
        DetecteurMotif("date", "date",
                       r"\b(?:\d{1,2}[/.-]\d{1,2}[/.-](?:\d{4}|\d{2})|\d{4}-\d{2}-\d{2}|\d{1,2}\s+" + _MOIS + r"\s+\d{4}"
                       r"|(?:January|February|March|April|May|June|July|August|September|October|November|December)"
                       r"\s+\d{1,2},?\s+\d{4})\b", 0.8, re.IGNORECASE),
        DetecteurMotif("grandeur", "grandeur", _GRANDEUR, 0.7),
        DetecteurAcronymes(),
        DetecteurFormules(),
        DetecteurAppelsNote(),
        DetecteurCodeEnLigne(),
    ])


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
