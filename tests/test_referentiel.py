"""The referential of elements, attributes and bbox properties stays consistent."""
import importlib.util
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DATA = json.loads((RACINE / "docs/referentiel/referentiel.json").read_text(encoding="utf-8"))
SOURCES = set(DATA["sources"])
SECTIONS = ("elements", "attributs", "proprietes_bbox")


def _rendu():
    spec = importlib.util.spec_from_file_location("rendre_referentiel", RACINE / "scripts/rendre_referentiel.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.rendre(DATA)


def test_every_id_is_unique_within_its_section():
    for section in SECTIONS:
        ids = [entry["id"] for entry in DATA[section]]
        assert len(ids) == len(set(ids)), section


def test_every_entry_cites_at_least_one_declared_source():
    for section in SECTIONS:
        for entry in DATA[section]:
            assert entry["sources"], entry["id"]
            assert {source.split(":", 1)[0] for source in entry["sources"]} <= SOURCES, entry["id"]


def test_elements_and_attributes_refer_to_declared_families():
    familles = set(DATA["familles"])
    assert {entry["famille"] for entry in DATA["elements"]} <= familles
    for attribut in DATA["attributs"]:
        assert attribut["familles"] and set(attribut["familles"]) <= familles, attribut["id"]


def test_every_family_holds_at_least_one_element():
    assert set(DATA["familles"]) == {entry["famille"] for entry in DATA["elements"]}


def test_the_markdown_view_is_rendered_from_the_json():
    assert (RACINE / "docs/referentiel/referentiel.md").read_text(encoding="utf-8") == _rendu()
