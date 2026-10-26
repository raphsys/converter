"""GLiNER (multilingual NER, ONNX on CPU) locates the expressions inside a text."""
import numpy as np
import pytest

from pdfexact.identification import gliner
from pdfexact.identification.referentiel import famille

MODELE = gliner.dossier_modele()


class _Tokeniseur:
    """One token per word, two for words longer than 6 characters."""

    _speciaux = {"<<ENT>>": 90, "<<SEP>>": 91}

    def encode(self, mots, is_pretokenized=True):
        ids, word_ids = [1], [None]
        for index, mot in enumerate(mots):
            for _ in range(1 if mot in self._speciaux or len(mot) <= 6 else 2):
                ids.append(self._speciaux.get(mot, 10 + index))
                word_ids.append(index)
        ids.append(2)
        word_ids.append(None)
        return type("Encodage", (), {"ids": ids, "word_ids": word_ids})()


def test_words_follow_the_splitter_gliner_was_trained_with():
    assert gliner.mots("E = mc², see www.x.org") == [
        ("E", 0, 1), ("=", 2, 3), ("mc²", 4, 7), (",", 7, 8), ("see", 9, 12),
        ("www", 13, 16), (".", 16, 17), ("x", 17, 18), (".", 18, 19), ("org", 19, 22)]


def test_the_prompt_lists_the_labels_and_only_text_words_are_numbered():
    ids, masque = gliner.encoder(_Tokeniseur(), ["date", "gdp"], ["On", "Tuesday", "it"])
    assert ids[:6] == [1, 90, 11, 90, 13, 91]
    # Tuesday takes two tokens: only its first one carries the word number.
    assert masque == [0, 0, 0, 0, 0, 0, 1, 2, 0, 3, 0]


def test_spans_are_clamped_to_the_text_as_the_onnx_export_expects():
    spans = gliner.spans(3, largeur=2)
    assert spans.tolist() == [[0, 0], [0, 1], [1, 1], [1, 2], [2, 2], [2, 2]]


def test_decoding_keeps_the_best_non_overlapping_spans_above_the_threshold():
    logits = np.full((3, 2, 2), -5.0)
    logits[0, 1, 0] = 2.0   # words 0-1, label 0
    logits[1, 0, 1] = 3.0   # word 1, label 1: overlaps, better score, wins
    logits[2, 0, 0] = 1.0   # word 2, label 0
    logits[2, 1, 1] = 9.0   # beyond the text: ignored
    assert [(a, b, c) for a, b, c, _ in gliner.decoder(logits, 3, seuil=0.5)] == [(1, 1, 1), (2, 2, 0)]


def test_long_texts_are_cut_into_windows_under_the_token_budget():
    fenetres = gliner.fenetres([1, 2, 1, 3, 1], budget=4)
    assert fenetres == [(0, 3), (3, 5)]


class _Modele:
    def __init__(self, entites):
        self.entites_, self.appels = entites, 0

    def entites(self, texte, libelles, seuil):
        self.appels += 1
        return [e for e in self.entites_ if e[2] in libelles]


def test_labels_become_referential_types_and_unmapped_labels_emit_nothing():
    texte = "The USGS measured 12% on 3 May 2005."
    modele = _Modele([(4, 8, "organization", 0.9), (18, 21, "percentage", 0.88), (25, 35, "date", 0.97)])
    detecteur = gliner.DetecteurGLiNER(modele, {**gliner.LIBELLES, "organization": None})
    trouvailles = detecteur.trouver(None, texte)
    assert [(texte[t.debut:t.fin], t.type) for t in trouvailles] == [("12%", "grandeur"), ("3 May 2005", "date")]
    assert ("USGS", "organisation") in {(texte[t.debut:t.fin], t.type)
                                        for t in gliner.DetecteurGLiNER(_Modele(modele.entites_)).trouver(None, texte)}
    assert all("gliner" in t.indice for t in trouvailles)
    detecteur.trouver(None, texte)
    assert modele.appels == 1


def test_every_label_maps_to_a_type_of_the_referential():
    for type_ in gliner.LIBELLES.values():
        assert type_ is None or famille(type_)


def test_new_labels_can_be_plugged_in_but_only_towards_referential_types():
    detecteur = gliner.DetecteurGLiNER(_Modele([]), {"phone number": "identifiant"})
    assert detecteur.libelles == {"phone number": "identifiant"}
    with pytest.raises(ValueError):
        gliner.DetecteurGLiNER(_Modele([]), {"phone number": "telephone_inexistant"})


def test_absent_model_gives_no_detector(tmp_path):
    assert gliner.creer_detecteur_gliner(tmp_path) is None


@pytest.mark.skipif(not gliner.modele_disponible(MODELE), reason="GLiNER model absent")
def test_the_real_model_finds_dates_and_percentages_in_several_languages():
    detecteur = gliner.creer_detecteur_gliner()
    for texte, attendus in [
        ("Hurricane Katrina made landfall on August 29, 2005, and 80% of the city flooded.",
         {("August 29, 2005", "date"), ("80%", "grandeur")}),
        ("Le taux d'humidité atteint 85 % le 3 mars 2021.", {("85 %", "grandeur"), ("3 mars 2021", "date")}),
    ]:
        assert attendus <= {(texte[t.debut:t.fin], t.type) for t in detecteur.trouver(None, texte)}
