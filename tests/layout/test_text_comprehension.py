from pdfexact.layout.text_comprehension import (
    TextUnderstandingDecision,
    comprendre_groupe_lignes,
    comprendre_ligne_texte,
    comprendre_reflow_paragraphe,
    configurer_fournisseur_comprehension_texte,
)
from pdfexact.analysis.text_segmentation import segmenter_page_textes
from pdfexact.geometry import BBox, pt_vers_emu
from pdfexact.ir import FontRef, Line, Page, Span, TextBox


def test_comprehension_fusionne_un_vrai_paragraphe_text_column():
    decision = comprendre_groupe_lignes(
        [
            "The mission architecture requires stable interfaces between",
            "launch systems and operational support teams so that the",
            "implementation remains consistent across all phases.",
        ],
        frame_role="text-column",
        frame_strategy="word-text",
    )

    assert decision.action == "merge-paragraph"
    assert decision.kind == "paragraph"


def test_comprehension_conserve_labels_de_schema():
    decision = comprendre_groupe_lignes(
        [
            "Transport Crew Cargo Support",
            "H1 H3 S1-S3 S5",
            "Level 3 Functions",
        ],
        frame_role="text-column",
        frame_strategy="word-text",
    )

    assert decision.action == "preserve-lines"


def test_comprehension_conserve_texte_hors_colonne():
    decision = comprendre_ligne_texte(
        "Vision Goals",
        frame_role="heading",
        frame_strategy="word-text",
    )

    assert decision.action == "preserve-line"


def test_comprehension_ia_prime_sur_heuristique():
    def provider(kind, lignes, frame_role, frame_strategy):
        assert kind == "group"
        assert frame_role == "text-column"
        assert frame_strategy == "word-text"
        assert lignes[0].startswith("Focus")
        return TextUnderstandingDecision("toc", "preserve-lines", 0.93, ("test-ai",))

    configurer_fournisseur_comprehension_texte(provider)
    try:
        decision = comprendre_groupe_lignes(
            [
                "Focus on Nuclear Material and Weapon Security . . . . . . 1",
                "Guest Editorial Securing Nuclear Warheads and Materials . 6",
            ],
            frame_role="text-column",
            frame_strategy="word-text",
        )
    finally:
        configurer_fournisseur_comprehension_texte(None)

    assert decision.kind == "toc"
    assert decision.action == "preserve-lines"
    assert decision.ai_used is True
    assert decision.fallback_used is False


def test_comprehension_ia_indisponible_retourne_heuristique():
    def provider(_kind, _lignes, _frame_role, _frame_strategy):
        raise RuntimeError("offline")

    configurer_fournisseur_comprehension_texte(provider)
    try:
        decision = comprendre_groupe_lignes(
            [
                "The mission architecture requires stable interfaces between",
                "launch systems and operational support teams so that the",
                "implementation remains consistent across all phases.",
            ],
            frame_role="text-column",
            frame_strategy="word-text",
        )
    finally:
        configurer_fournisseur_comprehension_texte(None)

    assert decision.action == "merge-paragraph"
    assert decision.fallback_used is True


def test_comprehension_ia_decide_les_transitions_dans_un_seul_paragraphe():
    def provider(kind, lignes, frame_role, frame_strategy):
        assert kind == "paragraph-reflow"
        assert len(lignes) == 3
        return TextUnderstandingDecision(
            "paragraph",
            "paragraph-reflow",
            0.94,
            ("test-ai",),
            ("space", "hyphen_join"),
        )

    configurer_fournisseur_comprehension_texte(provider)
    try:
        decision = comprendre_reflow_paragraphe(
            ["The text continues on the next", "line without a break", "re-search."],
            frame_role="text-column",
            frame_strategy="word-text",
        )
    finally:
        configurer_fournisseur_comprehension_texte(None)

    assert decision.line_joins == ("space", "hyphen_join")


def test_segmentation_ia_ne_fusionne_pas_deux_bboxes_sources():
    font = FontRef("Test", "Arial", False, False)

    def ligne(texte, y):
        bbox = BBox(pt_vers_emu(40), pt_vers_emu(y), pt_vers_emu(180), pt_vers_emu(y + 10))
        return Line(bbox, [Span(texte, font, 10, "000000")], pt_vers_emu(10), bbox.largeur)

    page = Page(
        index=0,
        largeur_emu=pt_vers_emu(300),
        hauteur_emu=pt_vers_emu(400),
        elements=[
            TextBox(
                BBox(pt_vers_emu(40), pt_vers_emu(40), pt_vers_emu(180), pt_vers_emu(50)),
                [ligne("First paragraph", 40)],
            ),
            TextBox(
                BBox(pt_vers_emu(40), pt_vers_emu(80), pt_vers_emu(180), pt_vers_emu(90)),
                [ligne("Second paragraph", 80)],
            ),
        ],
    )
    appels = []

    def provider(kind, lignes, frame_role, frame_strategy):
        appels.append(tuple(lignes))
        return TextUnderstandingDecision(
            "paragraph", "segment-page", 0.95, line_groups=((0,),)
        )

    configurer_fournisseur_comprehension_texte(provider)
    try:
        segmenter_page_textes(page)
    finally:
        configurer_fournisseur_comprehension_texte(None)

    # Each source block is a one-row zone: no boundary to decide, no model call.
    assert appels == []
    assert len(page.elements) == 2
    assert {element.presentation["comprehension_ia"] for element in page.elements} == {"sans-objet"}
