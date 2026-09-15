"""Polices : du nom relevé dans le PDF aux métriques réelles.

Le PDF nomme ses polices mais n'embarque que des sous-ensembles inexploitables. La
bibliothèque (pdfexact.fontlib) retrouve le vrai fichier ; ce module en tire les trois
grandeurs dont le writer a besoin :

- la largeur rendue d'une chaîne, pour corriger la dérive horizontale ;
- l'ascendante, pour que la baseline tombe au bon endroit ;
- la descendante, qui fixe la hauteur de ligne exacte imposée à Word.

Ces métriques sont celles de la police **déclarée dans le docx**, pas celles du PDF :
c'est avec elles que Word composera, donc c'est elles qui doivent servir au calcul.
"""
from functools import lru_cache

from fontTools.ttLib import TTFont

from pdfexact.fontlib import Bibliotheque, construire, normaliser_nom
from pdfexact.ir import FontAsset

# Proportions de repli quand aucune police n'a été retrouvée. Elles ne servent qu'à ne pas
# lever d'exception : une police non reconnue est signalée dans le rapport de conversion.
ASCENDANTE_DEFAUT = 0.8
DESCENDANTE_DEFAUT = -0.2
LARGEUR_MOYENNE_DEFAUT = 0.5


def _famille_de_repli(nom_postscript: str) -> str:
    """Nom de famille lisible tiré du nom PostScript, quand rien n'a été retrouvé."""
    for separateur in ("-", ","):
        if separateur in nom_postscript:
            return nom_postscript.split(separateur, 1)[0]
    return nom_postscript


def collecter_polices(doc, bibliotheque: Bibliotheque | None = None) -> dict[str, FontAsset]:
    """Recense les polices du document et les relie à la bibliothèque.

    La clé est le nom PostScript sans préfixe de sous-ensemble : c'est le seul point de
    jonction avec les spans, dont le dictionnaire ne porte aucun xref.
    """
    if bibliotheque is None:
        bibliotheque = construire()

    assets: dict[str, FontAsset] = {}
    for numero_page in range(doc.page_count):
        for entree in doc[numero_page].get_fonts(full=True):
            nom_base = entree[3]
            font_id = normaliser_nom(nom_base)
            if font_id in assets:
                continue

            resolution = bibliotheque.resoudre_detail(nom_base)
            trouvee = resolution.police
            assets[font_id] = FontAsset(
                font_id=font_id,
                famille=trouvee.famille if trouvee else _famille_de_repli(font_id),
                donnees=None,
                extension="",
                embarquee=False,
                chemin=trouvee.chemin if trouvee else None,
                reconnue=trouvee is not None,
                mode_resolution=resolution.mode,
                confiance_resolution=resolution.confiance,
                alias_resolution=resolution.police.famille if trouvee and resolution.mode != "exact" else None,
            )

    return assets


@lru_cache(maxsize=128)
def _metriques(chemin) -> tuple[dict, dict, int] | None:
    """Retourne (cmap, largeurs par glyphe, unités par cadratin) ou None."""
    try:
        police = TTFont(chemin, fontNumber=0, lazy=True)
        return police.getBestCmap() or {}, police["hmtx"].metrics, police["head"].unitsPerEm
    except Exception:  # noqa: BLE001 — une police illisible retombe sur les approximations
        return None


@lru_cache(maxsize=128)
def _ascendante_descendante(chemin) -> tuple[float, float] | None:
    """Ascendante et descendante en fraction de cadratin, ou None."""
    try:
        police = TTFont(chemin, fontNumber=0, lazy=True)
        unites = police["head"].unitsPerEm
        entete = police["hhea"]
        return entete.ascent / unites, entete.descent / unites
    except Exception:  # noqa: BLE001
        return None


def mesurer_largeur_pt(texte: str, asset: FontAsset, size_pt: float) -> float:
    """Largeur rendue de `texte`, en points, avec la police déclarée dans le docx."""
    if not texte:
        return 0.0

    donnees = _metriques(asset.chemin) if asset.chemin else None
    if donnees is None:
        return len(texte) * size_pt * LARGEUR_MOYENNE_DEFAUT

    cmap, largeurs, unites = donnees
    defaut = unites // 2

    total = 0
    for caractere in texte:
        glyphe = cmap.get(ord(caractere))
        total += largeurs[glyphe][0] if glyphe in largeurs else defaut

    return total / unites * size_pt


def ascendante_pt(asset: FontAsset, size_pt: float) -> float:
    """Hauteur au-dessus de la baseline, en points."""
    valeurs = _ascendante_descendante(asset.chemin) if asset.chemin else None
    fraction = valeurs[0] if valeurs else ASCENDANTE_DEFAUT
    return fraction * size_pt


def descendante_pt(asset: FontAsset, size_pt: float) -> float:
    """Profondeur sous la baseline, en points. Valeur positive."""
    valeurs = _ascendante_descendante(asset.chemin) if asset.chemin else None
    fraction = valeurs[1] if valeurs else DESCENDANTE_DEFAUT
    return abs(fraction) * size_pt
