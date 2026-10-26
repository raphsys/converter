"""PP-DocLayout again, at a low detection threshold, for elements the segmentation's zones missed.

The segmentation keeps confident zones only. An element no source settled gets a
second look by the same model with a lower threshold; the zone's own confidence stays
its score, so a weak zone yields a weak (often ambiguous) candidate, not a guess.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from pdfexact.identification.identificateurs import candidats_zone, zone_de
from pdfexact.model_paths import resolve_ai_models_root

NOM_MODELE = "PP-DocLayout_plus-L"
SEUIL_DETECTION = 0.15
# Page rendering scale handed to the model (as in the segmentation's pass).
ECHELLE_RENDU = 2.0


def dossier_modele(model_root=None) -> Path:
    return resolve_ai_models_root(model_root) / "ppstructurev3" / NOM_MODELE


class ModeleDocLayout:
    """Lazy PaddleX model, loaded once."""

    def __init__(self, dossier: Path):
        self.dossier = Path(dossier)
        self._modele = None

    def zones(self, image, largeur_pt: float, hauteur_pt: float) -> list:
        from pdfexact.layout.ai import _normaliser_detections, _options_cpu_paddlex

        if self._modele is None:
            os.environ.setdefault("DISABLE_MODEL_SOURCE_CHECK", "True")
            from paddlex import create_model  # type: ignore[import-not-found]

            self._modele = create_model(model_name=NOM_MODELE, model_dir=str(self.dossier), device="cpu",
                                        pp_option=_options_cpu_paddlex())
        bgr = np.asarray(image.convert("RGB"))[:, :, ::-1].copy()
        brut = self._modele.predict(bgr, batch_size=1, layout_nms=True, threshold=SEUIL_DETECTION)
        return _normaliser_detections(brut, provider="paddlex", model_id=NOM_MODELE, page_width_pt=largeur_pt,
                                      page_height_pt=hauteur_pt, image_width=image.width, image_height=image.height)


class IdentificateurDocLayout:
    nom = "pp-doclayout-seuil-bas"
    natures = frozenset({"text", "image", "shape"})

    def __init__(self, modele):
        self.modele = modele
        self._zones: dict[int, list] = {}

    def pertinent(self, element, contexte, candidats) -> bool:
        return not candidats

    def candidats(self, element, contexte):
        page = contexte.page
        if page.index not in self._zones:
            rendre_page = contexte.extra.get("rendre_page")
            if rendre_page is None:
                return []
            image = rendre_page(ECHELLE_RENDU)
            self._zones[page.index] = self.modele.zones(image, image.width / ECHELLE_RENDU, image.height / ECHELLE_RENDU)
        return candidats_zone(element, zone_de(element, page, self._zones[page.index]), self.nom)


def creer_identificateur_doclayout(model_root=None) -> IdentificateurDocLayout | None:
    """The second-look identificateur, or None when the model is not on this machine."""
    dossier = dossier_modele(model_root)
    return IdentificateurDocLayout(ModeleDocLayout(dossier)) if (dossier / "inference.yml").is_file() else None
