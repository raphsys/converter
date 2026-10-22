import zipfile
from copy import deepcopy
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest

from pdfexact.geometry import BBox, pt_vers_emu, quantifier_bbox
from pdfexact.analysis.text_geometry import geometry_contract_for, geometry_kind
from pdfexact.ir import (
    Document,
    FlowParagraph,
    FontRef,
    Line,
    Page,
    Span,
    TableCell,
    TableEl,
    TableRow,
    TextBox,
)
from pdfexact.render.package import GestionnaireRelations, ecrire_docx
from pdfexact.render.word_native_rewriter import (
    RewritePolicy,
    _regrouper_flow_paragraphes,
    rewrite_document_xml,
)


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _font():
    return FontRef("Test", "Arial", False, False)


def _page(elements):
    return Page(0, pt_vers_emu(595), pt_vers_emu(842), elements)


def test_le_texte_horizontal_est_directement_dans_le_body():
    bbox = BBox(pt_vers_emu(40), pt_vers_emu(80), pt_vers_emu(300), pt_vers_emu(96))
    line = Line(bbox, [Span("Texte courant", _font(), 10, "000000")], pt_vers_emu(12), bbox.largeur)
    paragraph = FlowParagraph(bbox, "Texte courant", _font(), 10, "000000", spans=list(line.spans), lignes=[line])
    result = rewrite_document_xml(Document([_page([paragraph])]), GestionnaireRelations())

    root = ElementTree.fromstring(result.xml.encode())
    body = root.find(f"{W}body")
    assert body is not None
    direct_paragraphs = [child for child in body if child.tag == f"{W}p"]
    assert any("Texte courant" in "".join(node.itertext()) for node in direct_paragraphs)
    assert "wps:txbx" not in result.xml
    assert result.diagnostics.direct_body_paragraphs == 1


def test_le_texte_vertical_reste_un_cadre_ancre_editable():
    bbox = BBox(pt_vers_emu(400), pt_vers_emu(80), pt_vers_emu(420), pt_vers_emu(180))
    line = Line(
        bbox,
        [Span("Crédit", _font(), 8, "000000")],
        pt_vers_emu(10),
        bbox.largeur,
        orientation="vertical",
        angle_deg=90,
    )
    textbox = TextBox(bbox, [line], orientation="vertical", semantic_role="credit")
    result = rewrite_document_xml(Document([_page([textbox])]), GestionnaireRelations())

    assert result.diagnostics.anchored_frames == 1
    assert "<wp:anchor" in result.xml
    assert "<mc:AlternateContent>" in result.xml
    assert '<v:shape id="vertical_text_' in result.xml
    assert 'type="#_x0000_t202"' in result.xml
    assert '<v:shapetype id="_x0000_t202"' in result.xml
    assert "rotation:-90" in result.xml
    assert 'xmlns:w10="urn:schemas-microsoft-com:office:word"' in result.xml
    assert '<a:xfrm rot="0">' in result.xml
    assert 'rot="0" vert="vert270"' in result.xml
    frame_bbox = quantifier_bbox(bbox)
    assert f'<a:ext cx="{frame_bbox.hauteur}" cy="{frame_bbox.largeur}"/>' in result.xml
    assert 'horzOverflow="overflow"' in result.xml
    assert 'w:line="179"' in result.xml
    assert result.xml.count("<w:br/>") == 0
    assert "Crédit" in result.xml
    assert "tidérC" not in result.xml
    for caractere in "Crédit":
        assert caractere in result.xml


def test_le_texte_vertical_inverse_utilise_le_mode_ooxml_inverse():
    bbox = BBox(pt_vers_emu(400), pt_vers_emu(80), pt_vers_emu(420), pt_vers_emu(180))
    line = Line(
        bbox,
        [Span("Crédit inverse", _font(), 8, "000000")],
        pt_vers_emu(10),
        bbox.largeur,
        orientation="vertical",
        angle_deg=-90,
    )
    textbox = TextBox(bbox, [line], orientation="vertical", semantic_role="credit")
    result = rewrite_document_xml(Document([_page([textbox])]), GestionnaireRelations())

    assert '<a:xfrm rot="0">' in result.xml
    assert 'rot="0" vert="vert"' in result.xml
    assert "Crédit inverse" in result.xml


def test_un_bloc_horizontal_positionne_reste_un_paragraphe_word_unique():
    bbox = BBox(pt_vers_emu(60), pt_vers_emu(120), pt_vers_emu(280), pt_vers_emu(170))
    lignes = [
        Line(
            BBox(pt_vers_emu(60), pt_vers_emu(120), pt_vers_emu(280), pt_vers_emu(136)),
            [Span("Première ligne", _font(), 10, "000000")],
            pt_vers_emu(12),
            bbox.largeur,
        ),
        Line(
            BBox(pt_vers_emu(60), pt_vers_emu(140), pt_vers_emu(280), pt_vers_emu(156)),
            [Span("Deuxième ligne", _font(), 10, "000000")],
            pt_vers_emu(12),
            bbox.largeur,
        ),
    ]
    textbox = TextBox(bbox, lignes, semantic_role="caption")
    result = rewrite_document_xml(Document([_page([textbox])]), GestionnaireRelations())

    root = ElementTree.fromstring(result.xml.encode())
    body = root.find(f"{W}body")
    direct_paragraphs = [child for child in body if child.tag == f"{W}p"]
    assert result.diagnostics.positioned_flow_paragraphs == 1
    assert result.diagnostics.anchored_frames == 0
    assert result.xml.count("<w:framePr") == 1
    assert result.xml.count("<w:fitText") == 1
    assert "wps:txbx" not in result.xml
    # Une legende verrouillee conserve ses frontieres de lignes pour la geometrie
    # source; le flux courant, lui, est traite par les assertions dediees ci-dessous.
    assert result.xml.count("<w:br/>") == 1
    assert any("Première ligne" in "".join(node.itertext()) for node in direct_paragraphs)
    assert any("Deuxième ligne" in "".join(node.itertext()) for node in direct_paragraphs)


def test_une_legende_garde_sa_largeur_et_sa_hauteur_source():
    bbox = BBox(pt_vers_emu(220), pt_vers_emu(300), pt_vers_emu(520), pt_vers_emu(321))
    lignes = [
        Line(
            BBox(pt_vers_emu(220), pt_vers_emu(300), pt_vers_emu(515), pt_vers_emu(310)),
            [Span("Première partie de la légende", _font(), 10, "000000")],
            pt_vers_emu(10),
            pt_vers_emu(295),
        ),
        Line(
            BBox(pt_vers_emu(220), pt_vers_emu(311), pt_vers_emu(510), pt_vers_emu(321)),
            [Span("Deuxième partie de la légende", _font(), 10, "000000")],
            pt_vers_emu(10),
            pt_vers_emu(290),
        ),
    ]
    caption = TextBox(bbox, lignes, semantic_role="caption")
    result = rewrite_document_xml(Document([_page([caption])]), GestionnaireRelations())

    # La région ne doit pas être élargie en colonne et le cadre ne doit pas
    # pouvoir grandir après le reflow Word.
    assert '<w:framePr w:w="6004"' in result.xml
    assert 'w:hRule="exact"' in result.xml
    assert 'w:h="425"' in result.xml


def test_un_bloc_a_retrait_conserve_sa_zone_exclusion_dans_le_contrat():
    bbox = BBox(pt_vers_emu(60), pt_vers_emu(120), pt_vers_emu(280), pt_vers_emu(170))
    lignes = [
        Line(
            BBox(pt_vers_emu(88), pt_vers_emu(120), pt_vers_emu(280), pt_vers_emu(136)),
            [Span("Ligne apres lettrine", _font(), 10, "000000")],
            pt_vers_emu(12),
            pt_vers_emu(192),
        ),
        Line(
            BBox(pt_vers_emu(60), pt_vers_emu(140), pt_vers_emu(280), pt_vers_emu(156)),
            [Span("Ligne pleine", _font(), 10, "000000")],
            pt_vers_emu(12),
            pt_vers_emu(220),
        ),
    ]
    textbox = TextBox(bbox, lignes)

    geometry = geometry_contract_for(textbox)

    assert geometry_kind(textbox) == "exclusion-flow"
    assert geometry.exclusion_bboxes == (
        BBox(pt_vers_emu(60), pt_vers_emu(120), pt_vers_emu(88), pt_vers_emu(136)),
    )


def test_des_flow_paragraphes_par_ligne_sont_regroupes_en_un_seul_p():
    lignes = [
        FlowParagraph(
            BBox(pt_vers_emu(60), pt_vers_emu(120), pt_vers_emu(280), pt_vers_emu(132)),
            "Une phrase qui continue",
            _font(),
            10,
            "000000",
            lignes=[Line(BBox(pt_vers_emu(60), pt_vers_emu(120), pt_vers_emu(280), pt_vers_emu(132)), [Span("Une phrase qui continue", _font(), 10, "000000")], pt_vers_emu(12), pt_vers_emu(220))],
        ),
        FlowParagraph(
            BBox(pt_vers_emu(60), pt_vers_emu(134), pt_vers_emu(280), pt_vers_emu(146)),
            "sur la deuxième ligne",
            _font(),
            10,
            "000000",
            lignes=[Line(BBox(pt_vers_emu(60), pt_vers_emu(134), pt_vers_emu(280), pt_vers_emu(146)), [Span("sur la deuxième ligne", _font(), 10, "000000")], pt_vers_emu(12), pt_vers_emu(220))],
        ),
    ]
    result = rewrite_document_xml(Document([_page(lignes)]), GestionnaireRelations())

    assert result.diagnostics.direct_body_paragraphs == 1
    assert result.xml.count("<w:p>") == 2  # le paragraphe texte et le saut de page
    # Les lignes d'un paragraphe de corps sont maintenant assemblees en runs
    # continus, avec un espace Word, sans sauts artificiels.
    assert result.xml.count("<w:br/>") == 0
    assert "wps:txbx" not in result.xml


def test_une_continuation_minuscule_est_fusionnee_meme_si_les_frames_diffèrent():
    premiere = FlowParagraph(
        BBox(pt_vers_emu(60), pt_vers_emu(120), pt_vers_emu(280), pt_vers_emu(132)),
        "La phrase se poursuit",
        _font(),
        10,
        "000000",
        layout_frame_id="frame-a",
        lignes=[Line(BBox(pt_vers_emu(60), pt_vers_emu(120), pt_vers_emu(280), pt_vers_emu(132)), [Span("La phrase se poursuit", _font(), 10, "000000")], pt_vers_emu(12), pt_vers_emu(220))],
    )
    suite = FlowParagraph(
        BBox(pt_vers_emu(60), pt_vers_emu(134), pt_vers_emu(280), pt_vers_emu(146)),
        "sans changer de paragraphe",
        _font(),
        10,
        "000000",
        layout_frame_id="frame-b",
        lignes=[Line(BBox(pt_vers_emu(60), pt_vers_emu(134), pt_vers_emu(280), pt_vers_emu(146)), [Span("sans changer de paragraphe", _font(), 10, "000000")], pt_vers_emu(12), pt_vers_emu(220))],
    )
    result = rewrite_document_xml(Document([_page([premiere, suite])]), GestionnaireRelations())

    assert result.diagnostics.direct_body_paragraphs == 1
    assert result.xml.count("<w:br/>") == 0


@pytest.mark.parametrize("roles,native_count", [
    (("text", "figure_text"), 2),
    (("figure_text", "text"), 2),
    (("text", "text"), 1),
])
def test_le_role_du_conteneur_prime_sur_un_role_semantique_de_fragment(roles, native_count):
    from pdfexact.analysis.provenance import observation_is_preserved, text_fusion_errors
    from pdfexact.analysis.semantic import regrouper_frames, regrouper_paragraphes
    from pdfexact.layout.text_comprehension import (
        configurer_fournisseur_comprehension_texte, contexte_comprehension_texte,
    )
    from pdfexact.render.reflow import fusionner_flow_paragraphes
    from pdfexact.render.render_plan import build_document_render_plan
    from pdfexact.scene import capture_source_observations

    def ligne(y, texte, role):
        bbox = BBox(pt_vers_emu(60), pt_vers_emu(y), pt_vers_emu(280), pt_vers_emu(y + 12))
        return FlowParagraph(
            bbox,
            texte,
            _font(),
            10,
            "000000",
            layout_frame_id="panel-2",
            layout_frame_role="text-column",
            semantic_role=role,
            lignes=[Line(bbox, [Span(texte, _font(), 10, "000000")], pt_vers_emu(12), bbox.largeur)],
        )

    sources = [ligne(120, "La phrase continue", roles[0]),
               ligne(134, "fish and wildlife resources", roles[1])]
    for index, source in enumerate(sources):
        source.confidence = None if index == 0 else 0.0
        source.lignes[0].confidence = 0.91 + index * 0.06
        source.lignes[0].spans[0].confidence = None if index == 0 else 0.0
        source.attributes[f"source-owner-{index}"] = {"unknown": None, "zero": 0}
    page = _page(sources)
    capture_source_observations(page, sources, source_kind="pdf-native")
    document = Document([page])
    before = deepcopy(document)

    with contexte_comprehension_texte():
        configurer_fournisseur_comprehension_texte(None)
        assert [len(group) for group in regrouper_paragraphes(sources)] == [2]
        assert [len(group) for group in regrouper_frames(sources)] == [2]
        if native_count == 2:
            assert text_fusion_errors(sources) == ["incompatible-semantic_role"]
            with pytest.raises(ValueError, match="incompatible-semantic_role"):
                fusionner_flow_paragraphes(sources)
        else:
            assert text_fusion_errors(sources) == []
        elements = _regrouper_flow_paragraphes(sources)
        plan = build_document_render_plan(document)

    textes = [element for element in elements if isinstance(element, FlowParagraph)]
    # Semantic continuity cannot erase conflicting acquired owner metadata.
    assert len(textes) == native_count
    assert [line for element in textes for line in element.lignes] == [
        source.lignes[0] for source in sources
    ]
    if native_count == 2:
        assert tuple(element.semantic_role for element in textes) == roles
        assert [element.confidence for element in textes] == [None, 0.0]
    else:
        assert textes[0].semantic_role == roles[0]
        assert textes[0].confidence is None
        for source in sources:
            assert any(entry.kind == "source-confidence" and entry.source == source.source_id
                       and entry.confidence == source.confidence for entry in textes[0].evidence)
    assert all(observation_is_preserved(source, textes) for source in sources)
    assert document == before
    assert document.pages[0].source_inventory == before.pages[0].source_inventory
    assert plan.validate(document) == []
    assert set(plan.source_coverage) == set(plan.source_inventory)
    assert len(plan.instructions_for_page(0)) == native_count


def test_une_puce_isolee_devient_une_liste_word_native():
    marker_bbox = BBox(pt_vers_emu(260), pt_vers_emu(120), pt_vers_emu(268), pt_vers_emu(132))
    marker_line = Line(
        marker_bbox,
        [Span("\uf06e", FontRef("Wingdings-Regular", "Wingdings", False, False), 9, "000000")],
        pt_vers_emu(10),
        marker_bbox.largeur,
    )
    marker = FlowParagraph(
        marker_bbox,
        "\uf06e",
        marker_line.spans[0].police,
        9,
        "000000",
        layout_frame_id="list-panel",
        layout_frame_role="text-column",
        lignes=[marker_line],
    )
    body_bbox = BBox(pt_vers_emu(274), pt_vers_emu(120), pt_vers_emu(420), pt_vers_emu(132))
    body_line = Line(
        body_bbox,
        [Span("Texte de la puce", _font(), 10, "000000")],
        pt_vers_emu(12),
        body_bbox.largeur,
        layout_frame_id="list-panel",
        layout_frame_role="text-column",
    )
    body = FlowParagraph(
        body_bbox,
        "Texte de la puce",
        _font(),
        10,
        "000000",
        layout_frame_id="list-panel",
        layout_frame_role="text-column",
        lignes=[body_line],
    )

    result = rewrite_document_xml(Document([_page([marker, body])]), GestionnaireRelations())

    assert "Texte de la puce" in result.xml
    assert "\\uf06e" not in result.xml
    assert "<w:numPr>" in result.xml
    assert result.numbering_xml is not None
    assert "<w:lvlText w:val=\"•\"/>" in result.numbering_xml


def test_un_frame_est_fusionne_meme_si_une_forme_est_intercalee_dans_lordre_pdf():
    def ligne(y, texte):
        bbox = BBox(pt_vers_emu(60), pt_vers_emu(y), pt_vers_emu(280), pt_vers_emu(y + 12))
        return FlowParagraph(
            bbox,
            texte,
            _font(),
            10,
            "000000",
            layout_frame_id="panel-1",
            layout_frame_role="text-column",
            lignes=[Line(bbox, [Span(texte, _font(), 10, "000000")], pt_vers_emu(12), bbox.largeur)],
        )

    forme_intercalee = SimpleNamespace(bbox=BBox(pt_vers_emu(10), pt_vers_emu(130), pt_vers_emu(20), pt_vers_emu(140)))
    elements = _regrouper_flow_paragraphes(
        [ligne(120, "La phrase continue"), forme_intercalee, ligne(134, "dans le même panneau")]
    )

    textes = [element for element in elements if isinstance(element, FlowParagraph)]
    assert len(textes) == 1
    assert len(textes[0].lignes) == 2
    assert forme_intercalee in elements


def test_ecrire_docx_native_rewriter_produit_un_package_valide(tmp_path):
    bbox = BBox(pt_vers_emu(30), pt_vers_emu(40), pt_vers_emu(180), pt_vers_emu(56))
    line = Line(bbox, [Span("OK", _font(), 10, "000000")], pt_vers_emu(12), bbox.largeur)
    paragraph = FlowParagraph(bbox, "OK", _font(), 10, "000000", spans=list(line.spans), lignes=[line])
    sortie = tmp_path / "native.docx"

    resultat = ecrire_docx(Document([_page([paragraph])]), sortie, native_rewriter=True)

    assert resultat is not None
    with zipfile.ZipFile(sortie) as archive:
        ElementTree.fromstring(archive.read("word/document.xml"))
    assert resultat.diagnostics.direct_body_paragraphs == 1


def test_un_element_partiellement_hors_page_est_signale():
    bbox = BBox(pt_vers_emu(-4), pt_vers_emu(40), pt_vers_emu(180), pt_vers_emu(56))
    paragraph = FlowParagraph(bbox, "Débordement", _font(), 10, "000000")

    result = rewrite_document_xml(Document([_page([paragraph])]), GestionnaireRelations())

    assert result.diagnostics.out_of_page_elements == [result.diagnostics.decisions[0].source_id]
    assert not result.diagnostics.conforme


def test_un_element_inconnu_ne_disparait_pas_silencieusement():
    bbox = BBox(pt_vers_emu(40), pt_vers_emu(80), pt_vers_emu(180), pt_vers_emu(96))
    unknown = SimpleNamespace(bbox=bbox)

    result = rewrite_document_xml(Document([_page([unknown])]), GestionnaireRelations())

    assert result.diagnostics.missing_elements == [result.diagnostics.decisions[0].source_id]
    assert not result.diagnostics.conforme


def test_la_politique_peut_interdire_les_cadres_ancrés():
    bbox = BBox(pt_vers_emu(400), pt_vers_emu(80), pt_vers_emu(420), pt_vers_emu(180))
    line = Line(bbox, [Span("Crédit", _font(), 8, "000000")], pt_vers_emu(10), bbox.largeur)
    textbox = TextBox(bbox, [line], orientation="vertical", semantic_role="credit")

    result = rewrite_document_xml(
        Document([_page([textbox])]),
        GestionnaireRelations(),
        RewritePolicy(allow_anchored_frames=False),
    )

    assert result.diagnostics.missing_elements == [result.diagnostics.decisions[0].source_id]
    assert "Crédit" not in result.xml


def test_une_texte_courbe_utilise_un_warp_drawingml_editable():
    bbox = BBox(pt_vers_emu(120), pt_vers_emu(120), pt_vers_emu(360), pt_vers_emu(160))
    line = Line(
        bbox,
        [Span("Texte courbe", _font(), 12, "000000")],
        pt_vers_emu(14),
        bbox.largeur,
        orientation="curved",
        curved=True,
        baseline_points=((pt_vers_emu(120), pt_vers_emu(140)), (pt_vers_emu(360), pt_vers_emu(110))),
    )
    textbox = TextBox(bbox, [line], orientation="curved", curved=True)

    result = rewrite_document_xml(Document([_page([textbox])]), GestionnaireRelations())

    assert result.diagnostics.anchored_frames == 1
    assert '<a:prstTxWarp prst="textArchDown">' in result.xml
    assert "Texte courbe" in result.xml


def test_un_texte_oblique_conserve_la_rotation_sans_le_sortir_du_cadre():
    bbox = BBox(pt_vers_emu(120), pt_vers_emu(120), pt_vers_emu(300), pt_vers_emu(160))
    line = Line(
        bbox,
        [Span("Texte oblique", _font(), 12, "000000")],
        pt_vers_emu(14),
        bbox.largeur,
        angle_deg=32,
        orientation="oblique-up",
    )
    textbox = TextBox(bbox, [line], orientation="oblique-up", angle_deg=32)

    result = rewrite_document_xml(Document([_page([textbox])]), GestionnaireRelations())

    assert 'rot="-1920000"' in result.xml
    assert 'vert="horz"' in result.xml


def test_une_region_horizontale_irreguliere_conserve_les_retraits_de_lignes():
    lignes = [
        Line(
            BBox(pt_vers_emu(120), pt_vers_emu(120), pt_vers_emu(260), pt_vers_emu(132)),
            [Span("Suite apres lettrine", _font(), 10, "000000")],
            pt_vers_emu(12),
            pt_vers_emu(140),
        ),
        Line(
            BBox(pt_vers_emu(60), pt_vers_emu(134), pt_vers_emu(280), pt_vers_emu(146)),
            [Span("La phrase reprend pleine largeur.", _font(), 10, "000000")],
            pt_vers_emu(12),
            pt_vers_emu(220),
        ),
    ]
    textbox = TextBox(
        BBox(pt_vers_emu(60), pt_vers_emu(120), pt_vers_emu(280), pt_vers_emu(146)),
        lignes,
        semantic_role="text-column",
    )

    assert geometry_kind(textbox) == "exclusion-flow"
    result = rewrite_document_xml(Document([_page([textbox])]), GestionnaireRelations())

    assert result.diagnostics.anchored_frames == 1
    assert result.xml.count("<w:p><w:pPr>") >= 2
    assert result.xml.count('<w:ind w:left=') >= 2
    assert 'w:left="1204"' in result.xml
    assert "Suite apres lettrine" in result.xml


def test_un_tableau_reste_un_vrai_tableau_positionne():
    bbox = BBox(pt_vers_emu(80), pt_vers_emu(180), pt_vers_emu(300), pt_vers_emu(240))
    cell_a = TableCell(BBox(pt_vers_emu(80), pt_vers_emu(180), pt_vers_emu(190), pt_vers_emu(210)), "A")
    cell_b = TableCell(BBox(pt_vers_emu(190), pt_vers_emu(180), pt_vers_emu(300), pt_vers_emu(210)), "B")
    row = TableRow(BBox(pt_vers_emu(80), pt_vers_emu(180), pt_vers_emu(300), pt_vers_emu(210)), [cell_a, cell_b])
    table = TableEl(bbox, [row], [cell_a.bbox.largeur, cell_b.bbox.largeur], _font(), 10)

    result = rewrite_document_xml(Document([_page([table])]), GestionnaireRelations())

    assert result.diagnostics.real_tables == 1
    assert result.diagnostics.positioned_tables == 1
    assert "<w:tbl>" in result.xml
    assert 'w:vertAnchor="page"' in result.xml
    assert "<wp:anchor" not in result.xml
