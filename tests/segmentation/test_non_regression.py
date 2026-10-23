"""SEGMENTATION is locked: its catalogue on a real PDF must not change.

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

PDF = Path(os.environ.get("PDFEXACT_PDF_REFERENCE",
                          "/home/raphael/Mes_Projets/vysi/vysi_real_corpus/pdf_native/0fd83d2aa11747d4_000152.pdf"))
MODELES = Path(os.environ.get("PDFEXACT_MODELES_REFERENCE", "/home/raphael/Mes_Projets/vysi/ai_models"))
REFERENCE = Path(__file__).with_name("reference") / "0fd83d2aa11747d4_000152_p1-5.json"
OPTIONS = OptionsSegmentation(
    pages=[0, 1, 2, 3, 4], dpi=100, text_mode="spans", layout_provider="paddlex",
    layout_model="ppstructurev3/PP-DocLayout_plus-L", layout_model_root=str(MODELES), layout_device="cpu",
)


def _empreinte(catalogue):
    pages = []
    for page in catalogue["pages"]:
        for element in page["text_elements"]:
            box = element["bbox"]["emu"]
            pages.append([page["index"], element["kind"], box["x0"], box["y0"], box["x1"], box["y1"], element["text"]])
        for element in page["visual_elements"]:
            box = element["bbox"]["emu"]
            pages.append([page["index"], element["kind"], box["x0"], box["y0"], box["x1"], box["y1"], None])
    brut = json.dumps(catalogue["pages"], sort_keys=True, ensure_ascii=False).encode("utf-8")
    return {"pages_sha256": hashlib.sha256(brut).hexdigest(), "totals": catalogue["totals"], "elements": pages}


@pytest.mark.skipif(not (PDF.exists() and (MODELES / "ppstructurev3").exists()),
                    reason="PDF or layout models of the reference absent")
def test_segmentation_of_the_reference_pdf_is_unchanged(tmp_path):
    catalogue_path = tmp_path / "catalogue.json"
    enregistrer_catalogue(segmenter(PDF, OPTIONS), PDF, catalogue_path)
    obtenu = _empreinte(json.loads(catalogue_path.read_text(encoding="utf-8")))
    if os.environ.get("PDFEXACT_MAJ_REFERENCE") == "1":
        REFERENCE.parent.mkdir(exist_ok=True)
        REFERENCE.write_text(json.dumps(obtenu, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    attendu = json.loads(REFERENCE.read_text(encoding="utf-8"))
    assert obtenu["totals"] == attendu["totals"]
    assert obtenu["elements"] == attendu["elements"]
    assert obtenu["pages_sha256"] == attendu["pages_sha256"]
