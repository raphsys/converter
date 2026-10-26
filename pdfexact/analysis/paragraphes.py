"""Joining text rows into paragraphs: geometry always, then the layout zone or the meaning.

Two rows (or groups of rows) belong to one paragraph when the lower one sits right under
the upper one, in the same column, with nothing between them (a drawing, a blank row, a
validated paragraph), with the same typography (size, weight, slant, colour), frame role
and orientation, and either:
- they lie in the same PP-DocLayout zone that holds a single paragraph, or
- the sentence of the upper one runs on into the lower one (vysi's semantic
  continuation, ``_is_semantic_continuation``).
A row opening with a list marker always starts a new paragraph.
"""
from __future__ import annotations

import re

# Geometry: the lower row starts at most this many row heights under the upper one, and
# the two overlap horizontally over this share of the narrower.
ECART_MAX_HAUTEURS = 1.0
CHEVAUCHEMENT_MIN = 0.5
RECOUVREMENT_ZONE = 0.5
# vysi: a size gap above max(1.2 pt, 18 %) is another typography.
ECART_TAILLE_PT = 1.2
ECART_TAILLE_PART = 0.18
# vysi: a row this long without a terminal mark runs on.
LONGUEUR_LIGNE_PLEINE = 80

# PP-DocLayout labels whose zone holds one paragraph (a table of contents, a bibliography,
# headers or footers hold several entries).
ZONES_UN_PARAGRAPHE = frozenset({
    "text", "paragraph_title", "doc_title", "abstract", "figure_title", "table_title", "chart_title", "aside_text",
})

# vysi's _SEMANTIC_TERMINAL_RE and _SEMANTIC_CONTINUATION_START_RE, with French connectors.
# Connectors are matched in lower case: a capital opens a sentence (Title Case rows are
# joined by their layout zone instead).
_TERMINAL = re.compile(r"""[.!?]["'’”)\]»]*$""")
_DEBUT_CONTINUATION = re.compile(
    r"^(?:and\b|or\b|but\b|nor\b|yet\b|so\b|"
    r"which\b|that\b|whose\b|where\b|when\b|while\b|than\b|"
    r"of\b|to\b|from\b|for\b|with\b|without\b|in\b|on\b|as\b|"
    r"including\b|following\b|because\b|although\b|however\b|"
    r"et\b|ou\b|mais\b|donc\b|ni\b|car\b|qui\b|que\b|qu['’]|dont\b|où\b|"
    r"de\b|du\b|des\b|d['’]|à\b|au\b|aux\b|pour\b|avec\b|sans\b|dans\b|sur\b|par\b|en\b|comme\b|"
    r"[,;:)\]])",
)
_FIN_PORTEUSE = re.compile(r"[-,/(]$")
_MARQUE_LISTE = re.compile(r"^\s*(?:[•●▪◦‣\-–—*]|\(?\d{1,3}[.)]|\(?[a-zA-Z][.)])\s")


def continuation_semantique(gauche: str, droite: str) -> bool:
    """The sentence of ``gauche`` runs on into ``droite`` (vysi's semantic continuation)."""
    gauche, droite = " ".join(gauche.split()), " ".join(droite.split())
    if not gauche or not droite or _TERMINAL.search(gauche):
        return False
    porteuse = bool(_FIN_PORTEUSE.search(gauche) or droite[:1].islower() or _DEBUT_CONTINUATION.search(droite)
                    or gauche.count("(") > gauche.count(")"))
    return porteuse or len(gauche) >= LONGUEUR_LIGNE_PLEINE


def _texte(unite) -> str:
    return "".join(span.texte for ligne in unite.lignes for span in ligne.spans)


def _typographie(unite):
    span = next((s for ligne in unite.lignes for s in ligne.spans if s.texte.strip()), None)
    if span is None:
        return None
    return (span.size_pt, bool(getattr(span.police, "gras", False)), bool(getattr(span.police, "italique", False)),
            str(span.couleur).casefold())


def meme_typographie(haute, basse) -> bool:
    a, b = _typographie(haute), _typographie(basse)
    if a is None or b is None:
        return False
    if a[0] > 0 and b[0] > 0 and abs(a[0] - b[0]) > max(ECART_TAILLE_PT, a[0] * ECART_TAILLE_PART):
        return False
    return a[1:] == b[1:]


def _intersection(a, b) -> int:
    return max(0, min(a.x1, b.x1) - max(a.x0, b.x0)) * max(0, min(a.y1, b.y1) - max(a.y0, b.y0))


def adjacentes(haute, basse, obstacles=()) -> bool:
    """``basse`` sits right under ``haute``, in its column, with nothing drawn between them."""
    a, b = haute.bbox, basse.bbox
    hauteur = max(a.hauteur, 1)
    ecart = b.y0 - a.y1
    if ecart < -hauteur / 2 or ecart > ECART_MAX_HAUTEURS * hauteur:
        return False
    chevauchement = min(a.x1, b.x1) - max(a.x0, b.x0)
    if chevauchement < CHEVAUCHEMENT_MIN * max(min(a.largeur, b.largeur), 1):
        return False
    if ecart <= 0:
        return True
    x0, x1 = max(a.x0, b.x0), min(a.x1, b.x1)
    # Something lies between the two rows unless it holds both (a background, a box).
    return not any(o.x0 < x1 and o.x1 > x0 and o.y0 < b.y0 and o.y1 > a.y1
                   and not (_contient(o, a) and _contient(o, b)) for o in obstacles)


def _contient(exterieur, interieur) -> bool:
    return (exterieur.x0 <= interieur.x0 and exterieur.y0 <= interieur.y0
            and exterieur.x1 >= interieur.x1 and exterieur.y1 >= interieur.y1)


def _zone(unite, zones) -> int | None:
    """Index of the layout zone holding the row, if one does."""
    aire = max(unite.bbox.largeur, 0) * max(unite.bbox.hauteur, 0) or 1
    index, part = max(((i, _intersection(unite.bbox, z.bbox)) for i, z in enumerate(zones)),
                      key=lambda item: item[1], default=(None, 0))
    return index if part / aire >= RECOUVREMENT_ZONE else None


def _zone_un_paragraphe(unite, zones) -> int | None:
    index = _zone(unite, zones)
    return index if index is not None and str(zones[index].label).casefold() in ZONES_UN_PARAGRAPHE else None


def _horizontale(unite) -> bool:
    return getattr(unite, "orientation", "horizontal") in (None, "horizontal") and not getattr(unite, "angle_deg", 0)


def _bloc_source_multiligne(unite) -> bool:
    return (getattr(unite, "presentation", None) or {}).get("source_visible_line_count", 1) > 1


def meme_paragraphe(haute, basse, zones=(), obstacles=()) -> bool:
    if not (_horizontale(haute) and _horizontale(basse)):
        return False
    if not adjacentes(haute, basse, obstacles) or not meme_typographie(haute, basse):
        return False
    if getattr(haute, "layout_frame_role", None) != getattr(basse, "layout_frame_role", None):
        return False
    if (getattr(basse, "presentation", None) or {}).get("boundary_before"):
        return False  # an approved boundary is never crossed
    texte_bas = _texte(basse)
    if _MARQUE_LISTE.match(texte_bas):
        return False
    zone = _zone_un_paragraphe(haute, zones)
    if zone is not None and zone == _zone_un_paragraphe(basse, zones):
        return True
    # Rows of a figure, a table, a table of contents… are labels or entries, not prose.
    if any(_zone(u, zones) is not None and _zone_un_paragraphe(u, zones) is None for u in (haute, basse)):
        return False
    # A source block of several rows is already a native paragraph: meaning alone does not
    # extend it into another block (its layout zone can).
    autre_bloc = (haute.presentation or {}).get("segmentation_owner") != (basse.presentation or {}).get("segmentation_owner")
    if autre_bloc and (_bloc_source_multiligne(haute) or _bloc_source_multiligne(basse)):
        return False
    return continuation_semantique(_texte(haute), texte_bas)


def fusionner_paragraphes(groupes, zones=(), obstacles=()) -> list[list]:
    """Join the groups of rows that continue one another; each group keeps its rows."""
    ordre = sorted((sorted(groupe, key=lambda u: (u.bbox.y0, u.bbox.x0)) for groupe in groupes if groupe),
                   key=lambda groupe: (groupe[0].bbox.y0, groupe[0].bbox.x0))
    resultat: list[list] = []
    for groupe in ordre:
        haut = groupe[0]
        suites = [(haut.bbox.y0 - max(precedent, key=lambda u: u.bbox.y1).bbox.y1, index)
                  for index, precedent in enumerate(resultat)
                  if meme_paragraphe(max(precedent, key=lambda u: u.bbox.y1), haut, zones, obstacles)]
        if suites:
            _, index = min(suites)
            resultat[index] = sorted([*resultat[index], *groupe], key=lambda u: (u.bbox.y0, u.bbox.x0))
        else:
            resultat.append(groupe)
    return resultat
