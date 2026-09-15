"""Outils de diagnostic et de rapatriement des polices."""
import argparse
import shutil
import sys
from collections import Counter
from pathlib import Path

import pymupdf

from pdfexact.font_fetcher import telecharger_polices_manquantes
from pdfexact.fontlib import construire, dossiers_par_defaut, normaliser_nom


def analyser_pages(expression: str) -> list[int]:
    indices: list[int] = []
    for morceau in expression.split(","):
        morceau = morceau.strip()
        if not morceau:
            continue
        if "-" in morceau:
            debut, _, fin = morceau.partition("-")
            premier, dernier = int(debut), int(fin)
            if premier > dernier:
                raise ValueError(f"intervalle inversé : {morceau}")
            indices.extend(range(premier - 1, dernier))
        else:
            indices.append(int(morceau) - 1)
    if any(index < 0 for index in indices):
        raise ValueError("les pages se numérotent à partir de 1")
    return indices


def _polices_pdf(chemins: list[Path], pages=None) -> Counter[str]:
    """Compte les noms PostScript demandés par un ou plusieurs PDF."""
    compteur: Counter[str] = Counter()
    for chemin in chemins:
        doc = pymupdf.open(chemin)
        try:
            indices = list(range(doc.page_count)) if pages is None else list(pages)
            hors_bornes = [i + 1 for i in indices if not 0 <= i < doc.page_count]
            if hors_bornes:
                raise ValueError(
                    f"{chemin}: page(s) {', '.join(map(str, hors_bornes))} absente(s), "
                    f"le document en compte {doc.page_count}"
                )
            for index in indices:
                for entree in doc[index].get_fonts(full=True):
                    compteur[normaliser_nom(entree[3])] += 1
        finally:
            doc.close()
    return compteur


def _dossiers_polices(arguments) -> list[Path]:
    return list(dossiers_par_defaut()) + [Path(d) for d in arguments.font_dir]


def commande_scan(arguments) -> int:
    pages = analyser_pages(arguments.pages) if arguments.pages else None
    chemins = [Path(p) for p in arguments.pdf]
    for chemin in chemins:
        if not chemin.exists():
            print(f"PDF introuvable : {chemin}", file=sys.stderr)
            return 2

    bibliotheque = construire(
        dossiers=_dossiers_polices(arguments),
        inclure_systeme=not arguments.no_system,
    )
    compteur = _polices_pdf(chemins, pages=pages)

    exactes = []
    substituees = []
    manquantes = []
    for nom, occurrences in sorted(compteur.items(), key=lambda item: item[0].lower()):
        resolution = bibliotheque.resoudre_detail(nom)
        if resolution.police is None:
            manquantes.append((nom, occurrences))
        elif resolution.mode in {"exact", "famille_style"}:
            exactes.append((nom, occurrences, resolution))
        else:
            substituees.append((nom, occurrences, resolution))

    print(f"{sum(compteur.values())} référence(s) de police, {len(compteur)} nom(s) distinct(s).")
    print(f"{len(exactes)} exacte(s), {len(substituees)} substituée(s), {len(manquantes)} manquante(s).")

    if exactes and arguments.details:
        print("\nExactes :")
        for nom, occurrences, resolution in exactes:
            police = resolution.police
            print(f"  {nom} ({occurrences}) -> {police.famille} / {police.style} [{police.source}]")

    if substituees:
        print("\nSubstituées :")
        for nom, occurrences, resolution in substituees:
            police = resolution.police
            print(
                f"  {nom} ({occurrences}) -> {police.famille} / {police.style} "
                f"[{resolution.mode}, {police.source}]"
            )
            print(f"    {police.chemin}")

    if manquantes:
        print("\nManquantes à déposer dans fonts/ :")
        for nom, occurrences in manquantes:
            print(f"  {nom} ({occurrences})")

    return 1 if manquantes and arguments.fail_on_missing else 0


def commande_copy_system(arguments) -> int:
    pages = analyser_pages(arguments.pages) if arguments.pages else None
    chemins = [Path(p) for p in arguments.pdf]
    for chemin in chemins:
        if not chemin.exists():
            print(f"PDF introuvable : {chemin}", file=sys.stderr)
            return 2

    cible = Path(arguments.output)
    cible.mkdir(parents=True, exist_ok=True)
    bibliotheque = construire(dossiers=_dossiers_polices(arguments), inclure_systeme=True)
    compteur = _polices_pdf(chemins, pages=pages)

    copies = 0
    deja = 0
    manquantes = []
    for nom in sorted(compteur):
        resolution = bibliotheque.resoudre_detail(nom)
        police = resolution.police
        if police is None:
            manquantes.append(nom)
            continue
        if police.source != "systeme" and not arguments.include_bundled:
            continue

        destination = cible / police.chemin.name
        if destination.exists():
            deja += 1
            continue
        shutil.copy2(police.chemin, destination)
        copies += 1
        print(f"copie: {police.chemin} -> {destination}")

    print(f"{copies} police(s) copiée(s), {deja} déjà présente(s).")
    if manquantes:
        print("Manquantes non copiables automatiquement :")
        for nom in manquantes:
            print(f"  {nom}")
    return 0


def commande_fetch(arguments) -> int:
    pages = analyser_pages(arguments.pages) if arguments.pages else None
    chemins = [Path(p) for p in arguments.pdf]
    for chemin in chemins:
        if not chemin.exists():
            print(f"PDF introuvable : {chemin}", file=sys.stderr)
            return 2

    bibliotheque = construire(
        dossiers=_dossiers_polices(arguments),
        inclure_systeme=not arguments.no_system,
    )
    compteur = _polices_pdf(chemins, pages=pages)
    manquantes = [
        nom for nom in sorted(compteur) if bibliotheque.resoudre_detail(nom).police is None
    ]
    if not manquantes:
        print("Aucune police manquante.")
        return 0

    rapport = telecharger_polices_manquantes(
        manquantes,
        destination=Path(arguments.output),
        timeout=arguments.timeout,
    )
    for item in rapport.telechargees:
        print(f"téléchargée: {item.demandee} -> {item.fichier} [{item.source}]")
    for nom in rapport.introuvables:
        print(f"introuvable: {nom}")
    for nom, erreur in rapport.erreurs.items():
        print(f"échec: {nom}: {erreur}", file=sys.stderr)

    return 0 if rapport.telechargees else 1


def commande_download(arguments) -> int:
    destination = Path(arguments.font_dir)
    rapport = telecharger_polices_manquantes(
        sorted({normaliser_nom(nom) for nom in arguments.font}),
        destination=destination,
        timeout=arguments.timeout,
    )
    for item in rapport.telechargees:
        print(f"téléchargée: {item.demandee} -> {item.fichier} [{item.source}]")
    for nom in rapport.introuvables:
        print(f"introuvable: {nom}")
    for nom, erreur in rapport.erreurs.items():
        print(f"échec: {nom}: {erreur}", file=sys.stderr)

    return 0 if rapport.telechargees else 1


def _analyseur() -> argparse.ArgumentParser:
    analyseur = argparse.ArgumentParser(
        prog="pdfexact-fonts",
        description="Diagnostique et rapatrie les polices nécessaires aux PDF.",
    )
    sous_commandes = analyseur.add_subparsers(dest="commande", required=True)

    scan = sous_commandes.add_parser("scan", help="liste les polices PDF et leur résolution")
    scan.add_argument("pdf", nargs="+", help="PDF à analyser")
    scan.add_argument("--pages", help="sélection de pages, par exemple 1-5,8")
    scan.add_argument("--font-dir", action="append", default=[], help="dossier de polices")
    scan.add_argument("--no-system", action="store_true", help="ignore les polices système")
    scan.add_argument("--details", action="store_true", help="liste aussi les exactes")
    scan.add_argument("--fail-on-missing", action="store_true", help="retourne 1 si manque")
    scan.set_defaults(fonction=commande_scan)

    copie = sous_commandes.add_parser(
        "copy-system",
        help="copie dans fonts/ les polices déjà trouvées sur le système",
    )
    copie.add_argument("pdf", nargs="+", help="PDF à analyser")
    copie.add_argument("--pages", help="sélection de pages, par exemple 1-5,8")
    copie.add_argument("--font-dir", action="append", default=[], help="dossier de polices")
    copie.add_argument("--output", default="fonts", help="dossier cible")
    copie.add_argument(
        "--include-bundled",
        action="store_true",
        help="copie aussi les polices livrées avec pdfexact",
    )
    copie.set_defaults(fonction=commande_copy_system)

    fetch = sous_commandes.add_parser(
        "fetch",
        help="télécharge les polices libres manquantes depuis les sources autorisées",
    )
    fetch.add_argument("pdf", nargs="+", help="PDF à analyser")
    fetch.add_argument("--pages", help="sélection de pages, par exemple 1-5,8")
    fetch.add_argument("--font-dir", action="append", default=[], help="dossier de polices")
    fetch.add_argument("--output", default="fonts/local", help="dossier cible")
    fetch.add_argument("--no-system", action="store_true", help="ignore les polices système")
    fetch.add_argument("--timeout", type=int, default=30, help="timeout réseau en secondes")
    fetch.set_defaults(fonction=commande_fetch)

    download = sous_commandes.add_parser(
        "download",
        help="alias: télécharge directement une liste de noms de polices",
    )
    download.add_argument("font", nargs="+", help="noms PostScript à télécharger")
    download.add_argument("--font-dir", default="fonts/local", help="dossier cible")
    download.add_argument("--timeout", type=int, default=30, help="timeout réseau en secondes")
    download.set_defaults(fonction=commande_download)

    return analyseur


def main(argv=None) -> int:
    arguments = _analyseur().parse_args(argv)
    try:
        return arguments.fonction(arguments)
    except ValueError as erreur:
        print(f"erreur : {erreur}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
