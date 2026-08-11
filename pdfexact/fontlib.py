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
_SUFFIXES_FONDERIE = ("psmt", "mt", "ps")

# Identifiants de la table `name` d'une police sfnt.
_NAME_FAMILLE = 1
_NAME_STYLE = 2
_NAME_POSTSCRIPT = 6

# Styles équivalents, ramenés à une forme unique pour que la résolution par
# famille + style ne dépende pas du vocabulaire du fondeur.
_STYLES_EQUIVALENTS = {
    "": "regular",
    "roman": "regular",
    "book": "regular",
    "normal": "regular",
    "plain": "regular",
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
    return nom.strip(), "regular"


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
        nom = normaliser_nom(nom_pdf).strip()
        if not nom:
            return None

        direct = self.par_nom.get(nom.lower())
        if direct is not None:
            return direct

        famille, style = _decouper_nom_postscript(nom)
        par_style = self.par_famille_style.get((famille.lower(), style))
        if par_style is not None:
            return par_style

        # Équivalence métrique : la famille nommée par le PDF n'est pas installée, mais un
        # clone de mêmes chasses l'est. La mise en page reste juste, le dessin diffère peu.
        familles, _styles = _table_alias()
        cible = familles.get(_cle_famille(famille))
        if cible is not None:
            par_alias = self.par_famille_style.get((cible.lower(), style))
            if par_alias is not None:
                return par_alias
            par_alias = self.par_famille_style.get((cible.lower(), "regular"))
            if par_alias is not None:
                return par_alias

        return self.par_famille_style.get((famille.lower(), "regular"))


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


def _indexer_dossier(dossier: Path):
    """Indexe récursivement les polices d'un dossier, en les ouvrant une à une."""
    if not dossier.is_dir():
        return

    for chemin in sorted(dossier.rglob("*")):
        if not chemin.is_file() or chemin.suffix.lower() not in EXTENSIONS_INDEXABLES:
            continue
        noms = _lire_noms_sfnt(chemin)
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
        if not nom_postscript or nom_postscript == "(null)":
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
