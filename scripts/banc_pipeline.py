#!/usr/bin/env python3
"""Banc de test du pipeline (interface web Gradio, locale).

Un PDF choisi sur le PC ou donné par URL, un niveau du pipeline, des options : le
banc lance les modules et montre les pages annotées, le résumé et les fichiers produits.

    PYTHONPATH=. .converter/bin/python scripts/banc_pipeline.py
"""
from __future__ import annotations

import argparse
import contextlib
import io
import re
import sys
import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from time import monotonic, perf_counter
from types import SimpleNamespace
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

import pymupdf

from pdfexact.bboxes import annotate_pdf_bboxes, write_bbox_docx
from pdfexact.identification import annoter_pdf_types, enregistrer_identification, identifier
from pdfexact.identification.expressions import DetecteurAppelsNote, RegistreExpressions
from pdfexact.identification.vision import creer_identificateur_vision
from pdfexact.model_paths import resolve_ai_models_root
from pdfexact.segmentation import OptionsSegmentation, enregistrer_catalogue, segmenter
from scripts.reconstruct_bbox_native import _pages, _rapporter

DOSSIER_SORTIES = Path(__file__).resolve().parent.parent / "results" / "banc"
# Niveau -> modules exécutés, dans l'ordre du pipeline (le suivant s'ajoutera ici).
NIVEAUX = {
    "Segmentation": ("segmentation",),
    "Segmentation + Identification": ("segmentation", "identification"),
}
TAILLE_MAX_PDF = 200 * 1024 * 1024
DELAI_TELECHARGEMENT_S = 60
# Un PDF peut commencer par quelques octets parasites avant son en-tête.
ZONE_ENTETE_PDF = 1024
APERCU_DPI = 72
APERCUS_MAX = 30
# The page polls the background run at this period; it shows the end of the log only.
RAFRAICHISSEMENT_S = 2.0
LIGNES_JOURNAL = 300
_PAGE_EN_COURS = re.compile(r"page (\d+)/(\d+)")


@dataclass(frozen=True)
class OptionsBanc:
    niveau: str = "Segmentation + Identification"
    pages: str = "all"
    granularite: str = "blocs"
    text_mode: str = "spans"
    dpi: int = 100
    ocr_language: str = "auto"
    ocr_images: bool = False
    doclayout: bool = True
    vision: bool = True
    vision_formes: bool = False
    formulenet: bool = True
    expressions: bool = True


@dataclass(frozen=True)
class SortieBanc:
    dossier: Path
    fichiers: list[Path]
    apercus: list[Path]
    resume: str
    journal: str


def _nom_sur(nom: str) -> str:
    nom = re.sub(r"[^\w.-]+", "_", nom).strip("._") or "document"
    return nom if nom.casefold().endswith(".pdf") else f"{nom}.pdf"


def telecharger_pdf(url: str, dossier: Path, taille_max: int = TAILLE_MAX_PDF) -> Path:
    """Download a PDF over http(s) into ``dossier``; refuse anything else."""
    adresse = urlparse((url or "").strip())
    if adresse.scheme not in ("http", "https") or not adresse.netloc:
        raise ValueError(f"URL non prise en charge (http ou https seulement) : {url!r}")
    requete = Request(adresse.geturl(), headers={"User-Agent": "pdfexact-banc"})
    with urlopen(requete, timeout=DELAI_TELECHARGEMENT_S) as reponse:
        contenu = reponse.read(taille_max + 1)
    if len(contenu) > taille_max:
        raise ValueError(f"PDF trop volumineux (plus de {taille_max} octets) : {url}")
    if b"%PDF" not in contenu[:ZONE_ENTETE_PDF]:
        raise ValueError(f"Le fichier téléchargé n'est pas un PDF : {url}")
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / _nom_sur(Path(unquote(adresse.path)).name)
    chemin.write_bytes(contenu)
    return chemin


def resoudre_source(fichier: str | None, url: str | None, dossier: Path) -> Path:
    """The PDF chosen on the PC, otherwise the one at the URL."""
    if fichier:
        return Path(fichier)
    if url and url.strip():
        return telecharger_pdf(url.strip(), dossier)
    raise ValueError("Choisis un fichier PDF sur le PC ou donne l'URL d'un PDF.")


def _apercus(pdf_annote: Path, dossier: Path, pages: list[int] | None) -> list[Path]:
    """PNG of the processed pages (all when ``pages`` is None), at most APERCUS_MAX."""
    dossier.mkdir(parents=True, exist_ok=True)
    images = []
    with pymupdf.open(pdf_annote) as pdf:
        for index in (range(pdf.page_count) if pages is None else pages)[:APERCUS_MAX]:
            chemin = dossier / f"page_{index + 1:03d}.png"
            pdf[index].get_pixmap(dpi=APERCU_DPI).save(chemin)
            images.append(chemin)
    return images


class _FluxParFil:
    """sys.stdout / sys.stderr stand-in: each thread may copy what it writes into its own buffers."""

    def __init__(self, reel):
        self.reel = reel
        self.local = threading.local()

    def write(self, texte):
        for tampon in getattr(self.local, "tampons", ()):
            tampon.write(texte)
        return self.reel.write(texte)

    def flush(self):
        self.reel.flush()

    def __getattr__(self, nom):
        return getattr(self.reel, nom)


@contextlib.contextmanager
def _capturer(tampon: io.StringIO):
    """Copy what the current thread prints into ``tampon``; the terminal still shows it."""
    flux = []
    for nom in ("stdout", "stderr"):
        courant = getattr(sys, nom)
        if not isinstance(courant, _FluxParFil):
            courant = _FluxParFil(courant)
            setattr(sys, nom, courant)
        courant.local.tampons = (*getattr(courant.local, "tampons", ()), tampon)
        flux.append(courant)
    try:
        yield tampon
    finally:
        for courant in flux:
            courant.local.tampons = tuple(t for t in courant.local.tampons if t is not tampon)


def _ia(active: bool) -> str | None:
    return "auto" if active else None


def lancer(source: Path, options: OptionsBanc, dossier: Path, models_root: str | None = None,
           progres=None) -> SortieBanc:
    """Run the modules of the chosen level on ``source``; outputs go to ``dossier``."""
    signaler = progres or (lambda fraction, desc: None)
    source, dossier = Path(source), Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    modules = NIVEAUX[options.niveau]
    pdf_out, docx_out = dossier / f"{source.stem}_bboxes.pdf", dossier / f"{source.stem}.docx"
    catalogue = docx_out.with_suffix(".extraction.json")
    journal = io.StringIO()
    identification = None
    with _capturer(journal):
        with pymupdf.open(source) as pdf:
            pages = _pages(options.pages, pdf.page_count)
        signaler(0.05, "Segmentation")
        resultat = segmenter(source, OptionsSegmentation(
            pages=pages, dpi=options.dpi, text_mode=options.text_mode, ocr_language=options.ocr_language,
            ai_models_root=models_root, layout_provider="paddlex", layout_model_root=models_root,
            layout_device="cpu", granularite=options.granularite, ocr_images=options.ocr_images))
        enregistrer_catalogue(resultat, source, catalogue)
        records = annotate_pdf_bboxes(source, pdf_out, resultat.boites())
        write_bbox_docx(resultat.document, docx_out, records)
        fichiers, pdf_annote = [pdf_out, docx_out, catalogue], pdf_out
        if "identification" in modules:
            signaler(0.5, "Identification")
            debut = perf_counter()
            detecteurs = None if options.expressions else RegistreExpressions([DetecteurAppelsNote()])
            vision = _ia(options.vision)
            if options.vision and options.vision_formes:
                vision = creer_identificateur_vision(models_root, formes=True)
            identification = identifier(
                resultat, source, doclayout=_ia(options.doclayout), vision=vision,
                formulenet=_ia(options.formulenet), detecteurs=detecteurs, model_root=models_root,
                progres=lambda fait, total: signaler(0.5 + 0.45 * fait / total, f"Identification : élément {fait}/{total}"))
            types_out = pdf_out.with_name(f"{pdf_out.stem}_types.pdf")
            enregistrer_identification(identification, source, docx_out.with_suffix(".identification.json"))
            annoter_pdf_types(source, types_out, identification)
            resultat.durees["identification"] = perf_counter() - debut
            fichiers += [docx_out.with_suffix(".identification.json"), types_out]
            pdf_annote = types_out
    signaler(0.95, "Aperçus")
    resume = io.StringIO()
    with _capturer(resume):
        _rapporter(resultat, records, SimpleNamespace(pdf_out=pdf_out, docx_out=docx_out, types_out=None), identification)
    return SortieBanc(dossier, fichiers, _apercus(pdf_annote, dossier / "apercus", pages), resume.getvalue(), journal.getvalue())


def progression_segmentation(journal: str) -> tuple[int, int] | None:
    """(page, pages) of the last page announced by the segmentation in its log."""
    trouvees = _PAGE_EN_COURS.findall(journal)
    return (int(trouvees[-1][0]), int(trouvees[-1][1])) if trouvees else None


@dataclass
class Tache:
    """A pipeline run going on in a server thread; the page reads its state."""

    source: Path
    options: OptionsBanc
    dossier: Path
    debut: float = field(default_factory=monotonic)
    journal: io.StringIO = field(default_factory=io.StringIO)
    etape: str = "Démarrage"
    fraction: float = 0.0
    statut: str = "en_cours"
    erreur: str | None = None
    sortie: SortieBanc | None = None
    fil: threading.Thread | None = None

    def signaler(self, fraction: float, etape: str) -> None:
        self.fraction, self.etape = fraction, etape

    def etat(self) -> dict:
        journal = self.journal.getvalue()
        etape, fraction = self.etape, self.fraction
        page = progression_segmentation(journal) if etape == "Segmentation" else None
        if page is not None:
            etape, fraction = f"Segmentation : page {page[0]}/{page[1]}", 0.05 + 0.45 * page[0] / page[1]
        return {"statut": self.statut, "etape": etape, "fraction": fraction, "duree": monotonic() - self.debut,
                "journal": journal, "erreur": self.erreur, "sortie": self.sortie}


_VERROU = threading.Lock()
_COURANTE: Tache | None = None


def tache_courante() -> Tache | None:
    return _COURANTE


def _executer_tache(tache: Tache, models_root: str | None) -> None:
    with _capturer(tache.journal):
        try:
            tache.sortie = lancer(tache.source, tache.options, tache.dossier, models_root, progres=tache.signaler)
            tache.statut = "termine"
        except Exception as erreur:
            traceback.print_exc()
            tache.erreur = f"{type(erreur).__name__}: {erreur}"
            tache.statut = "erreur"


def demarrer(source: Path, options: OptionsBanc, dossier: Path, models_root: str | None = None) -> Tache:
    """Start a run in the background; one at a time (the models are not shared between runs)."""
    global _COURANTE
    with _VERROU:
        if _COURANTE is not None and _COURANTE.statut == "en_cours":
            raise ValueError("Un test est déjà en cours : attends sa fin avant d'en lancer un autre.")
        tache = Tache(Path(source), options, Path(dossier))
        tache.fil = threading.Thread(target=_executer_tache, args=(tache, models_root), daemon=True, name="banc")
        _COURANTE = tache
        tache.fil.start()
    return tache


def _duree(secondes: float) -> str:
    minutes, secondes = divmod(int(secondes), 60)
    return f"{minutes} min {secondes:02d} s" if minutes else f"{secondes} s"


def _statut(etat: dict) -> str:
    if etat["statut"] == "en_cours":
        return f"⏳ **{etat['etape']}** — {round(100 * etat['fraction'])} % — {_duree(etat['duree'])}"
    if etat["statut"] == "termine":
        return f"✅ **Terminé** en {_duree(etat['duree'])}"
    return f"❌ **Erreur** après {_duree(etat['duree'])} : {etat['erreur']}"


def construire_interface(models_root: str | None = None):
    import gradio as gr

    def lancer_clic(fichier, url, niveau, pages, granularite, text_mode, dpi, ocr_language, ocr_images, doclayout,
                    vision, vision_formes, formulenet, expressions, racine):
        dossier = DOSSIER_SORTIES / datetime.now().strftime("%Y%m%d-%H%M%S")
        options = OptionsBanc(niveau, pages or "all", granularite, text_mode, int(dpi), ocr_language or "auto",
                              ocr_images, doclayout, vision, vision_formes, formulenet, expressions)
        try:
            demarrer(resoudre_source(fichier, url, dossier / "source"), options, dossier, racine or None)
        except ValueError as erreur:
            raise gr.Error(str(erreur)) from erreur
        return rafraichir()

    def rafraichir():
        """Status, log and, once the run is over, its results; the timer stops then."""
        tache = tache_courante()
        if tache is None:
            return ("Aucun test lancé.", gr.update(), gr.update(), gr.update(), gr.update(), gr.update(),
                    gr.update(interactive=True), gr.Timer(active=False))
        etat = tache.etat()
        journal = "\n".join(etat["journal"].splitlines()[-LIGNES_JOURNAL:])
        if etat["statut"] == "en_cours":
            return (_statut(etat), journal, gr.update(), gr.update(), gr.update(), str(tache.dossier),
                    gr.update(interactive=False), gr.Timer(active=True))
        sortie = etat["sortie"]
        if sortie is None:
            return (_statut(etat), journal, "", None, None, str(tache.dossier), gr.update(interactive=True),
                    gr.Timer(active=False))
        return (_statut(etat), journal, sortie.resume, [str(p) for p in sortie.apercus],
                [str(p) for p in sortie.fichiers], str(sortie.dossier), gr.update(interactive=True),
                gr.Timer(active=False))

    with gr.Blocks(title="Banc de test pdfexact") as interface:
        gr.Markdown("# Banc de test du pipeline\nChoisis un PDF (sur le PC ou par URL), le niveau, les options, puis lance. "
                    "Le test tourne sur le serveur : tu peux recharger la page, il continue.")
        minuterie = gr.Timer(RAFRAICHISSEMENT_S, active=False)
        with gr.Row():
            with gr.Column(scale=1):
                fichier = gr.File(label="PDF sur le PC", file_types=[".pdf"], type="filepath")
                url = gr.Textbox(label="… ou URL du PDF", placeholder="https://exemple.org/document.pdf")
                niveau = gr.Radio(list(NIVEAUX), value="Segmentation + Identification", label="Niveau du pipeline")
                with gr.Accordion("Options de segmentation", open=True):
                    pages = gr.Textbox(value="all", label="Pages", info="all, 3, 1-5, 1,4,7-9")
                    granularite = gr.Radio(["blocs", "fine"], value="blocs", label="Granularité",
                                           info="blocs : paragraphes, images entières ; fine : lignes, parties d'images")
                    text_mode = gr.Radio(["spans", "rapidocr"], value="spans", label="Texte",
                                         info="spans : PDF natif ; rapidocr : PDF scanné")
                    dpi = gr.Slider(72, 300, value=100, step=1, label="DPI")
                    ocr_language = gr.Textbox(value="auto", label="Langue OCR",
                                              info="auto (9 modèles, lent), en, fr, ru, zh, ja, ko, ru+ja…")
                    ocr_images = gr.Checkbox(False, label="Lire aussi le texte des images des pages natives (OCR, lent)")
                with gr.Accordion("Sources IA de l'identification", open=True) as sources_ia:
                    doclayout = gr.Checkbox(True, label="PP-DocLayout, seconde passe à seuil bas")
                    vision = gr.Checkbox(True, label="SmolVLM sur les images")
                    vision_formes = gr.Checkbox(False, label="SmolVLM aussi sur les formes vectorielles (lent, peu utile)")
                    formulenet = gr.Checkbox(True, label="PP-FormulaNet (confirmation des formules)")
                    expressions = gr.Checkbox(True, label="GLiNER (expressions dans le texte)")
                racine = gr.Textbox(value=str(resolve_ai_models_root(models_root)), label="Dossier des modèles IA")
                bouton = gr.Button("Lancer le test", variant="primary")
            with gr.Column(scale=2):
                statut = gr.Markdown("Aucun test lancé.")
                resume = gr.Textbox(label="Résumé", lines=12)
                galerie = gr.Gallery(label="Pages annotées", columns=2)
                fichiers = gr.File(label="Fichiers produits", file_count="multiple")
                dossier = gr.Textbox(label="Dossier des sorties")
                journal = gr.Textbox(label="Journal du pipeline (fin)", lines=12, max_lines=24, autoscroll=True)
        sorties = [statut, journal, resume, galerie, fichiers, dossier, bouton, minuterie]
        niveau.change(lambda n: gr.update(visible="identification" in NIVEAUX[n]), niveau, sources_ia)
        bouton.click(lancer_clic, [fichier, url, niveau, pages, granularite, text_mode, dpi, ocr_language, ocr_images,
                                   doclayout,
                                   vision, vision_formes, formulenet, expressions, racine], sorties)
        minuterie.tick(rafraichir, None, sorties)
        interface.load(rafraichir, None, sorties)
    return interface


def main() -> int:
    parser = argparse.ArgumentParser(description="Banc de test web (local) du pipeline pdfexact.")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--models-root", default=None, help="dossier des modèles IA (défaut : celui du projet)")
    args = parser.parse_args()
    DOSSIER_SORTIES.mkdir(parents=True, exist_ok=True)
    # Local only: the bench reads and writes files of this machine.
    construire_interface(args.models_root).queue(default_concurrency_limit=1).launch(
        server_name="127.0.0.1", server_port=args.port, inbrowser=True, allowed_paths=[str(DOSSIER_SORTIES)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
