"""The unified referential: one closed list of types, each notion defined once.

It is the contract of identification: for every bbox out of segmentation, the
type it can take, the bbox properties to fill, and the attributes of that type.
"""
import importlib.util
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DATA = json.loads((RACINE / "docs/referentiel/referentiel.json").read_text(encoding="utf-8"))
SECTIONS = ("types", "proprietes_bbox", "attributs", "document", "page")
RAISONS = {"doublon", "recalculable", "detail_de_format", "decision_de_reconstruction", "style_pas_type", "hors_identification"}


def _rendu():
    spec = importlib.util.spec_from_file_location("rendre_referentiel", RACINE / "scripts/rendre_referentiel.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.rendre(DATA)


def _ids():
    return [entry["id"] for section in SECTIONS for entry in DATA[section]]


def test_every_notion_has_one_name_across_the_whole_referential():
    ids = _ids()
    assert len(ids) == len(set(ids)), sorted({i for i in ids if ids.count(i) > 1})


def test_no_entry_cites_a_provenance():
    for section in SECTIONS:
        for entry in DATA[section]:
            assert not {"sources", "vysi"} & set(entry), entry["id"]


def test_every_family_holds_types_and_every_type_a_declared_family():
    familles = set(DATA["familles"])
    assert {entry["famille"] for entry in DATA["types"]} == familles


def test_every_attribute_applies_to_declared_families():
    familles = set(DATA["familles"])
    for attribut in DATA["attributs"]:
        assert attribut["portee"] and set(attribut["portee"]) <= familles, attribut["id"]


def test_every_family_except_unknown_is_described_by_some_attribute():
    couvertes = {famille for attribut in DATA["attributs"] for famille in attribut["portee"]}
    assert set(DATA["familles"]) - couvertes <= {"inconnu"}


def test_excluded_names_never_come_back_and_each_has_a_reason():
    ids = set(_ids())
    for exclusion in DATA["exclusions"]:
        assert exclusion["raison"] in RAISONS, exclusion["nom"]
        assert exclusion["nom"] not in ids, exclusion["nom"]
        if exclusion["raison"] == "doublon":
            assert exclusion["remplace_par"] in ids, exclusion["nom"]


def test_every_entry_says_what_values_it_takes():
    for section in ("proprietes_bbox", "attributs", "document", "page"):
        for entry in DATA[section]:
            assert entry["libelle"] and entry["valeurs"], entry["id"]


def test_the_markdown_view_is_rendered_from_the_json():
    assert (RACINE / "docs/referentiel/referentiel.md").read_text(encoding="utf-8") == _rendu()
