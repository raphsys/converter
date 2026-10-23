#!/usr/bin/env python3
"""Rend docs/referentiel/referentiel.md depuis referentiel.json (source unique)."""
from __future__ import annotations

import json
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent.parent / "docs" / "referentiel"
RAISONS = {
    "doublon": "doublon, fusionné dans",
    "recalculable": "recalculable à partir des autres champs",
    "detail_de_format": "détail propre à un format de fichier",
    "decision_de_reconstruction": "décision de la reconstruction, pas de l'identification",
    "style_pas_type": "style ou caractère, pas un type de bbox",
    "hors_identification": "hors du périmètre de l'identification",
}


def _table(entetes, lignes):
    return ["| " + " | ".join(entetes) + " |", "|" + "---|" * len(entetes)] + ["| " + " | ".join(l) + " |" for l in lignes]


def rendre(data: dict) -> str:
    familles = data["familles"]
    conv = data["conventions"]
    out = [
        "# Référentiel d'identification", "",
        "Rendu depuis `referentiel.json` (source unique) par `scripts/rendre_referentiel.py`. Ne pas éditer à la main.", "",
        f"**Finalité.** {data['finalite']}", "",
        f"- Positions : {conv['positions']}.",
        f"- Champs : {conv['champs']}",
        f"- Portée : {conv['portee']}",
        f"- Priorité : {conv['priorite']}", "",
        f"**{len(data['types'])} types, {len(data['proprietes_bbox'])} propriétés de bbox, "
        f"{len(data['attributs'])} attributs, {len(data['document'])} attributs de document, "
        f"{len(data['page'])} attributs de page.**", "",
        "## 1. Types", "",
    ]
    for famille, libelle in familles.items():
        out += [f"### {libelle} (`{famille}`)", ""]
        out += _table(("id", "type"), [(f"`{t['id']}`", t["libelle"]) for t in data["types"] if t["famille"] == famille])
        out.append("")
    out += ["## 2. Propriétés de toute bbox", ""]
    for groupe in dict.fromkeys(p["groupe"] for p in data["proprietes_bbox"]):
        out += [f"### {groupe}", ""]
        out += _table(("id", "propriété", "valeurs"),
                      [(f"`{p['id']}`", p["libelle"], p["valeurs"]) for p in data["proprietes_bbox"] if p["groupe"] == groupe])
        out.append("")
    out += ["## 3. Attributs par type", ""]
    for groupe in dict.fromkeys(a["groupe"] for a in data["attributs"]):
        out += [f"### {groupe}", ""]
        out += _table(("id", "attribut", "valeurs", "familles"),
                      [(f"`{a['id']}`", a["libelle"], a["valeurs"], ", ".join(a["portee"]))
                       for a in data["attributs"] if a["groupe"] == groupe])
        out.append("")
    for section, titre in (("document", "4. Attributs du document"), ("page", "5. Attributs de la page")):
        out += [f"## {titre}", ""]
        out += _table(("id", "attribut", "valeurs"), [(f"`{e['id']}`", e["libelle"], e["valeurs"]) for e in data[section]])
        out.append("")
    out += ["## Annexe : notions écartées lors de la fusion", ""]
    out += _table(("notion", "raison"), [
        (f"`{e['nom']}`", f"{RAISONS[e['raison']]} `{e['remplace_par']}`" if e["remplace_par"] else RAISONS[e["raison"]])
        for e in data["exclusions"]])
    out.append("")
    return "\n".join(out)


def main() -> int:
    data = json.loads((DOSSIER / "referentiel.json").read_text(encoding="utf-8"))
    (DOSSIER / "referentiel.md").write_text(rendre(data), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
