import shutil
import subprocess
from pathlib import Path

import pytest

from pdfexact.fontlib import Bibliotheque, construire, normaliser_nom


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


def test_une_police_inconnue_retourne_none():
    bibliotheque = construire(inclure_systeme=True)

    assert bibliotheque.resoudre("PoliceQuiNExistePasDuTout-Ultra") is None


def test_la_resolution_par_famille_et_style_fonctionne():
    """Liberation Sans est présente sur toute installation Debian de base."""
    bibliotheque = construire(inclure_systeme=True)
    if not any("liberation" in cle for cle in bibliotheque.par_nom):
        pytest.skip("Liberation non installée")

    resultat = bibliotheque.resoudre("LiberationSans-Bold")

    assert resultat is not None
    assert "bold" in resultat.style.lower()


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
