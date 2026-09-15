import pymupdf

from pdfexact.extract.blocks import OcrLine
from pdfexact.extract.document import _filtrer_zones_images_avec_texte_natif, _tableau_ressemble_bandeau_entete
from pdfexact.extract.layout_map import LayoutSpan, PageLayoutMap, _ajouter_lignes_visuelles_natives
from pdfexact.extract.ocr import (
    _alignement_ligne,
    _bbox_occultee_apres_seqno,
    _choisir_lignes_word_native,
    _groupes_caracteres_visibles,
    _ligne_formule_a_rasteriser,
    _ligne_figure_isolee,
    _ligne_dans_cadres_lecture,
    _lignes_natives_hybrides,
    _paragraphes_word_native,
    _ajuster_largeur_ocr,
    _zones_glyphes_symboles_non_reconnus,
)
from pdfexact.geometry import BBox, pt_vers_emu
from pdfexact.ir import FontAsset, FontRef, Line, Span, TableCell, TableEl, TableRow


def _bbox_pt(x0, y0, x1, y1):
    return BBox(pt_vers_emu(x0), pt_vers_emu(y0), pt_vers_emu(x1), pt_vers_emu(y1))


def test_occlusion_ignore_les_remplissages_anterieurs():
    texte = _bbox_pt(10, 10, 20, 20)
    occlusions = [(3, _bbox_pt(8, 8, 22, 22))]

    assert not _bbox_occultee_apres_seqno(texte, 5, occlusions)


def test_occlusion_masque_un_caractere_couvert_par_remplissage_posterieur():
    texte = _bbox_pt(10, 10, 20, 20)
    occlusions = [(8, _bbox_pt(8, 8, 22, 22))]

    assert _bbox_occultee_apres_seqno(texte, 5, occlusions)


def test_groupes_caracteres_visibles_scinde_les_lignes_dune_trace_powerpoint():
    caracteres = [
        ("A", _bbox_pt(10, 10, 16, 20)),
        ("B", _bbox_pt(17, 10, 23, 20)),
        ("C", _bbox_pt(10, 30, 16, 40)),
        ("D", _bbox_pt(17, 30, 23, 40)),
    ]

    groupes = _groupes_caracteres_visibles(caracteres)

    assert ["".join(car for car, _bbox in groupe) for groupe in groupes] == ["AB", "CD"]


def test_groupes_caracteres_visibles_scinde_les_gros_gaps_horizontaux():
    caracteres = [
        ("A", _bbox_pt(10, 10, 16, 20)),
        ("B", _bbox_pt(17, 10, 23, 20)),
        ("C", _bbox_pt(90, 10, 96, 20)),
        ("D", _bbox_pt(97, 10, 103, 20)),
    ]

    groupes = _groupes_caracteres_visibles(caracteres)

    assert ["".join(car for car, _bbox in groupe) for groupe in groupes] == ["AB", "CD"]


def test_lignes_natives_hybrides_filtrent_zones_protegees():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(300), hauteur_emu=pt_vers_emu(300))
    carte.ajouter("native-visual-line", _bbox_pt(20, 20, 120, 30), "test", text="Titre")
    carte.ajouter("native-visual-line", _bbox_pt(20, 80, 120, 90), "test", text="Table")

    lignes = _lignes_natives_hybrides(carte, [_bbox_pt(10, 70, 160, 100)])

    assert [ligne.texte for ligne in lignes] == ["Titre"]


def test_lignes_natives_hybrides_preservent_legende_dans_cadre_lecture():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(612), hauteur_emu=pt_vers_emu(792))
    legende = _bbox_pt(358, 324, 551, 346)
    carte.ajouter_cadre_lecture(legende)
    carte.ajouter(
        "native-line",
        legende,
        "test",
        text="Zvezda, the International Space Station module where astronauts live and work.",
    )

    lignes = _lignes_natives_hybrides(carte, [_bbox_pt(350, 318, 570, 352)], lignes_visuelles=False)

    assert [ligne.texte for ligne in lignes] == [
        "Zvezda, the International Space Station module where astronauts live and work."
    ]


def test_cadres_lecture_completent_une_zone_ia_partielle_par_colonnes_natives():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(612), hauteur_emu=pt_vers_emu(792))
    carte.ajouter_cadre_lecture(_bbox_pt(300, 40, 540, 740))
    for i in range(8):
        y = 60 + i * 24
        carte.ajouter("native-line", _bbox_pt(60, y, 250, y + 10), "test", text=f"left listing row {i}")
        carte.ajouter("native-line", _bbox_pt(310, y, 500, y + 10), "test", text=f"right listing row {i}")

    cadres = carte.cadres_lecture_natifs()

    assert any(cadre.x0 <= pt_vers_emu(60) <= cadre.x1 for cadre in cadres)
    assert any(cadre.x0 <= pt_vers_emu(300) <= cadre.x1 for cadre in cadres)


def test_word_native_utilise_lignes_natives_non_fusionnees():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(500), hauteur_emu=pt_vers_emu(200))
    carte.ajouter("native-line", _bbox_pt(40, 40, 210, 52), "test", text="Colonne gauche")
    carte.ajouter("native-line", _bbox_pt(245, 40, 420, 52), "test", text="Colonne droite")
    carte.ajouter(
        "native-visual-line",
        _bbox_pt(40, 40, 420, 52),
        "test",
        text="Colonne gauche Colonne droite",
    )

    lignes = _lignes_natives_hybrides(carte, [], lignes_visuelles=False)

    assert [ligne.texte for ligne in lignes] == ["Colonne gauche", "Colonne droite"]
    assert [ligne.bbox for ligne in lignes] == [_bbox_pt(40, 40, 210, 52), _bbox_pt(245, 40, 420, 52)]


def test_word_native_prefere_lignes_natives_meme_page_sparse():
    brutes = [OcrLine("Los Alamos National Laboratory Vol. 3, No. 3", 0.9, _bbox_pt(40, 132, 572, 143))]
    natives = [
        OcrLine("Reflections", 1.0, _bbox_pt(36, 40, 568, 146)),
        OcrLine("Los Alamos National Laboratory", 1.0, _bbox_pt(40, 132, 180, 143)),
        OcrLine("Vol. 3, No. 3", 1.0, _bbox_pt(459, 132, 572, 143)),
    ]

    assert _choisir_lignes_word_native(brutes, natives, []) == natives


def test_cadre_lecture_conserve_label_une_ligne_dix_points():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(612), hauteur_emu=pt_vers_emu(792))
    cadre = _bbox_pt(459, 132, 572, 143)

    carte.ajouter_cadre_lecture(cadre)

    cadres = carte._cadres_lecture_taxonomie()
    assert len(cadres) == 1
    assert cadres[0].hauteur >= pt_vers_emu(3)


def test_tableau_bandeau_entete_est_rejete_comme_vraie_table():
    police = FontRef("Test", "Arial", False, False)
    tableau = TableEl(
        bbox=_bbox_pt(36, 78, 576, 146),
        rows=[TableRow(_bbox_pt(36, 78, 576, 146), [TableCell(_bbox_pt(36, 78, 576, 146), "")])],
        col_widths_emu=[pt_vers_emu(540)],
        police=police,
        size_pt=9,
    )
    lignes = [_bbox_pt(40, 132, 180, 143), _bbox_pt(459, 132, 572, 143)]

    assert _tableau_ressemble_bandeau_entete(tableau, lignes, pt_vers_emu(792))


def test_lignes_visuelles_natives_ne_fusionnent_pas_deux_colonnes_proches():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(612), hauteur_emu=pt_vers_emu(792))
    carte.ajouter(
        "native-line",
        _bbox_pt(54, 220, 295, 232),
        "test",
        text="species, usually of fish or shellfish, is restricted) to",
    )
    carte.ajouter(
        "native-line",
        _bbox_pt(321, 220, 546, 232),
        "test",
        text="areas. Wilderness is not a concept easily applied to",
    )

    _ajouter_lignes_visuelles_natives(carte, 10)

    lignes_visuelles = carte.lignes_visuelles_natives()
    assert [ligne.text for ligne in lignes_visuelles] == [
        "species, usually of fish or shellfish, is restricted) to",
        "areas. Wilderness is not a concept easily applied to",
    ]


def test_lignes_natives_hybrides_conservent_les_spans_et_corrigent_wingdings():
    carte = PageLayoutMap(largeur_emu=pt_vers_emu(400), hauteur_emu=pt_vers_emu(200))
    carte.ajouter(
        "native-visual-line",
        _bbox_pt(20, 20, 260, 34),
        "test",
        text="InterAction Î Giving",
        spans=(
            LayoutSpan("InterAction ", _bbox_pt(20, 20, 90, 34), "TimesNewRomanPSMT", 10, 0, 4),
            LayoutSpan("Î", _bbox_pt(90, 20, 100, 34), "Wingdings-Regular", 10, 0, 0),
            LayoutSpan(" Giving", _bbox_pt(100, 20, 160, 34), "TimesNewRomanPSMT", 10, 0, 4),
        ),
    )
    polices = {
        "TimesNewRomanPSMT": FontAsset(
            "TimesNewRomanPSMT", "Liberation Serif", None, "", False, reconnue=True
        ),
        "Wingdings-Regular": FontAsset(
            "Wingdings-Regular", "D050000L", None, "", False, reconnue=True
        ),
    }

    lignes = _lignes_natives_hybrides(carte, [], polices)

    assert lignes[0].texte == "InterAction → Giving"
    assert [span.texte for span in lignes[0].spans] == ["InterAction ", "→", " Giving"]
    assert lignes[0].spans[1].police.famille == "Liberation Serif"


def test_word_native_rejette_ligne_hors_cadre_de_lecture():
    ligne_graphe = OcrLine("Atom 8", 1.0, _bbox_pt(260, 510, 300, 522))
    ligne_texte = OcrLine("Project Description", 1.0, _bbox_pt(72, 120, 260, 134))
    cadres = [_bbox_pt(60, 90, 540, 420)]

    assert _ligne_dans_cadres_lecture(ligne_texte, cadres, pt_vers_emu(792))
    assert not _ligne_dans_cadres_lecture(ligne_graphe, cadres, pt_vers_emu(792))


def test_filtre_figure_conserve_ligne_native_courte_confirmee():
    police = FontRef("TimesNewRomanPS-ItalicMT", "Times New Roman", False, True)
    bbox = _bbox_pt(132, 274, 140, 288)
    ligne_native = OcrLine(
        "v.",
        1.0,
        bbox,
        spans=(Span("v.", police, 12, "000000", bbox=bbox),),
    )
    ligne_ocr = OcrLine("v.", 0.92, bbox)

    assert not _ligne_figure_isolee(ligne_native)
    assert _ligne_figure_isolee(ligne_ocr)


def test_glyphes_symbole_non_reconnus_deviennent_zone_raster():
    police_symbole = FontRef("WP-MathExtendedA", "Liberation Serif", False, False)
    polices = {
        "WP-MathExtendedA": FontAsset(
            "WP-MathExtendedA",
            "Liberation Serif",
            None,
            "",
            False,
            reconnue=False,
        )
    }
    lignes = [
        OcrLine(
            "-",
            1.0,
            _bbox_pt(346.4, 175.5, 347.4, 202.3),
            spans=(
                Span(
                    "-",
                    police_symbole,
                    12,
                    "000000",
                    bbox=_bbox_pt(346.4, 175.5, 347.4, 202.3),
                ),
            ),
        ),
        OcrLine(
            "N",
            1.0,
            _bbox_pt(344.6, 321.3, 347.4, 348.1),
            spans=(
                Span(
                    "N",
                    police_symbole,
                    12,
                    "000000",
                    bbox=_bbox_pt(344.6, 321.3, 347.4, 348.1),
                ),
            ),
        ),
    ]

    zones = _zones_glyphes_symboles_non_reconnus(lignes, polices)

    assert len(zones) == 2


def test_ajustement_ocr_ne_reduit_pas_taille_police_non_reconnue(monkeypatch):
    from pdfexact.extract import fonts as fonts_mod

    police = FontRef("Police-Manquante", "Liberation Serif", False, False)
    ligne = Line(
        bbox=_bbox_pt(10, 10, 70, 22),
        spans=[Span("Texte beaucoup trop large", police, 12, "000000")],
        hauteur_ligne_emu=pt_vers_emu(12),
        largeur_cible_emu=pt_vers_emu(60),
    )
    polices = {
        "Police-Manquante": FontAsset(
            "Police-Manquante",
            "Liberation Serif",
            None,
            "",
            False,
            reconnue=False,
        )
    }
    monkeypatch.setattr(fonts_mod, "mesurer_largeur_pt", lambda *_args: 140.0)

    _ajuster_largeur_ocr(ligne, polices)

    assert ligne.spans[0].size_pt == 12
    assert ligne.spans[0].espacement_twips < 0


def test_ligne_liste_equilibree_reste_alignee_a_gauche():
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)

    alignement = _alignement_ligne(
        page,
        _bbox_pt(100.8, 641.0, 509.0, 653.1),
        "o Information on relief activities of the humanitarian community can be found at www.reliefweb.int.",
    )

    assert alignement == "left"


def test_titre_court_multiligne_nest_pas_pris_pour_un_fragment_de_figure():
    police = FontRef("Test", "Arial", False, False)
    ligne = OcrLine(
        "New Focus",
        1.0,
        _bbox_pt(40, 340, 150, 360),
        spans=(Span("New Focus", police, 22, "243A9A", bbox=_bbox_pt(40, 340, 150, 360)),),
    )

    assert not _ligne_figure_isolee(ligne)


def test_colonne_de_presse_centree_sur_la_page_ne_devient_pas_centree():
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    lignes = [
        OcrLine("For the U.S., the changes in Russia's agricultural imports", 1.0, _bbox_pt(220, 150, 390, 162)),
        OcrLine("have meant about a 35-percent drop in value.", 1.0, _bbox_pt(220, 164, 390, 176)),
    ]

    alignement = _alignement_ligne(page, lignes[0].bbox, lignes[0].texte, lignes, 0)

    assert alignement != "center"


def test_paragraphe_word_native_scinde_lettrine_du_texte_courant():
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    police = FontRef("TimesNewRomanPSMT", "Liberation Serif", False, False)
    ligne = OcrLine(
        "R ussia, formerly one of the world's largest grain importers",
        1.0,
        _bbox_pt(40, 330, 250, 370),
        spans=(
            Span("R", police, 39.5, "000000", bbox=_bbox_pt(40, 330, 62, 370)),
            Span(" ussia, formerly one of the world's", police, 10, "000000", bbox=_bbox_pt(70, 350, 210, 362)),
            Span(" largest grain importers", police, 10, "000000", bbox=_bbox_pt(70, 363, 225, 375)),
        ),
    )

    paragraphes = _paragraphes_word_native(page, {}, [ligne], 12700.0)

    assert [p.texte for p in paragraphes] == ["R", "ussia, formerly one of the world's largest grain importers"]
    assert paragraphes[1].bbox.x0 > paragraphes[0].bbox.x1


def test_paragraphe_word_native_liste_utilise_un_retrait_suspendu():
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    police = FontRef("TimesNewRomanPSMT", "Liberation Serif", False, False)
    ligne = OcrLine(
        "o USAID: www.usaid.gov",
        1.0,
        _bbox_pt(100.8, 606.5, 317.4, 618.6),
        spans=(
            Span("o", police, 10, "000000", bbox=_bbox_pt(100.8, 607.2, 106.8, 618.6)),
            Span("\t", police, 10, "000000", bbox=_bbox_pt(106.8, 606.5, 109.6, 617.7)),
            Span("USAID: www.usaid.gov", police, 10, "000000", bbox=_bbox_pt(118.8, 606.7, 250, 617.8)),
        ),
    )

    paragraphes = _paragraphes_word_native(page, {}, [ligne], 12700.0)

    assert paragraphes[0].alignement == "left"
    assert paragraphes[0].retrait_gauche_emu == pt_vers_emu(118.8)
    assert paragraphes[0].retrait_premiere_ligne_emu == pt_vers_emu(100.8) - pt_vers_emu(118.8)


def test_paragraphe_word_native_groupe_les_lignes_de_corps():
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    police = FontRef("TimesNewRomanPSMT", "Liberation Serif", False, False)
    lignes = [
        OcrLine(
            "The objective of this project is to develop and demonstrate methods",
            1.0,
            _bbox_pt(72, 100, 500, 112),
            spans=(Span("The objective of this project is to develop and demonstrate methods", police, 10, "000000"),),
        ),
        OcrLine(
            "using adaptivity in angle variables and transport equations.",
            1.0,
            _bbox_pt(72, 113, 470, 125),
            spans=(Span("using adaptivity in angle variables and transport equations.", police, 10, "000000"),),
        ),
    ]

    paragraphes = _paragraphes_word_native(page, {}, lignes, 12700.0)

    assert len(paragraphes) == 1
    assert paragraphes[0].texte.startswith("The objective")
    assert any(span.texte == "\n" for span in paragraphes[0].spans)


def test_alignement_ligne_detecte_titre_centre():
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)

    alignement = _alignement_ligne(page, _bbox_pt(210, 100, 402, 114), "CENTERED SECTION TITLE")

    assert alignement == "center"


def test_alignement_ligne_ne_centre_pas_un_corps_large():
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    texte = "The most effective way people can assist relief efforts is by making cash contributions."
    ligne = OcrLine(texte, 1.0, _bbox_pt(72, 100, 540, 114))
    suivante = OcrLine("Those donations can be transferred quickly to the affected region.", 1.0, _bbox_pt(72, 115, 538, 129))

    alignement = _alignement_ligne(page, ligne.bbox, ligne.texte, [ligne, suivante], 0)

    assert alignement == "both"


def test_alignement_ligne_detecte_corps_justifie_large_sans_voisin():
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    texte = "This is the determination of the Railroad Retirement Board concerning the status of"

    alignement = _alignement_ligne(page, _bbox_pt(63, 145, 543, 160), texte, [OcrLine(texte, 1.0, _bbox_pt(63, 145, 543, 160))], 0)

    assert alignement == "both"


def test_alignement_ligne_detecte_droite():
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)

    alignement = _alignement_ligne(page, _bbox_pt(470, 100, 592, 114), "September 5, 2007")

    assert alignement == "right"


def test_alignement_ligne_garde_les_listes_a_gauche():
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    texte = "• More information on making donations and volunteering services can be found at:"

    alignement = _alignement_ligne(page, _bbox_pt(72, 100, 540, 114), texte)

    assert alignement == "left"


def test_word_native_prefere_ocr_brut_si_natif_sous_segmente():
    natives = [OcrLine(f"N{i}", 1.0, _bbox_pt(10, 10 + i * 10, 100, 18 + i * 10)) for i in range(5)]
    brutes = [OcrLine(f"B{i}", 1.0, _bbox_pt(10, 10 + i * 8, 100, 16 + i * 8)) for i in range(9)]
    mots = [OcrLine(f"M{i}", 1.0, _bbox_pt(10, 10 + i * 8, 100, 16 + i * 8)) for i in range(4)]

    assert _choisir_lignes_word_native(brutes, natives, mots) is brutes


def test_word_native_garde_natif_si_couverture_suffisante():
    natives = [OcrLine(f"N{i}", 1.0, _bbox_pt(10, 10 + i * 10, 100, 18 + i * 10)) for i in range(8)]
    brutes = [OcrLine(f"B{i}", 1.0, _bbox_pt(10, 10 + i * 8, 100, 16 + i * 8)) for i in range(10)]
    mots = [OcrLine(f"M{i}", 1.0, _bbox_pt(10, 10 + i * 8, 100, 16 + i * 8)) for i in range(6)]

    assert _choisir_lignes_word_native(brutes, natives, mots) is natives


def test_listing_sas_natif_ascii_nest_pas_rasterise_comme_formule():
    police = FontRef("SASMonospaceBT-Roman", "Liberation Mono", False, False)
    ligne = OcrLine(
        "T:Mean=0     45.64992  Pr>|T|     0.0001",
        1.0,
        _bbox_pt(72, 300, 280, 312),
        spans=(Span("T:Mean=0     45.64992  Pr>|T|     0.0001", police, 8, "000000"),),
    )

    assert not _ligne_formule_a_rasteriser(ligne, {})


def test_zone_image_avec_texte_natif_ne_bloque_pas_ocr():
    image = _bbox_pt(100, 100, 300, 260)
    table = _bbox_pt(350, 100, 500, 260)
    lignes = [
        _bbox_pt(120, 130, 260, 142),
        _bbox_pt(120, 148, 270, 160),
    ]

    zones = _filtrer_zones_images_avec_texte_natif([image, table], [image], lignes)

    assert zones == [table]
