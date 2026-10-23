#!/usr/bin/env python3
"""Rend docs/referentiel/referentiel.md depuis referentiel.json (source unique)."""
from __future__ import annotations

import json
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent.parent / "docs" / "referentiel"


def _liste(valeurs) -> str:
    return ", ".join(valeurs) or "—"


def rendre(data: dict) -> str:
    familles = data["familles"]
    lignes = [
        "# Référentiel des éléments, attributs et propriétés des bboxes", "",
        "Rendu depuis `referentiel.json` (source unique) par `scripts/rendre_referentiel.py`. Ne pas éditer à la main.", "",
        f"- Convention des positions : {data['convention_positions']}.",
        f"- Politique des champs : {data['politique_champs']}", "",
        f"**{len(data['elements'])} éléments, {len(data['attributs'])} attributs, "
        f"{len(data['proprietes_bbox'])} propriétés de bbox.** Colonne vysi : noms existants dans vysi ; « — » = absent de vysi.",
        "", "## Sources", "",
    ]
    lignes += [f"- **{cle}** : {texte}" for cle, texte in data["sources"].items()]
    lignes += ["", "## 1. Éléments", ""]
    for famille, libelle in familles.items():
        lignes += [f"### {libelle} (`{famille}`)", "", "| id | élément | sources | vysi |", "|---|---|---|---|"]
        lignes += [f"| `{e['id']}` | {e['libelle']} | {_liste(e['sources'])} | {_liste(e['vysi'])} |"
                   for e in data["elements"] if e["famille"] == famille]
        lignes.append("")
    lignes += ["## 2. Attributs des éléments", ""]
    for groupe in dict.fromkeys(a["groupe"] for a in data["attributs"]):
        lignes += [f"### {groupe}", "", "| id | attribut | valeurs / unité | s'applique à | sources | vysi |",
                   "|---|---|---|---|---|---|"]
        for a in data["attributs"]:
            if a["groupe"] == groupe:
                portee = "toutes" if set(a["familles"]) == set(familles) else ", ".join(a["familles"])
                lignes.append(f"| `{a['id']}` | {a['libelle']} | {a['valeurs']} | {portee} | "
                              f"{_liste(a['sources'])} | {_liste(a['vysi'])} |")
        lignes.append("")
    lignes += ["## 3. Propriétés des bboxes", ""]
    for groupe in dict.fromkeys(p["groupe"] for p in data["proprietes_bbox"]):
        lignes += [f"### {groupe}", "", "| id | propriété | valeurs / unité | sources | vysi |", "|---|---|---|---|---|"]
        lignes += [f"| `{p['id']}` | {p['libelle']} | {p['valeurs']} | {_liste(p['sources'])} | {_liste(p['vysi'])} |"
                   for p in data["proprietes_bbox"] if p["groupe"] == groupe]
        lignes.append("")
    return "\n".join(lignes)


def main() -> int:
    data = json.loads((DOSSIER / "referentiel.json").read_text(encoding="utf-8"))
    (DOSSIER / "referentiel.md").write_text(rendre(data), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
