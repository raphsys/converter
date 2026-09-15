import subprocess
from pathlib import Path

import pytest

from pdfexact.font_fetcher import cle_famille_police, telecharger_polices_manquantes


def _une_police_systeme_ttf():
    sortie = subprocess.run(
        ["fc-list", "--format", "%{file}\n"], capture_output=True, timeout=20
    ).stdout.decode(errors="replace")
    for ligne in sortie.splitlines():
        if ligne.endswith(".ttf"):
            return Path(ligne)
    pytest.skip("aucune police TrueType installée sur cette machine")


class _Reponse:
    status = 200

    def __init__(self, donnees: bytes):
        self.donnees = donnees

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.donnees


def test_cle_famille_police_normalise_le_nom_pdf():
    assert cle_famille_police("ABCDEF+Raleway-Regular") == "raleway"


def test_cle_famille_police_retire_style_ms_concatene():
    assert cle_famille_police("TimesNewRomanBdMS") == "timesnewroman"


def test_telecharger_polices_manquantes_valide_et_ecrit_la_police(monkeypatch, tmp_path):
    donnees = _une_police_systeme_ttf().read_bytes()

    monkeypatch.setattr(
        "pdfexact.font_fetcher._sources_google_fonts",
        lambda _cle, timeout=30: [
            {
                "url": "https://example.test/font.ttf",
                "filename": "Fetched.ttf",
                "source": "test",
            }
        ],
    )
    monkeypatch.setattr("pdfexact.font_fetcher.urlopen", lambda *_args, **_kwargs: _Reponse(donnees))

    rapport = telecharger_polices_manquantes(["Fetched-Regular"], tmp_path)

    assert len(rapport.telechargees) == 1
    assert (tmp_path / "Fetched.ttf").is_file()
    assert not rapport.introuvables


def test_telecharger_polices_manquantes_tente_alias_libre(monkeypatch, tmp_path):
    donnees = _une_police_systeme_ttf().read_bytes()

    def faux_sources(cle, timeout=30):
        if cle == "liberationserif":
            return [
                {
                    "url": "https://example.test/liberation-serif.ttf",
                    "filename": "LiberationSerif.ttf",
                    "source": "test-alias",
                }
            ]
        return []

    monkeypatch.setattr("pdfexact.font_fetcher._sources_google_fonts", faux_sources)
    monkeypatch.setattr("pdfexact.font_fetcher.urlopen", lambda *_args, **_kwargs: _Reponse(donnees))

    rapport = telecharger_polices_manquantes(["TimesNewRomanBdMS"], tmp_path)

    assert len(rapport.telechargees) == 1
    assert rapport.alias_utilises["TimesNewRomanBdMS"] == "Liberation Serif"


def test_telecharger_polices_manquantes_priorise_le_style_de_lalias(monkeypatch, tmp_path):
    donnees = _une_police_systeme_ttf().read_bytes()

    monkeypatch.setattr(
        "pdfexact.font_fetcher._charger_sources_manifest",
        lambda: {
            "sourcesans3": [
                {
                    "url": "https://example.test/SourceSans3-Regular.ttf",
                    "filename": "SourceSans3-Regular.ttf",
                    "style": "regular",
                    "source": "test-alias",
                },
                {
                    "url": "https://example.test/SourceSans3-MediumIt.ttf",
                    "filename": "SourceSans3-MediumIt.ttf",
                    "style": "medium italic",
                    "source": "test-alias",
                },
            ]
        },
    )
    monkeypatch.setattr("pdfexact.font_fetcher.urlopen", lambda *_args, **_kwargs: _Reponse(donnees))

    rapport = telecharger_polices_manquantes(["LegacySans-MediumItalic"], tmp_path)

    assert len(rapport.telechargees) == 1
    assert rapport.telechargees[0].fichier.name == "SourceSans3-MediumIt.ttf"
    assert rapport.alias_utilises["LegacySans-MediumItalic"] == "Source Sans 3"


def test_telecharger_polices_manquantes_ne_deduplique_pas_les_styles(monkeypatch, tmp_path):
    donnees = _une_police_systeme_ttf().read_bytes()

    monkeypatch.setattr(
        "pdfexact.font_fetcher._charger_sources_manifest",
        lambda: {
            "sourcesans3": [
                {
                    "url": "https://example.test/SourceSans3-Regular.ttf",
                    "filename": "SourceSans3-Regular.ttf",
                    "style": "regular",
                    "source": "test-alias",
                },
                {
                    "url": "https://example.test/SourceSans3-Bold.ttf",
                    "filename": "SourceSans3-Bold.ttf",
                    "style": "bold",
                    "source": "test-alias",
                },
            ]
        },
    )
    monkeypatch.setattr("pdfexact.font_fetcher.urlopen", lambda *_args, **_kwargs: _Reponse(donnees))

    rapport = telecharger_polices_manquantes(["LegacySans-Bold", "LegacySans-Book"], tmp_path)

    assert [item.fichier.name for item in rapport.telechargees] == [
        "SourceSans3-Bold.ttf",
        "SourceSans3-Regular.ttf",
    ]
