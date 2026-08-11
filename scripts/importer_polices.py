"""Importe dans fonts/ les polices complètes trouvées sur la machine.

Une machine de développement contient des centaines de fichiers de police éparpillés dans
des applications, des environnements et des caches, dont fontconfig ignore la plupart.
Beaucoup sont des sous-ensembles inutilisables (fragments KaTeX, polices web, données de
test) ; certains sont de vraies familles complètes.

Le tri se fait sur la qualité, pas sur l'emplacement : une police n'est retenue que si
elle porte un nom PostScript et une table cmap fournie. Ce critère écarte les
sous-ensembles sans avoir à énumérer les répertoires à éviter.

Usage : python scripts/importer_polices.py [--racine /chemin] [--destination fonts/]
        [--min-cmap 100] [--simulation]
"""
import argparse
import shutil
import sys
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont

EXTENSIONS = {".ttf", ".otf", ".ttc"}
TAILLE_MINIMALE = 20 * 1024

# Répertoires dont le contenu n'est jamais une police utilisable : jeux de test de
# fontTools, et le dossier de destination lui-même.
FRAGMENTS_EXCLUS = ("/Tests/", "/aots/", "/site-packages/fontTools/")


def _polices_du_fichier(chemin: Path):
    """Retourne les TTFont d'un fichier, en gérant les collections .ttc."""
    if chemin.suffix.lower() == ".ttc":
        return list(TTCollection(chemin, lazy=True).fonts)
    return [TTFont(chemin, fontNumber=0, lazy=True)]


def examiner(chemin: Path, min_cmap: int):
    """Retourne (nom PostScript, nombre d'entrées cmap) si la police est complète."""
    try:
        polices = _polices_du_fichier(chemin)
    except Exception:  # noqa: BLE001 — un fichier illisible est simplement ignoré
        return None

    meilleur = None
    for police in polices:
        try:
            nom = police["name"].getDebugName(6) or police["name"].getDebugName(1)
            cmap = police.getBestCmap() or {}
        except Exception:  # noqa: BLE001
            continue
        if not nom or len(cmap) < min_cmap:
            continue
        if meilleur is None or len(cmap) > meilleur[1]:
            meilleur = (nom.strip(), len(cmap))

    return meilleur


def collecter(racines, min_cmap: int):
    """Parcourt les racines et retient la meilleure version de chaque police."""
    retenues: dict[str, tuple[Path, int]] = {}
    examines = 0

    for racine in racines:
        for chemin in Path(racine).rglob("*"):
            if chemin.suffix.lower() not in EXTENSIONS or not chemin.is_file():
                continue
            texte = str(chemin)
            if any(fragment in texte for fragment in FRAGMENTS_EXCLUS):
                continue
            try:
                if chemin.stat().st_size < TAILLE_MINIMALE:
                    continue
            except OSError:
                continue

            examines += 1
            resultat = examiner(chemin, min_cmap)
            if resultat is None:
                continue

            nom, taille_cmap = resultat
            ancien = retenues.get(nom)
            # À nom égal, on garde la version au cmap le plus fourni.
            if ancien is None or taille_cmap > ancien[1]:
                retenues[nom] = (chemin, taille_cmap)

    return retenues, examines


def main(argv=None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--racine", action="append", default=None, help="racine à explorer (répétable)"
    )
    analyseur.add_argument("--destination", default="fonts", help="dossier d'accueil")
    analyseur.add_argument(
        "--min-cmap",
        type=int,
        default=100,
        help="nombre minimal d'entrées cmap pour qu'une police soit jugée complète",
    )
    analyseur.add_argument(
        "--simulation", action="store_true", help="affiche sans rien copier"
    )
    arguments = analyseur.parse_args(argv)

    destination = Path(arguments.destination)
    racines = arguments.racine or [str(Path.home()), "/usr/share/fonts", "/var/lib/flatpak"]

    print(f"exploration : {', '.join(racines)}")
    retenues, examines = collecter(racines, arguments.min_cmap)
    print(f"{examines} fichiers examinés, {len(retenues)} polices complètes retenues")

    if arguments.simulation:
        for nom, (chemin, taille) in sorted(retenues.items()):
            print(f"  {nom:40} {taille:5} glyphes  {chemin}")
        return 0

    destination.mkdir(parents=True, exist_ok=True)
    copiees = 0
    for nom, (chemin, _taille) in sorted(retenues.items()):
        cible = destination / f"{nom}{chemin.suffix.lower()}"
        if cible.exists():
            continue
        try:
            shutil.copy2(chemin, cible)
            copiees += 1
        except OSError as erreur:
            print(f"  échec sur {nom} : {erreur}", file=sys.stderr)

    print(f"{copiees} polices copiées dans {destination}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
