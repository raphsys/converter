"""SEGMENTATION is locked: its catalogue on real PDFs must not change.

The reference holds a readable summary of every element and the hash of the
whole pages section. After a deliberate improvement of segmentation, refresh it
with PDFEXACT_MAJ_REFERENCE=1. Skipped when the PDF or the layout models are
not on this machine.
"""
import hashlib
import json
import os
from pathlib import Path

import pytest

from pdfexact.segmentation import OptionsSegmentation, enregistrer_catalogue, segmenter

CORPUS = Path(os.environ.get("PDFEXACT_CORPUS_REFERENCE", "/home/raphael/Mes_Projets/vysi/vysi_real_corpus/pdf_native"))
MODELES = Path(os.environ.get("PDFEXACT_MODELES_REFERENCE", "/home/raphael/Mes_Projets/vysi/ai_models"))
# (PDF, pages 0-based, reference prefix): a text report, and a page frame over full-page visuals.
DOCUMENTS = [
    ("0fd83d2aa11747d4_000152.pdf", [0, 1, 2, 3, 4], "0fd83d2aa11747d4_000152_p1-5"),
    ("1b7b94191ff4628a_000162.pdf", [0, 1, 2], "1b7b94191ff4628a_000162_p1-3"),
]
CAS = [(nom, pages, f"{prefixe}_{granularite}.json", granularite)
       for nom, pages, prefixe in DOCUMENTS for granularite in ("fine", "blocs")]


def _sans_noms_media(valeur):
    if isinstance(valeur, dict):
        return {cle: _sans_noms_media(item) for cle, item in valeur.items() if cle != "media_ref"}
    if isinstance(valeur, list):
        return [_sans_noms_media(item) for item in valeur]
    return valeur


def _empreinte(catalogue):
    pages = []
    for page in catalogue["pages"]:
        for element in page["text_elements"]:
            box = element["bbox"]["emu"]
            pages.append([page["index"], element["kind"], box["x0"], box["y0"], box["x1"], box["y1"], element["text"]])
        for element in page["visual_elements"]:
            box = element["bbox"]["emu"]
            pages.append([page["index"], element["kind"], box["x0"], box["y0"], box["x1"], box["y1"], None])
    # Media names come from a process-wide counter: internal, not a property of the page.
    brut = json.dumps(_sans_noms_media(catalogue["pages"]), sort_keys=True, ensure_ascii=False).encode("utf-8")
    return {"pages_sha256": hashlib.sha256(brut).hexdigest(), "totals": catalogue["totals"], "elements": pages}


@pytest.mark.parametrize("nom,pages,reference,granularite", CAS)
def test_segmentation_of_the_reference_pdfs_is_unchanged(tmp_path, nom, pages, reference, granularite):
    pdf = CORPUS / nom
    if not (pdf.exists() and (MODELES / "ppstructurev3").exists()):
        pytest.skip("PDF or layout models of the reference absent")
    options = OptionsSegmentation(
        pages=pages, dpi=100, text_mode="spans", layout_provider="paddlex",
        layout_model="ppstructurev3/PP-DocLayout_plus-L", layout_model_root=str(MODELES), layout_device="cpu",
        granularite=granularite,
    )
    catalogue_path = tmp_path / "catalogue.json"
    enregistrer_catalogue(segmenter(pdf, options), pdf, catalogue_path)
    obtenu = _empreinte(json.loads(catalogue_path.read_text(encoding="utf-8")))
    chemin = Path(__file__).with_name("reference") / reference
    if os.environ.get("PDFEXACT_MAJ_REFERENCE") == "1":
        chemin.parent.mkdir(exist_ok=True)
        chemin.write_text(json.dumps(obtenu, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    attendu = json.loads(chemin.read_text(encoding="utf-8"))
    assert obtenu["totals"] == attendu["totals"]
    assert obtenu["elements"] == attendu["elements"]
    assert obtenu["pages_sha256"] == attendu["pages_sha256"]
