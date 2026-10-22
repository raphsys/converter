from pdfexact.extract.orientation import angle_depuis_points, classer_orientation


def test_orientation_classe_horizontal_vertical_et_oblique():
    assert classer_orientation("Titre", 0).kind == "horizontal"
    assert classer_orientation("Credit", 90).kind == "vertical"
    assert classer_orientation("Label", 32).kind == "oblique-down"
    assert classer_orientation("Label", -32).kind == "oblique-up"


def test_orientation_conserve_un_role_semantique_de_credit():
    decision = classer_orientation("Photo courtesy of the author", 90)
    assert decision.semantic_role == "credit"


def test_orientation_detecte_une_ligne_de_base_courbe():
    decision = classer_orientation(
        "Caption on a curve",
        0.0,
        baseline_points=((0, 0), (20, 0), (40, 8), (60, 20)),
    )

    assert decision.kind == "curved"
    assert decision.curved is True


def test_angle_depuis_quadrilatere():
    assert round(angle_depuis_points(((0, 0), (0, 10)))) == 90
