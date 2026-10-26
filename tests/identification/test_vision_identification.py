"""Vision identification with SmolVLM: deterministic parts without the model, one real check."""
from pathlib import Path

import numpy as np
import pymupdf
import pytest
from PIL import Image

from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.identification import vision
from pdfexact.identification.base import ContextePage
from pdfexact.identification.referentiel import famille
from pdfexact.ir import FontRef, ImageEl, Line, Page, ShapeEl, Span, TextBox

ARIAL = FontRef("f", "Arial", False, False)
from pdfexact.identification.base import Candidat

MODELE = vision.dossier_modele("/home/raphael/Mes_Projets/vysi/ai_models")
PDF = Path("/home/raphael/Mes_Projets/vysi/vysi_real_corpus/pdf_native/1b7b94191ff4628a_000162.pdf")


def test_image_is_resized_padded_normalised_and_masked():
    pixels, masque = vision.pretraiter(Image.new("RGB", (200, 100), (255, 255, 255)))
    assert pixels.shape == (1, 1, 3, 512, 512) and pixels.dtype == np.float32
    assert masque.shape == (1, 1, 512, 512) and masque.dtype == bool
    assert masque[0, 0, :256, :].all() and not masque[0, 0, 256:, :].any()
    assert pixels[0, 0, :, 0, 0].tolist() == [1.0, 1.0, 1.0] and pixels[0, 0, :, 300, 0].tolist() == [0.0, 0.0, 0.0]


@pytest.mark.skipif(not vision.modele_disponible(MODELE), reason="SmolVLM tokenizer absent")
def test_prefix_frames_sixty_four_image_tokens_and_questions_close_the_turn():
    from tokenizers import Tokenizer

    tokeniseur = Tokenizer.from_file(str(MODELE / vision.FICHIERS["tokeniseur"]))
    prefixe = vision.ids_prefixe(tokeniseur)
    assert prefixe[0] == vision.DEBUT and (prefixe == vision.JETON_IMAGE).sum() == vision.JETONS_PAR_IMAGE
    debut = list(prefixe).index(vision.JETON_IMAGE)
    assert prefixe[debut - 2:debut].tolist() == [vision.AUTOUR_IMAGE, vision.IMAGE_GLOBALE]
    assert prefixe[debut + vision.JETONS_PAR_IMAGE] == vision.AUTOUR_IMAGE
    question = vision.ids_question(tokeniseur, "Is this a logo? Answer yes or no.")
    assert vision.FIN_TOUR in question.tolist()


def test_every_question_maps_to_a_type_of_the_referential_or_to_nothing():
    for _phrase, type_ in vision.QUESTIONS.values():
        assert type_ is None or famille(type_)


def test_confidence_grows_with_the_score_and_with_the_margin_over_the_second():
    assert vision.confiance(4.5, 1.9) > vision.confiance(1.8, 1.0) > 0
    assert vision.confiance(-1.0, -2.0) < 0.3


class _ModeleFactice:
    def __init__(self, scores):
        self.scores, self.appels = scores, []

    def log_odds(self, image, questions, gabarit=vision.GABARIT_ZONE):
        self.appels.append(gabarit)
        return {cle: self.scores.get(cle, -3.0) for cle in questions}


def _image(_bbox, cote_px=None):
    assert cote_px == vision.TAILLE  # shown at the model's input size
    return Image.new("RGB", (64, 64))


def _contexte(element, page_index=0, **extra):
    page = Page(page_index, u(612), u(792), [element])
    return ContextePage(page, extra={"rendre": _image, "rendre_marque": _image, **extra})


def test_an_image_is_shown_alone_and_identical_images_are_asked_once():
    modele = _ModeleFactice({"logo": 4.5, "diagram": 1.9})
    identificateur = vision.IdentificateurVision(modele)
    element = ImageEl(BBox(u(50), u(50), u(125), u(125)), "logo")
    candidats = identificateur.candidats(element, _contexte(element))
    assert candidats[0].type == "logo" and candidats[0].score >= 0.6 and "smolvlm" in candidats[0].indice
    identificateur.candidats(element, _contexte(element))
    assert modele.appels == [vision.GABARIT_ZONE]


def test_a_full_page_image_is_asked_whether_it_is_a_scan_or_a_background():
    modele = _ModeleFactice({"scan": 3.5})
    pleine = ImageEl(BBox(0, 0, u(612), u(792)), "f")
    assert vision.IdentificateurVision(modele).candidats(pleine, _contexte(pleine))[0].type == "page_numerisee"


def test_shapes_and_elongated_images_are_shown_framed_on_their_page():
    modele = _ModeleFactice({"frame": 3.0, "band": 3.0})
    identificateur = vision.IdentificateurVision(modele, formes=True)
    cadre = ShapeEl(BBox(u(50), u(18), u(563), u(765)), [], None, "0000FF", u(1))
    assert identificateur.candidats(cadre, _contexte(cadre))[0].type in {"bordure_page", "bandeau"}
    bande = ImageEl(BBox(u(54), u(22), u(558), u(40)), "bande")
    identificateur.candidats(bande, _contexte(bande))
    assert modele.appels == [vision.GABARIT_MARQUE, vision.GABARIT_MARQUE]


def test_a_shape_repeated_on_every_page_is_asked_once():
    modele = _ModeleFactice({"frame": 3.0})
    identificateur = vision.IdentificateurVision(modele, formes=True)
    for index in range(3):
        cadre = ShapeEl(BBox(u(50), u(18), u(563), u(765)), [], None, "0000FF", u(1))
        identificateur.candidats(cadre, _contexte(cadre, page_index=index))
    assert len(modele.appels) == 1


def test_texts_are_left_to_the_layout_model():
    assert "text" not in vision.IdentificateurVision(_ModeleFactice({})).natures


def test_tiny_images_and_missing_renderers_give_nothing():
    modele = _ModeleFactice({"logo": 4.5})
    identificateur = vision.IdentificateurVision(modele)
    petit = ImageEl(BBox(u(10), u(10), u(20), u(20)), "p")
    normal = ImageEl(BBox(u(50), u(50), u(125), u(125)), "n")
    assert identificateur.candidats(petit, _contexte(petit)) == []
    assert identificateur.candidats(normal, ContextePage(Page(0, u(612), u(792), [normal]))) == []
    assert modele.appels == []


def test_every_question_set_maps_to_types_of_the_referential():
    for questions in vision.QUESTIONS_PAR_NATURE.values():
        for _phrase, type_ in questions.values():
            assert type_ is None or famille(type_)


@pytest.mark.skipif(not (vision.modele_disponible(MODELE) and PDF.exists()), reason="SmolVLM model or PDF absent")
def test_the_real_model_recognises_a_logo():
    with pymupdf.open(PDF) as pdf:
        pix = pdf[0].get_pixmap(clip=pymupdf.Rect(50, 50, 125, 125), dpi=150)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    scores = vision.ModeleSmolVLM(MODELE).log_odds(image, vision.QUESTIONS)
    assert max(scores, key=scores.get) == "logo"


def test_an_empty_render_is_not_shown_to_the_model():
    modele = _ModeleFactice({"logo": 4.5})
    element = ImageEl(BBox(u(50), u(50), u(125), u(125)), "logo")
    vide = lambda bbox, cote_px=None: Image.new("RGB", (0, 0))
    contexte = ContextePage(Page(0, u(612), u(792), [element]), extra={"rendre": vide, "rendre_marque": vide})
    assert vision.IdentificateurVision(modele).candidats(element, contexte) == []
    assert modele.appels == []


def test_shapes_are_asked_only_on_request_and_layout_labels_are_left_to_pp_doclayout():
    assert vision.IdentificateurVision(_ModeleFactice({})).natures == {"image"}
    assert vision.IdentificateurVision(_ModeleFactice({}), formes=True).natures == {"image", "shape"}
    # Formulas and tables are PP-DocLayout labels; the small VLM answered them at random.
    assert {"formula", "table"}.isdisjoint(vision.QUESTIONS)
