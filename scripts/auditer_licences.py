"""Trie les polices de fonts/ selon leur droit de redistribution.

Le projet embarque sa bibliothèque pour être autonome sur n'importe quelle machine. Cela
signifie redistribuer les fichiers de police, ce que toutes les licences n'autorisent pas.

Les polices portent cette information en interne, à deux endroits :

- `OS/2.fsType`, un masque de bits qui dit ce que le fondeur autorise. La valeur 2
  (Restricted License) interdit explicitement l'embarquement et la redistribution.
- La table `name`, dont les identifiants 13 et 14 portent le texte et l'URL de la licence.

Une police n'est déclarée redistribuable que si sa licence est reconnue comme libre. Le
doute profite au fondeur : une licence non identifiée est classée « à vérifier », jamais
« autorisée ».

Usage : python scripts/auditer_licences.py [--dossier fonts] [--appliquer]
"""
import argparse
import re
import shutil
from collections import Counter
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont

_NAME_LICENCE = 13
_NAME_URL_LICENCE = 14
_NAME_COPYRIGHT = 0

FSTYPE_RESTREINT = 0x0002

# Motifs de licences dont la redistribution est explicitement autorisée.
LICENCES_LIBRES = (
    ("OFL", r"open font license|\bOFL\b|SIL Open Font"),
    ("Apache", r"apache licen[cs]e"),
    ("GPL+FE", r"GPL.{0,40}font exception|font exception.{0,40}GPL"),
    ("LGPL", r"lesser general public"),
    ("Ubuntu FL", r"ubuntu font licen[cs]e"),
    ("MIT", r"\bMIT licen[cs]e\b|permission is hereby granted, free of charge"),
    ("Domaine public", r"public domain|CC0|unlicen[cs]e"),
    ("MPL", r"mozilla public licen[cs]e"),
    ("AFPL/URW", r"aladdin|URW\+\+.{0,60}GPL"),
)


# Familles dont la licence est connue et libre, mais qui ne la déclarent pas dans leur
# table `name`. Sans cette liste, elles seraient écartées à tort — or ce sont précisément
# les clones métriques dont dépend la reconnaissance d'Arial, Helvetica, Times et Courier.
#
# URW base35 : AGPL assortie d'une exception de fonderie, distribuées avec Ghostscript et
#              présentes dans Debian main.
# Liberation : SIL Open Font License, publiée par Red Hat.
FAMILLES_LIBRES_CONNUES = (
    "nimbussans",
    "nimbusroman",
    "nimbusmono",
    "nimbussansnarrow",
    "urwbookman",
    "urwgothic",
    "c059",
    "p052",
    "z003",
    "d050000l",
    "standardsymbolsps",
    "liberationsans",
    "liberationserif",
    "liberationmono",
)


def _est_famille_connue(nom: str) -> bool:
    compact = re.sub(r"[^a-z0-9]", "", (nom or "").lower())
    return any(compact.startswith(famille) for famille in FAMILLES_LIBRES_CONNUES)


def _polices_du_fichier(chemin: Path):
    if chemin.suffix.lower() == ".ttc":
        return list(TTCollection(chemin, lazy=True).fonts)
    return [TTFont(chemin, fontNumber=0, lazy=True)]


def examiner(chemin: Path) -> tuple[str, str]:
    """Retourne (verdict, motif). Verdict : 'libre', 'restreint' ou 'a_verifier'."""
    try:
        polices = _polices_du_fichier(chemin)
    except Exception as erreur:  # noqa: BLE001
        return "a_verifier", f"illisible ({type(erreur).__name__})"

    for police in polices:
        try:
            table = police["name"]
            fstype = police["OS/2"].fsType if "OS/2" in police else 0
        except Exception:  # noqa: BLE001
            return "a_verifier", "table name ou OS/2 absente"

        if fstype & FSTYPE_RESTREINT:
            return "restreint", "fsType interdit l'embarquement"

        texte = " ".join(
            filter(
                None,
                (
                    table.getDebugName(_NAME_LICENCE),
                    table.getDebugName(_NAME_URL_LICENCE),
                    table.getDebugName(_NAME_COPYRIGHT),
                ),
            )
        )
        for nom_licence, motif in LICENCES_LIBRES:
            if re.search(motif, texte, re.IGNORECASE):
                return "libre", nom_licence

        nom_famille = table.getDebugName(6) or table.getDebugName(1)
        if _est_famille_connue(nom_famille):
            return "libre", "famille connue (licence non déclarée)"

        return "a_verifier", "licence non identifiée"

    return "a_verifier", "aucune police lisible"


def main(argv=None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--dossier", default="fonts")
    analyseur.add_argument(
        "--appliquer",
        action="store_true",
        help="déplace les polices non libres vers fonts/local/ (non suivi par git)",
    )
    arguments = analyseur.parse_args(argv)

    dossier = Path(arguments.dossier)
    quarantaine = dossier / "local"

    verdicts: dict[str, list[tuple[Path, str]]] = {"libre": [], "restreint": [], "a_verifier": []}
    for chemin in sorted(dossier.glob("*")):
        if not chemin.is_file() or chemin.suffix.lower() not in {".ttf", ".otf", ".ttc"}:
            continue
        verdict, motif = examiner(chemin)
        verdicts[verdict].append((chemin, motif))

    for verdict, entrees in verdicts.items():
        octets = sum(c.stat().st_size for c, _ in entrees)
        print(f"{verdict:12} {len(entrees):4} polices  {octets / 1024 / 1024:7.1f} Mo")
        motifs = Counter(motif for _c, motif in entrees)
        for motif, nombre in motifs.most_common(8):
            print(f"    {nombre:4}  {motif}")

    if not arguments.appliquer:
        print("\nsimulation — relancer avec --appliquer pour déplacer les non libres")
        return 0

    quarantaine.mkdir(parents=True, exist_ok=True)
    deplacees = 0
    for verdict in ("restreint", "a_verifier"):
        for chemin, _motif in verdicts[verdict]:
            shutil.move(str(chemin), str(quarantaine / chemin.name))
            deplacees += 1

    print(f"\n{deplacees} polices déplacées vers {quarantaine}/ (non suivi par git)")
    print(f"{len(verdicts['libre'])} polices libres conservées dans {dossier}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
