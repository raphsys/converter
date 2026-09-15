"""Bibliothèque de polices : reconnaître la police exacte nommée par un PDF.

Un PDF n'embarque qu'un sous-ensemble de police, dont la table cmap est souvent vide ou
absente — inutilisable pour mesurer du texte. En revanche il en donne toujours le nom
PostScript. Ce module retrouve le vrai fichier de police correspondant, dans un dossier
curaté ou parmi les polices du système, et c'est ce fichier qui fait autorité pour les
métriques et pour le nom déclaré dans le docx.

Substituer à l'aveugle vers Arial fausse les largeurs, donc la mise en page. Reconnaître
la police évite ce détour.
"""
import json
import re
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from difflib import SequenceMatcher
from pathlib import Path

from fontTools.ttLib import TTFont

EXTENSIONS_INDEXABLES = {".ttf", ".otf", ".ttc"}

FICHIER_ALIAS = Path(__file__).parent / "data" / "alias_polices.json"

# Bibliothèque livrée avec le paquet : c'est elle qui rend une conversion identique d'une
# machine à l'autre, sans dépendre de ce qui est installé localement.
DOSSIER_EMBARQUE = Path(__file__).parent / "fonts"

# Dossier d'extension, à la racine du projet. Ce que l'utilisateur y dépose l'emporte sur
# la bibliothèque embarquée.
NOM_DOSSIER_LOCAL = "fonts"

# Suffixes de fonderie accolés aux noms PostScript : ArialMT, TimesNewRomanPSMT.
# Ils ne portent aucune information de style et empêchent la correspondance.
_SUFFIXES_FONDERIE = ("psmt", "mt", "ps", "ms")
_SUFFIXES_STYLE_POSTSCRIPT = (
    ("bolditalic", "bold italic"),
    ("boldital", "bold italic"),
    ("bditalic", "bold italic"),
    ("bdit", "bold italic"),
    ("bd", "bold"),
    ("bold", "bold"),
    ("semibold", "bold"),
    ("black", "bold"),
    ("italic", "italic"),
    ("ital", "italic"),
    ("it", "italic"),
)

# Identifiants de la table `name` d'une police sfnt.
_NAME_FAMILLE = 1
_NAME_STYLE = 2
_NAME_POSTSCRIPT = 6

_WORDPERFECT_FONT_FILES = {
    "wpce08n_": ("WP-GreekCentury", "WP Greek Century", "Regular"),
    "wphv06na": ("WP-MathA", "WP MathA", "Regular"),
    "wphv07na": ("WP-MathExtendedA", "WP MathExtendedA", "Regular"),
    "wphv02n_": ("WP-Phonetic", "WP Phonetic", "Regular"),
}

# Styles équivalents, ramenés à une forme unique pour que la résolution par
# famille + style ne dépende pas du vocabulaire du fondeur.
_STYLES_EQUIVALENTS = {
    "": "regular",
    "roman": "regular",
    "book": "regular",
    "normal": "regular",
    "plain": "regular",
    "regular": "regular",
    "medium": "medium",
    "mediumit": "medium italic",
    "mediumitalic": "medium italic",
    "mediumitalicmt": "medium italic",
    "bold": "bold",
    "bd": "bold",
    "italic": "italic",
    "ita": "italic",
    "oblique": "italic",
    "boldoblique": "bold italic",
    "bolditalic": "bold italic",
    "italicbold": "bold italic",
}


@dataclass(frozen=True)
class PoliceIndexee:
    """Une police retrouvée sur le disque."""

    nom_postscript: str
    famille: str
    style: str
    chemin: Path
    source: str  # "dossier" ou "systeme"


@dataclass(frozen=True)
class ResolutionPolice:
    """Résultat détaillé d'une résolution de police."""

    demandee: str
    police: PoliceIndexee | None
    mode: str  # "exact", "famille_style", "alias", "famille", "manquante"
    alias_depuis: str | None = None
    confiance: float = 0.0


def normaliser_nom(nom_pdf: str) -> str:
    """Retire le préfixe de sous-ensemble « ABCDEF+ » que les PDF ajoutent."""
    return nom_pdf.split("+", 1)[-1] if "+" in nom_pdf else nom_pdf


@lru_cache(maxsize=1)
def _table_alias() -> tuple[dict, dict]:
    """Charge la table d'équivalences. Absente ou illisible : on continue sans."""
    try:
        donnees = json.loads(FICHIER_ALIAS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    return donnees.get("familles", {}), donnees.get("styles", {})


def _cle_famille(famille: str) -> str:
    """Ramène un nom de famille à une clé comparable : minuscules, sans ponctuation.

    Les suffixes de fonderie sont retirés, sinon « ArialMT » ne rejoint jamais « arial ».
    """
    compact = re.sub(r"[^a-z0-9]", "", famille.lower())
    for suffixe in _SUFFIXES_FONDERIE:
        if compact.endswith(suffixe) and len(compact) > len(suffixe):
            return compact[: -len(suffixe)]
    return compact


def _retirer_suffixes_fonderie(compact: str) -> str:
    courant = compact
    change = True
    while change:
        change = False
        for suffixe in _SUFFIXES_FONDERIE:
            if courant.endswith(suffixe) and len(courant) > len(suffixe):
                courant = courant[: -len(suffixe)]
                change = True
                break
    return courant


def _normaliser_style(style: str) -> str:
    compact = style.strip().lower().replace("-", "").replace("_", "").replace(" ", "")
    for suffixe in _SUFFIXES_FONDERIE:
        if compact.endswith(suffixe) and len(compact) > len(suffixe):
            compact = compact[: -len(suffixe)]
            break

    if compact in _STYLES_EQUIVALENTS:
        return _STYLES_EQUIVALENTS[compact]

    _familles, styles = _table_alias()
    if compact in styles:
        return styles[compact]

    return " ".join(style.strip().lower().split()) or "regular"


def _decouper_nom_postscript(nom: str) -> tuple[str, str]:
    """Sépare « HelveticaNeue-Bold » en famille et style.

    Les PDF utilisent le tiret, parfois la virgule (« Arial,Bold »). Sans séparateur, on
    considère que le nom entier est la famille et que le style est Regular.
    """
    for separateur in ("-", ","):
        if separateur in nom:
            famille, _, style = nom.partition(separateur)
            return famille.strip(), _normaliser_style(style)

    compact = _retirer_suffixes_fonderie(re.sub(r"[^a-z0-9]", "", nom.lower()))
    for suffixe, style in _SUFFIXES_STYLE_POSTSCRIPT:
        if compact.endswith(suffixe) and len(compact) > len(suffixe) + 2:
            return compact[: -len(suffixe)], style
    return compact or nom.strip(), "regular"


_PROBE_METRIQUE = "Hamburgefonstiv 0123456789 MWil."
_SERIF_HINTS = {
    "serif",
    "roman",
    "times",
    "garamond",
    "caslon",
    "bookman",
    "palatino",
    "baskerville",
    "schoolbook",
    "meridien",
}
_SANS_HINTS = {
    "sans",
    "arial",
    "helvetica",
    "gothic",
    "grotesk",
    "grotesque",
    "frutiger",
    "myriad",
    "officina",
    "verdana",
    "tahoma",
    "trebuchet",
    "geneva",
}
_MONO_HINTS = {"mono", "courier", "typewriter", "console", "fixed", "lettergothic"}
_SYMBOLES_HINTS = {"symbol", "ding", "wingding", "math", "phonetic", "wp"}


def _classe_nom_police(nom: str) -> str:
    cle = _cle_famille(nom)
    if any(indice in cle for indice in _SYMBOLES_HINTS):
        return "symbol"
    if any(indice in cle for indice in _MONO_HINTS):
        return "mono"
    if any(indice in cle for indice in _SERIF_HINTS):
        return "serif"
    if any(indice in cle for indice in _SANS_HINTS):
        return "sans"
    return "sans"


@lru_cache(maxsize=512)
def _signature_metrique(chemin: Path | str) -> tuple[float, ...] | None:
    try:
        police = TTFont(chemin, fontNumber=0, lazy=True)
        cmap = police.getBestCmap() or {}
        largeurs = police["hmtx"].metrics
        unites = float(police["head"].unitsPerEm)
    except Exception:  # noqa: BLE001
        return None

    signature = []
    defaut = unites * 0.5
    for caractere in _PROBE_METRIQUE:
        glyphe = cmap.get(ord(caractere))
        signature.append((largeurs[glyphe][0] if glyphe in largeurs else defaut) / unites)
    return tuple(signature)


def _distance_signature(signature: tuple[float, ...] | None, classe: str) -> float:
    if signature is None:
        return 0.18
    moyenne = sum(signature) / max(len(signature), 1)
    if classe == "mono":
        dispersion = sum(abs(v - moyenne) for v in signature) / len(signature)
        return min(0.35, dispersion)
    cible = 0.49 if classe == "serif" else 0.52
    return min(0.35, abs(moyenne - cible))


def _style_flags(style: str) -> tuple[bool, bool]:
    normal = _normaliser_style(style)
    return "bold" in normal, "italic" in normal


def _score_substitut(
    nom: str,
    famille: str,
    style: str,
    candidat: PoliceIndexee,
) -> float:
    classe_voulue = _classe_nom_police(famille or nom)
    classe_candidate = _classe_nom_police(candidat.famille)
    if classe_voulue == "symbol":
        return 0.0

    bold_voulu, italic_voulu = _style_flags(style)
    bold_candidat, italic_candidat = _style_flags(candidat.style)
    score = 0.42 if classe_candidate == classe_voulue else 0.18
    score += 0.16 if bold_voulu == bold_candidat else -0.12
    score += 0.16 if italic_voulu == italic_candidat else -0.12
    score += 0.14 * SequenceMatcher(None, _cle_famille(famille), _cle_famille(candidat.famille)).ratio()
    score += max(0.0, 0.12 - _distance_signature(_signature_metrique(candidat.chemin), classe_voulue))
    if candidat.source == "dossier":
        score += 0.03
    return max(0.0, min(0.86, score))


def _substitut_dynamique(
    nom: str,
    famille: str,
    style: str,
    candidats: list[PoliceIndexee] | tuple[PoliceIndexee, ...] | object,
) -> tuple[PoliceIndexee, float] | None:
    meilleur: tuple[PoliceIndexee, float] | None = None
    vus: set[Path] = set()
    for candidat in candidats:
        if candidat.chemin in vus:
            continue
        vus.add(candidat.chemin)
        score = _score_substitut(nom, famille, style, candidat)
        if meilleur is None or score > meilleur[1]:
            meilleur = (candidat, score)
    if meilleur is None or meilleur[1] < 0.52:
        return None
    return meilleur


@dataclass
class Bibliotheque:
    """Index des polices disponibles, interrogeable par nom PostScript."""

    par_nom: dict[str, PoliceIndexee] = field(default_factory=dict)
    par_famille_style: dict[tuple[str, str], PoliceIndexee] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.par_nom)

    def ajouter(self, police: PoliceIndexee, prioritaire: bool) -> None:
        """Insère une police. `prioritaire` autorise l'écrasement d'une entrée existante."""
        cle_nom = police.nom_postscript.lower()
        if prioritaire or cle_nom not in self.par_nom:
            self.par_nom[cle_nom] = police

        cle_famille = (police.famille.lower(), _normaliser_style(police.style))
        if prioritaire or cle_famille not in self.par_famille_style:
            self.par_famille_style[cle_famille] = police

    def resoudre(self, nom_pdf: str) -> PoliceIndexee | None:
        """Retrouve la police correspondant au nom relevé dans un PDF.

        Cascade, du plus sûr au plus permissif : nom PostScript exact, puis famille et
        style, puis famille seule en Regular. Aucune correspondance approximative au-delà :
        mieux vaut retomber sur une substitution explicite qu'inventer un rapprochement.
        """
        return self.resoudre_detail(nom_pdf).police

    def resoudre_detail(self, nom_pdf: str) -> ResolutionPolice:
        """Retrouve une police et indique si la correspondance est stricte ou substituée."""
        nom = normaliser_nom(nom_pdf).strip()
        if not nom:
            return ResolutionPolice(nom_pdf, None, "manquante", confiance=0.0)

        direct = self.par_nom.get(nom.lower())
        if direct is not None:
            return ResolutionPolice(nom, direct, "exact", confiance=1.0)

        famille, style = _decouper_nom_postscript(nom)
        par_style = self.par_famille_style.get((famille.lower(), style))
        if par_style is not None:
            return ResolutionPolice(nom, par_style, "famille_style", confiance=0.98)

        # Équivalence métrique : la famille nommée par le PDF n'est pas installée, mais un
        # clone de mêmes chasses l'est. La mise en page reste juste, le dessin diffère peu.
        familles, _styles = _table_alias()
        cible = familles.get(_cle_famille(nom)) or familles.get(_cle_famille(famille))
        if cible is not None:
            par_alias = self.par_famille_style.get((cible.lower(), style))
            if par_alias is not None:
                return ResolutionPolice(nom, par_alias, "alias", alias_depuis=famille, confiance=0.92)
            if style in {"medium", "medium italic"}:
                style_famille = "italic" if style.endswith("italic") else "regular"
                par_alias = self.par_famille_style.get((f"{cible} Medium".lower(), style_famille))
                if par_alias is not None:
                    return ResolutionPolice(nom, par_alias, "alias", alias_depuis=famille, confiance=0.88)
            par_alias = self.par_famille_style.get((cible.lower(), "regular"))
            if par_alias is not None:
                return ResolutionPolice(nom, par_alias, "alias", alias_depuis=famille, confiance=0.84)

        par_famille = self.par_famille_style.get((famille.lower(), "regular"))
        if par_famille is not None:
            return ResolutionPolice(nom, par_famille, "famille", confiance=0.76)

        dynamique = _substitut_dynamique(nom, famille, style, self.par_famille_style.values())
        if dynamique is not None:
            police, confiance = dynamique
            return ResolutionPolice(nom, police, "dynamique", alias_depuis=famille, confiance=confiance)

        return ResolutionPolice(nom, None, "manquante", confiance=0.0)


def _lire_noms_sfnt(chemin: Path) -> tuple[str, str, str] | None:
    """Lit (nom PostScript, famille, style) dans la table `name`. None si illisible."""
    try:
        police = TTFont(chemin, fontNumber=0, lazy=True)
        table = police["name"]
    except Exception:  # noqa: BLE001 — un fichier de police cassé ne doit rien interrompre
        return None

    def _valeur(identifiant):
        entree = table.getDebugName(identifiant)
        return entree.strip() if entree else ""

    nom_postscript = _valeur(_NAME_POSTSCRIPT)
    famille = _valeur(_NAME_FAMILLE)
    style = _valeur(_NAME_STYLE)

    if not nom_postscript:
        if not famille:
            return None
        nom_postscript = famille.replace(" ", "")
        if style and style.lower() != "regular":
            nom_postscript += "-" + style.replace(" ", "")

    return nom_postscript, famille or nom_postscript, style or "Regular"


def _alias_wordperfect_depuis_fichier(chemin: Path) -> tuple[str, str, str] | None:
    return _WORDPERFECT_FONT_FILES.get(chemin.stem.lower())


def _indexer_dossier(dossier: Path):
    """Indexe récursivement les polices d'un dossier, en les ouvrant une à une."""
    if not dossier.is_dir():
        return

    for chemin in sorted(dossier.rglob("*")):
        if not chemin.is_file() or chemin.suffix.lower() not in EXTENSIONS_INDEXABLES:
            continue
        noms = _alias_wordperfect_depuis_fichier(chemin) or _lire_noms_sfnt(chemin)
        if noms is None:
            continue
        nom_postscript, famille, style = noms
        yield PoliceIndexee(
            nom_postscript=nom_postscript,
            famille=famille,
            style=style,
            chemin=chemin,
            source="dossier",
        )


@lru_cache(maxsize=1)
def _lignes_fontconfig() -> tuple[str, ...]:
    """Interroge fontconfig, qui connaît déjà le nom PostScript de chaque police.

    Passer par son cache évite d'ouvrir plusieurs centaines de fichiers avec fontTools.
    """
    try:
        resultat = subprocess.run(
            ["fc-list", "--format", "%{file}|%{postscriptname}|%{family}|%{style}\n"],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    return tuple(resultat.stdout.decode(errors="replace").splitlines())


def _indexer_systeme():
    """Indexe les polices installées, via fontconfig."""
    for ligne in _lignes_fontconfig():
        parts = ligne.split("|")
        if len(parts) != 4:
            continue
        fichier, nom_postscript, famille, style = (p.strip() for p in parts)

        chemin = Path(fichier)
        if chemin.suffix.lower() not in EXTENSIONS_INDEXABLES:
            continue
        alias_wordperfect = _alias_wordperfect_depuis_fichier(chemin)
        if alias_wordperfect is not None:
            nom_postscript, famille, style = alias_wordperfect
        elif not nom_postscript or nom_postscript == "(null)":
            continue

        # fontconfig renvoie les variantes localisées séparées par des virgules.
        famille = famille.split(",")[0].strip()
        style = style.split(",")[0].strip()

        yield PoliceIndexee(
            nom_postscript=nom_postscript,
            famille=famille or nom_postscript,
            style=style or "Regular",
            chemin=chemin,
            source="systeme",
        )


def dossiers_par_defaut() -> list[Path]:
    """Bibliothèque embarquée, puis dossier d'extension du projet s'il existe."""
    candidats = [DOSSIER_EMBARQUE, Path.cwd() / NOM_DOSSIER_LOCAL]
    return [dossier for dossier in candidats if dossier.is_dir()]


def construire(dossiers=None, inclure_systeme: bool = True) -> Bibliotheque:
    """Construit l'index des polices disponibles.

    Ordre d'indexation, du moins au plus prioritaire : polices installées sur la machine,
    bibliothèque embarquée dans le paquet, puis dossiers d'extension. Le dernier inscrit
    l'emporte, de sorte qu'une police déposée par l'utilisateur prime sur celle livrée,
    qui prime elle-même sur celle du système.

    `dossiers=None` utilise les emplacements par défaut ; passer une liste, même vide,
    la remplace intégralement.
    """
    bibliotheque = Bibliotheque()

    if inclure_systeme:
        for police in _indexer_systeme():
            bibliotheque.ajouter(police, prioritaire=False)

    for dossier in dossiers_par_defaut() if dossiers is None else dossiers:
        for police in _indexer_dossier(Path(dossier)):
            bibliotheque.ajouter(police, prioritaire=True)

    return bibliotheque
