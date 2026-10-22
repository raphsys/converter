from pathlib import Path

import pymupdf
import pytest

import pdfexact.fontlib as fontlib
from pdfexact.extract.fonts import collecter_polices
from pdfexact.fontlib import Bibliotheque, PoliceIndexee


def _candidate(tmp_path, family, style="Regular"):
    return PoliceIndexee(
        nom_postscript=family.replace(" ", "") + "-" + style,
        famille=family,
        style=style,
        chemin=tmp_path / (family.replace(" ", "") + "-" + style + ".ttf"),
        source="dossier",
    )


def _library(*candidates):
    library = Bibliotheque()
    for candidate in candidates:
        library.ajouter(candidate, prioritaire=True)
    return library


@pytest.mark.parametrize("name", ["OpaqueResource42", "UnknownFace", "cmr10"])
def test_unknown_font_name_is_not_evidence_of_sans(name):
    assert fontlib._classe_nom_police(name) == "unknown"


def test_unclassified_candidate_does_not_win_by_defaulting_to_sans(tmp_path, monkeypatch):
    monkeypatch.setattr(fontlib, "_signature_metrique", lambda path: (0.52,) * 10)
    opaque = _candidate(tmp_path, "Unidentified42")
    sans = _candidate(tmp_path, "Candidate Sans")

    result = _library(opaque, sans).resoudre_detail("OpaqueResource42")

    assert result.police == sans
    assert result.mode == "dynamique"
    assert 0.52 <= result.confiance <= 0.60


def test_opaque_source_fallback_is_not_high_confidence_recognition(tmp_path, monkeypatch):
    monkeypatch.setattr(fontlib, "_signature_metrique", lambda path: (0.52,) * 10)
    sans = _candidate(tmp_path, "Candidate Sans")

    result = _library(sans).resoudre_detail("OpaqueResource42")

    assert result.police == sans
    assert result.mode == "dynamique"
    assert result.confiance <= 0.60


def test_explicit_opaque_font_name_still_resolves_exactly(tmp_path):
    opaque = _candidate(tmp_path, "Unidentified42")

    result = _library(opaque).resoudre_detail("ABCDEF+" + opaque.nom_postscript)

    assert result.police == opaque
    assert result.mode == "exact"
    assert result.confiance == 1.0


def test_known_serif_and_explicit_bold_keep_their_class_and_style(tmp_path, monkeypatch):
    monkeypatch.setattr(fontlib, "_signature_metrique", lambda path: (0.49,) * 10)
    opaque = _candidate(tmp_path, "Unidentified42", "Bold")
    serif = _candidate(tmp_path, "Candidate Serif", "Bold")
    sans = _candidate(tmp_path, "Candidate Sans")

    result = _library(opaque, sans, serif).resoudre_detail("MissingRoman-Bold")

    assert result.police == serif
    assert result.mode == "dynamique"


@pytest.mark.parametrize("style", ["Book Oblique", "Medium Oblique", "Oblique"])
def test_regular_fallback_does_not_select_an_oblique_face(tmp_path, monkeypatch, style):
    monkeypatch.setattr(fontlib, "_signature_metrique", lambda path: (0.52,) * 10)
    oblique = _candidate(tmp_path, "Candidate Sans", style)
    regular = _candidate(tmp_path, "Candidate Sans")

    result = _library(oblique, regular).resoudre_detail("OpaqueResource42")

    assert result.police == regular


def test_source_embedding_is_retained_separately_from_the_word_substitute():
    font_path = Path(fontlib.DOSSIER_EMBARQUE) / "NimbusSans-Regular.otf"
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_font(fontname="F0", fontfile=str(font_path))
        page.insert_text((50, 50), "Native source text", fontname="F0")
        entry = page.get_fonts(full=True)[0]
        expected_data = document.extract_font(entry[0])[3]
        library = _library(PoliceIndexee(
            nom_postscript=fontlib.normaliser_nom(entry[3]),
            famille="Nimbus Sans",
            style="Regular",
            chemin=font_path,
            source="dossier",
        ))

        asset = collecter_polices(document, library)[fontlib.normaliser_nom(entry[3])]

    assert asset.embarquee is True
    assert asset.donnees == expected_data
    assert asset.extension
    assert asset.chemin == font_path
    assert asset.metriques["ascender_ratio"] > 0


def test_standard_font_is_not_reported_as_embedded():
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((50, 50), "Standard source text")

        asset = collecter_polices(document, Bibliotheque())["Helvetica"]

    assert asset.embarquee is False
    assert asset.donnees is None
    assert asset.extension == ""


def test_opaque_cff_source_is_not_confused_with_resolved_word_font():
    font_path = fontlib.DOSSIER_EMBARQUE / "NimbusSans-Regular.otf"
    substitute = PoliceIndexee(
        "NimbusSans-Regular", "Nimbus Sans", "Regular", font_path, "dossier"
    )
    source_data = b"opaque embedded CFF subset"

    class Page:
        def get_fonts(self, full):
            return [(7, "cff", "Type1", "ABCDEF+OpaqueResource42")]

    class Document:
        page_count = 1

        def __getitem__(self, index):
            return Page()

        def extract_font(self, xref):
            return "ABCDEF+OpaqueResource42", "cff", "Type1", source_data

    asset = collecter_polices(Document(), _library(substitute))["OpaqueResource42"]

    assert asset.embarquee is True
    assert asset.donnees == source_data
    assert asset.extension == "cff"
    assert asset.chemin == font_path
    assert asset.donnees != font_path.read_bytes()
    assert asset.mode_resolution == "dynamique"
    assert asset.confiance_resolution <= 0.60
    assert asset.metriques["ascender_ratio"] > 0


def test_unreadable_embedded_font_does_not_abort_collection(caplog):
    class Page:
        def get_fonts(self, full):
            return [(7, "cff", "Type1", "ABCDEF+OpaqueResource42")]

    class Document:
        page_count = 2

        def __getitem__(self, index):
            return Page()

        def extract_font(self, xref):
            raise RuntimeError("broken font stream")

    assets = collecter_polices(Document(), Bibliotheque())

    assert assets["OpaqueResource42"].donnees is None
    assert "OpaqueResource42" in caplog.text
    assert "broken font stream" in caplog.text
    assert caplog.text.count("broken font stream") == 1
