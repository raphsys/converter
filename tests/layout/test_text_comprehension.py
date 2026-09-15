from pdfexact.layout.text_comprehension import (
    TextUnderstandingDecision,
    comprendre_groupe_lignes,
    comprendre_ligne_texte,
    configurer_fournisseur_comprehension_texte,
)


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
