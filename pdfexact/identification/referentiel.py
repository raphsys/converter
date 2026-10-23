"""Liste fermée des types, lue dans le référentiel d'identification."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

CHEMIN = Path(os.environ.get(
    "PDFEXACT_REFERENTIEL",
    Path(__file__).resolve().parents[2] / "docs" / "referentiel" / "referentiel.json",
))


@lru_cache(maxsize=1)
def _donnees() -> dict:
    return json.loads(CHEMIN.read_text(encoding="utf-8"))


def familles_des_types() -> dict[str, str]:
    """Type id -> family id, for every type of the referential."""
    return {entree["id"]: entree["famille"] for entree in _donnees()["types"]}


def familles() -> dict[str, str]:
    """Family id -> label."""
    return dict(_donnees()["familles"])


def famille(type_id: str) -> str:
    """Family of a type; a type outside the referential is refused."""
    try:
        return familles_des_types()[type_id]
    except KeyError:
        raise ValueError(f"type hors référentiel : {type_id!r}") from None
