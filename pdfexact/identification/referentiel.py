"""Types of the identification, read from the referential; the referential stays open.

Two ways to add reference entries later, without touching the base file:
- an extension file ``docs/referentiel/extensions/*.json`` (same shape: ``familles``,
  ``types``), merged at load time;
- ``etendre_referentiel(types, familles)`` at run time, for a plugged identificateur.
A type declared in two different families is refused.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

CHEMIN = Path(os.environ.get(
    "PDFEXACT_REFERENTIEL",
    Path(__file__).resolve().parents[2] / "docs" / "referentiel" / "referentiel.json",
))
DOSSIER_EXTENSIONS = CHEMIN.parent / "extensions"
_types_ajoutes: dict[str, str] = {}
_familles_ajoutees: dict[str, str] = {}


def _fusionner(types: dict[str, str], familles: dict[str, str], nouveaux_types: dict[str, str],
               nouvelles_familles: dict[str, str], origine: str) -> None:
    familles.update(nouvelles_familles)
    for type_id, famille_id in nouveaux_types.items():
        if famille_id not in familles:
            raise ValueError(f"{origine} : famille inconnue {famille_id!r} pour le type {type_id!r}")
        if types.get(type_id, famille_id) != famille_id:
            raise ValueError(f"{origine} : le type {type_id!r} est déjà dans la famille {types[type_id]!r}")
        types[type_id] = famille_id


@lru_cache(maxsize=1)
def _donnees() -> tuple[dict[str, str], dict[str, str]]:
    """(type -> family, family -> label) of the base file and its extension files."""
    base = json.loads(CHEMIN.read_text(encoding="utf-8"))
    types = {entree["id"]: entree["famille"] for entree in base["types"]}
    familles = dict(base["familles"])
    for fichier in sorted(Path(DOSSIER_EXTENSIONS).glob("*.json")):
        extension = json.loads(fichier.read_text(encoding="utf-8"))
        _fusionner(types, familles, {e["id"]: e["famille"] for e in extension.get("types", ())},
                   dict(extension.get("familles", {})), fichier.name)
    return types, familles


def familles_des_types() -> dict[str, str]:
    """Type id -> family id, for every type of the referential and its extensions."""
    return {**_donnees()[0], **_types_ajoutes}


def familles() -> dict[str, str]:
    """Family id -> label."""
    return {**_donnees()[1], **_familles_ajoutees}


def famille(type_id: str) -> str:
    """Family of a type; a type outside the referential is refused."""
    try:
        return familles_des_types()[type_id]
    except KeyError:
        raise ValueError(f"type hors référentiel : {type_id!r}") from None


def etendre_referentiel(types: dict[str, str], familles_nouvelles: dict[str, str] | None = None) -> None:
    """Add types (and families) at run time; existing entries cannot change family."""
    tous_types, toutes_familles = familles_des_types(), familles()
    _fusionner(tous_types, toutes_familles, dict(types), dict(familles_nouvelles or {}), "extension")
    _familles_ajoutees.update(familles_nouvelles or {})
    _types_ajoutes.update(types)


def recharger() -> None:
    """Forget run-time additions and read the files again."""
    _donnees.cache_clear()
    _types_ajoutes.clear()
    _familles_ajoutees.clear()
