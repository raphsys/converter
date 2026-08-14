import json
import zipfile

import pytest

from pdfexact.cli import analyser_pages, main
from pdfexact.report import PageDegradee, Rapport


def test_conversion_de_bout_en_bout(pdf_texte, tmp_path):
    sortie = tmp_path / "resultat.docx"

    code = main([str(pdf_texte), str(sortie)])

    assert code == 0
    with zipfile.ZipFile(sortie) as z:
        assert "word/document.xml" in z.namelist()


def test_un_document_riche_passe_entierement(pdf_image, tmp_path):
    sortie = tmp_path / "riche.docx"

    code = main([str(pdf_image), str(sortie)])

    assert code == 0
    with zipfile.ZipFile(sortie) as z:
        noms = z.namelist()
    assert any(nom.startswith("word/media/") for nom in noms)


def test_le_rapport_est_ecrit_en_json(pdf_texte, tmp_path):
    sortie = tmp_path / "resultat.docx"
    rapport = tmp_path / "rapport.json"

    main([str(pdf_texte), str(sortie), "--report", str(rapport)])

    donnees = json.loads(rapport.read_text(encoding="utf-8"))
    assert donnees["pages_totales"] == 1


def test_un_fichier_introuvable_retourne_un_code_derreur(tmp_path):
    assert main([str(tmp_path / "absent.pdf"), str(tmp_path / "sortie.docx")]) == 2


def test_une_selection_de_pages_invalide_est_refusee(pdf_texte, tmp_path):
    code = main([str(pdf_texte), str(tmp_path / "s.docx"), "--pages", "5-2"])

    assert code == 2


def test_un_dossier_de_polices_supplementaire_est_accepte(pdf_texte, tmp_path):
    supplement = tmp_path / "polices"
    supplement.mkdir()

    code = main([str(pdf_texte), str(tmp_path / "s.docx"), "--font-dir", str(supplement)])

    assert code == 0


def test_la_granularite_ocr_est_acceptee(pdf_texte, tmp_path):
    code = main(
        [
            str(pdf_texte),
            str(tmp_path / "s.docx"),
            "--ocr-granularity",
            "char",
            "--ocr-layout",
            "blocks",
        ]
    )

    assert code == 0


def test_le_layout_word_native_est_accepte(pdf_texte, tmp_path):
    code = main(
        [
            str(pdf_texte),
            str(tmp_path / "s.docx"),
            "--ocr-layout",
            "word-native",
        ]
    )

    assert code == 0


def test_lanalyse_des_pages_accepte_les_intervalles():
    assert analyser_pages("1-3,7") == [0, 1, 2, 6]


def test_lanalyse_des_pages_accepte_une_page_seule():
    assert analyser_pages("4") == [3]


def test_lanalyse_des_pages_rejette_le_desordre():
    with pytest.raises(ValueError):
        analyser_pages("5-2")


def test_lanalyse_des_pages_rejette_le_zero():
    """Les pages se numérotent à partir de 1 : « 0 » donnerait un index négatif."""
    with pytest.raises(ValueError):
        analyser_pages("0")


def test_un_rapport_neuf_est_vide():
    rapport = Rapport(pages_totales=10)

    assert rapport.pages_degradees == [] and rapport.clusters_rasterises == 0


def test_le_json_du_rapport_est_analysable():
    rapport = Rapport(pages_totales=3, clusters_rasterises=4)
    rapport.pages_degradees.append(PageDegradee(index=1, motif="échec de l'extraction"))

    donnees = json.loads(rapport.vers_json())

    assert donnees["pages_totales"] == 3
    assert donnees["pages_degradees"][0]["index"] == 1


def test_le_resume_liste_les_polices_a_recuperer():
    rapport = Rapport(pages_totales=1, polices_non_reconnues=["TT2Bo00"])

    texte = rapport.resume()

    assert "TT2Bo00" in texte and "fonts/" in texte


def test_le_resume_signale_les_pages_degradees():
    rapport = Rapport(pages_totales=40)
    rapport.pages_degradees.append(PageDegradee(index=7, motif="dégradé non transposable"))

    texte = rapport.resume()

    assert "40" in texte and "page 8" in texte


def test_une_page_hors_bornes_est_signalee_clairement(pdf_texte, tmp_path, capsys):
    """Le message doit parler en numéros de page, pas en indices internes."""
    code = main([str(pdf_texte), str(tmp_path / "s.docx"), "--pages", "1-3"])

    assert code == 1
    erreur = capsys.readouterr().err
    assert "page(s) 2, 3" in erreur and "compte 1" in erreur
