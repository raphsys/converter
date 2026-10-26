"""Test bench of the pipeline: PDF from the PC or a URL, a pipeline level, options, outputs."""
import io
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest

from scripts import banc_pipeline as banc


class _Reponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _pdf(tmp_path, nom="doc.pdf", pages=2):
    chemin = tmp_path / nom
    with pymupdf.open() as doc:
        for _ in range(pages):
            doc.new_page(width=612, height=792)
        doc.save(chemin)
    return chemin


def test_only_http_urls_are_downloaded(tmp_path):
    for url in ("file:///etc/passwd", "ftp://x/y.pdf", "javascript:alert(1)", ""):
        with pytest.raises(ValueError):
            banc.telecharger_pdf(url, tmp_path)


def test_a_downloaded_file_must_be_a_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(banc, "urlopen", lambda requete, timeout: _Reponse(b"<html>not a pdf</html>"))
    with pytest.raises(ValueError, match="PDF"):
        banc.telecharger_pdf("https://example.org/rapport.pdf", tmp_path)


def test_a_downloaded_pdf_keeps_a_safe_name_and_a_size_limit(tmp_path, monkeypatch):
    contenu = _pdf(tmp_path).read_bytes()
    monkeypatch.setattr(banc, "urlopen", lambda requete, timeout: _Reponse(contenu))
    chemin = banc.telecharger_pdf("https://example.org/dir/../Rapport%20final.pdf?x=1", tmp_path / "dl")
    assert chemin.parent == tmp_path / "dl" and chemin.name == "Rapport_final.pdf"
    assert chemin.read_bytes() == contenu
    with pytest.raises(ValueError, match="volumineux"):
        banc.telecharger_pdf("https://example.org/gros.pdf", tmp_path / "dl", taille_max=10)


def test_the_source_is_the_chosen_file_otherwise_the_url(tmp_path, monkeypatch):
    local = _pdf(tmp_path)
    assert banc.resoudre_source(str(local), "https://example.org/x.pdf", tmp_path) == local
    monkeypatch.setattr(banc, "telecharger_pdf", lambda url, dossier: tmp_path / "url.pdf")
    assert banc.resoudre_source(None, " https://example.org/x.pdf ", tmp_path) == tmp_path / "url.pdf"
    with pytest.raises(ValueError):
        banc.resoudre_source(None, "  ", tmp_path)


def test_levels_are_ordered_and_open_to_future_modules():
    assert list(banc.NIVEAUX) == ["Segmentation", "Segmentation + Identification"]
    assert banc.NIVEAUX["Segmentation"] == ("segmentation",)
    assert banc.NIVEAUX["Segmentation + Identification"] == ("segmentation", "identification")


@pytest.fixture
def pipeline(monkeypatch, tmp_path):
    appels = {}
    document = SimpleNamespace(pages=[])
    resultat = SimpleNamespace(document=document, diagnostics=[], vision=[], textes_images=0, durees={"extraction": 1.0},
                               boites=lambda: [])

    def segmenter(source, options):
        appels["segmentation"] = options
        print("page 1/1")
        return resultat

    def identifier(segmentation, source, **kwargs):
        appels["identification"] = kwargs
        return SimpleNamespace(elements=[], expressions=[], identificateurs=("pp-doclayout",))

    def annoter(source, destination, *args):
        Path(destination).write_bytes(Path(source).read_bytes())
        return []

    monkeypatch.setattr(banc, "segmenter", segmenter)
    monkeypatch.setattr(banc, "identifier", identifier)
    monkeypatch.setattr(banc, "enregistrer_catalogue", lambda r, s, d: Path(d).write_text("{}"))
    monkeypatch.setattr(banc, "annotate_pdf_bboxes", annoter)
    monkeypatch.setattr(banc, "write_bbox_docx", lambda doc, d, records: Path(d).write_bytes(b"docx"))
    monkeypatch.setattr(banc, "enregistrer_identification", lambda r, s, d: Path(d).write_text("{}"))
    monkeypatch.setattr(banc, "annoter_pdf_types", annoter)
    return appels


def test_segmentation_level_stops_before_identification(pipeline, tmp_path):
    options = banc.OptionsBanc(niveau="Segmentation", pages="2", granularite="fine", text_mode="rapidocr", dpi=120)
    sortie = banc.lancer(_pdf(tmp_path), options, tmp_path / "out", models_root="/m")
    segmentation = pipeline["segmentation"]
    assert (segmentation.pages, segmentation.granularite, segmentation.text_mode, segmentation.dpi) == ([1], "fine", "rapidocr", 120)
    assert segmentation.layout_provider == "paddlex" and segmentation.layout_model_root == "/m"
    assert segmentation.ocr_images is False
    assert "identification" not in pipeline
    assert {p.name for p in sortie.fichiers} == {"doc_bboxes.pdf", "doc.docx", "doc.extraction.json"}
    assert "page 1/1" in sortie.journal and "bboxes=0" in sortie.resume
    assert [p.name for p in sortie.apercus] == ["page_002.png"]  # only the processed pages


def test_identification_level_passes_the_chosen_ai_sources(pipeline, tmp_path):
    options = banc.OptionsBanc(niveau="Segmentation + Identification", vision=False, expressions=False)
    sortie = banc.lancer(_pdf(tmp_path), options, tmp_path / "out", models_root="/m")
    appel = pipeline["identification"]
    assert appel["vision"] is None and appel["doclayout"] == "auto" and appel["formulenet"] == "auto"
    assert appel["model_root"] == "/m" and appel["detecteurs"].noms == ("appels-note",)
    assert {"doc_bboxes_types.pdf", "doc.identification.json"} <= {p.name for p in sortie.fichiers}
    assert "identification:" in sortie.resume


def test_the_interface_builds():
    import gradio as gr

    assert isinstance(banc.construire_interface(), gr.Blocks)


def _attendre(tache):
    tache.fil.join(timeout=10)
    assert not tache.fil.is_alive()


def test_a_run_goes_on_in_the_background_and_its_log_is_captured(tmp_path, monkeypatch):
    def lancer(source, options, dossier, models_root=None, progres=None):
        print("page 3/4 (PDF 3)")
        progres(0.5, "Identification")
        return banc.SortieBanc(Path(dossier), [], [], "bboxes=1", "")

    monkeypatch.setattr(banc, "lancer", lancer)
    tache = banc.demarrer(_pdf(tmp_path), banc.OptionsBanc(), tmp_path / "out")
    _attendre(tache)
    etat = tache.etat()
    assert etat["statut"] == "termine" and etat["sortie"].resume == "bboxes=1"
    assert "page 3/4 (PDF 3)" in etat["journal"]


def test_segmentation_progress_is_read_from_the_page_lines():
    assert banc.progression_segmentation("x\n  page 3/57 (PDF 3) - texte=spans\n  page 12/57 (PDF 12)\n") == (12, 57)
    assert banc.progression_segmentation("rien") is None


def test_a_failed_run_shows_the_exact_error(tmp_path, monkeypatch):
    def lancer(*args, **kwargs):
        raise RuntimeError("modèle introuvable : PP-DocLayout")

    monkeypatch.setattr(banc, "lancer", lancer)
    tache = banc.demarrer(_pdf(tmp_path), banc.OptionsBanc(), tmp_path / "out")
    _attendre(tache)
    assert tache.etat()["statut"] == "erreur"
    assert "modèle introuvable : PP-DocLayout" in tache.etat()["erreur"]


def test_only_one_run_at_a_time(tmp_path, monkeypatch):
    import threading

    libre = threading.Event()

    def lancer(*args, **kwargs):
        libre.wait(5)
        return banc.SortieBanc(tmp_path, [], [], "", "")

    monkeypatch.setattr(banc, "lancer", lancer)
    tache = banc.demarrer(_pdf(tmp_path), banc.OptionsBanc(), tmp_path / "a")
    with pytest.raises(ValueError, match="déjà en cours"):
        banc.demarrer(_pdf(tmp_path), banc.OptionsBanc(), tmp_path / "b")
    libre.set()
    _attendre(tache)
    assert banc.tache_courante() is tache


def test_vision_on_shapes_is_an_option(pipeline, tmp_path, monkeypatch):
    cree = {}
    monkeypatch.setattr(banc, "creer_identificateur_vision", lambda root, formes=False: (cree.update(formes=formes), "vision")[1])
    banc.lancer(_pdf(tmp_path), banc.OptionsBanc(vision_formes=True), tmp_path / "out", models_root="/m")
    assert cree["formes"] is True and pipeline["identification"]["vision"] == "vision"
