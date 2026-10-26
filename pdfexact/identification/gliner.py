"""Expressions inside a text with GLiNER multi v2.1 (zero-shot NER), ONNX on CPU, no torch.

The labels are plain-language descriptions ("percentage", "chemical formula"); the model
scores every span of up to ``max_width`` words against each of them. Inference mirrors
the reference gliner.js: the prompt ``<<ENT>> label ... <<SEP>>`` precedes the words,
only the first token of each text word is numbered, spans are clamped to the text.
Only the fp32 export is used: the onnx-community int8/uint8 exports return near-constant
logits (verified 2026-10-23).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from pdfexact.identification.expressions import Trouvaille
from pdfexact.identification.referentiel import famille
from pdfexact.model_paths import resolve_ai_models_root

FICHIERS = {"modele": "onnx/model.onnx", "tokeniseur": "tokenizer.json", "config": "gliner_config.json"}
ENT, SEP = "<<ENT>>", "<<SEP>>"
# The word splitter GLiNER was trained with ("whitespace" splitter of the library).
MOT = re.compile(r"\w+(?:[-_]\w+)*|\S")
SEUIL = 0.5
# mDeBERTa positions; a few left for [CLS], [SEP].
JETONS_MAX = 510

# Label asked to the model -> type of the referential (None: asked, never emitted).
LIBELLES = {
    "web address": "url", "email address": "email", "doi": "identifiant", "isbn": "identifiant", "date": "date",
    "quantity with unit": "grandeur", "percentage": "grandeur", "acronym": "acronyme", "source code": "code_en_ligne",
    "mathematical expression": "formule_en_ligne", "chemical formula": "formule_en_ligne",
    "person": "personne", "organization": "organisation", "location": "lieu", "event": "evenement",
    "product or software": "produit", "monetary amount": "montant", "phone number": "telephone",
    "postal address": "adresse_postale",
}


def dossier_modele(model_root=None) -> Path:
    return resolve_ai_models_root(model_root) / "ner" / "gliner_multi-v2.1"


def modele_disponible(dossier: Path) -> bool:
    return all((Path(dossier) / chemin).is_file() for chemin in FICHIERS.values())


def mots(texte: str) -> list[tuple[str, int, int]]:
    return [(m.group(), m.start(), m.end()) for m in MOT.finditer(texte)]


def encoder(tokeniseur, libelles, mots_texte) -> tuple[list[int], list[int]]:
    """Token ids of prompt + words, and the words mask (1-based number on each text word's first token)."""
    invite = [x for libelle in libelles for x in (ENT, libelle)] + [SEP]
    encodage = tokeniseur.encode(invite + list(mots_texte), is_pretokenized=True)
    masque, precedent = [], None
    for mot in encodage.word_ids:
        premier = mot is not None and mot != precedent and mot >= len(invite)
        masque.append(mot - len(invite) + 1 if premier else 0)
        precedent = mot
    return list(encodage.ids), masque


def spans(n: int, largeur: int) -> np.ndarray:
    return np.array([[i, min(i + k, n - 1)] for i in range(n) for k in range(largeur)], dtype=np.int64)


def decoder(logits: np.ndarray, n: int, seuil: float = SEUIL) -> list[tuple[int, int, int, float]]:
    """(first word, last word, label, probability): the best spans, never overlapping."""
    probabilites = 1.0 / (1.0 + np.exp(-logits))
    candidats = sorted(((float(probabilites[i, k, c]), int(i), int(i + k), int(c))
                        for i, k, c in zip(*np.nonzero(probabilites >= seuil)) if i + k < n), reverse=True)
    gardes: list[tuple[int, int, int, float]] = []
    for score, debut, fin, libelle in candidats:
        if all(fin < a or debut > b for a, b, _, _ in gardes):
            gardes.append((debut, fin, libelle, score))
    return sorted(gardes)


def fenetres(jetons_par_mot: list[int], budget: int) -> list[tuple[int, int]]:
    """Consecutive [start, end) word windows whose tokens fit the budget."""
    resultat, debut, total = [], 0, 0
    for index, jetons in enumerate(jetons_par_mot):
        if total + jetons > budget and index > debut:
            resultat.append((debut, index))
            debut, total = index, 0
        total += jetons
    if debut < len(jetons_par_mot):
        resultat.append((debut, len(jetons_par_mot)))
    return resultat


class ModeleGLiNER:
    """Loaded on first use."""

    def __init__(self, dossier: Path):
        self.dossier = Path(dossier)
        self._session = self._tokeniseur = None
        self.largeur = json.loads((self.dossier / FICHIERS["config"]).read_text(encoding="utf-8"))["max_width"]

    def _charger(self) -> None:
        if self._session is None:
            import onnxruntime
            from tokenizers import Tokenizer

            self._tokeniseur = Tokenizer.from_file(str(self.dossier / FICHIERS["tokeniseur"]))
            self._session = onnxruntime.InferenceSession(str(self.dossier / FICHIERS["modele"]),
                                                         providers=["CPUExecutionProvider"])

    def entites(self, texte: str, libelles: list[str], seuil: float = SEUIL) -> list[tuple[int, int, str, float]]:
        """(start, end, label, probability) by characters of the text."""
        self._charger()
        decoupe = mots(texte)
        if not decoupe:
            return []
        jetons = [len(self._tokeniseur.encode(m, add_special_tokens=False).ids) or 1 for m, _, _ in decoupe]
        invite = len(encoder(self._tokeniseur, libelles, [])[0])
        resultat = []
        for debut, fin in fenetres(jetons, JETONS_MAX - invite):
            fenetre = decoupe[debut:fin]
            for a, b, libelle, score in self._inferer([m for m, _, _ in fenetre], libelles, seuil):
                resultat.append((fenetre[a][1], fenetre[b][2], libelles[libelle], score))
        return resultat

    def _inferer(self, mots_texte, libelles, seuil):
        ids, masque = encoder(self._tokeniseur, libelles, mots_texte)
        n = len(mots_texte)
        indices = spans(n, self.largeur)
        logits = self._session.run(["logits"], {
            "input_ids": np.array([ids], dtype=np.int64), "attention_mask": np.ones((1, len(ids)), dtype=np.int64),
            "words_mask": np.array([masque], dtype=np.int64), "text_lengths": np.array([[n]], dtype=np.int64),
            "span_idx": indices[None], "span_mask": np.ones((1, len(indices)), dtype=bool),
        })[0][0]
        return decoder(logits, n, seuil)


class DetecteurGLiNER:
    """Expressions found by GLiNER; ``libelles`` (label -> type or None) is open to new labels."""

    nom = "gliner"

    def __init__(self, modele, libelles: dict[str, str | None] | None = None, seuil: float = SEUIL):
        self.modele, self.seuil = modele, seuil
        self.libelles = dict(LIBELLES if libelles is None else libelles)
        for type_ in self.libelles.values():
            if type_ is not None:
                famille(type_)
        self._cache: dict[str, list[Trouvaille]] = {}

    def trouver(self, element, texte: str) -> list[Trouvaille]:
        if texte not in self._cache:
            self._cache[texte] = [
                Trouvaille(debut, fin, self.libelles[libelle], round(score, 3), f"gliner: {libelle}")
                for debut, fin, libelle, score in self.modele.entites(texte, list(self.libelles), self.seuil)
                if self.libelles.get(libelle) is not None]
        return list(self._cache[texte])


def creer_detecteur_gliner(model_root=None) -> DetecteurGLiNER | None:
    """The GLiNER detector, or None when the model is not on this machine."""
    dossier = dossier_modele(model_root)
    return DetecteurGLiNER(ModeleGLiNER(dossier)) if modele_disponible(dossier) else None
