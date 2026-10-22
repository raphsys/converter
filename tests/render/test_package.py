import os
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

from pdfexact.geometry import emu_vers_pt, pt_vers_emu, pt_vers_twips, quantifier_bbox
from pdfexact.geometry import BBox
from pdfexact.ir import (
    Document,
    FontAsset,
    FontRef,
    ImageEl,
    FlowParagraph,
    Line,
    MediaItem,
    Page,
    ShapeEl,
    Span,
    TableBorder,
    TableCell,
    TableEl,
    TableRow,
    TextBox,
)
from pdfexact.render.drawing import _hauteurs_lignes_table
from pdfexact.render.docx_writer import (
    _ajuster_spans_a_largeur,
    _fusionner_fragments_meme_ligne,
    _grille_vertical_layout,
    _ligne_ajustee_largeur,
    _ordonner_bandeaux_sur_images,
)
from pdfexact.render.package import GestionnaireRelations, ecrire_docx
from pdfexact.render.native_contract import corriger_document_word_native, inspecter_docx_word_native

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


def test_bandeau_vectoriel_recouvrant_une_image_est_emis_apres_l_image():
    image = ImageEl(BBox(0, pt_vers_emu(20), A4_LARGEUR, pt_vers_emu(300)), "photo")
    bandeau = ShapeEl(
        BBox(0, pt_vers_emu(20), A4_LARGEUR, pt_vers_emu(45)),
        [],
        "000000",
        None,
        0,
    )
    page = Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR)
    resultat = _ordonner_bandeaux_sur_images([bandeau, image], page)
    assert resultat[-1] is bandeau


def test_fragments_de_regions_differentes_ne_sont_pas_fusionnes():
    police = FontRef("Test", "Arial", False, False)
    bbox_a = BBox(pt_vers_emu(40), pt_vers_emu(80), pt_vers_emu(150), pt_vers_emu(94))
    bbox_b = BBox(pt_vers_emu(160), pt_vers_emu(80), pt_vers_emu(270), pt_vers_emu(94))
    ligne_a = Line(
        bbox=bbox_a,
        spans=[Span("left region", police, 10, "000000", bbox=bbox_a)],
        hauteur_ligne_emu=pt_vers_emu(14),
        largeur_cible_emu=pt_vers_emu(110),
    )
    ligne_b = Line(
        bbox=bbox_b,
        spans=[Span("right region", police, 10, "000000", bbox=bbox_b)],
        hauteur_ligne_emu=pt_vers_emu(14),
        largeur_cible_emu=pt_vers_emu(110),
    )
    a = FlowParagraph(
        bbox=bbox_a,
        texte="left region",
        police=police,
        size_pt=10,
        couleur="000000",
        spans=list(ligne_a.spans),
        lignes=[ligne_a],
        layout_frame_id="left",
        layout_frame_bbox=BBox(pt_vers_emu(40), pt_vers_emu(70), pt_vers_emu(150), pt_vers_emu(110)),
    )
    b = FlowParagraph(
        bbox=bbox_b,
        texte="right region",
        police=police,
        size_pt=10,
        couleur="000000",
        spans=list(ligne_b.spans),
        lignes=[ligne_b],
        layout_frame_id="right",
        layout_frame_bbox=BBox(pt_vers_emu(160), pt_vers_emu(70), pt_vers_emu(270), pt_vers_emu(110)),
    )

    fragments = _fusionner_fragments_meme_ligne([(1, a), (1, b)])

    assert len(fragments) == 2


def test_grille_verticale_compresse_les_minima_qui_depassent_la_page():
    police = FontRef("Test", "Arial", False, False)
    paragraphes = []
    for index in range(70):
        y = 20 + index * 12
        bbox = BBox(pt_vers_emu(40), pt_vers_emu(y), pt_vers_emu(280), pt_vers_emu(y + 18))
        ligne = Line(
            bbox=bbox,
            spans=[Span(f"Line {index}", police, 18, "000000", bbox=bbox)],
            hauteur_ligne_emu=pt_vers_emu(18),
            largeur_cible_emu=pt_vers_emu(240),
        )
        paragraphes.append(
            FlowParagraph(
                bbox=bbox,
                texte=f"Line {index}",
                police=police,
                size_pt=18,
                couleur="000000",
                spans=list(ligne.spans),
                lignes=[ligne],
                layout_frame_id=f"frame-{index}",
                layout_frame_role="text-column",
                layout_frame_bbox=bbox,
            )
        )
    page = Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR)

    _bornes, hauteurs, hauteur_grille, compactage = _grille_vertical_layout(paragraphes, page)

    assert compactage
    assert sum(hauteurs) <= pt_vers_twips(emu_vers_pt(hauteur_grille))


def _env_libreoffice(tmp_path):
    libreoffice_home = tmp_path / "lo-home"
    libreoffice_profile = tmp_path / "lo-profile"
    xdg_config = tmp_path / "xdg-config"
    xdg_cache = tmp_path / "xdg-cache"
    xdg_runtime = tmp_path / "xdg-runtime"
    for chemin in (libreoffice_home, libreoffice_profile, xdg_config, xdg_cache, xdg_runtime):
        chemin.mkdir()
    xdg_runtime.chmod(0o700)

    return {
        **os.environ,
        "HOME": str(libreoffice_home),
        "XDG_CONFIG_HOME": str(xdg_config),
        "XDG_CACHE_HOME": str(xdg_cache),
        "XDG_RUNTIME_DIR": str(xdg_runtime),
        "SAL_USE_VCLPLUGIN": "svp",
    }, libreoffice_profile


def _skip_si_libreoffice_ne_convertit_pas(tmp_path, env, profile):
    entree = tmp_path / "smoke.txt"
    entree.write_text("smoke\n", encoding="utf-8")
    resultat = subprocess.run(
        [
            "soffice",
            "--headless",
            f"-env:UserInstallation={profile.as_uri()}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(tmp_path),
            str(entree),
        ],
        capture_output=True,
        env=env,
        timeout=180,
    )
    if resultat.returncode != 0 or not (tmp_path / "smoke.pdf").exists():
        pytest.skip("LibreOffice headless ne peut pas convertir dans cet environnement")


def test_le_zip_contient_les_parties_obligatoires(docx_deux_pages):
    with zipfile.ZipFile(docx_deux_pages) as z:
        noms = set(z.namelist())

    assert "[Content_Types].xml" in noms
    assert "_rels/.rels" in noms
    assert "word/document.xml" in noms
    assert "word/_rels/document.xml.rels" in noms
    assert "word/styles.xml" in noms
    assert "word/settings.xml" in noms


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


def test_les_ancres_sont_quantifiees_au_dixieme_de_millimetre(tmp_path):
    police = FontRef("Test", "Arial", False, False)
    ligne = Line(
        bbox=BBox(pt_vers_emu(10.03), pt_vers_emu(20.07), pt_vers_emu(110.02), pt_vers_emu(31.04)),
        spans=[Span("snap", police, 10, "000000")],
        hauteur_ligne_emu=pt_vers_emu(11),
        largeur_cible_emu=pt_vers_emu(100),
    )
    sortie = tmp_path / "snap.docx"

    ecrire_docx(
        Document(
            pages=[
                Page(
                    index=0,
                    largeur_emu=A4_LARGEUR,
                    hauteur_emu=A4_HAUTEUR,
                    elements=[TextBox(ligne.bbox, [ligne])],
                )
            ]
        ),
        sortie,
    )

    xml = _lire(sortie, "word/document.xml").decode()
    assert '<wp:posOffset>126000</wp:posOffset>' in xml
    assert '<wp:posOffset>252000</wp:posOffset>' in xml


def test_lajustement_largeur_reduit_une_prose_trop_large(monkeypatch):
    police = FontRef("Wide-Regular", "Wide", False, False)
    spans = [Span("Texte tres long", police, 18.0, "000000")]

    def faux_mesurer(texte, _asset, size_pt):
        return len(texte) * size_pt

    monkeypatch.setattr("pdfexact.extract.fonts.mesurer_largeur_pt", faux_mesurer)
    ajustes = _ajuster_spans_a_largeur(spans, pt_vers_emu(20), {"Wide-Regular": object()}, compact=True)

    assert ajustes[0].size_pt < 18.0
    assert ajustes[0].espacement_twips == 0


def test_lajustement_largeur_clampe_la_compression_existante(monkeypatch):
    police = FontRef("Wide-Regular", "Wide", False, False)
    spans = [Span("Compression", police, 30.0, "000000", espacement_twips=-120)]

    def faux_mesurer(texte, _asset, size_pt):
        return len(texte) * size_pt

    monkeypatch.setattr("pdfexact.extract.fonts.mesurer_largeur_pt", faux_mesurer)
    ajustes = _ajuster_spans_a_largeur(spans, pt_vers_emu(20), {"Wide-Regular": object()}, compact=True)

    assert ajustes[0].espacement_twips == -24


def test_ligne_paragraphe_sans_frame_ne_subit_pas_compactage_fort(monkeypatch):
    police = FontRef("Wide-Regular", "Wide", False, False)
    ligne = Line(
        bbox=BBox(0, 0, pt_vers_emu(90), pt_vers_emu(12)),
        spans=[Span("This is a normal paragraph line with several words.", police, 10.0, "000000")],
        hauteur_ligne_emu=pt_vers_emu(12),
        largeur_cible_emu=pt_vers_emu(90),
    )

    def faux_mesurer(texte, _asset, size_pt):
        return len(texte) * size_pt

    monkeypatch.setattr("pdfexact.extract.fonts.mesurer_largeur_pt", faux_mesurer)
    ajustee = _ligne_ajustee_largeur(ligne, {"Wide-Regular": object()})

    assert ajustee.spans[0].espacement_twips == 0


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


def test_paragraphe_de_section_a_hauteur_minimale(docx_deux_pages):
    xml = _lire(docx_deux_pages, "word/document.xml").decode()

    assert '<w:spacing w:before="0" w:after="0" w:line="1" w:lineRule="exact"/><w:sectPr>' in xml


def test_la_derniere_section_est_au_niveau_du_corps(docx_deux_pages):
    """OOXML impose que la dernière section soit fille de w:body, pas d'un paragraphe."""
    racine = ElementTree.fromstring(_lire(docx_deux_pages, "word/document.xml"))

    corps = racine.find(f"{W}body")
    assert corps[-1].tag == f"{W}sectPr"


def test_le_style_est_declare_en_relation(docx_deux_pages):
    relations = _lire(docx_deux_pages, "word/_rels/document.xml.rels").decode()

    assert "styles.xml" in relations


def test_les_parametres_word_sont_declares_en_relation(docx_deux_pages):
    relations = _lire(docx_deux_pages, "word/_rels/document.xml.rels").decode()
    settings = _lire(docx_deux_pages, "word/settings.xml").decode()

    assert "settings.xml" in relations
    assert 'w:name="compatibilityMode"' in settings
    assert 'w:val="15"' in settings


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


def test_tableau_paysage_est_positionne_page(tmp_path):
    police = FontRef("ArialNarrow-Bold", "Liberation Sans Narrow", True, False)
    table = TableEl(
        bbox=BBox(pt_vers_emu(44), pt_vers_emu(102), pt_vers_emu(1210), pt_vers_emu(612)),
        rows=[
            TableRow(
                bbox=BBox(pt_vers_emu(44), pt_vers_emu(102), pt_vers_emu(1210), pt_vers_emu(126)),
                cells=[
                    TableCell(
                        bbox=BBox(pt_vers_emu(44), pt_vers_emu(102), pt_vers_emu(320), pt_vers_emu(126)),
                        texte="SUBDIVISION",
                        spans=[
                            Span(
                                "SUBDIVISION",
                                police,
                                9,
                                "000000",
                                bbox=BBox(
                                    pt_vers_emu(160),
                                    pt_vers_emu(108),
                                    pt_vers_emu(230),
                                    pt_vers_emu(118),
                                ),
                            )
                        ],
                    ),
                    TableCell(
                        bbox=BBox(pt_vers_emu(320), pt_vers_emu(102), pt_vers_emu(1210), pt_vers_emu(126)),
                        texte="Remarks",
                        fond="264769",
                        spans=[
                            Span(
                                "Remarks",
                                police,
                                9,
                                "000000",
                                bbox=BBox(
                                    pt_vers_emu(1120),
                                    pt_vers_emu(108),
                                    pt_vers_emu(1170),
                                    pt_vers_emu(118),
                                ),
                            )
                        ],
                    ),
                ],
            )
        ],
        col_widths_emu=[pt_vers_emu(276), pt_vers_emu(890)],
        police=police,
        size_pt=9,
    )
    document = Document(
        pages=[Page(index=0, largeur_emu=pt_vers_emu(1224), hauteur_emu=pt_vers_emu(792), elements=[table])]
    )
    sortie = tmp_path / "landscape_table_positioned.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert '<w:pgSz w:w="24480" w:h="15840" w:orient="landscape"/>' in xml
    assert "<w:tbl>" not in xml
    assert "<wp:anchor" in xml
    assert "<wps:txbx>" in xml
    assert '<a:srgbClr val="264769">' in xml
    assert '<w:color w:val="FFFFFF"/>' in xml
    assert "SUBDIVISION" in xml


def test_tableau_utilise_position_texte_cellule_depuis_bbox(tmp_path):
    police = FontRef("ArialNarrow-Bold", "Liberation Sans Narrow", True, False)
    cell_bbox = BBox(pt_vers_emu(100), pt_vers_emu(100), pt_vers_emu(260), pt_vers_emu(130))
    table = TableEl(
        bbox=cell_bbox,
        rows=[
            TableRow(
                bbox=cell_bbox,
                cells=[
                    TableCell(
                        bbox=cell_bbox,
                        texte="Remarks",
                        spans=[
                            Span(
                                "Remarks",
                                police,
                                9,
                                "000000",
                                bbox=BBox(
                                    pt_vers_emu(112),
                                    pt_vers_emu(107),
                                    pt_vers_emu(156),
                                    pt_vers_emu(117),
                                ),
                            )
                        ],
                        alignement="left",
                    )
                ],
            )
        ],
        col_widths_emu=[cell_bbox.largeur],
        police=police,
        size_pt=9,
    )
    document = Document(
        pages=[Page(index=0, largeur_emu=pt_vers_emu(300), hauteur_emu=pt_vers_emu(400), elements=[table])]
    )
    sortie = tmp_path / "table_cell_text_position.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert '<w:vAlign w:val="top"/>' in xml
    assert '<w:left w:w="244" w:type="dxa"/>' in xml
    assert '<w:right w:w="0" w:type="dxa"/>' in xml
    assert '<w:top w:w="142" w:type="dxa"/>' in xml
    assert '<w:jc w:val="left"/>' in xml


def test_tableau_ancre_ne_double_pas_son_decalage_x(tmp_path):
    police = FontRef("Test", "Arial", False, False)
    texte = TextBox(
        bbox=BBox(pt_vers_emu(72), pt_vers_emu(120), pt_vers_emu(240), pt_vers_emu(136)),
        lignes=[
            Line(
                bbox=BBox(pt_vers_emu(72), pt_vers_emu(120), pt_vers_emu(240), pt_vers_emu(136)),
                spans=[Span("Avant le tableau", police, 10, "000000")],
                hauteur_ligne_emu=pt_vers_emu(12),
                largeur_cible_emu=pt_vers_emu(168),
            )
        ],
    )
    table = TableEl(
        bbox=BBox(pt_vers_emu(96), pt_vers_emu(180), pt_vers_emu(240), pt_vers_emu(220)),
        rows=[
            TableRow(
                bbox=BBox(pt_vers_emu(96), pt_vers_emu(180), pt_vers_emu(240), pt_vers_emu(220)),
                cells=[
                    TableCell(
                        bbox=BBox(pt_vers_emu(96), pt_vers_emu(180), pt_vers_emu(240), pt_vers_emu(220)),
                        texte="Cell",
                    )
                ],
            )
        ],
        col_widths_emu=[pt_vers_emu(144)],
        police=police,
        size_pt=8,
    )
    document = Document(
        pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[texte, table])]
    )
    sortie = tmp_path / "anchored_table_no_double_x.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert "<wp:anchor" in xml
    assert '<w:tblInd w:w="0" w:type="dxa"/>' in xml


def test_tableau_recouvrant_texte_positionne_devient_fond_et_grille(tmp_path):
    police = FontRef("Test", "Arial", False, False)
    table = TableEl(
        bbox=BBox(pt_vers_emu(80), pt_vers_emu(120), pt_vers_emu(360), pt_vers_emu(210)),
        rows=[
            TableRow(
                bbox=BBox(pt_vers_emu(80), pt_vers_emu(120), pt_vers_emu(360), pt_vers_emu(210)),
                cells=[
                    TableCell(
                        bbox=BBox(pt_vers_emu(80), pt_vers_emu(120), pt_vers_emu(360), pt_vers_emu(210)),
                        texte="",
                        fond="FFF2CC",
                    )
                ],
            )
        ],
        col_widths_emu=[pt_vers_emu(280)],
        police=police,
        size_pt=9,
    )
    lignes = []
    for index, texte_ligne in enumerate(["Checkpoint 2", "The following equations"]):
        bbox = BBox(
            pt_vers_emu(100),
            pt_vers_emu(132 + index * 14),
            pt_vers_emu(300),
            pt_vers_emu(144 + index * 14),
        )
        lignes.append(
            Line(
                bbox=bbox,
                spans=[Span(texte_ligne, police, 9, "000000", bbox=bbox)],
                hauteur_ligne_emu=bbox.hauteur,
                largeur_cible_emu=bbox.largeur,
            )
        )
    elements = [table, *(TextBox(ligne.bbox, [ligne]) for ligne in lignes)]
    document = Document(
        pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=elements)]
    )
    sortie = tmp_path / "table_as_background.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert "<w:tbl>" not in xml
    assert "Checkpoint 2" in xml
    assert "The following equations" in xml


def test_tableau_a_sous_lignes_chevauchantes_reste_dans_sa_bbox():
    police = FontRef("Test", "Arial", False, False)
    table = TableEl(
        bbox=BBox(pt_vers_emu(100), pt_vers_emu(100), pt_vers_emu(300), pt_vers_emu(200)),
        rows=[
            TableRow(BBox(pt_vers_emu(100), pt_vers_emu(100), pt_vers_emu(300), pt_vers_emu(160)), []),
            TableRow(BBox(pt_vers_emu(100), pt_vers_emu(130), pt_vers_emu(300), pt_vers_emu(160)), []),
            TableRow(BBox(pt_vers_emu(100), pt_vers_emu(160), pt_vers_emu(300), pt_vers_emu(200)), []),
        ],
        col_widths_emu=[pt_vers_emu(200)],
        police=police,
        size_pt=8,
    )

    hauteurs = _hauteurs_lignes_table(table)

    assert hauteurs == [pt_vers_emu(30), pt_vers_emu(30), pt_vers_emu(40)]
    assert sum(hauteurs) == table.bbox.hauteur


def test_un_tableau_preserve_les_fusions_verticales_word(tmp_path):
    table = TableEl(
        bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(240), pt_vers_emu(130)),
        rows=[
            TableRow(
                bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(240), pt_vers_emu(100)),
                cells=[
                    TableCell(
                        bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(156), pt_vers_emu(100)),
                        texte="Header",
                        v_merge="restart",
                    ),
                    TableCell(
                        bbox=BBox(pt_vers_emu(156), pt_vers_emu(72), pt_vers_emu(240), pt_vers_emu(100)),
                        texte="B",
                    ),
                ],
            ),
            TableRow(
                bbox=BBox(pt_vers_emu(72), pt_vers_emu(100), pt_vers_emu(240), pt_vers_emu(130)),
                cells=[
                    TableCell(
                        bbox=BBox(pt_vers_emu(72), pt_vers_emu(100), pt_vers_emu(156), pt_vers_emu(130)),
                        texte="",
                        v_merge="continue",
                    ),
                    TableCell(
                        bbox=BBox(pt_vers_emu(156), pt_vers_emu(100), pt_vers_emu(240), pt_vers_emu(130)),
                        texte="C",
                    ),
                ],
            ),
        ],
        col_widths_emu=[pt_vers_emu(84), pt_vers_emu(84)],
        police=FontRef("Test", "Arial", False, False),
        size_pt=8,
    )
    document = Document(pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[table])])
    sortie = tmp_path / "table_vmerge.docx"

    ecrire_docx(document, sortie)

    racine = ElementTree.fromstring(_lire(sortie, "word/document.xml"))
    fusions = list(racine.iter(f"{W}vMerge"))
    assert len(fusions) == 2
    assert fusions[0].attrib[f"{W}val"] == "restart"


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


def test_tableau_rend_fond_et_bordures_de_cellule(tmp_path):
    table = TableEl(
        bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(156), pt_vers_emu(100)),
        rows=[
            TableRow(
                bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(156), pt_vers_emu(100)),
                cells=[
                    TableCell(
                        bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(156), pt_vers_emu(100)),
                        texte="A",
                        fond="E6E6E6",
                        bordures={
                            "top": TableBorder(couleur="FF0000", sz=8),
                            "left": TableBorder(couleur="00AA00", sz=4),
                        },
                    ),
                ],
            )
        ],
        col_widths_emu=[pt_vers_emu(84)],
        police=FontRef("Test", "Arial", False, False),
        size_pt=8,
    )
    document = Document(pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[table])])
    sortie = tmp_path / "table_cell_style.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert '<w:shd w:fill="E6E6E6"/>' in xml
    assert "<w:tcBorders>" in xml
    assert '<w:top w:val="single" w:sz="8" w:space="0" w:color="FF0000"/>' in xml
    assert '<w:left w:val="single" w:sz="4" w:space="0" w:color="00AA00"/>' in xml


def test_tableau_listing_sans_bordures_globales_garde_bordures_cellules(tmp_path):
    table = TableEl(
        bbox=BBox(pt_vers_emu(10), pt_vers_emu(10), pt_vers_emu(110), pt_vers_emu(40)),
        rows=[
            TableRow(
                bbox=BBox(pt_vers_emu(10), pt_vers_emu(10), pt_vers_emu(110), pt_vers_emu(40)),
                cells=[
                    TableCell(
                        bbox=BBox(pt_vers_emu(10), pt_vers_emu(10), pt_vers_emu(60), pt_vers_emu(40)),
                        texte="Subject",
                        bordures={"right": TableBorder(couleur="231F20", sz=4)},
                    ),
                    TableCell(
                        bbox=BBox(pt_vers_emu(60), pt_vers_emu(10), pt_vers_emu(110), pt_vers_emu(40)),
                        texte="Number",
                    ),
                ],
            )
        ],
        col_widths_emu=[pt_vers_emu(50), pt_vers_emu(50)],
        police=FontRef("Test", "Arial", False, False),
        size_pt=8,
        bordures_globales=False,
    )
    document = Document(pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[table])])
    sortie = tmp_path / "table_sparse_borders.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert '<w:insideH w:val="nil"/>' in xml
    assert '<w:right w:val="single" w:sz="4" w:space="0" w:color="231F20"/>' in xml


def test_tableau_rend_direction_verticale_de_cellule(tmp_path):
    table = TableEl(
        bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(110), pt_vers_emu(170)),
        rows=[
            TableRow(
                bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(110), pt_vers_emu(170)),
                cells=[
                    TableCell(
                        bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(110), pt_vers_emu(170)),
                        texte="Vertical header",
                        direction_texte="btLr",
                    ),
                ],
            )
        ],
        col_widths_emu=[pt_vers_emu(38)],
        police=FontRef("Test", "Arial", False, False),
        size_pt=8,
    )
    document = Document(pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[table])])
    sortie = tmp_path / "table_cell_vertical.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert '<w:textDirection w:val="btLr"/>' in xml


def test_tableau_exact_verrouille_hauteur_et_marges(tmp_path):
    table = TableEl(
        bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(156), pt_vers_emu(92)),
        rows=[
            TableRow(
                bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(156), pt_vers_emu(92)),
                cells=[
                    TableCell(
                        bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(156), pt_vers_emu(92)),
                        texte="Cellule longue",
                    ),
                ],
            )
        ],
        col_widths_emu=[pt_vers_emu(84)],
        police=FontRef("Test", "Arial", False, False),
        size_pt=12,
    )
    document = Document(pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[table])])
    sortie = tmp_path / "table_exact.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert '<w:cantSplit/>' in xml
    assert 'w:hRule="exact"' in xml
    assert '<w:tblCellMar>' in xml
    assert '<w:top w:w="0" w:type="dxa"/>' in xml


def test_tableau_exact_preserve_la_taille_de_police_source(tmp_path):
    police = FontRef("Test", "Arial", False, False)
    table = TableEl(
        bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(108), pt_vers_emu(84)),
        rows=[
            TableRow(
                bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(108), pt_vers_emu(84)),
                cells=[
                    TableCell(
                        bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(108), pt_vers_emu(84)),
                        texte="Texte long",
                        spans=[Span("Texte long", police, 12, "000000")],
                    ),
                ],
            )
        ],
        col_widths_emu=[pt_vers_emu(36)],
        police=police,
        size_pt=12,
    )
    document = Document(pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[table])])
    sortie = tmp_path / "table_preserve_size.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert '<w:sz w:val="24"/>' in xml


def test_tableau_exact_necrit_pas_approche_negative_wps(tmp_path):
    police = FontRef("Test", "Arial", False, False)
    table = TableEl(
        bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(102), pt_vers_emu(90)),
        rows=[
            TableRow(
                bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(102), pt_vers_emu(90)),
                cells=[
                    TableCell(
                        bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(102), pt_vers_emu(90)),
                    texte="Very long header",
                    spans=[Span("Very long header", police, 12, "000000")],
                    ),
                ],
            )
        ],
        col_widths_emu=[pt_vers_emu(30)],
        police=police,
        size_pt=12,
    )
    document = Document(pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[table])])
    sortie = tmp_path / "table_fit_spacing.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert '<w:sz w:val="24"/>' in xml
    assert '<w:spacing w:val="-12"/>' not in xml


def test_run_multiligne_devient_des_sauts_word(tmp_path):
    police = FontRef("Test", "Arial", False, False)
    table = TableEl(
        bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(150), pt_vers_emu(112)),
        rows=[
            TableRow(
                bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(150), pt_vers_emu(112)),
                cells=[
                    TableCell(
                        bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(150), pt_vers_emu(112)),
                        texte="COUNT\nY/CITY",
                        spans=[Span("COUNT\nY/CITY", police, 9, "000000")],
                    ),
                ],
            )
        ],
        col_widths_emu=[pt_vers_emu(78)],
        police=police,
        size_pt=9,
    )
    document = Document(pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[table])])
    sortie = tmp_path / "table_multiline.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert "<w:br/>" in xml
    assert ">COUNT<" in xml
    assert ">Y/CITY<" in xml


def test_tableau_exact_force_le_contraste_sur_fond_sombre(tmp_path):
    police = FontRef("Test", "Arial", False, False)
    table = TableEl(
        bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(160), pt_vers_emu(100)),
        rows=[
            TableRow(
                bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(160), pt_vers_emu(100)),
                cells=[
                    TableCell(
                        bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(160), pt_vers_emu(100)),
                        texte="Header",
                        fond="000000",
                        spans=[Span("Header", police, 9, "000000")],
                    ),
                ],
            )
        ],
        col_widths_emu=[pt_vers_emu(88)],
        police=police,
        size_pt=9,
    )
    document = Document(pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[table])])
    sortie = tmp_path / "table_dark.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert '<w:shd w:fill="000000"/>' in xml
    assert '<w:color w:val="FFFFFF"/>' in xml
    assert '<w:vAlign w:val="top"/>' in xml


def test_tableau_en_flux_word_natif_n_est_pas_dans_un_drawing(tmp_path):
    police = FontRef("Test", "Arial", False, False)
    paragraphe = FlowParagraph(
        bbox=BBox(pt_vers_emu(72), pt_vers_emu(72), pt_vers_emu(220), pt_vers_emu(90)),
        texte="Avant le tableau",
        police=police,
        size_pt=10,
        couleur="000000",
    )
    table = TableEl(
        bbox=BBox(pt_vers_emu(72), pt_vers_emu(100), pt_vers_emu(156), pt_vers_emu(130)),
        rows=[
            TableRow(
                bbox=BBox(pt_vers_emu(72), pt_vers_emu(100), pt_vers_emu(156), pt_vers_emu(130)),
                cells=[
                    TableCell(
                        bbox=BBox(pt_vers_emu(72), pt_vers_emu(100), pt_vers_emu(156), pt_vers_emu(130)),
                        texte="Cellule",
                    ),
                ],
            )
        ],
        col_widths_emu=[pt_vers_emu(84)],
        police=police,
        size_pt=8,
    )
    document = Document(
        pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[paragraphe, table])]
    )
    sortie = tmp_path / "native_flow_table.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert "<w:tbl>" in xml
    assert "<w:drawing>" not in xml


def test_fond_vectoriel_en_flux_devient_un_shading_word(tmp_path):
    police = FontRef("Test", "Arial", False, False)
    fond = ShapeEl(
        bbox=BBox(pt_vers_emu(70), pt_vers_emu(90), pt_vers_emu(520), pt_vers_emu(115)),
        chemins=[],
        remplissage="000080",
        contour=None,
        epaisseur_emu=0,
    )
    paragraphe = FlowParagraph(
        bbox=BBox(pt_vers_emu(120), pt_vers_emu(100), pt_vers_emu(470), pt_vers_emu(122)),
        texte="ABBREVIATIONS AND ACRONYMS",
        police=police,
        size_pt=12,
        couleur="FFFFFF",
        alignement="center",
    )
    document = Document(
        pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[fond, paragraphe])]
    )
    sortie = tmp_path / "native_flow_shading.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert '<w:shd w:fill="000080"/>' in xml
    assert "<w:drawing>" not in xml


def test_entree_sommaire_en_flux_utilise_tabulation_leader_word(tmp_path):
    police = FontRef("Test", "Arial", False, False)
    paragraphe = FlowParagraph(
        bbox=BBox(pt_vers_emu(86), pt_vers_emu(120), pt_vers_emu(528), pt_vers_emu(136)),
        texte="Purpose ------------------------------------------------------------ 7",
        police=police,
        size_pt=10,
        couleur="000000",
    )
    document = Document(
        pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[paragraphe])]
    )
    sortie = tmp_path / "toc_leader.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert '<w:tab w:val="right" w:leader="hyphen"' in xml
    assert "<w:tab/>" in xml
    assert "Purpose ------------------------------------------------------------ 7" not in xml
    assert '<w:t xml:space="preserve">Purpose</w:t>' in xml
    assert '<w:t xml:space="preserve">7</w:t>' in xml


def test_paragraphe_flux_conserve_les_spans_natfs(tmp_path):
    normal = FontRef("TimesNewRomanPSMT", "Liberation Serif", False, False)
    italique = FontRef("TimesNewRomanPS-ItalicMT", "Liberation Serif", False, True)
    paragraphe = FlowParagraph(
        bbox=BBox(pt_vers_emu(60), pt_vers_emu(120), pt_vers_emu(540), pt_vers_emu(134)),
        texte="USAID/OFDA bulletins http://example.test",
        police=italique,
        size_pt=9,
        couleur="000000",
        spans=[
            Span("USAID/OFDA bulletins ", italique, 9, "000000"),
            Span("http://example.test", normal, 9, "0000FF"),
        ],
    )
    document = Document(
        pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[paragraphe])]
    )
    sortie = tmp_path / "native_flow_spans.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert '<w:i/>' in xml
    assert '<w:color w:val="0000FF"/>' in xml
    assert '<w:t xml:space="preserve">USAID/OFDA bulletins </w:t>' in xml
    assert '<w:t xml:space="preserve">http://example.test</w:t>' in xml


def test_paragraphe_flux_liste_ecrit_tabulation_et_retrait_suspendu(tmp_path):
    police = FontRef("TimesNewRomanPSMT", "Liberation Serif", False, False)
    paragraphe = FlowParagraph(
        bbox=BBox(pt_vers_emu(100.8), pt_vers_emu(120), pt_vers_emu(320), pt_vers_emu(134)),
        texte="o USAID: www.usaid.gov",
        police=police,
        size_pt=10,
        couleur="000000",
        retrait_gauche_emu=pt_vers_emu(118.8),
        retrait_premiere_ligne_emu=pt_vers_emu(100.8) - pt_vers_emu(118.8),
        spans=[
            Span("o", police, 10, "000000"),
            Span("\t", police, 10, "000000"),
            Span("USAID: www.usaid.gov", police, 10, "000000"),
        ],
    )
    document = Document(
        pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[paragraphe])]
    )
    sortie = tmp_path / "native_flow_list_indent.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert '<w:tab w:val="left"' in xml
    assert "<w:tab/>" in xml
    assert 'w:firstLine="-360"' in xml


def test_paragraphe_word_native_reste_un_paragraphe_reel(tmp_path):
    police = FontRef("TimesNewRomanPSMT", "Liberation Serif", False, False)
    paragraphe = FlowParagraph(
        bbox=BBox(pt_vers_emu(72), pt_vers_emu(120), pt_vers_emu(300), pt_vers_emu(134)),
        texte="Texte positionne",
        police=police,
        size_pt=10,
        couleur="000000",
        retrait_gauche_emu=pt_vers_emu(72),
    )
    document = Document(
        pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[paragraphe])]
    )
    sortie = tmp_path / "native_positioned_frame.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert "<w:framePr " not in xml
    assert "<wp:anchor" not in xml
    assert "wps:txbx" not in xml
    assert "Texte positionne" in xml
    assert '<w:ind w:left="1440"' in xml


def test_paragraphe_word_native_n_ecrit_pas_approche_negative_wps(tmp_path):
    police = FontRef("TimesNewRomanPSMT", "Liberation Serif", False, False)
    paragraphe = FlowParagraph(
        bbox=BBox(pt_vers_emu(72), pt_vers_emu(120), pt_vers_emu(300), pt_vers_emu(134)),
        texte="Texte lisible",
        police=police,
        size_pt=10,
        couleur="000000",
        spans=[Span("Texte lisible", police, 10, "000000", espacement_twips=-4)],
    )
    document = Document(
        pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[paragraphe])]
    )
    sortie = tmp_path / "native_no_negative_tracking.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert '<w:spacing w:val="-4"/>' not in xml


def test_ligne_positionnee_ecrit_approche_negative_page_exact(tmp_path):
    police = FontRef("TimesNewRomanPSMT", "Liberation Serif", False, False)
    ligne = Line(
        bbox=BBox(pt_vers_emu(72), pt_vers_emu(120), pt_vers_emu(300), pt_vers_emu(134)),
        spans=[Span("Titre large", police, 36, "000000", espacement_twips=-18)],
        hauteur_ligne_emu=pt_vers_emu(42),
        largeur_cible_emu=pt_vers_emu(228),
    )
    document = Document(
        pages=[
            Page(
                index=0,
                largeur_emu=A4_LARGEUR,
                hauteur_emu=A4_HAUTEUR,
                elements=[TextBox(bbox=ligne.bbox, lignes=[ligne])],
            )
        ]
    )
    sortie = tmp_path / "native_positioned_negative_tracking.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert '<w:spacing w:val="-18"/>' in xml


def test_paragraphe_word_native_multiligne_reste_une_seule_zone(tmp_path):
    police = FontRef("TimesNewRomanPSMT", "Liberation Serif", False, False)
    lignes = [
        Line(
            bbox=BBox(pt_vers_emu(72), pt_vers_emu(120), pt_vers_emu(300), pt_vers_emu(132)),
            spans=[Span("Premiere ligne", police, 10, "000000")],
            hauteur_ligne_emu=pt_vers_emu(12),
            largeur_cible_emu=pt_vers_emu(228),
        ),
        Line(
            bbox=BBox(pt_vers_emu(72), pt_vers_emu(134), pt_vers_emu(310), pt_vers_emu(146)),
            spans=[Span("Deuxieme ligne", police, 10, "000000")],
            hauteur_ligne_emu=pt_vers_emu(12),
            largeur_cible_emu=pt_vers_emu(238),
        ),
    ]
    paragraphe = FlowParagraph(
        bbox=BBox(pt_vers_emu(72), pt_vers_emu(120), pt_vers_emu(310), pt_vers_emu(146)),
        texte="Premiere ligne Deuxieme ligne",
        police=police,
        size_pt=10,
        couleur="000000",
        retrait_gauche_emu=pt_vers_emu(72),
        lignes=lignes,
    )
    document = Document(
        pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[paragraphe])]
    )
    sortie = tmp_path / "native_positioned_paragraph.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert "<wps:txbx>" not in xml
    assert "<wp:anchor" not in xml
    # Les retours PDF ordinaires sont reflowes dans le meme paragraphe Word.
    assert "<w:br/>" not in xml


def test_paragraphe_word_native_preserve_les_decalages_de_lignes(tmp_path):
    police = FontRef("TimesNewRomanPSMT", "Liberation Serif", False, False)
    lignes = [
        Line(
            bbox=BBox(pt_vers_emu(110), pt_vers_emu(120), pt_vers_emu(300), pt_vers_emu(132)),
            spans=[Span("Ligne contournee", police, 10, "000000")],
            hauteur_ligne_emu=pt_vers_emu(12),
            largeur_cible_emu=pt_vers_emu(190),
        ),
        Line(
            bbox=BBox(pt_vers_emu(72), pt_vers_emu(134), pt_vers_emu(310), pt_vers_emu(146)),
            spans=[Span("Retour marge gauche", police, 10, "000000")],
            hauteur_ligne_emu=pt_vers_emu(12),
            largeur_cible_emu=pt_vers_emu(238),
        ),
    ]
    paragraphe = FlowParagraph(
        bbox=BBox(pt_vers_emu(72), pt_vers_emu(120), pt_vers_emu(310), pt_vers_emu(146)),
        texte="Ligne contournee Retour marge gauche",
        police=police,
        size_pt=10,
        couleur="000000",
        retrait_gauche_emu=pt_vers_emu(72),
        lignes=lignes,
    )
    document = Document(
        pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[paragraphe])]
    )
    sortie = tmp_path / "native_positioned_line_offsets.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert "<wps:txbx>" not in xml
    assert "<wp:anchor" not in xml
    assert '<w:tab w:val="left" w:pos="760"/>' in xml
    assert "<w:tab/>" in xml


def test_paragraphe_word_native_conserve_la_taille_pdf(tmp_path):
    police = FontRef("MyriadPro-BoldCond", "Source Sans Pro", True, False)
    paragraphe = FlowParagraph(
        bbox=BBox(pt_vers_emu(120), pt_vers_emu(60), pt_vers_emu(420), pt_vers_emu(84)),
        texte="Grand titre",
        police=police,
        size_pt=18,
        couleur="00806F",
        retrait_gauche_emu=pt_vers_emu(120),
        interligne_emu=pt_vers_emu(21),
    )
    document = Document(
        pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[paragraphe])]
    )
    sortie = tmp_path / "native_positioned_title_size.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert '<w:sz w:val="36"/>' in xml
    assert "<wps:txbx>" not in xml
    assert "<wp:anchor" not in xml
    assert '<w:ind w:left="2400"' in xml


def test_paragraphe_word_native_ne_double_pas_les_espaces_pdf(tmp_path):
    police = FontRef("TimesNewRomanPSMT", "Liberation Serif", False, False)
    paragraphe = FlowParagraph(
        bbox=BBox(pt_vers_emu(72), pt_vers_emu(120), pt_vers_emu(300), pt_vers_emu(134)),
        texte="Texte positionne",
        police=police,
        size_pt=10,
        couleur="000000",
        retrait_gauche_emu=pt_vers_emu(72),
        espace_avant_emu=pt_vers_emu(18),
        espace_apres_emu=pt_vers_emu(9),
        interligne_emu=pt_vers_emu(12),
    )
    document = Document(
        pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[paragraphe])]
    )
    sortie = tmp_path / "native_no_double_spacing.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert 'w:before="360"' not in xml
    assert 'w:after="180"' not in xml
    assert '<w:spacing w:before="2400" w:after="0" w:line="280" w:lineRule="exact"/>' in xml


def test_paragraphe_word_native_compresse_pour_tenir_dans_la_bbox_pdf(tmp_path):
    police = FontRef("WideTest-Regular", "Nimbus Sans Narrow", False, False)
    paragraphe = FlowParagraph(
        bbox=BBox(pt_vers_emu(120), pt_vers_emu(60), pt_vers_emu(260), pt_vers_emu(84)),
        texte="Development and Study of a Method Adaptive in Angle",
        police=police,
        size_pt=24,
        couleur="00806F",
        retrait_gauche_emu=pt_vers_emu(120),
        retrait_droite_emu=pt_vers_emu(335),
        interligne_emu=pt_vers_emu(24),
    )
    document = Document(
        pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[paragraphe])]
    )
    document.polices["WideTest-Regular"] = FontAsset(
        font_id="WideTest-Regular",
        famille="Nimbus Sans Narrow",
        donnees=None,
        extension="otf",
        embarquee=False,
        chemin=Path("pdfexact/fonts/NimbusSansNarrow-Regular.otf"),
        reconnue=True,
    )
    sortie = tmp_path / "native_flow_fit_width.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert "<wp:anchor" not in xml
    assert "wps:txbx" not in xml
    assert '<w:ind w:left="2400"' in xml
    assert "<w:framePr " not in xml


def test_tableau_word_native_reste_un_tableau_reel(tmp_path):
    police = FontRef("Test", "Arial", False, False)
    table = TableEl(
        bbox=BBox(pt_vers_emu(80), pt_vers_emu(160), pt_vers_emu(220), pt_vers_emu(184)),
        rows=[
            TableRow(
                bbox=BBox(pt_vers_emu(80), pt_vers_emu(160), pt_vers_emu(220), pt_vers_emu(184)),
                cells=[
                    TableCell(
                        bbox=BBox(pt_vers_emu(80), pt_vers_emu(160), pt_vers_emu(220), pt_vers_emu(184)),
                        texte="Cell",
                    )
                ],
            )
        ],
        col_widths_emu=[pt_vers_emu(140)],
        police=police,
        size_pt=10,
    )
    paragraphe = FlowParagraph(
        bbox=BBox(pt_vers_emu(72), pt_vers_emu(120), pt_vers_emu(200), pt_vers_emu(134)),
        texte="Anchor",
        police=police,
        size_pt=10,
        couleur="000000",
        retrait_gauche_emu=pt_vers_emu(72),
    )
    document = Document(
        pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[paragraphe, table])]
    )
    sortie = tmp_path / "native_positioned_table.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert "<w:tbl>" in xml
    assert "<w:tblpPr " in xml
    assert "<pic:pic>" not in xml


def test_contrat_word_native_detecte_les_faux_natfs(tmp_path):
    police = FontRef("TimesNewRomanPSMT", "Liberation Serif", False, False)
    paragraphe = FlowParagraph(
        bbox=BBox(pt_vers_emu(72), pt_vers_emu(120), pt_vers_emu(300), pt_vers_emu(134)),
        texte="Texte natif",
        police=police,
        size_pt=10,
        couleur="000000",
        retrait_gauche_emu=pt_vers_emu(72),
    )
    document = Document(
        pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[paragraphe])]
    )
    sortie = tmp_path / "native_contract.docx"

    ecrire_docx(document, sortie)

    diagnostic = inspecter_docx_word_native(sortie)
    assert diagnostic.conforme
    assert diagnostic.paragraphes >= 1
    assert diagnostic.frames == 0
    assert diagnostic.textboxes == 0


def test_image_croisant_un_paragraphe_word_native_passe_derriere(tmp_path):
    police = FontRef("TimesNewRomanPSMT", "Liberation Serif", False, False)
    document = Document(
        pages=[
            Page(
                index=0,
                largeur_emu=A4_LARGEUR,
                hauteur_emu=A4_HAUTEUR,
                elements=[
                    FlowParagraph(
                        bbox=BBox(pt_vers_emu(80), pt_vers_emu(100), pt_vers_emu(300), pt_vers_emu(114)),
                        texte="Texte devant image",
                        police=police,
                        size_pt=10,
                        couleur="000000",
                        retrait_gauche_emu=pt_vers_emu(80),
                    ),
                    ImageEl(
                        bbox=BBox(pt_vers_emu(70), pt_vers_emu(95), pt_vers_emu(320), pt_vers_emu(130)),
                        media_ref="img1",
                    ),
                ],
            )
        ]
    )
    document.media["img1"] = MediaItem("img1", b"\x89PNG\r\n\x1a\n", "png")
    sortie = tmp_path / "native_image_behind.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert 'behindDoc="1"' in xml
    assert "Texte devant image" in xml


def test_fond_positionne_croisant_un_paragraphe_passe_derriere(tmp_path):
    police = FontRef("TimesNewRomanPSMT", "Liberation Serif", False, False)
    document = Document(
        pages=[
            Page(
                index=0,
                largeur_emu=A4_LARGEUR,
                hauteur_emu=A4_HAUTEUR,
                elements=[
                    ShapeEl(
                        bbox=BBox(pt_vers_emu(70), pt_vers_emu(95), pt_vers_emu(320), pt_vers_emu(140)),
                        chemins=[],
                        remplissage="CCFFFF",
                        contour="000000",
                        epaisseur_emu=pt_vers_emu(0.5),
                    ),
                    FlowParagraph(
                        bbox=BBox(pt_vers_emu(80), pt_vers_emu(100), pt_vers_emu(300), pt_vers_emu(126)),
                        texte="Texte devant fond",
                        police=police,
                        size_pt=10,
                        couleur="000000",
                        retrait_gauche_emu=pt_vers_emu(80),
                    ),
                ],
            )
        ]
    )
    sortie = tmp_path / "native_shape_behind.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert 'behindDoc="1"' in xml
    assert "Texte devant fond" in xml


def test_correcteur_word_native_conserve_ligne_isolee_sans_frame(tmp_path):
    police = FontRef("TimesNewRomanPSMT", "Liberation Serif", False, False)
    ligne = Line(
        bbox=BBox(pt_vers_emu(80), pt_vers_emu(100), pt_vers_emu(300), pt_vers_emu(114)),
        spans=[Span("Texte recupere", police, 10, "000000")],
        hauteur_ligne_emu=pt_vers_emu(14),
        largeur_cible_emu=pt_vers_emu(220),
        alignement="left",
    )
    document = Document(
        pages=[
            Page(
                index=0,
                largeur_emu=A4_LARGEUR,
                hauteur_emu=A4_HAUTEUR,
                elements=[TextBox(ligne.bbox, [ligne])],
            )
        ]
    )
    sortie = tmp_path / "native_contract_corrected.docx"

    correction = corriger_document_word_native(document)
    ecrire_docx(document, sortie)

    diagnostic = inspecter_docx_word_native(sortie)
    assert correction.textboxes_converties == 0
    assert correction.lignes_converties == 0
    assert diagnostic.conforme
    assert diagnostic.textboxes >= 1
    assert diagnostic.paragraphes >= 1


def test_correcteur_word_native_fusionne_seulement_vrai_paragraphe_dans_frame(tmp_path):
    police = FontRef("TimesNewRomanPSMT", "Liberation Serif", False, False)
    frame = BBox(pt_vers_emu(80), pt_vers_emu(100), pt_vers_emu(330), pt_vers_emu(150))
    textes = [
        "The mission architecture requires a stable set of interfaces",
        "between launch systems and operational support teams",
        "so the implementation can remain consistent across phases.",
    ]
    lignes = []
    for index, texte in enumerate(textes):
        y0 = 100 + index * 13
        lignes.append(
            Line(
                bbox=BBox(pt_vers_emu(80), pt_vers_emu(y0), pt_vers_emu(320), pt_vers_emu(y0 + 11)),
                spans=[Span(texte, police, 10, "000000")],
                hauteur_ligne_emu=pt_vers_emu(13),
                largeur_cible_emu=pt_vers_emu(240),
                alignement="left",
                layout_frame_id="0:text-column:frame",
                layout_frame_role="text-column",
                layout_frame_strategy="word-text",
                layout_frame_bbox=frame,
            )
        )
    document = Document(
        pages=[
            Page(
                index=0,
                largeur_emu=A4_LARGEUR,
                hauteur_emu=A4_HAUTEUR,
                elements=[TextBox(ligne.bbox, [ligne], layout_frame_id=ligne.layout_frame_id, layout_frame_role="text-column") for ligne in lignes],
            )
        ]
    )
    sortie = tmp_path / "native_contract_frame_corrected.docx"

    correction = corriger_document_word_native(document)
    ecrire_docx(document, sortie)

    diagnostic = inspecter_docx_word_native(sortie)
    assert correction.textboxes_converties == 3
    assert correction.lignes_converties == 3
    assert isinstance(document.pages[0].elements[0], FlowParagraph)
    assert diagnostic.conforme


def test_correcteur_word_native_ne_duplique_pas_textbox_partiellement_convertie(tmp_path):
    police = FontRef("TimesNewRomanPSMT", "Liberation Serif", False, False)
    police_math = FontRef("CMSY10", "Latin Modern Math", False, False)
    frame = BBox(pt_vers_emu(80), pt_vers_emu(100), pt_vers_emu(360), pt_vers_emu(180))
    lignes = []
    textes = [
        "Speed is the magnitude of velocity; that is, speed is velocity",
        "stripped of any indication of direction, either in words or signs.",
        "The speedometer in a car measures speed, not velocity.",
    ]
    for index, texte in enumerate(textes):
        y0 = 100 + index * 13
        lignes.append(
            Line(
                bbox=BBox(pt_vers_emu(80), pt_vers_emu(y0), pt_vers_emu(350), pt_vers_emu(y0 + 11)),
                spans=[Span(texte, police, 10, "000000")],
                hauteur_ligne_emu=pt_vers_emu(13),
                largeur_cible_emu=pt_vers_emu(270),
                alignement="left",
                layout_frame_id="0:text-column:frame",
                layout_frame_role="text-column",
                layout_frame_strategy="word-text",
                layout_frame_bbox=frame,
            )
        )
    lignes.append(
        Line(
            bbox=BBox(pt_vers_emu(80), pt_vers_emu(152), pt_vers_emu(170), pt_vers_emu(166)),
            spans=[Span("v = dx / dt", police_math, 12, "000000")],
            hauteur_ligne_emu=pt_vers_emu(14),
            largeur_cible_emu=pt_vers_emu(90),
            alignement="center",
            layout_frame_id="0:text-column:frame",
            layout_frame_role="text-column",
            layout_frame_strategy="word-text",
            layout_frame_bbox=frame,
        )
    )
    document = Document(
        pages=[
            Page(
                index=0,
                largeur_emu=A4_LARGEUR,
                hauteur_emu=A4_HAUTEUR,
                elements=[TextBox(frame, lignes, layout_frame_id="0:text-column:frame", layout_frame_role="text-column")],
            )
        ]
    )
    sortie = tmp_path / "native_contract_partial_textbox.docx"

    correction = corriger_document_word_native(document)
    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert correction.textboxes_converties == 1
    assert correction.lignes_converties == 3
    assert xml.count("Speed is the magnitude") == 1
    assert xml.count("stripped of any indication") == 1
    assert xml.count("v = dx / dt") == 1


def test_correcteur_word_native_ne_fusionne_pas_grand_titre_heading(tmp_path):
    police = FontRef("FuturaStd-CondensedBold", "Nimbus Sans Narrow", True, False)
    frame = BBox(pt_vers_emu(260), pt_vers_emu(160), pt_vers_emu(400), pt_vers_emu(250))
    lignes = []
    for index, texte in enumerate(("Compression", "du signal", "audiovisuel")):
        y0 = 160 + index * 28
        lignes.append(
            Line(
                bbox=BBox(pt_vers_emu(260), pt_vers_emu(y0), pt_vers_emu(400), pt_vers_emu(y0 + 24)),
                spans=[Span(texte, police, 30, "000000", espacement_twips=-80)],
                hauteur_ligne_emu=pt_vers_emu(28),
                largeur_cible_emu=pt_vers_emu(140),
                alignement="left",
                layout_frame_id="0:heading:frame",
                layout_frame_role="heading",
                layout_frame_strategy="word-text",
                layout_frame_bbox=frame,
            )
        )
    document = Document(
        pages=[
            Page(
                index=0,
                largeur_emu=A4_LARGEUR,
                hauteur_emu=A4_HAUTEUR,
                elements=[
                    TextBox(ligne.bbox, [ligne], layout_frame_id=ligne.layout_frame_id, layout_frame_role="heading")
                    for ligne in lignes
                ],
            )
        ]
    )

    correction = corriger_document_word_native(document)

    assert correction.textboxes_converties == 0
    assert correction.lignes_converties == 0
    assert all(isinstance(element, TextBox) for element in document.pages[0].elements)


def test_correcteur_word_native_fusionne_vrai_paragraphe_sans_frame(tmp_path):
    police = FontRef("TimesNewRomanPSMT", "Liberation Serif", False, False)
    textes = [
        "The estuary contains freshwater and saltwater in a mixed habitat",
        "where several species depend on nutrients and changing tides",
        "throughout the year as conditions vary across the shoreline.",
    ]
    lignes = []
    for index, texte in enumerate(textes):
        y0 = 100 + index * 13
        lignes.append(
            Line(
                bbox=BBox(pt_vers_emu(100), pt_vers_emu(y0), pt_vers_emu(430), pt_vers_emu(y0 + 11)),
                spans=[Span(texte, police, 10, "000000")],
                hauteur_ligne_emu=pt_vers_emu(13),
                largeur_cible_emu=pt_vers_emu(330),
                alignement="left",
            )
        )
    document = Document(
        pages=[
            Page(
                index=0,
                largeur_emu=A4_LARGEUR,
                hauteur_emu=A4_HAUTEUR,
                elements=[TextBox(ligne.bbox, [ligne]) for ligne in lignes],
            )
        ]
    )

    correction = corriger_document_word_native(document)

    assert correction.textboxes_converties == 3
    assert correction.lignes_converties == 3
    assert len([element for element in document.pages[0].elements if isinstance(element, FlowParagraph)]) == 1


def test_correcteur_word_native_fusionne_question_multiligne_dans_frame():
    police = FontRef("TimesNewRomanPSMT", "Liberation Serif", False, False)
    frame = BBox(pt_vers_emu(100), pt_vers_emu(100), pt_vers_emu(430), pt_vers_emu(130))
    lignes = [
        Line(
            bbox=BBox(pt_vers_emu(100), pt_vers_emu(100), pt_vers_emu(420), pt_vers_emu(112)),
            spans=[Span("10. Estuaries are typically classified based on how saltwater", police, 10, "000000")],
            hauteur_ligne_emu=pt_vers_emu(13),
            largeur_cible_emu=pt_vers_emu(320),
            layout_frame_id="q10",
            layout_frame_role="text-column",
            layout_frame_strategy="word-text",
            layout_frame_bbox=frame,
        ),
        Line(
            bbox=BBox(pt_vers_emu(118), pt_vers_emu(113), pt_vers_emu(425), pt_vers_emu(125)),
            spans=[Span("and freshwater mix in the estuary and on their shape.", police, 10, "000000")],
            hauteur_ligne_emu=pt_vers_emu(13),
            largeur_cible_emu=pt_vers_emu(307),
            layout_frame_id="q10",
            layout_frame_role="text-column",
            layout_frame_strategy="word-text",
            layout_frame_bbox=frame,
        ),
    ]
    document = Document(
        pages=[
            Page(
                index=0,
                largeur_emu=A4_LARGEUR,
                hauteur_emu=A4_HAUTEUR,
                elements=[TextBox(ligne.bbox, [ligne]) for ligne in lignes],
            )
        ]
    )

    correction = corriger_document_word_native(document)

    assert correction.textboxes_converties == 2
    assert len(document.pages[0].elements) == 1
    assert isinstance(document.pages[0].elements[0], FlowParagraph)
    assert len(document.pages[0].elements[0].lignes) == 2


def test_correcteur_word_native_ne_fusionne_pas_questions_numerotees_distinctes():
    police = FontRef("Meridien-Roman", "Meridien", False, False)
    frame = BBox(pt_vers_emu(100), pt_vers_emu(100), pt_vers_emu(430), pt_vers_emu(170))
    textes = [
        "1. An __________ is a partially enclosed body of water and its",
        "adjacent habitats where saltwater from the ocean mixes",
        "2. Waters whose salt content is between that of freshwater and",
        "that of seawater are called __________.",
    ]
    lignes = [
        Line(
            bbox=BBox(pt_vers_emu(100), pt_vers_emu(100 + index * 13), pt_vers_emu(420), pt_vers_emu(112 + index * 13)),
            spans=[Span(texte, police, 10, "231F20")],
            hauteur_ligne_emu=pt_vers_emu(13),
            largeur_cible_emu=pt_vers_emu(320),
            layout_frame_id="worksheet-frame",
            layout_frame_role="text-column",
            layout_frame_strategy="word-text",
            layout_frame_bbox=frame,
        )
        for index, texte in enumerate(textes)
    ]
    document = Document(
        pages=[
            Page(
                index=0,
                largeur_emu=A4_LARGEUR,
                hauteur_emu=A4_HAUTEUR,
                elements=[TextBox(ligne.bbox, [ligne]) for ligne in lignes],
            )
        ]
    )

    correction = corriger_document_word_native(document)

    paragraphes = [element for element in document.pages[0].elements if isinstance(element, FlowParagraph)]
    assert correction.textboxes_converties == 4
    assert len(paragraphes) == 2
    assert paragraphes[0].texte.startswith("1.")
    assert paragraphes[1].texte.startswith("2.")


def test_question_multiligne_word_native_reflow_sans_retours_forces_ni_espaces_finaux(tmp_path):
    police = FontRef("Meridien-Roman", "Meridien", False, False)
    lignes = [
        Line(
            bbox=BBox(pt_vers_emu(100), pt_vers_emu(100), pt_vers_emu(420), pt_vers_emu(112)),
            spans=[Span("3. Of the 32 largest cities in the world, 22 are located on              ", police, 10, "231F20")],
            hauteur_ligne_emu=pt_vers_emu(13),
            largeur_cible_emu=pt_vers_emu(320),
            layout_frame_id="q3",
            layout_frame_role="text-column",
            layout_frame_strategy="word-text",
            layout_frame_bbox=BBox(pt_vers_emu(100), pt_vers_emu(100), pt_vers_emu(430), pt_vers_emu(130)),
        ),
        Line(
            bbox=BBox(pt_vers_emu(118), pt_vers_emu(113), pt_vers_emu(260), pt_vers_emu(125)),
            spans=[Span("__________.", police, 10, "231F20")],
            hauteur_ligne_emu=pt_vers_emu(13),
            largeur_cible_emu=pt_vers_emu(142),
            layout_frame_id="q3",
            layout_frame_role="text-column",
            layout_frame_strategy="word-text",
            layout_frame_bbox=BBox(pt_vers_emu(100), pt_vers_emu(100), pt_vers_emu(430), pt_vers_emu(130)),
        ),
    ]
    document = Document(
        pages=[
            Page(
                index=0,
                largeur_emu=A4_LARGEUR,
                hauteur_emu=A4_HAUTEUR,
                elements=[TextBox(ligne.bbox, [ligne]) for ligne in lignes],
            )
        ]
    )
    sortie = tmp_path / "worksheet_question.docx"

    corriger_document_word_native(document)
    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert "<w:br/>" not in xml
    assert "on              " not in xml
    assert "located on</w:t>" in xml


def test_correcteur_word_native_fusionne_bloc_court_dans_frame_et_garde_verticalite(tmp_path):
    police = FontRef("TimesNewRomanPSMT", "Liberation Serif", False, False)
    frame = BBox(pt_vers_emu(90), pt_vers_emu(100), pt_vers_emu(360), pt_vers_emu(180))
    lignes = [
        Line(
            bbox=BBox(pt_vers_emu(120), pt_vers_emu(128), pt_vers_emu(330), pt_vers_emu(140)),
            spans=[Span("Short paragraph block", police, 10, "000000")],
            hauteur_ligne_emu=pt_vers_emu(13),
            largeur_cible_emu=pt_vers_emu(210),
            alignement="center",
            layout_frame_id="short-block",
            layout_frame_role="text-column",
            layout_frame_strategy="word-text",
            layout_frame_bbox=frame,
        ),
        Line(
            bbox=BBox(pt_vers_emu(122), pt_vers_emu(142), pt_vers_emu(328), pt_vers_emu(154)),
            spans=[Span("with two native lines.", police, 10, "000000")],
            hauteur_ligne_emu=pt_vers_emu(13),
            largeur_cible_emu=pt_vers_emu(206),
            alignement="center",
            layout_frame_id="short-block",
            layout_frame_role="text-column",
            layout_frame_strategy="word-text",
            layout_frame_bbox=frame,
        ),
    ]
    document = Document(
        pages=[
            Page(
                index=0,
                largeur_emu=A4_LARGEUR,
                hauteur_emu=A4_HAUTEUR,
                elements=[TextBox(ligne.bbox, [ligne]) for ligne in lignes],
            )
        ]
    )
    sortie = tmp_path / "short_block_vertical.docx"

    correction = corriger_document_word_native(document)
    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode("utf-8")
    assert correction.textboxes_converties == 2
    assert len(document.pages[0].elements) == 1
    assert isinstance(document.pages[0].elements[0], FlowParagraph)
    assert document.pages[0].elements[0].alignement == "center"
    assert document.pages[0].elements[0].vertical_alignement == "center"
    assert '<w:textAlignment w:val="center"/>' in xml
    assert "<wp:anchor" not in xml
    assert '<w:jc w:val="center"/>' in xml


def test_correcteur_word_native_fusionne_bloc_frame_sur_image_de_fond():
    police = FontRef("TimesNewRomanPSMT", "Liberation Serif", False, False)
    frame = BBox(pt_vers_emu(100), pt_vers_emu(100), pt_vers_emu(430), pt_vers_emu(130))
    lignes = [
        Line(
            bbox=BBox(pt_vers_emu(100), pt_vers_emu(100), pt_vers_emu(420), pt_vers_emu(112)),
            spans=[Span("10. Estuaries are typically classified based on how saltwater", police, 10, "000000")],
            hauteur_ligne_emu=pt_vers_emu(13),
            largeur_cible_emu=pt_vers_emu(320),
            layout_frame_id="q10",
            layout_frame_role="text-column",
            layout_frame_strategy="word-text",
            layout_frame_bbox=frame,
        ),
        Line(
            bbox=BBox(pt_vers_emu(118), pt_vers_emu(113), pt_vers_emu(425), pt_vers_emu(125)),
            spans=[Span("and freshwater mix in the estuary and on their shape.", police, 10, "000000")],
            hauteur_ligne_emu=pt_vers_emu(13),
            largeur_cible_emu=pt_vers_emu(307),
            layout_frame_id="q10",
            layout_frame_role="text-column",
            layout_frame_strategy="word-text",
            layout_frame_bbox=frame,
        ),
    ]
    document = Document(
        pages=[
            Page(
                index=0,
                largeur_emu=A4_LARGEUR,
                hauteur_emu=A4_HAUTEUR,
                elements=[
                    ImageEl(BBox(pt_vers_emu(90), pt_vers_emu(95), pt_vers_emu(440), pt_vers_emu(135)), "fond"),
                    *(TextBox(ligne.bbox, [ligne]) for ligne in lignes),
                ],
            )
        ]
    )

    correction = corriger_document_word_native(document)

    assert correction.textboxes_converties == 2
    assert any(isinstance(element, FlowParagraph) for element in document.pages[0].elements)


def test_paragraphe_justifie_est_ecrit_en_reflow_word_sans_retours_ligne_forces(tmp_path):
    police = FontRef("CenturyGothic", "URW Gothic", False, False)
    lignes = [
        Line(
            bbox=BBox(pt_vers_emu(63), pt_vers_emu(145 + index * 15), pt_vers_emu(543), pt_vers_emu(160 + index * 15)),
            spans=[Span(texte, police, 12, "000000")],
            hauteur_ligne_emu=pt_vers_emu(15),
            largeur_cible_emu=pt_vers_emu(480),
            alignement="both",
        )
        for index, texte in enumerate(
            [
                "This is the determination of the Railroad Retirement Board concerning the status of   ",
                "Indiana Boxcar Corporation (IBC), as an employer under the Railroad Retirement",
            ]
        )
    ]
    paragraphe = FlowParagraph(
        bbox=BBox(pt_vers_emu(63), pt_vers_emu(145), pt_vers_emu(543), pt_vers_emu(175)),
        texte="This is the determination of the Railroad Retirement Board concerning the status of Indiana Boxcar Corporation (IBC), as an employer under the Railroad Retirement",
        police=police,
        size_pt=12,
        couleur="000000",
        alignement="both",
        retrait_gauche_emu=pt_vers_emu(63),
        interligne_emu=pt_vers_emu(15),
        spans=[Span("This is the determination of the Railroad Retirement Board concerning the status of   ", police, 12, "000000"), Span("\n", police, 12, "000000"), Span("Indiana Boxcar Corporation (IBC), as an employer under the Railroad Retirement", police, 12, "000000")],
        lignes=lignes,
    )
    document = Document(
        pages=[Page(index=0, largeur_emu=A4_LARGEUR, hauteur_emu=A4_HAUTEUR, elements=[paragraphe])]
    )
    sortie = tmp_path / "justified_reflow.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert '<w:jc w:val="both"/>' in xml
    assert "<w:br/>" not in xml
    assert "status of   " not in xml
    assert "status of</w:t>" in xml


def test_correcteur_word_native_ne_fusionne_pas_labels_sans_frame():
    police = FontRef("Arial-BoldMT", "Arial", True, False)
    lignes = [
        Line(
            bbox=BBox(pt_vers_emu(100), pt_vers_emu(100 + index * 18), pt_vers_emu(220), pt_vers_emu(112 + index * 18)),
            spans=[Span(texte, police, 14, "000000")],
            hauteur_ligne_emu=pt_vers_emu(14),
            largeur_cible_emu=pt_vers_emu(120),
            alignement="left",
        )
        for index, texte in enumerate(["SALINITY", "TIDES", "HABITATS"])
    ]
    document = Document(
        pages=[
            Page(
                index=0,
                largeur_emu=A4_LARGEUR,
                hauteur_emu=A4_HAUTEUR,
                elements=[TextBox(ligne.bbox, [ligne]) for ligne in lignes],
            )
        ]
    )

    correction = corriger_document_word_native(document)

    assert correction.textboxes_converties == 0
    assert all(isinstance(element, TextBox) for element in document.pages[0].elements)


def test_entree_sommaire_ancree_utilise_tabulation_leader_word(tmp_path):
    police = FontRef("Test", "Arial", False, False)
    ligne = Line(
        bbox=BBox(pt_vers_emu(86), pt_vers_emu(120), pt_vers_emu(528), pt_vers_emu(136)),
        spans=[
            Span(
                "Purpose ------------------------------------------------------------ 7",
                police,
                10,
                "000000",
            )
        ],
        hauteur_ligne_emu=pt_vers_emu(16),
        largeur_cible_emu=pt_vers_emu(442),
    )
    document = Document(
        pages=[
            Page(
                index=0,
                largeur_emu=A4_LARGEUR,
                hauteur_emu=A4_HAUTEUR,
                elements=[TextBox(ligne.bbox, [ligne])],
            )
        ]
    )
    sortie = tmp_path / "toc_leader_anchor.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert "<wp:anchor" in xml
    assert '<w:tab w:val="right" w:leader="hyphen"' in xml
    assert "<w:tab/>" in xml
    assert "Purpose ------------------------------------------------------------ 7" not in xml
    assert '<w:t xml:space="preserve">Purpose</w:t>' in xml
    assert '<w:t xml:space="preserve">7</w:t>' in xml


def test_correcteur_word_native_ne_fusionne_pas_sommaire_multiligne_a_leaders():
    police = FontRef("OfficinaSans-Bold", "Source Sans Pro", True, False)
    frame = BBox(pt_vers_emu(70), pt_vers_emu(360), pt_vers_emu(530), pt_vers_emu(455))
    textes = [
        "Focus on Nuclear Material and Weapon Security . . . . . . . . . . . 1",
        "Guest Editorial: Securing Nuclear Warheads and Materials . . . . . . 6",
        "Material Protection, Control, and Accounting . . . . . . . . . . . . 9",
    ]
    lignes = [
        Line(
            bbox=BBox(pt_vers_emu(70), pt_vers_emu(360 + index * 16), pt_vers_emu(528), pt_vers_emu(374 + index * 16)),
            spans=[Span(texte, police, 10, "264769")],
            hauteur_ligne_emu=pt_vers_emu(16),
            largeur_cible_emu=pt_vers_emu(458),
            alignement="left",
            layout_frame_id="toc",
            layout_frame_role="text-column",
            layout_frame_strategy="word-text",
            layout_frame_bbox=frame,
        )
        for index, texte in enumerate(textes)
    ]
    document = Document(
        pages=[
            Page(
                index=0,
                largeur_emu=A4_LARGEUR,
                hauteur_emu=A4_HAUTEUR,
                elements=[TextBox(ligne.bbox, [ligne]) for ligne in lignes],
            )
        ]
    )

    correction = corriger_document_word_native(document)

    assert correction.textboxes_converties == 0
    assert all(isinstance(element, TextBox) for element in document.pages[0].elements)


def test_entree_sommaire_a_points_espaces_garde_leader_visuel_positionne(tmp_path):
    police = FontRef("TrebuchetMS-Bold", "Nimbus Sans", True, False)
    ligne = Line(
        bbox=BBox(pt_vers_emu(45), pt_vers_emu(523), pt_vers_emu(305), pt_vers_emu(534)),
        spans=[
            Span(
                "Focus on Nuclear Material and Weapon Security . . . . . . . . . . . . . . . . . . . . . . 1",
                police,
                9,
                "274268",
                espacement_twips=-44,
            )
        ],
        hauteur_ligne_emu=pt_vers_emu(11),
        largeur_cible_emu=pt_vers_emu(516),
        alignement="both",
    )
    document = Document(
        pages=[
            Page(
                index=0,
                largeur_emu=A4_LARGEUR,
                hauteur_emu=A4_HAUTEUR,
                elements=[TextBox(ligne.bbox, [ligne])],
            )
        ]
    )
    sortie = tmp_path / "toc_spaced_dots.docx"

    ecrire_docx(document, sortie)

    xml = _lire(sortie, "word/document.xml").decode()
    assert '<w:tab w:val="right" w:leader="dot"' not in xml
    assert "<w:tab/>" not in xml
    assert 'w:spacing w:val="-44"' not in xml
    assert '<w:t xml:space="preserve">Focus on Nuclear Material and Weapon Security</w:t>' in xml
    assert '<w:t xml:space="preserve">1</w:t>' in xml
    assert xml.count('<wp:anchor') == 3
    assert 'w:jc w:val="right"' in xml


def test_correcteur_word_native_assemble_par_position_pas_par_frame_id():
    police = FontRef("TimesNewRomanMS", "Liberation Serif", False, False)
    textes = [
        ("0", 344.4, "remained in its original locations."),
        ("0", 370.8, "Initially Sandia provided armored security blankets"),
        ("7", 386.6, "and containers for weapons and weapon parts in tran-"),
        ("0", 399.1, "sit and has improved the security of Russian railcars"),
        ("7", 415.0, "for transporting nuclear weapons and materials for"),
        ("7", 429.2, "the CTR program. More recently Sandia’s technical"),
    ]
    lignes = [
        Line(
            bbox=BBox(pt_vers_emu(46.2), pt_vers_emu(y), pt_vers_emu(305.6), pt_vers_emu(y + 13.6)),
            spans=[Span(texte, police, 10.8, "000000")],
            hauteur_ligne_emu=pt_vers_emu(14),
            largeur_cible_emu=pt_vers_emu(259.4),
            alignement="left",
            layout_frame_id=f"{frame}:text-column",
            layout_frame_role="text-column",
            layout_frame_strategy="word-text",
            layout_frame_bbox=BBox(pt_vers_emu(40), pt_vers_emu(300), pt_vers_emu(310), pt_vers_emu(460)),
        )
        for frame, y, texte in textes
    ]
    document = Document(
        pages=[
            Page(
                index=0,
                largeur_emu=A4_LARGEUR,
                hauteur_emu=A4_HAUTEUR,
                elements=[TextBox(ligne.bbox, [ligne]) for ligne in lignes],
            )
        ]
    )

    corriger_document_word_native(document)

    paragraphes = [element for element in document.pages[0].elements if isinstance(element, FlowParagraph)]
    assert len(paragraphes) == 1
    assert paragraphes[0].texte.startswith("Initially")
    assert "tran-" in paragraphes[0].texte
    assert "for transporting" in paragraphes[0].texte
    lignes_preservees = [element for element in document.pages[0].elements if isinstance(element, TextBox)]
    textes_preserves = [
        "".join(span.texte for span in element.lignes[0].spans)
        for element in lignes_preservees
    ]
    assert any("remained in its original locations." in texte for texte in textes_preserves)
    for ligne in lignes_preservees:
        texte = "".join(span.texte for span in ligne.lignes[0].spans)
        if "remained in its original locations." in texte:
            assert ligne.bbox.y1 <= paragraphes[0].bbox.y0


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
    env, libreoffice_profile = _env_libreoffice(tmp_path)
    _skip_si_libreoffice_ne_convertit_pas(tmp_path, env, libreoffice_profile)

    resultat = subprocess.run(
        [
            "soffice",
            "--headless",
            f"-env:UserInstallation={libreoffice_profile.as_uri()}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(tmp_path),
            str(docx_deux_pages),
        ],
        capture_output=True,
        env=env,
        timeout=180,
    )

    assert resultat.returncode == 0, resultat.stderr.decode(errors="replace")
    assert (tmp_path / "vide.pdf").exists()
