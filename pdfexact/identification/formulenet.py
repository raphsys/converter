"""PP-FormulaNet (PP-StructureV3) confirms a suspected formula by recognising it.

Measured on CPU: it transcribes a real formula well, but invents LaTeX on a logo
or on ordinary text (and runs for minutes on large text zones). So it is only
consulted when an earlier source already suspects a formula, on zones of
reasonable size, and only structured LaTeX counts as a confirmation.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import numpy as np

from pdfexact.geometry import emu_vers_pt
from pdfexact.identification.base import Candidat
from pdfexact.model_paths import resolve_ai_models_root

NOM_MODELE = "PP-FormulaNet_plus-L"
SCORE_CONFIRMATION = 0.8
# Beyond this size a zone is not a single formula, and recognition takes minutes.
COTE_MAX_PT = 600.0
PART_PAGE_MAX = 0.4
_STRUCTURE = re.compile(r"=|\\frac|\\sqrt|\^|_|\\sum|\\prod|\\int|\\pm|\\mp|\\le|\\ge|\\neq|\\approx|\\times|\\cdot"
                        r"|\\partial|\\nabla|\\infty|\\rightarrow|\\to|\\lim|\\(alpha|beta|gamma|delta|theta|lambda|mu"
                        r"|pi|sigma|phi|omega)")
_INVENTE = re.compile(r"\\textcircled")


def latex_structure(latex: str) -> bool:
    """LaTeX of a real formula: a relation or an operator, and none of the invented marks."""
    latex = (latex or "").strip()
    return len(latex) >= 3 and not _INVENTE.search(latex) and bool(_STRUCTURE.search(latex))


def dossier_modele(model_root=None) -> Path:
    return resolve_ai_models_root(model_root) / "ppstructurev3" / NOM_MODELE


class ModeleFormuleNet:
    """Lazy PaddleX model, loaded once."""

    def __init__(self, dossier: Path):
        self.dossier = Path(dossier)
        self._modele = None

    def reconnaitre(self, image) -> str:
        if self._modele is None:
            os.environ.setdefault("DISABLE_MODEL_SOURCE_CHECK", "True")
            from paddlex import create_model  # type: ignore[import-not-found]

            from pdfexact.layout.ai import _options_cpu_paddlex

            self._modele = create_model(model_name=NOM_MODELE, model_dir=str(self.dossier), device="cpu",
                                        pp_option=_options_cpu_paddlex())
        bgr = np.asarray(image.convert("RGB"))[:, :, ::-1].copy()
        resultat = next(iter(self._modele.predict(bgr, batch_size=1)))
        donnees = resultat.json.get("res", resultat.json)
        return str(donnees.get("rec_formula", ""))


class IdentificateurFormuleNet:
    nom = "ppstructure-formulenet"
    natures = frozenset({"text", "image"})

    def __init__(self, modele):
        self.modele = modele
        self._cache: dict[str, str] = {}

    def pertinent(self, element, contexte, candidats) -> bool:
        page, boite = contexte.page, element.bbox
        part = (boite.largeur * boite.hauteur) / ((page.largeur_emu * page.hauteur_emu) or 1)
        # Only PP-DocLayout's own formula label sends a zone here: a guess of the vision
        # model made FormulaNet invent LaTeX on banners (and cost 83 s a call).
        return (any(c.type == "formule_bloc" and c.indice.startswith("pp-doclayout") for c in candidats)
                and max(emu_vers_pt(boite.largeur), emu_vers_pt(boite.hauteur)) <= COTE_MAX_PT
                and part <= PART_PAGE_MAX)

    def candidats(self, element, contexte):
        rendre = contexte.extra.get("rendre")
        if rendre is None:
            return []
        image = rendre(element.bbox)
        if image is None or 0 in image.size:
            return []  # a zone without area renders nothing to read
        cle = hashlib.sha256(image.tobytes() + repr(image.size).encode()).hexdigest()
        if cle not in self._cache:
            self._cache[cle] = self.modele.reconnaitre(image)
        latex = self._cache[cle]
        if not latex_structure(latex):
            return []
        return [Candidat("formule_bloc", SCORE_CONFIRMATION, f"PP-FormulaNet: {latex[:60]}")]


def creer_identificateur_formulenet(model_root=None) -> IdentificateurFormuleNet | None:
    dossier = dossier_modele(model_root)
    return IdentificateurFormuleNet(ModeleFormuleNet(dossier)) if (dossier / "inference.yml").is_file() else None
