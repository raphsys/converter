"""Formulas: mathematical, scientific and chemical expressions, never translated.

Shared by block identification (a whole text element is a formula) and by inline
identification (a formula inside a sentence, located by characters).
"""
from __future__ import annotations

import re

# Relations, operators and symbols that only occur in formulas.
SYMBOLES_FORTS = set("=≠≈≡≤≥±∓×÷·∑∏∫∮∂∇√∞∝∈∉⊂⊃⊆⊇∪∩∀∃→←↔⇒⇔⇌⟶∆")
GRECQUES = set("αβγδεζηθικλμνξοπρστυφχψωΓΔΘΛΞΠΣΦΨΩ")
INDICES = set("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻₀₁₂₃₄₅₆₇₈₉₊₋")
# Fonts made for mathematics (TeX, Symbol, STIX, Cambria Math…).
POLICES_MATH = ("cmmi", "cmsy", "cmex", "msam", "msbm", "symbol", "stix", "cambria math", "mathjax", "euclid",
                "mt extra", "math")
# Known function names; other words of a formula are short variables.
FONCTIONS = {"sin", "cos", "tan", "log", "ln", "exp", "lim", "max", "min", "det", "sup", "inf", "arg", "mod"}
ELEMENTS = set("""H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr
Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re
Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr""".split())
# Above these ratios a text element is a formula.
_RATIO_POLICE_MATH = 0.5
_SYMBOLES_MIN = 2

_CHIMIQUE = re.compile(r"(?<![\w])((?:[A-Z][a-z]?[0-9₀-₉]*)+(?:[⁰-⁹]*[⁺⁻])?)(?![\w])")
_SYMBOLE = re.compile(r"[A-Z][a-z]?")
_JETON = re.compile(r"\s+|[^\W_]+[⁰-⁹₀-₉⁺⁻′″]*|\S")
_OPERATEURS = set("+-−*/^_()[]{}|<>")
_PONCTUATION = set(".,;:")


def police_math(nom: str) -> bool:
    nom = nom.casefold()
    return any(marque in nom for marque in POLICES_MATH)


def est_formule_bloc(texte: str, polices: list[tuple[str, int]]) -> bool:
    """A whole text element written in math fonts, or made of formula symbols.

    ``polices``: (font name, number of characters) of the element.
    """
    total = sum(n for _, n in polices) or 1
    if sum(n for nom, n in polices if police_math(nom)) / total >= _RATIO_POLICE_MATH:
        return True
    symboles = sum(1 for c in texte if c in SYMBOLES_FORTS or c in GRECQUES)
    mots = len(re.findall(r"[^\W\d_]{4,}", texte))
    return symboles >= _SYMBOLES_MIN and mots <= max(2, symboles // 2)


def _chimique(candidat: str) -> bool:
    symboles = _SYMBOLE.findall(candidat)
    if len(symboles) < 2 or any(s not in ELEMENTS for s in symboles):
        return False
    # A formula carries a count, a charge or a two-letter element (NaCl);
    # this keeps acronyms such as "USGS" or "IN" out.
    return bool(re.search(r"[0-9₀-₉⁺⁻]", candidat) or any(len(s) == 2 for s in symboles))


def _nature_jeton(jeton: str) -> str | None:
    """'fort' anchors a formula; 'membre' may extend it; None is ordinary prose."""
    if any(c in SYMBOLES_FORTS or c in GRECQUES or c in INDICES for c in jeton):
        return "fort"
    if jeton in _OPERATEURS or jeton in _PONCTUATION or re.fullmatch(r"\d+(?:[.,]\d+)?", jeton):
        return "membre"
    if (len(jeton) == 1 and jeton.isalpha()) or jeton.casefold() in FONCTIONS or re.fullmatch(r"[A-Za-z]\d+", jeton):
        return "membre"
    # A chemical species with its coefficient (2H2O, O2) inside a reaction.
    especes = re.fullmatch(r"\d*((?:[A-Z][a-z]?\d*)+)", jeton)
    if especes and re.search(r"\d", especes.group(1)) and all(s in ELEMENTS for s in _SYMBOLE.findall(especes.group(1))):
        return "membre"
    return None


def formules_en_ligne(texte: str) -> list[tuple[int, int]]:
    """(start, end) character spans of formulas inside a text."""
    jetons = [(m.start(), m.end(), m.group(0)) for m in _JETON.finditer(texte)]
    natures = [None if j.isspace() else _nature_jeton(j) for _, _, j in jetons]
    spans, i = [], 0
    while i < len(jetons):
        if natures[i] != "fort":
            i += 1
            continue
        gauche = droite = i
        while gauche > 0 and (jetons[gauche - 1][2].isspace() or natures[gauche - 1]):
            gauche -= 1
        while droite + 1 < len(jetons) and (jetons[droite + 1][2].isspace() or natures[droite + 1]):
            droite += 1
        # Trim spaces and sentence punctuation at both ends.
        while gauche < droite and (jetons[gauche][2].isspace() or jetons[gauche][2] in _PONCTUATION):
            gauche += 1
        while droite > gauche and (jetons[droite][2].isspace() or jetons[droite][2] in _PONCTUATION):
            droite -= 1
        if sum(1 for k in range(gauche, droite + 1) if natures[k]) >= 2:
            spans.append((jetons[gauche][0], jetons[droite][1]))
        i = droite + 1
    for match in _CHIMIQUE.finditer(texte):
        if _chimique(match.group(1)):
            spans.append((match.start(1), match.end(1)))
    return spans
