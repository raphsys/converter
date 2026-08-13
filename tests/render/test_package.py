import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

from pdfexact.geometry import pt_vers_emu
from pdfexact.geometry import BBox
from pdfexact.ir import Document, FontAsset, FontRef, MediaItem, Page, TableCell, TableEl, TableRow
from pdfexact.render.package import GestionnaireRelations, ecrire_docx

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Une A4 vaut 595 x 842 pt, soit exactement ces valeurs en EMU.
A4_LARGEUR = pt_vers_emu(595)
A4_HAUTEUR = pt_vers_emu(842)


def _document_deux_pages():
    return Document(
        pages=[
            Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR),
            Page(index=1, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR),
        ]
    )


@pytest.fixture
def docx_deux_pages(tmp_path):
    sortie = tmp_path / "vide.docx"
    ecrire_docx(_document_deux_pages(), sortie)
    return sortie


def _lire(chemin, partie):
    with zipfile.ZipFile(chemin) as z:
        return z.read(partie)


def test_le_zip_contient_les_parties_obligatoires(docx_deux_pages):
    with zipfile.ZipFile(docx_deux_pages) as z:
        noms = set(z.namelist())

    assert "[Content_Types].xml" in noms
    assert "_rels/.rels" in noms
    assert "word/document.xml" in noms
    assert "word/_rels/document.xml.rels" in noms
    assert "word/styles.xml" in noms


def test_toutes_les_parties_xml_sont_bien_formees(docx_deux_pages):
    with zipfile.ZipFile(docx_deux_pages) as z:
        for nom in z.namelist():
            if nom.endswith(".xml") or nom.endswith(".rels"):
                ElementTree.fromstring(z.read(nom))


def test_la_taille_de_page_est_en_twips(docx_deux_pages):
    racine = ElementTree.fromstring(_lire(docx_deux_pages, "word/document.xml"))

    premiere = next(racine.iter(f"{W}pgSz"))
    assert premiere.get(f"{W}w") == "11900"  # 595 pt x 20
    assert premiere.get(f"{W}h") == "16840"  # 842 pt x 20


def test_une_page_paysage_declare_son_orientation(tmp_path):
    document = Document(
        pages=[Page(index=0, largeur_emu=pt_vers_emu(842), hauteur_emu=pt_vers_emu(595))]
    )
    sortie = tmp_path / "paysage.docx"

    ecrire_docx(document, sortie)

    racine = ElementTree.fromstring(_lire(sortie, "word/document.xml"))
    taille = next(racine.iter(f"{W}pgSz"))
    assert taille.get(f"{W}orient") == "landscape"


def test_les_marges_sont_nulles(docx_deux_pages):
    racine = ElementTree.fromstring(_lire(docx_deux_pages, "word/document.xml"))

    marges = next(racine.iter(f"{W}pgMar"))
    for bord in ("top", "right", "bottom", "left"):
        assert marges.get(f"{W}{bord}") == "0"


def test_une_section_par_page(docx_deux_pages):
    racine = ElementTree.fromstring(_lire(docx_deux_pages, "word/document.xml"))

    assert len(list(racine.iter(f"{W}sectPr"))) == 2


def test_la_derniere_section_est_au_niveau_du_corps(docx_deux_pages):
    """OOXML impose que la dernière section soit fille de w:body, pas d'un paragraphe."""
    racine = ElementTree.fromstring(_lire(docx_deux_pages, "word/document.xml"))

    corps = racine.find(f"{W}body")
    assert corps[-1].tag == f"{W}sectPr"


def test_le_style_est_declare_en_relation(docx_deux_pages):
    relations = _lire(docx_deux_pages, "word/_rels/document.xml.rels").decode()

    assert "styles.xml" in relations


def test_les_media_sont_ecrits(tmp_path):
    document = _document_deux_pages()
    document.media["image1"] = MediaItem(
        media_ref="image1", donnees=b"\x89PNG\r\n\x1a\n", extension="png"
    )
    sortie = tmp_path / "avec_media.docx"

    ecrire_docx(document, sortie)

    with zipfile.ZipFile(sortie) as z:
        assert "word/media/image1.png" in z.namelist()
        assert z.read("word/media/image1.png") == b"\x89PNG\r\n\x1a\n"


def test_les_polices_reconnues_sont_embarquees(tmp_path):
    source = tmp_path / "police.ttf"
    source.write_bytes(b"\0" * 64)
    document = _document_deux_pages()
    document.polices["Test-Regular"] = FontAsset(
        font_id="Test-Regular",
        famille="Test",
        donnees=None,
        extension="",
        embarquee=False,
        chemin=Path(source),
        reconnue=True,
    )
    sortie = tmp_path / "avec_police.docx"

    ecrire_docx(document, sortie)

    with zipfile.ZipFile(sortie) as z:
        noms = set(z.namelist())
        assert "word/fontTable.xml" in noms
        assert "word/_rels/fontTable.xml.rels" in noms
        assert any(nom.startswith("word/fonts/") and nom.endswith(".odttf") for nom in noms)
        assert "fontTable.xml" in z.read("word/_rels/document.xml.rels").decode()


def test_un_document_sans_page_reste_valide(tmp_path):
    sortie = tmp_path / "vide_total.docx"

    ecrire_docx(Document(), sortie)

    ElementTree.fromstring(_lire(sortie, "word/document.xml"))


def test_un_tableau_est_rendu_comme_vrai_tableau_word(tmp_path):
    table = TableEl(
        bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(240), pt_vers_emu(130)),
        rows=[
            TableRow(
                bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(240), pt_vers_emu(100)),
                cells=[
                    TableCell(
                        bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(156), pt_vers_emu(100)),
                        texte="A",
                    ),
                    TableCell(
                        bbox=BBox(pt_vers_emu(156), pt_vers_emu(72), pt_vers_emu(240), pt_vers_emu(100)),
                        texte="B",
                    ),
                ],
            )
        ],
        col_widths_emu=[pt_vers_emu(84), pt_vers_emu(84)],
        police=FontRef("Test", "Arial", False, False),
        size_pt=8,
    )
    document = Document(pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[table])])
    sortie = tmp_path / "table.docx"

    ecrire_docx(document, sortie)

    racine = ElementTree.fromstring(_lire(sortie, "word/document.xml"))
    assert len(list(racine.iter(f"{W}tbl"))) == 1
    assert len(list(racine.iter(f"{W}tc"))) == 2


def test_styles_de_span_sont_rendus_en_ooxml(tmp_path):
    from pdfexact.ir import Line, Span, TextBox

    span = Span(
        texte="Style",
        police=FontRef("Test", "Arial", True, True),
        size_pt=11,
        couleur="AA0000",
        souligne=True,
        barre=True,
        capitales=True,
        surlignage="yellow",
    )
    ligne = Line(
        bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(140), pt_vers_emu(86)),
        spans=[span],
        hauteur_ligne_emu=pt_vers_emu(14),
        largeur_cible_emu=pt_vers_emu(68),
    )
    document = Document(
        pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[TextBox(ligne.bbox, [ligne])])]
    )
    sortie = tmp_path / "styles.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert "<w:b/>" in xml
    assert "<w:i/>" in xml
    assert '<w:u w:val="single"/>' in xml
    assert "<w:strike/>" in xml
    assert "<w:caps/>" in xml
    assert '<w:highlight w:val="yellow"/>' in xml


def test_tableau_utilise_couleur_et_epaisseur_de_bordure(tmp_path):
    table = TableEl(
        bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(156), pt_vers_emu(100)),
        rows=[
            TableRow(
                bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(156), pt_vers_emu(100)),
                cells=[
                    TableCell(
                        bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(156), pt_vers_emu(100)),
                        texte="A",
                    ),
                ],
            )
        ],
        col_widths_emu=[pt_vers_emu(84)],
        police=FontRef("Test", "Arial", False, False),
        size_pt=8,
        bordure_couleur="336699",
        bordure_sz=12,
    )
    document = Document(pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[table])])
    sortie = tmp_path / "table_border.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert 'w:sz="12"' in xml
    assert 'w:color="336699"' in xml


def test_le_gestionnaire_de_relations_numerote_a_partir_de_un():
    gestionnaire = GestionnaireRelations()

    premier = gestionnaire.ajouter("media/image1.png", "image")
    second = gestionnaire.ajouter("media/image2.png", "image")

    assert premier == "rId1"
    assert second == "rId2"


def test_une_meme_cible_reutilise_son_identifiant():
    """Une image placée cinquante fois ne doit produire qu'une seule relation."""
    gestionnaire = GestionnaireRelations()

    premier = gestionnaire.ajouter("media/image1.png", "image")
    second = gestionnaire.ajouter("media/image1.png", "image")

    assert premier == second


def test_une_relation_externe_est_marquee():
    gestionnaire = GestionnaireRelations()

    gestionnaire.ajouter("https://example.org/", "hyperlink", externe=True)

    assert 'TargetMode="External"' in gestionnaire.vers_xml()


def test_une_cible_de_relation_est_echappee():
    gestionnaire = GestionnaireRelations()

    gestionnaire.ajouter('https://example.org/?a=1&b="deux"', "hyperlink", externe=True)

    xml = gestionnaire.vers_xml()
    assert "a=1&amp;b=&quot;deux&quot;" in xml


def test_une_relation_interne_nest_pas_marquee():
    gestionnaire = GestionnaireRelations()

    gestionnaire.ajouter("media/image1.png", "image")

    assert "TargetMode" not in gestionnaire.vers_xml()


def test_libreoffice_ouvre_le_fichier(docx_deux_pages, tmp_path):
    """Vérifie qu'un lecteur réel consomme le package, sans plus.

    LibreOffice n'est PAS un validateur : il convertit même du texte brut renommé en
    .docx sans erreur (mesuré dans tests/visual/test_harness.py). La conformité
    structurelle est couverte par les tests de parties obligatoires et de bonne formation
    XML ci-dessus ; celui-ci ajoute seulement qu'un vrai lecteur ne s'étrangle pas.
    """
    resultat = subprocess.run(
        [
            "soffice",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(tmp_path),
            str(docx_deux_pages),
        ],
        capture_output=True,
        timeout=180,
    )

    assert resultat.returncode == 0, resultat.stderr.decode(errors="replace")
    assert (tmp_path / "vide.pdf").exists()
