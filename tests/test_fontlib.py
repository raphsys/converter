import shutil
import subprocess
from pathlib import Path

import pytest

from pdfexact.fontlib import Bibliotheque, PoliceIndexee, construire, normaliser_nom


def _une_police_systeme_ttf():
    """Chemin d'un .ttf réellement installé, pour peupler un dossier de test."""
    sortie = subprocess.run(
        ["fc-list", "--format", "%{file}\n"], capture_output=True, timeout=20
    ).stdout.decode(errors="replace")
    for ligne in sortie.splitlines():
        if ligne.endswith(".ttf"):
            return Path(ligne)
    pytest.skip("aucune police TrueType installée sur cette machine")


@pytest.fixture
def dossier_polices(tmp_path):
    source = _une_police_systeme_ttf()
    dossier = tmp_path / "fonts"
    dossier.mkdir()
    shutil.copy(source, dossier / source.name)
    return dossier, source


def test_le_prefixe_de_sous_ensemble_est_retire():
    assert normaliser_nom("AAAAAB+HelveticaNeue-Bold") == "HelveticaNeue-Bold"


def test_un_nom_sans_prefixe_est_inchange():
    assert normaliser_nom("Raleway-Medium") == "Raleway-Medium"


def test_un_nom_vide_ne_leve_pas():
    assert normaliser_nom("") == ""


def test_lindex_systeme_nest_pas_vide():
    bibliotheque = construire(inclure_systeme=True)

    assert len(bibliotheque) > 0


def test_un_dossier_est_indexe(dossier_polices):
    dossier, _source = dossier_polices

    bibliotheque = construire(dossiers=[dossier], inclure_systeme=False)

    assert len(bibliotheque) >= 1


def test_fichier_wordperfect_corel_resout_nom_pdf(dossier_polices, tmp_path):
    _dossier, source = dossier_polices
    dossier = tmp_path / "wpfonts"
    dossier.mkdir()
    shutil.copy(source, dossier / "Wphv06na.ttf")

    bibliotheque = construire(dossiers=[dossier], inclure_systeme=False)
    resultat = bibliotheque.resoudre_detail("WP-MathA")

    assert resultat.mode == "exact"
    assert resultat.police is not None
    assert resultat.police.chemin.name == "Wphv06na.ttf"


def test_une_police_du_dossier_est_resolue_par_son_nom_postscript(dossier_polices):
    dossier, _source = dossier_polices
    bibliotheque = construire(dossiers=[dossier], inclure_systeme=False)
    nom = next(iter(bibliotheque.par_nom.values())).nom_postscript

    resultat = bibliotheque.resoudre(nom)

    assert resultat is not None
    assert resultat.chemin.parent == dossier


def test_la_resolution_ignore_la_casse(dossier_polices):
    dossier, _source = dossier_polices
    bibliotheque = construire(dossiers=[dossier], inclure_systeme=False)
    nom = next(iter(bibliotheque.par_nom.values())).nom_postscript

    assert bibliotheque.resoudre(nom.upper()) is not None
    assert bibliotheque.resoudre(nom.lower()) is not None


def test_le_prefixe_de_sous_ensemble_nempeche_pas_la_resolution(dossier_polices):
    dossier, _source = dossier_polices
    bibliotheque = construire(dossiers=[dossier], inclure_systeme=False)
    nom = next(iter(bibliotheque.par_nom.values())).nom_postscript

    assert bibliotheque.resoudre(f"ZFDQAQ+{nom}") is not None


def test_une_police_inconnue_utilise_un_substitut_dynamique():
    bibliotheque = construire(inclure_systeme=True)

    resultat = bibliotheque.resoudre_detail("PoliceQuiNExistePasDuTout-Regular")

    assert resultat.police is not None
    assert resultat.mode == "dynamique"
    assert resultat.confiance >= 0.52


def test_une_police_symbole_inconnue_ne_prend_pas_un_substitut_texte():
    bibliotheque = construire(inclure_systeme=True)

    resultat = bibliotheque.resoudre_detail("WP-PoliceSymboliqueAbsente")

    assert resultat.police is None
    assert resultat.mode == "manquante"


def test_le_substitut_dynamique_respecte_style_et_classe(tmp_path):
    bibliotheque = Bibliotheque()
    sans_bold = PoliceIndexee(
        nom_postscript="CandidateSans-Bold",
        famille="Candidate Sans",
        style="Bold",
        chemin=tmp_path / "sans-bold.ttf",
        source="dossier",
    )
    serif_regular = PoliceIndexee(
        nom_postscript="CandidateSerif-Regular",
        famille="Candidate Serif",
        style="Regular",
        chemin=tmp_path / "serif.ttf",
        source="dossier",
    )
    bibliotheque.ajouter(sans_bold, prioritaire=True)
    bibliotheque.ajouter(serif_regular, prioritaire=True)

    resultat = bibliotheque.resoudre_detail("UnknownGothic-Bold")

    assert resultat.mode == "dynamique"
    assert resultat.police == sans_bold


def test_la_resolution_par_famille_et_style_fonctionne():
    """Liberation Sans est présente sur toute installation Debian de base."""
    bibliotheque = construire(inclure_systeme=True)
    if not any("liberation" in cle for cle in bibliotheque.par_nom):
        pytest.skip("Liberation non installée")

    resultat = bibliotheque.resoudre("LiberationSans-Bold")

    assert resultat is not None
    assert "bold" in resultat.style.lower()


def test_alias_resout_les_graisses_encodees_dans_la_famille(tmp_path):
    bibliotheque = Bibliotheque()
    police = PoliceIndexee(
        nom_postscript="SourceSans3-MediumIt",
        famille="Source Sans 3 Medium",
        style="Italic",
        chemin=tmp_path / "SourceSans3-MediumIt.ttf",
        source="dossier",
    )
    bibliotheque.ajouter(police, prioritaire=True)

    resultat = bibliotheque.resoudre_detail("LegacySans-MediumItalic")

    assert resultat.mode == "alias"
    assert resultat.police == police


def test_le_dossier_a_priorite_sur_le_systeme(dossier_polices):
    """Une police présente dans le dossier ET sur le système doit venir du dossier."""
    dossier, source = dossier_polices
    bibliotheque = construire(dossiers=[dossier], inclure_systeme=True)

    nom = None
    for entree in bibliotheque.par_nom.values():
        if entree.chemin.name == source.name:
            nom = entree.nom_postscript
            break
    assert nom is not None, "la police copiée devrait être indexée"

    resultat = bibliotheque.resoudre(nom)

    assert resultat.source == "dossier"
    assert resultat.chemin.parent == dossier


def test_les_fichiers_non_indexables_sont_ignores(tmp_path):
    dossier = tmp_path / "fonts"
    dossier.mkdir()
    (dossier / "notes.txt").write_text("pas une police")
    (dossier / "cassee.ttf").write_bytes(b"pas un sfnt valide")

    bibliotheque = construire(dossiers=[dossier], inclure_systeme=False)

    assert len(bibliotheque) == 0


def test_une_bibliotheque_vide_resout_none():
    bibliotheque = Bibliotheque(par_nom={}, par_famille_style={})

    assert bibliotheque.resoudre("Arial") is None


def test_la_bibliotheque_embarquee_est_livree_avec_le_paquet():
    from pdfexact.fontlib import DOSSIER_EMBARQUE

    assert DOSSIER_EMBARQUE.is_dir(), "pdfexact/fonts/ doit être livré avec le paquet"
    assert any(DOSSIER_EMBARQUE.glob("*.ttf")) or any(DOSSIER_EMBARQUE.glob("*.otf"))


def test_les_familles_courantes_sont_reconnues_sans_le_systeme():
    """Le test qui garantit l'autonomie : aucune police système, tout vient du paquet.

    Sur une machine nue, ces familles doivent se résoudre via la bibliothèque embarquée
    et la table d'équivalences métriques.
    """
    from pdfexact.fontlib import DOSSIER_EMBARQUE

    bibliotheque = construire(dossiers=[DOSSIER_EMBARQUE], inclure_systeme=False)

    for nom in ("Arial", "ArialMT", "Helvetica", "TimesNewRomanPSMT", "Courier"):
        assert bibliotheque.resoudre(nom) is not None, f"{nom} non reconnue hors système"


def test_garamond_est_resolu_depuis_les_polices_du_projet():
    """EB Garamond remplace Garamond quand la fonte propriétaire n'est pas fournie."""
    from pdfexact.fontlib import DOSSIER_EMBARQUE

    bibliotheque = construire(dossiers=[Path("fonts"), DOSSIER_EMBARQUE], inclure_systeme=False)

    for nom, style in (
        ("Garamond", "regular"),
        ("Garamond-Bold", "bold"),
        ("Garamond-Italic", "italic"),
    ):
        resultat = bibliotheque.resoudre_detail(nom)

        assert resultat.police is not None, f"{nom} non reconnue hors système"
        assert resultat.police.famille == "EB Garamond 12"
        assert style in resultat.police.style.lower()


def test_wingdings_utilise_un_alias_dingbats_libre():
    from pdfexact.fontlib import DOSSIER_EMBARQUE

    bibliotheque = construire(dossiers=[DOSSIER_EMBARQUE], inclure_systeme=False)

    resultat = bibliotheque.resoudre_detail("Wingdings-Regular")

    assert resultat.police is not None
    assert resultat.mode == "alias"
    assert resultat.police.famille == "D050000L"


def test_myriad_et_geneva_sont_resolus_par_alias_libres():
    from pdfexact.fontlib import DOSSIER_EMBARQUE

    bibliotheque = construire(dossiers=[DOSSIER_EMBARQUE], inclure_systeme=False)

    attendues = {
        "MyriadPro-Cond": ("Liberation Sans Narrow", "Regular"),
        "MyriadPro-BoldCond": ("Liberation Sans Narrow", "Bold"),
        "MyriadPro-Regular": ("Source Sans Pro", "Regular"),
        "MyriadPro-SemiboldCond": ("Liberation Sans Narrow", "Bold"),
        "MyriadPro-Bold": ("Source Sans Pro", "Bold"),
        "MyriadPro-It": ("Source Sans Pro", "Italic"),
        "Myriad-Roman": ("Source Sans Pro", "Regular"),
        "Myriad-Italic": ("Source Sans Pro", "Italic"),
        "Myriad-Bold": ("Source Sans Pro", "Bold"),
        "MyriadPro-Black": ("Source Sans Pro", "Bold"),
        "FuturaStd-CondensedBold": ("Nimbus Sans Narrow", "Bold"),
        "Geneva": ("Liberation Sans", "Regular"),
        "CenturyGothic": ("URW Gothic", "Book"),
        "CenturyGothic-Bold": ("URW Gothic", "Demi"),
        "OfficinaSans-Book": ("Source Sans Pro", "Regular"),
        "OfficinaSans-Bold": ("Source Sans Pro", "Bold"),
        "OfficinaSerif-Bold": ("C059", "Bold"),
        "Meridien-Roman": ("C059", "Roman"),
        "Meridien-Medium": ("C059", "Roman"),
    }

    for nom, (famille, style) in attendues.items():
        resultat = bibliotheque.resoudre_detail(nom)
        assert resultat.police is not None, f"{nom} non résolue"
        assert resultat.mode == "alias"
        assert resultat.police.famille == famille
        assert style.lower() in resultat.police.style.lower()


def test_polices_ms_concatenees_sont_resolues_par_alias_libres():
    from pdfexact.fontlib import DOSSIER_EMBARQUE

    bibliotheque = construire(dossiers=[DOSSIER_EMBARQUE], inclure_systeme=False)

    attendues = {
        "ArialMS": ("Liberation Sans", "Regular"),
        "TimesNewRomanMS": ("Liberation Serif", "Regular"),
        "TimesNewRomanBdMS": ("Liberation Serif", "Bold"),
        "TimesNewRomanItMS": ("Liberation Serif", "Italic"),
        "TimesNewRomanBdItMS": ("Liberation Serif", "Bold Italic"),
        "TrebuchetMS": ("DejaVu Sans", "Book"),
        "TrebuchetMS-Italic": ("DejaVu Sans", "Oblique"),
    }

    for nom, (famille, style) in attendues.items():
        resultat = bibliotheque.resoudre_detail(nom)
        assert resultat.police is not None, f"{nom} non resolue"
        assert resultat.mode == "alias"
        assert resultat.police.famille == famille
        assert style.lower() in resultat.police.style.lower()


def test_le_dossier_dextension_du_projet_est_charge_par_defaut(tmp_path, monkeypatch):
    from pdfexact.fontlib import NOM_DOSSIER_LOCAL, dossiers_par_defaut

    extension = tmp_path / NOM_DOSSIER_LOCAL
    extension.mkdir()
    monkeypatch.chdir(tmp_path)

    assert extension in dossiers_par_defaut()
