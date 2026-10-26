"""Vision identification with SmolVLM-500M (Idefics3), ONNX on CPU, no torch.

One yes/no question per category; a category's score is the log-odds of "yes"
against "no" (a small model answers short binary questions far more reliably than a
long list of labels). The image is encoded once and all questions run in one batch.

What the model sees depends on what decides the type:
- an image: the zone itself ("Is this a logo?"), its content decides;
- a vector shape, a very elongated image: the whole page with the element framed in
  red ("Is the element in the red box a frame around the page?"), its place on the
  page decides, judged by the model and not by a layout rule.
Texts are left to PP-DocLayout: measured 2026-10-23, the 500M model cannot tell the
role of a text (answers near zero, page numbers at random), whatever the view.
"""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image

from pdfexact.geometry import emu_vers_pt
from pdfexact.identification.base import Candidat
from pdfexact.identification.identificateurs import nature
from pdfexact.model_paths import resolve_ai_models_root

FICHIERS = {
    "vision": "onnx/vision_encoder_q4.onnx",
    "embed": "onnx/embed_tokens_int8.onnx",
    "decodeur": "onnx/decoder_model_merged_int8.onnx",
    "tokeniseur": "tokenizer.json",
}
TAILLE = 512
JETONS_PAR_IMAGE = 64
DIM, COUCHES, TETES_KV, DIM_TETE = 960, 32, 5, 64
DEBUT, AUTOUR_IMAGE, IMAGE_GLOBALE, JETON_IMAGE, FIN_TOUR, REMPLISSAGE = 1, 49189, 49152, 49190, 49279, 2

GABARIT_ZONE = "Is this {}? Answer yes or no."
GABARIT_MARQUE = "Is the element in the red box {}? Answer yes or no."

# Category -> (what the question asks, type of the referential or None). No formula or
# table question: those are PP-DocLayout labels, and the 500M model answered them at
# random (logos and banners taken for formulas, measured 2026-10-25).
QUESTIONS = {
    "photo": ("a photograph", "photo"),
    "logo": ("a logo", "logo"),
    "chart": ("a chart or graph of data", "graphique"),
    "diagram": ("a diagram or schema", "diagramme"),
    "map": ("a map", "carte"),
    "drawing": ("a drawing or illustration", "illustration"),
    "decoration": ("a decorative ornament or banner", "ornement"),
    "background": ("a background image or texture", "arriere_plan"),
    "scan": ("a scanned page of a document", "page_numerisee"),
    "icon": ("a small icon", "icone"),
    "signature": ("a handwritten signature", "signature"),
    "handwriting": ("handwritten text", "ecriture_manuscrite"),
    "stamp": ("a stamp or seal", "sceau"),
    "qr": ("a QR code", "qr_code"),
    "barcode": ("a barcode", "code_barres"),
    "text": ("an image of text", None),
}
QUESTIONS_FORME = {
    "frame": ("a frame or border around the page", "bordure_page"),
    "rule": ("a separator line", "separateur"),
    "band": ("a colored band or background", "bandeau"),
    "arrow": ("an arrow or a connector", "connecteur"),
    "shape": ("a geometric shape", "forme"),
    "ornament": ("a decorative ornament", "ornement"),
    "logo": ("part of a logo", "logo"),
    "chart": ("part of a chart", "graphique"),
    "diagram": ("part of a diagram", "diagramme"),
}
QUESTIONS_PAR_NATURE = {"image": QUESTIONS, "shape": QUESTIONS_FORME}
# Weight of vision among the rules, and the margin over the second category
# below which the answer is uncertain.
POIDS_VISION = 0.85
MARGE_PLEINE = 1.5
POIDS_SECOND = 0.5
# Vision refines what no earlier source established this firmly.
TYPE_DEJA_ETABLI = 0.7
# Model limit: squeezed into 512x512, a zone this elongated is unreadable on its own,
# so it is shown framed on its page instead.
ALLONGEMENT_MAX = 6.0
# Model limit: below this size an image is a speck the model cannot read.
COTE_MIN_PT = 32.0


def dossier_modele(model_root=None) -> Path:
    return resolve_ai_models_root(model_root) / "visual_layout" / "smolvlm-500m"


def modele_disponible(dossier: Path) -> bool:
    return all((Path(dossier) / chemin).is_file() for chemin in FICHIERS.values())


def pretraiter(image: Image.Image):
    """Resize the longest side to 512, pad to 512x512, normalise to [-1, 1], with its pixel mask."""
    image = image.convert("RGB")
    echelle = TAILLE / max(image.size)
    image = image.resize((max(1, round(image.width * echelle)), max(1, round(image.height * echelle))), Image.BILINEAR)
    pixels = np.zeros((TAILLE, TAILLE, 3), np.float32)
    masque = np.zeros((TAILLE, TAILLE), bool)
    valeurs = (np.asarray(image, np.float32) / 255.0 - 0.5) / 0.5
    pixels[:image.height, :image.width] = valeurs
    masque[:image.height, :image.width] = True
    return pixels.transpose(2, 0, 1)[None, None], masque[None, None]


def ids_prefixe(tokeniseur) -> np.ndarray:
    """User turn opening and the framed image tokens."""
    utilisateur = tokeniseur.encode("User:", add_special_tokens=False).ids
    return np.array([DEBUT, *utilisateur, AUTOUR_IMAGE, IMAGE_GLOBALE,
                     *[JETON_IMAGE] * JETONS_PAR_IMAGE, AUTOUR_IMAGE], np.int64)


def ids_question(tokeniseur, texte: str) -> np.ndarray:
    """Question, end of the user turn and the assistant opening."""
    question = tokeniseur.encode(texte, add_special_tokens=False).ids
    assistant = tokeniseur.encode("\nAssistant:", add_special_tokens=False).ids
    return np.array([*question, FIN_TOUR, *assistant], np.int64)


def _log_softmax(valeurs: np.ndarray) -> np.ndarray:
    valeurs = valeurs - valeurs.max()
    return valeurs - math.log(float(np.exp(valeurs).sum()))


def confiance(meilleur: float, second: float) -> float:
    """Probability of the best category, damped when the second is close."""
    sigmoide = 1.0 / (1.0 + math.exp(-meilleur))
    return POIDS_VISION * sigmoide * min(1.0, max(0.0, meilleur - second) / MARGE_PLEINE)


class ModeleSmolVLM:
    """Lazy ONNX sessions, loaded once and reused for every image."""

    def __init__(self, dossier: Path, threads: int | None = None):
        self.dossier = Path(dossier)
        self.threads = threads or os.cpu_count() or 1
        self._sessions = None
        self._tokeniseur = None
        self._oui_non = None

    def _charger(self):
        if self._sessions is not None:
            return
        import onnxruntime as ort
        from tokenizers import Tokenizer

        options = ort.SessionOptions()
        options.intra_op_num_threads = self.threads
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._sessions = {nom: ort.InferenceSession(str(self.dossier / FICHIERS[nom]), options,
                                                    providers=["CPUExecutionProvider"])
                          for nom in ("vision", "embed", "decodeur")}
        self._tokeniseur = Tokenizer.from_file(str(self.dossier / FICHIERS["tokeniseur"]))
        jeton = lambda mot: self._tokeniseur.encode(mot, add_special_tokens=False).ids[0]  # noqa: E731
        self._oui_non = ((jeton(" yes"), jeton(" Yes")), (jeton(" no"), jeton(" No")))

    def log_odds(self, image: Image.Image, questions: dict, gabarit: str = GABARIT_ZONE) -> dict[str, float]:
        """Log-odds of "yes" for every category question about the image.

        The image is encoded once; all questions run in one left-padded batch (the
        merged decoder takes several new tokens only without a past cache).
        """
        self._charger()
        pixels, masque = pretraiter(image)
        traits = self._sessions["vision"].run(None, {"pixel_values": pixels, "pixel_attention_mask": masque})[0]
        prefixe = ids_prefixe(self._tokeniseur)
        cles = list(questions)
        lignes = [np.concatenate([prefixe, ids_question(self._tokeniseur, gabarit.format(questions[cle][0]))])
                  for cle in cles]
        longueur = max(len(ligne) for ligne in lignes)
        ids = np.full((len(lignes), longueur), REMPLISSAGE, np.int64)
        attention = np.zeros((len(lignes), longueur), np.int64)
        for rang, ligne in enumerate(lignes):
            ids[rang, longueur - len(ligne):] = ligne
            attention[rang, longueur - len(ligne):] = 1
        embeds = self._sessions["embed"].run(None, {"input_ids": ids})[0]
        embeds[ids == JETON_IMAGE] = np.tile(traits.reshape(-1, DIM), (len(lignes), 1))
        entrees = {"inputs_embeds": embeds, "attention_mask": attention,
                   "position_ids": np.clip(np.cumsum(attention, axis=1) - 1, 0, None)}
        vide = np.zeros((len(lignes), TETES_KV, 0, DIM_TETE), np.float32)
        for couche in range(COUCHES):
            entrees[f"past_key_values.{couche}.key"] = vide
            entrees[f"past_key_values.{couche}.value"] = vide
        logits = self._sessions["decodeur"].run(["logits"], entrees)[0]
        (oui, Oui), (non, Non) = self._oui_non
        scores = {}
        for rang, cle in enumerate(cles):
            probas = _log_softmax(logits[rang, -1])
            scores[cle] = float(np.logaddexp(probas[oui], probas[Oui]) - np.logaddexp(probas[non], probas[Non]))
        return scores


class IdentificateurVision:
    """SmolVLM decides what no earlier source settled: generic images and shapes.

    The renderers come from the context: ``rendre`` (the zone) and ``rendre_marque``
    (the page with the element framed in red).
    """

    nom = "vision-smolvlm"
    def __init__(self, modele, formes: bool = False):
        self.modele = modele
        # Shapes are asked only on request: measured 2026-10-25, 60 calls (6 s each) for
        # nearly nothing useful on vector rules and frames.
        self.natures = frozenset({"image", "shape"} if formes else {"image"})
        self._cache: dict[str, dict[str, float]] = {}

    def pertinent(self, element, contexte, candidats) -> bool:
        return not any(c.score >= TYPE_DEJA_ETABLI and c.type != "image_generique" for c in candidats)

    def _vue(self, element, contexte):
        """(image shown, questions, template, cache key) or None when nothing can be shown."""
        nat, boite = nature(element), element.bbox
        allongee = max(boite.largeur, boite.hauteur) >= ALLONGEMENT_MAX * max(min(boite.largeur, boite.hauteur), 1)
        if nat == "image" and not allongee:
            rendre = contexte.extra.get("rendre")
            if rendre is None or max(emu_vers_pt(boite.largeur), emu_vers_pt(boite.hauteur)) < COTE_MIN_PT:
                return None
            image = rendre(boite, TAILLE)
            if _vide(image):
                return None
            return image, QUESTIONS, GABARIT_ZONE, _empreinte(image, nat)
        rendre = contexte.extra.get("rendre_marque")
        if rendre is None:
            return None
        image = rendre(boite, TAILLE)
        if _vide(image):
            return None
        if nat == "shape":
            # A shape repeated on every page (frame, band) is asked about once.
            cle = f"forme:{_arrondi(boite)}:{getattr(element, 'remplissage', None)}:{getattr(element, 'contour', None)}"
        else:
            cle = _empreinte(image, nat)
        return image, QUESTIONS_PAR_NATURE[nat], GABARIT_MARQUE, cle

    def candidats(self, element, contexte):
        vue = self._vue(element, contexte)
        if vue is None:
            return []
        image, questions, gabarit, cle = vue
        if cle not in self._cache:
            self._cache[cle] = self.modele.log_odds(image, questions, gabarit)
        classes = sorted(self._cache[cle].items(), key=lambda item: -item[1])
        resultat = []
        for rang, (categorie, score) in enumerate(classes[:2]):
            type_ = questions[categorie][1]
            suivant = classes[rang + 1][1] if rang + 1 < len(classes) else score - MARGE_PLEINE
            poids = 1.0 if rang == 0 else POIDS_SECOND
            if type_ is not None and score > 0:
                resultat.append(Candidat(type_, poids * confiance(score, suivant), f"smolvlm: {categorie} ({score:.1f})"))
        return resultat


def _vide(image) -> bool:
    """A zone without area renders nothing to read."""
    return image is None or 0 in image.size


def _empreinte(image: Image.Image, nat: str) -> str:
    return f"{nat}:" + hashlib.sha256(image.tobytes() + repr(image.size).encode()).hexdigest()


def _arrondi(boite) -> tuple[int, int, int, int]:
    return tuple(round(emu_vers_pt(v)) for v in (boite.x0, boite.y0, boite.x1, boite.y1))


def creer_identificateur_vision(model_root=None, formes: bool = False) -> IdentificateurVision | None:
    """The vision identificateur, or None when the model is not on this machine."""
    dossier = dossier_modele(model_root)
    return IdentificateurVision(ModeleSmolVLM(dossier), formes) if modele_disponible(dossier) else None
