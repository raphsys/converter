"""Offline contracts for the ECMA-376 types used by these producers.

These check the emitted subset of CT_Compat, CT_Font, CT_PPrBase and CT_FitText,
not whole-document XSD validity. Full official-schema evidence is kept separately.
"""
from dataclasses import replace
import pickle
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from pdfexact.geometry import BBox, pt_vers_emu
from pdfexact.ir import Document, FontAsset, FontRef, Span
from pdfexact.render import package, text_backend
from pdfexact.render.geometry_adapter import TextGeometrySpec
from pdfexact.render.text_backend import TextInstructions
from pdfexact.render.text_runs import RunInstruction, render_runs


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {
    "w": W, "r": R,
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "v": "urn:schemas-microsoft-com:vml",
    "o": "urn:schemas-microsoft-com:office:office",
    "w10": "urn:schemas-microsoft-com:office:word",
}
# Exact relative order of the CT_PPrBase children emitted by text_backend.
PPR_ORDER = ("keepLines", "framePr", "widowControl", "numPr", "tabs", "spacing", "ind", "jc")


def _root(xml):
    declarations = " ".join(f'xmlns:{key}="{value}"' for key, value in NS.items())
    return ET.fromstring(f"<root {declarations}>{xml}</root>")


def _local(node):
    return node.tag.rsplit("}", 1)[-1]


def _assert_ppr(root):
    properties = root.findall(".//w:pPr", NS)
    assert properties
    for node in properties:
        names = [_local(child) for child in node]
        assert len(names) == len(set(names)), names
        assert all(name in PPR_ORDER for name in names), names
        assert names == sorted(names, key=PPR_ORDER.index), names


@pytest.fixture
def text_case():
    box = BBox(*(pt_vers_emu(v) for v in (20, 30, 220, 65)))
    span = Span("alpha", FontRef("fixture", "Fixture Sans", False, False), 11, "123456")
    runs = (RunInstruction(span),)
    geometry = TextGeometrySpec(box, "left", "rectangular-flow", 240, 260, 700,
                                "atLeast", 700, 260, (360,), 240, 2)
    orientation = SimpleNamespace(vertical=False, special=False, warp=None,
                                  body_rotation=0, body_vertical="horz", vml_rotation=0)
    text = TextInstructions(None, geometry, orientation, runs, runs, runs,
                            ((40, 60, 240, runs),), ((240, runs), (240, runs)))
    element = SimpleNamespace(list_marker="bullet")
    numbering = SimpleNamespace(num_id=lambda _element: "7")
    return text, element, numbering


def test_settings_sequence_and_intended_hyphenation_setting():
    root = ET.fromstring(package._SETTINGS)
    compat = root.find("w:compat", NS)
    assert [_local(node) for node in compat] == [
        "doNotExpandShiftReturn", "doNotUseHTMLParagraphAutoSpacing",
        "compatSetting", "compatSetting",
    ]
    settings = {node.get(f"{{{W}}}name"): node for node in compat.findall("w:compatSetting", NS)}
    assert set(settings) == {"compatibilityMode", "useWord2013TrackBottomHyphenation"}
    assert settings["compatibilityMode"].get(f"{{{W}}}val") == "15"
    intended = settings["useWord2013TrackBottomHyphenation"]
    assert intended.attrib == {
        f"{{{W}}}name": "useWord2013TrackBottomHyphenation",
        f"{{{W}}}uri": "http://schemas.microsoft.com/office/word",
        f"{{{W}}}val": "1",
    }


@pytest.mark.parametrize("reverse", [False, True])
def test_all_embedded_faces_follow_ct_font_order(tmp_path, monkeypatch, reverse):
    faces = ["Regular", "Bold", "Italic", "BoldItalic"]
    if reverse:
        faces.reverse()
    document = Document()
    for face in faces:
        path = tmp_path / (face + ".ttf")
        path.write_bytes(face.encode() * 32)
        name = "Fixture-" + face
        document.polices[name] = FontAsset(name, "Fixture", None, "ttf", False,
                                           chemin=path, reconnue=True)
    monkeypatch.setattr(package, "nouveau_guid", lambda: "{00000000-0000-0000-0000-000000000001}")
    relations = package.GestionnaireRelations("word/fontTable.xml")
    xml, files = package._table_polices_xml(document, relations)
    font = ET.fromstring(xml).find("w:font", NS)
    assert [_local(node) for node in font] == ["embedRegular", "embedBold", "embedItalic", "embedBoldItalic"]
    assert len(files) == 4
    mapping = {entry.identifiant: entry.cible for entry in relations._entrees}
    for node, face in zip(font, ["Regular", "Bold", "Italic", "BoldItalic"]):
        payload = files[mapping[node.get(f"{{{R}}}id")].removeprefix("fonts/")]
        assert package.obfusquer_police(payload, node.get(f"{{{W}}}fontKey")) == face.encode() * 32


@pytest.mark.parametrize("listed", [False, True])
@pytest.mark.parametrize("path", ["flow", "positioned", "native", "unpositioned-native",
                                  "frame", "layered", "vertical", "vml",
                                  "exclusion-flow", "variable-width-flow"])
def test_every_active_paragraph_property_path_has_schema_order(text_case, path, listed):
    text, element, numbering = text_case
    numbering = numbering if listed else None
    page = SimpleNamespace(largeur_emu=pt_vers_emu(400))
    before = pickle.dumps(text)
    if path == "flow":
        xml = text_backend.render_flow(text, element, page, pt_vers_emu(8), None, numbering)
    elif path == "positioned":
        xml = text_backend.render_positioned(text, element, None, numbering)
    elif path in {"native", "unpositioned-native"}:
        xml = text_backend.render_native_paragraph(text, positioned=path == "native")
    else:
        if path in {"exclusion-flow", "variable-width-flow"}:
            text = replace(text, geometry=replace(text.geometry, kind=path))
        if path in {"vertical", "vml"}:
            text = replace(text, orientation=SimpleNamespace(vertical=True, special=True, warp=None,
                           body_rotation=0, body_vertical="vert", vml_rotation=-90))
        before = pickle.dumps(text)
        xml = (text_backend.render_vml(text, 1, 100, None) if path == "vml" else
               text_backend.render_frame(text, element, 1, 100, None, numbering, layered=path == "layered"))
    _assert_ppr(_root(xml))
    assert pickle.dumps(text) == before


def test_flow_list_has_one_indent_with_page_position_and_hanging_marker(text_case):
    text, element, numbering = text_case
    xml = text_backend.render_flow(text, element, SimpleNamespace(largeur_emu=pt_vers_emu(400)), 0, None, numbering)
    root = _root(xml)
    indents = root.findall(".//w:pPr/w:ind", NS)
    assert len(indents) == 1
    assert indents[0].attrib == {f"{{{W}}}left": "400", f"{{{W}}}right": "3600", f"{{{W}}}hanging": "240"}


@pytest.mark.parametrize("width", [40, 400])
def test_positioned_fit_groups_formatted_runs_without_changing_text_or_font_size(text_case, width):
    text, element, _ = text_case
    first = replace(text.flow_runs[0].span, texte="alpha & ", lien="https://example.invalid/alpha")
    second = replace(first, texte="beta", lien=None, police=replace(first.police, gras=True), size_pt=15)
    runs = (RunInstruction(first, width_percent=85), RunInstruction(command="space"), RunInstruction(second))
    box = replace(text.geometry.bbox, x1=text.geometry.bbox.x0 + pt_vers_emu(width))
    text = replace(text, flow_runs=runs, geometry=replace(text.geometry, bbox=box))
    before = pickle.dumps(text)
    relations = package.GestionnaireRelations()
    root = _root(text_backend.render_positioned(text, element, relations))
    expected = _root(render_runs(runs, package.GestionnaireRelations()))
    assert [node.text for node in root.findall(".//w:t", NS)] == [node.text for node in expected.findall(".//w:t", NS)]
    assert [node.attrib for node in root.findall(".//w:sz", NS)] == [node.attrib for node in expected.findall(".//w:sz", NS)]
    assert root.find(".//w:hyperlink", NS).get(f"{{{R}}}id") == "rId1"
    assert root.find(".//w:rPr/w:w", NS).get(f"{{{W}}}val") == "85"
    emitted = root.findall(".//w:r", NS)
    fits = [node.find("w:rPr/w:fitText", NS) for node in emitted]
    assert all(node is not None for node in fits)
    assert {node.get(f"{{{W}}}val") for node in fits} == {str(width * 20)}
    assert len({node.get(f"{{{W}}}id") for node in fits}) == 1
    assert fits[0].get(f"{{{W}}}id") is not None
    assert root.find(".//w:pPr/w:fitText", NS) is None
    assert pickle.dumps(text) == before


@pytest.mark.parametrize("inline", [False, True])
def test_positioned_line_breaks_keep_separate_fit_groups(text_case, inline):
    text, element, _ = text_case
    span = text.flow_runs[0].span
    runs = ((RunInstruction(replace(span, texte="first\nsecond")),) if inline else
            (RunInstruction(replace(span, texte="first")), RunInstruction(command="break"),
             RunInstruction(replace(span, texte="second"))))
    root = _root(text_backend.render_positioned(replace(text, flow_runs=runs), element, None))
    assert [node.text for node in root.findall(".//w:t", NS)] == ["first", "second"]
    assert len(root.findall(".//w:br", NS)) == 1
    fits = root.findall(".//w:rPr/w:fitText", NS)
    assert len(fits) == 2
    assert len({node.get(f"{{{W}}}id") for node in fits}) == 2
    assert {node.get(f"{{{W}}}val") for node in fits} == {"4000"}


@pytest.mark.parametrize("inline", [False, True])
def test_positioned_tab_fitting_gap_is_explicit(text_case, inline):
    text, element, _ = text_case
    runs = ((RunInstruction(replace(text.flow_runs[0].span, texte="a\tb")),) if inline else
            (RunInstruction(command="tab"), *text.flow_runs))
    with pytest.raises(ValueError, match="unsupported-fit-text:positioned-tab"):
        text_backend.render_positioned(replace(text, flow_runs=runs), element, None)


def test_blank_positioned_tabs_keep_native_tokens_without_fitting(text_case):
    text, element, _ = text_case
    runs = (RunInstruction(replace(text.flow_runs[0].span, texte="\t ")),
            RunInstruction(command="break"), RunInstruction(command="space"))
    root = _root(text_backend.render_positioned(replace(text, flow_runs=runs), element, None))
    expected = _root(render_runs(runs))
    assert [ET.tostring(node) for node in root.findall("w:p/w:r", NS)] == [
        ET.tostring(node) for node in expected.findall("w:r", NS)
    ]
    assert root.find(".//w:fitText", NS) is None
