from pathlib import Path

from pdfexact.font_fetcher import PoliceTelechargee, RapportTelechargement
from pdfexact.fonts_cli import main
from pdfexact.fontlib import Bibliotheque


def test_scan_liste_les_polices_du_pdf(pdf_texte, capsys):
    code = main(["scan", str(pdf_texte), "--details"])

    sortie = capsys.readouterr().out
    assert code == 0
    assert "référence(s) de police" in sortie
    assert "Helvetica" in sortie or "Times" in sortie


def test_scan_refuse_un_pdf_absent(tmp_path, capsys):
    code = main(["scan", str(tmp_path / "absent.pdf")])

    assert code == 2
    assert "introuvable" in capsys.readouterr().err


def test_copy_system_cree_le_dossier_cible(pdf_texte, tmp_path):
    cible = tmp_path / "fonts"

    code = main(["copy-system", str(pdf_texte), "--output", str(cible)])

    assert code == 0
    assert cible.is_dir()


def test_copy_system_respecte_la_selection_de_pages(pdf_texte, tmp_path):
    cible = tmp_path / "fonts"

    code = main(["copy-system", str(pdf_texte), "--pages", "1", "--output", str(cible)])

    assert code == 0
    assert isinstance(cible, Path)


def test_fetch_telecharge_les_polices_manquantes(pdf_texte, tmp_path, monkeypatch, capsys):
    def faux_fetch(noms, destination, timeout=30):
        return RapportTelechargement(
            telechargees=[PoliceTelechargee(noms[0], Path(destination) / "Fetched.ttf", "test")]
        )

    monkeypatch.setattr("pdfexact.fonts_cli.construire", lambda *args, **kwargs: Bibliotheque())
    monkeypatch.setattr("pdfexact.fonts_cli.telecharger_polices_manquantes", faux_fetch)

    code = main(["fetch", str(pdf_texte), "--output", str(tmp_path)])

    sortie = capsys.readouterr().out
    assert code == 0
    assert "téléchargée:" in sortie


def test_download_telecharge_des_noms_directs(tmp_path, monkeypatch, capsys):
    def faux_fetch(noms, destination, timeout=30):
        assert noms == ["WP-MathA"]
        return RapportTelechargement(
            telechargees=[PoliceTelechargee(noms[0], Path(destination) / "WP-MathA.ttf", "test")]
        )

    monkeypatch.setattr("pdfexact.fonts_cli.telecharger_polices_manquantes", faux_fetch)

    code = main(["download", "--font-dir", str(tmp_path), "WP-MathA"])

    sortie = capsys.readouterr().out
    assert code == 0
    assert "téléchargée:" in sortie
