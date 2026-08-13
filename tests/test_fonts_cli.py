from pathlib import Path

from pdfexact.fonts_cli import main


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
