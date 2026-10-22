"""Offline lexical contract isolated by the LibreOffice 25.2 import probes."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from xml.dom import minidom
from xml.etree import ElementTree as ET
import zipfile

import pytest

from pdfexact.render import package


CT = "http://schemas.openxmlformats.org/package/2006/content-types"


def _expanded(node):
    return (node.tag, dict(node.attrib), node.text, node.tail,
            tuple(_expanded(child) for child in node))


def _assert_default_namespace(xml):
    with minidom.parseString(xml) as document:
        root = document.documentElement
        assert root.namespaceURI == CT
        assert root.prefix is None
        assert root.getAttribute("xmlns") == CT
        children = [node for node in root.childNodes if node.nodeType == node.ELEMENT_NODE]
        assert children
        assert all(node.namespaceURI == CT and node.prefix is None for node in children)


@pytest.mark.parametrize("extra", [False, True])
def test_actual_content_types_call_uses_scoped_default_namespace(extra, monkeypatch):
    parts = {"word/document.xml": b"document bytes", "_rels/.rels": b"relationship bytes"}
    if extra:
        parts.update({"word/styles.xml": b"styles", "word/settings.xml": b"settings",
                      "word/fontTable.xml": b"fonts", "word/fonts/font1.odttf": b"font payload",
                      "word/media/one.png": b"png payload", "pdfexact/render-manifest.json": b"{}"})
    before = deepcopy(parts)
    registry = dict(ET._namespace_map)

    def forbidden(*args, **kwargs):
        raise AssertionError("ContentTypes emission must not mutate the global namespace registry")

    monkeypatch.setattr(ET, "register_namespace", forbidden)
    xml = package._content_types_for(parts)

    _assert_default_namespace(xml)
    assert parts == before
    assert dict(ET._namespace_map) == registry
    root = ET.fromstring(xml)
    overrides = {node.get("PartName") for node in root.findall(f"{{{CT}}}Override")}
    assert overrides == {"/" + name for name in parts if name in {
        "word/document.xml", "word/styles.xml", "word/settings.xml", "word/fontTable.xml",
    }}
    defaults = {node.get("Extension"): node.get("ContentType") for node in root.findall(f"{{{CT}}}Default")}
    if extra:
        assert defaults["json"] == "application/json"
        assert defaults["odttf"] == "application/vnd.openxmlformats-officedocument.obfuscatedFont"


def test_two_way_prefix_control_preserves_expanded_names_attributes_and_text():
    parts = {"word/document.xml": b"doc", "word/styles.xml": b"styles"}
    actual = package._content_types_for(parts)
    prefixed_control = ET.tostring(ET.fromstring(actual), encoding="utf-8", xml_declaration=True)
    assert _expanded(ET.fromstring(actual)) == _expanded(ET.fromstring(prefixed_control))
    _assert_default_namespace(actual)
    with minidom.parseString(prefixed_control) as control:
        assert control.documentElement.prefix is not None


@pytest.mark.parametrize("root_prefix,child_prefix", [(False, False), (True, False), (False, True), (True, True)])
def test_root_and_children_are_unprefixed_regardless_of_template_prefixes(monkeypatch, root_prefix, child_prefix):
    root_name = "ct:Types" if root_prefix else "Types"
    child_name = "ct:Default" if child_prefix else "Default"
    template = (f'<{root_name} xmlns="{CT}" xmlns:ct="{CT}">'
                f'<{child_name} Extension="xml" ContentType="application/xml"/>'
                f'</{root_name}>')
    monkeypatch.setattr(package, "_CONTENT_TYPES", template)
    xml = package._content_types_for({"word/document.xml": b"document"})
    _assert_default_namespace(xml)
    assert _expanded(ET.fromstring(xml)) == _expanded(ET.fromstring(template))


def test_content_types_emission_does_not_change_concurrent_other_part_serialization():
    other = ET.Element(f"{{{CT}}}UnrelatedPart", {"value": "preserved"})
    expected = package._xml(other)
    registry = dict(ET._namespace_map)

    def emit(index):
        if index % 2:
            return package._content_types_for({"word/document.xml": b"document"})
        return package._xml(other)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(emit, range(32)))
    for index, result in enumerate(results):
        if index % 2:
            _assert_default_namespace(result)
        else:
            assert result == expected
    assert dict(ET._namespace_map) == registry


def test_scoped_serialization_preserves_template_content_and_qualified_attributes(monkeypatch):
    template = (f'<Types xmlns="{CT}" xmlns:meta="urn:metadata" meta:revision="one &amp; two">'
                '<Default Extension="xml" ContentType="application/xml"/>payload'
                '<Override PartName="/word/document.xml" ContentType="application/main+xml"/>'
                '</Types>')
    monkeypatch.setattr(package, "_CONTENT_TYPES", template)
    actual = package._content_types_for({"word/document.xml": b"doc"})
    assert _expanded(ET.fromstring(actual)) == _expanded(ET.fromstring(template))
    _assert_default_namespace(actual)


def test_changing_only_content_types_serialization_preserves_all_zip_data():
    parts = {"word/document.xml": b"native content", "_rels/.rels": b"root relationship",
             "word/fontTable.xml": b"font metadata", "word/fonts/a.odttf": bytes(range(64)),
             "pdfexact/render-manifest.json": b'{"source": "unchanged"}'}
    fixed = package._content_types_for(parts)
    prefixed = ET.tostring(ET.fromstring(fixed), encoding="utf-8", xml_declaration=True)
    archives = []
    for content_types in (prefixed, fixed):
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, value in {**parts, "[Content_Types].xml": content_types}.items():
                archive.writestr(name, value)
        with zipfile.ZipFile(buffer) as archive:
            archives.append({name: archive.read(name) for name in archive.namelist()})
    assert set(archives[0]) == set(archives[1])
    assert {name: value for name, value in archives[0].items() if name != "[Content_Types].xml"} == parts
    assert {name: value for name, value in archives[1].items() if name != "[Content_Types].xml"} == parts
    _assert_default_namespace(archives[1]["[Content_Types].xml"])
