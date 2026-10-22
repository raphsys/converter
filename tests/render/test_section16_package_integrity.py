import json
import os
import pickle
from pathlib import Path
from unittest.mock import Mock
from xml.etree import ElementTree as ET
import zipfile

import pytest

from pdfexact.analysis.options import PackageOptions
from pdfexact.geometry import BBox, pt_vers_emu
from pdfexact.ir import Document, FontRef, ImageEl, Line, MediaItem, Page, Span, TextBox
from pdfexact.render import package
from pdfexact.render.render_plan import build_document_render_plan


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"


def _rels(*entries):
    root = ET.Element(f"{{{REL}}}Relationships")
    for entry in entries:
        ET.SubElement(root, f"{{{REL}}}Relationship", entry)
    return ET.tostring(root)


def _relation(ident, target, kind="image", **extra):
    return {"Id": ident, "Target": target, "Type": f"{R}/{kind}", **extra}


def _parts(body=""):
    return {
        "word/document.xml": f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body>{body}<w:sectPr/></w:body></w:document>',
        "word/styles.xml": f'<w:styles xmlns:w="{W}"><w:style w:type="paragraph" w:styleId="Normal"/></w:styles>',
        "word/settings.xml": f'<w:settings xmlns:w="{W}"/>',
        "_rels/.rels": _rels(_relation("doc", "word/document.xml", "officeDocument")),
        "word/_rels/document.xml.rels": _rels(
            _relation("styles", "styles.xml", "styles"),
            _relation("settings", "settings.xml", "settings"),
        ),
    }


def _archive(tmp_path, parts):
    parts = dict(parts)
    if "[Content_Types].xml" not in parts:
        root = ET.Element(f"{{{CT}}}Types")
        defaults = {
            "xml": "application/xml", "rels": "application/vnd.openxmlformats-package.relationships+xml",
            "png": "image/png", "odttf": "application/vnd.openxmlformats-officedocument.obfuscatedFont",
            "json": "application/json",
        }
        for ext, content_type in defaults.items():
            ET.SubElement(root, f"{{{CT}}}Default", Extension=ext, ContentType=content_type)
        parts["[Content_Types].xml"] = ET.tostring(root)
    target = tmp_path / "fixture.docx"
    with zipfile.ZipFile(target, "w") as archive:
        for name, value in parts.items():
            archive.writestr(name, value)
    return target


@pytest.mark.parametrize("part", [
    "word/styles.xml", "word/settings.xml", "word/numbering.xml", "word/fontTable.xml",
    "word/header1.xml", "customXml/item1.xml", "word/_rels/header1.xml.rels",
])
def test_every_xml_and_relationship_part_is_parsed(tmp_path, part):
    parts = _parts()
    parts[part] = "<broken"
    errors = package.valider_package_ooxml(_archive(tmp_path, parts))
    assert f"invalid-xml:{part}" in errors


def test_nested_relative_targets_and_external_uris_are_resolved_correctly(tmp_path):
    parts = _parts()
    parts["word/charts/chart1.xml"] = f'<a:blip xmlns:a="urn:test" xmlns:r="{R}" r:embed="image"/>'
    parts["word/charts/_rels/chart1.xml.rels"] = _rels(
        _relation("image", "../media/picture%20one.png"),
        _relation("external", "https://example.org/a/../b?q=x#part", "hyperlink", TargetMode="External"),
    )
    parts["word/media/picture one.png"] = b"image"
    target = _archive(tmp_path, parts)
    assert package.valider_relations(target) == []
    assert package.valider_medias(target) == []
    assert package.valider_package_ooxml(target) == []


@pytest.mark.parametrize("target", ["../../escape.png", "missing.png", "https://example.org/file"])
def test_invalid_internal_targets_are_rejected(tmp_path, target):
    parts = _parts()
    parts["word/_rels/document.xml.rels"] = _rels(_relation("image", target))
    assert package.valider_relations(_archive(tmp_path, parts))


@pytest.mark.parametrize("entries", [
    [_relation("same", "styles.xml", "styles"), _relation("same", "settings.xml", "settings")],
    [{"Target": "styles.xml", "Type": f"{R}/styles"}],
    [{"Id": "no-target", "Type": f"{R}/image"}],
    [{"Id": "no-type", "Target": "styles.xml"}],
])
def test_relationship_ids_and_required_fields_are_validated(tmp_path, entries):
    parts = _parts()
    parts["word/_rels/document.xml.rels"] = _rels(*entries)
    assert package.valider_relations(_archive(tmp_path, parts))


def test_relationship_reference_in_secondary_xml_part_must_exist(tmp_path):
    parts = _parts()
    parts["word/footer1.xml"] = f'<w:ftr xmlns:w="{W}" xmlns:r="{R}"><w:hyperlink r:id="absent"/></w:ftr>'
    errors = package.valider_relations(_archive(tmp_path, parts))
    assert any("absent" in error and "footer1.xml" in error for error in errors)


def test_duplicate_zip_part_cannot_hide_an_earlier_payload(tmp_path):
    target = _archive(tmp_path, _parts())
    with zipfile.ZipFile(target, "a") as archive, pytest.warns(UserWarning, match="Duplicate name"):
        archive.writestr("word/document.xml", _parts()["word/document.xml"])
    assert "duplicate-part:word/document.xml" in package.valider_package_ooxml(target)


def test_xml_content_type_is_parsed_even_with_an_unusual_extension(tmp_path):
    parts = _parts()
    parts["customXml/source.data"] = "<broken"
    parts["[Content_Types].xml"] = f'<Types xmlns="{CT}"><Default Extension="xml" ContentType="application/xml"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/customXml/source.data" ContentType="application/vnd.example+xml"/></Types>'
    assert "invalid-xml:customXml/source.data" in package.valider_package_ooxml(_archive(tmp_path, parts))


def test_required_root_relationship_cannot_be_replaced_by_an_image_relation(tmp_path):
    parts = _parts()
    parts["_rels/.rels"] = _rels(_relation("doc", "word/document.xml", "image"))
    assert any("office-document" in error for error in package.valider_package_ooxml(_archive(tmp_path, parts)))


@pytest.mark.parametrize("content_types", [
    f'<Types xmlns="{CT}"><Override PartName="/absent.xml" ContentType="application/xml"/></Types>',
    f'<Types xmlns="{CT}"><Default Extension="xml" ContentType="application/xml"/><Default Extension="xml" ContentType="application/xml"/></Types>',
])
def test_invalid_content_type_declarations_are_rejected(tmp_path, content_types):
    parts = _parts()
    parts["[Content_Types].xml"] = content_types
    assert any("content-type" in error for error in package.valider_package_ooxml(_archive(tmp_path, parts)))


@pytest.mark.parametrize("style_body", [
    '<w:style w:type="paragraph" w:styleId="Same"/><w:style w:type="paragraph" w:styleId="Same"/>',
    '<w:style w:type="paragraph"/>',
    '<w:style w:type="paragraph" w:styleId="One"><w:basedOn w:val="Missing"/></w:style>',
    '<w:style w:type="paragraph" w:styleId="One"><w:basedOn w:val="Two"/></w:style><w:style w:type="paragraph" w:styleId="Two"><w:basedOn w:val="One"/></w:style>',
])
def test_invalid_style_definitions_are_rejected(tmp_path, style_body):
    parts = _parts()
    parts["word/styles.xml"] = f'<w:styles xmlns:w="{W}">{style_body}</w:styles>'
    assert any("style" in error for error in package.valider_package_ooxml(_archive(tmp_path, parts)))


@pytest.mark.parametrize("tag", ["pStyle", "rStyle", "tblStyle"])
def test_style_references_must_resolve(tmp_path, tag):
    parts = _parts(f'<w:{tag} w:val="MissingStyle"/>')
    errors = package.valider_package_ooxml(_archive(tmp_path, parts))
    assert any("MissingStyle" in error for error in errors)


@pytest.mark.parametrize("reference", ["basedOn", "next", "link"])
@pytest.mark.parametrize("compatible", [False, True])
def test_style_definition_references_must_have_compatible_types(tmp_path, reference, compatible):
    parts = _parts()
    character = (reference == "link") == compatible
    target_type = "character" if character else "paragraph"
    parts["word/styles.xml"] = (
        f'<w:styles xmlns:w="{W}"><w:style w:type="paragraph" w:styleId="One">'
        f'<w:{reference} w:val="Other"/></w:style>'
        f'<w:style w:type="{target_type}" w:styleId="Other"/></w:styles>'
    )
    errors = package.valider_package_ooxml(_archive(tmp_path, parts))
    if compatible:
        assert errors == []
    else:
        assert any("style" in error and "Other" in error for error in errors)


@pytest.mark.parametrize("numbering", [
    '<w:num w:numId="1"><w:abstractNumId w:val="7"/></w:num>',
    '<w:abstractNum w:abstractNumId="0"/><w:abstractNum w:abstractNumId="0"/>',
    '<w:abstractNum w:abstractNumId="0"/><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>',
    '<w:num><w:abstractNumId w:val="0"/></w:num>',
])
def test_numbering_definitions_and_abstract_links_are_validated(tmp_path, numbering):
    parts = _parts()
    parts["word/numbering.xml"] = f'<w:numbering xmlns:w="{W}">{numbering}</w:numbering>'
    assert any("numbering" in error for error in package.valider_package_ooxml(_archive(tmp_path, parts)))


def test_num_id_zero_is_reset_but_other_ids_require_numbering(tmp_path):
    parts = _parts('<w:p><w:pPr><w:numPr><w:numId w:val="0"/></w:numPr></w:pPr></w:p>')
    assert package.valider_package_ooxml(_archive(tmp_path, parts)) == []
    parts["word/document.xml"] = parts["word/document.xml"].replace('val="0"', 'val="42"')
    assert any("42" in error for error in package.valider_package_ooxml(_archive(tmp_path, parts)))


def test_numbering_numeric_ids_cannot_be_duplicated_by_leading_zeroes(tmp_path):
    parts = _parts()
    parts["word/numbering.xml"] = f'<w:numbering xmlns:w="{W}"><w:abstractNum w:abstractNumId="0"/><w:abstractNum w:abstractNumId="00"/></w:numbering>'
    assert any("invalid-numbering-id" in error for error in package.valider_package_ooxml(_archive(tmp_path, parts)))


@pytest.mark.parametrize("level", ["3", "9"])
def test_numbering_reference_must_resolve_to_a_defined_level(tmp_path, level):
    parts = _parts(f'<w:numPr><w:ilvl w:val="{level}"/><w:numId w:val="1"/></w:numPr>')
    parts["word/numbering.xml"] = f'<w:numbering xmlns:w="{W}"><w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"/></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>'
    assert any("numbering-level" in error for error in package.valider_package_ooxml(_archive(tmp_path, parts)))


def test_image_relationship_cannot_point_to_an_xml_part(tmp_path):
    parts = _parts()
    parts["word/_rels/document.xml.rels"] = _rels(_relation("image", "styles.xml"))
    assert any("image-content-type" in error for error in package.valider_package_ooxml(_archive(tmp_path, parts)))


def test_font_table_embeds_resolve_to_font_relationship_and_existing_part(tmp_path):
    parts = _parts()
    parts["word/fontTable.xml"] = f'<w:fonts xmlns:w="{W}" xmlns:r="{R}"><w:font w:name="Source"><w:embedRegular r:id="font1" w:fontKey="{{00000000-0000-0000-0000-000000000000}}"/></w:font></w:fonts>'
    parts["word/_rels/fontTable.xml.rels"] = _rels(_relation("font1", "fonts/source.odttf", "font"))
    parts["word/fonts/source.odttf"] = b"font payload"
    target = _archive(tmp_path, parts)
    assert package.valider_fonts(target) == []
    del parts["word/fonts/source.odttf"]
    assert package.valider_fonts(_archive(tmp_path, parts))


def test_font_table_unknown_embed_id_cannot_pass_with_unrelated_font(tmp_path):
    parts = _parts()
    parts["word/fontTable.xml"] = f'<w:fonts xmlns:w="{W}" xmlns:r="{R}"><w:font w:name="Source"><w:embedRegular r:id="absent"/></w:font></w:fonts>'
    parts["word/_rels/fontTable.xml.rels"] = _rels(_relation("other", "fonts/source.odttf", "font"))
    parts["word/fonts/source.odttf"] = b"font payload"
    assert any("absent" in error for error in package.valider_fonts(_archive(tmp_path, parts)))


@pytest.mark.parametrize("kind", ["styles", "numbering"])
def test_contract_parts_can_live_at_relationship_resolved_paths(tmp_path, kind):
    body = '<w:pStyle w:val="Custom"/>' if kind == "styles" else '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
    parts = _parts(body)
    if kind == "styles":
        parts.pop("word/styles.xml")
        parts["word/shared/styles.xml"] = f'<w:styles xmlns:w="{W}"><w:style w:type="paragraph" w:styleId="Custom"/></w:styles>'
    else:
        parts["word/shared/numbering.xml"] = f'<w:numbering xmlns:w="{W}"><w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"/></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>'
    entries = [_relation("settings", "settings.xml", "settings"), _relation("contract", f"shared/{kind}.xml", kind)]
    if kind != "styles":
        entries.append(_relation("styles", "styles.xml", "styles"))
    parts["word/_rels/document.xml.rels"] = _rels(*entries)
    assert package.valider_package_ooxml(_archive(tmp_path, parts)) == []


def test_font_embed_reference_is_checked_in_relocated_font_table(tmp_path):
    parts = _parts()
    parts["word/shared/fontTable.xml"] = f'<w:fonts xmlns:w="{W}" xmlns:r="{R}"><w:font w:name="Source"><w:embedRegular r:id="absent"/></w:font></w:fonts>'
    parts["word/shared/_rels/fontTable.xml.rels"] = _rels(_relation("other", "../fonts/source.odttf", "font"))
    parts["word/fonts/source.odttf"] = b"font payload"
    parts["word/_rels/document.xml.rels"] = _rels(
        _relation("styles", "styles.xml", "styles"), _relation("fonts", "shared/fontTable.xml", "fontTable"),
    )
    assert any("absent" in error for error in package.valider_fonts(_archive(tmp_path, parts)))


def test_manager_deduplicates_normalized_targets_and_retains_source_mapping():
    relations = package.GestionnaireRelations()
    first = relations.ajouter("media/./one.png", "image", source_ids=("source-one",))
    second = relations.ajouter("media/one.png", "image", source_ids=("source-two",))
    assert first == second
    assert relations.source_mapping[first] == ("source-one", "source-two")


def test_manager_reports_unknown_relationship_type():
    with pytest.raises(ValueError, match="unknown-relation-type"):
        package.GestionnaireRelations().ajouter("part.xml", "unknown")


def test_manager_does_not_merge_different_internal_uri_fragments():
    relations = package.GestionnaireRelations()
    first = relations.ajouter("document.xml#first", "hyperlink")
    second = relations.ajouter("./document.xml#second", "hyperlink")
    assert first != second


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("invalid_kind", ["xml", "relationship", "style", "numbering"])
def test_invalid_generated_package_never_replaces_destination(tmp_path, monkeypatch, existing, invalid_kind):
    target = tmp_path / "destination.docx"
    if existing:
        target.write_bytes(b"preserved bytes")
    body = "<broken" if invalid_kind == "xml" else _parts()["word/document.xml"]
    if invalid_kind == "relationship":
        body = _parts('<w:hyperlink r:id="absent"/>')["word/document.xml"]
    if invalid_kind == "style":
        body = _parts('<w:pStyle w:val="Missing"/>')["word/document.xml"]
    if invalid_kind == "numbering":
        body = _parts('<w:numPr><w:numId w:val="99"/></w:numPr>')["word/document.xml"]
    monkeypatch.setattr(package, "construire_document_xml_compat", lambda *args: body)
    replace = Mock(side_effect=AssertionError("invalid package replaced destination"))
    monkeypatch.setattr(os, "replace", replace)
    document = Document()
    before = pickle.dumps(document)

    with pytest.raises(ValueError, match="invalid-ooxml-package"):
        package.ecrire_docx(document, target)

    replace.assert_not_called()
    assert pickle.dumps(document) == before
    assert target.read_bytes() == b"preserved bytes" if existing else not target.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ([target.name] if existing else [])


def test_atomic_success_is_validated_in_same_parent_and_preserves_mode(tmp_path, monkeypatch):
    target = tmp_path / "destination.docx"
    target.write_bytes(b"old")
    target.chmod(0o640)
    validate = package.valider_package_ooxml
    validated = []

    def inspect(path, *args, **kwargs):
        validated.append(Path(path))
        assert Path(path).parent.parent == target.parent
        assert target.read_bytes() == b"old"
        return validate(path, *args, **kwargs)

    monkeypatch.setattr(package, "valider_package_ooxml", inspect)
    package.ecrire_docx(Document(), target)
    assert len(validated) == 1 and not validated[0].exists()
    assert target.stat().st_mode & 0o777 == 0o640
    assert validate(target) == []


def test_zip_write_failure_preserves_existing_file_and_cleans_temporary_directory(tmp_path, monkeypatch):
    target = tmp_path / "destination.docx"
    target.write_bytes(b"keep me")
    monkeypatch.setattr(zipfile.ZipFile, "writestr", Mock(side_effect=OSError("disk write failed")))
    with pytest.raises(OSError, match="disk write failed"):
        package.ecrire_docx(Document(), target)
    assert target.read_bytes() == b"keep me"
    assert [path.name for path in tmp_path.iterdir()] == [target.name]


def test_validator_failure_preserves_existing_file(tmp_path, monkeypatch):
    target = tmp_path / "destination.docx"
    target.write_bytes(b"keep me")
    monkeypatch.setattr(package, "valider_package_ooxml", Mock(side_effect=RuntimeError("validation failed")))
    with pytest.raises(RuntimeError, match="validation failed"):
        package.ecrire_docx(Document(), target)
    assert target.read_bytes() == b"keep me"
    assert [path.name for path in tmp_path.iterdir()] == [target.name]


def _native_document():
    bbox = BBox(*(pt_vers_emu(v) for v in (20, 20, 160, 32)))
    span = Span("Auditable text", FontRef("Source", "Arial", False, False), 12, "000000", bbox=bbox, source_id="span")
    line = Line(bbox, [span], bbox.hauteur, bbox.largeur, source_id="line")
    text = TextBox(bbox, [line], source_id="text", semantic_role="caption")
    return Document([Page(7, pt_vers_emu(300), pt_vers_emu(200), [text])])


def test_internal_manifest_exports_canonical_sources_decisions_options_and_incomplete_mapping(tmp_path):
    document = _native_document()
    document.source_pdf_id = "source-pdf"
    plan = build_document_render_plan(document)
    options = {"include_scene_manifest": True}
    before = pickle.dumps((document, plan, options))
    target = tmp_path / "manifest.docx"
    package.ecrire_docx(document, target, native_rewriter=True, render_plan=plan, package_options=options)
    with zipfile.ZipFile(target) as archive:
        manifest = json.loads(archive.read("pdfexact/render-manifest.json"))
    assert manifest["pages"]["7"][0]["element_id"] == "text"
    assert manifest["pages"]["7"][0]["reason_codes"]
    assert manifest["pages"]["7"][0]["decision"]["element_id"] == "text"
    assert manifest["document"]["source_pdf_id"] == "source-pdf"
    assert {"text", "line", "span"} <= set(manifest["sources"])
    assert manifest["analysis_options"]["target_reader"] == plan.options.target_reader
    assert manifest["provenance"] == {"status": "incomplete", "reason": "xml-source-mapping-unavailable"}
    assert pickle.dumps((document, plan, options)) == before
    assert package.valider_package_ooxml(target) == []


def test_strict_provenance_refuses_unavailable_upstream_xml_mapping(tmp_path):
    document = _native_document()
    plan = build_document_render_plan(document)
    target = tmp_path / "preserved.docx"
    target.write_bytes(b"keep me")
    with pytest.raises(ValueError, match="xml-source-mapping-unavailable"):
        package.ecrire_docx(document, target, native_rewriter=True, render_plan=plan,
                            package_options={"strict_provenance": True})
    assert target.read_bytes() == b"keep me"


def test_media_aliases_share_payload_and_manifest_retains_each_source(tmp_path):
    document = _native_document()
    page = document.pages[0]
    page.elements = [ImageEl(BBox(0, 0, 100, 100), name, source_id=name) for name in ("one", "two")]
    document.media = {
        name: MediaItem(name, b"same-image", "png", source_ids=(f"{name}-source",))
        for name in ("one", "two")
    }
    before = pickle.dumps(document)
    target = tmp_path / "deduplicated.docx"
    package.ecrire_docx(document, target, package_options=PackageOptions(include_scene_manifest=True))
    with zipfile.ZipFile(target) as archive:
        assert len([name for name in archive.namelist() if name.startswith("word/media/")]) == 1
        manifest = json.loads(archive.read("pdfexact/render-manifest.json"))
        root = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        assert len({node.get("Target") for node in root if node.get("Type") == f"{R}/image"}) == 1
    assert {source for entry in manifest["media"] for source in entry["source_ids"]} == {"one-source", "two-source"}
    assert pickle.dumps(document) == before


def test_manifest_media_hash_detects_modified_payload(tmp_path):
    parts = _parts()
    parts["word/media/one.png"] = b"changed"
    parts["pdfexact/render-manifest.json"] = json.dumps({
        "schema_version": 1, "provenance": {"status": "incomplete", "reason": "render-plan-unavailable"},
        "pages": {}, "sources": {}, "media": [{"part": "word/media/one.png", "sha256": "wrong"}],
    })
    errors = package.valider_package_ooxml(_archive(tmp_path, parts))
    assert "manifest-media-mismatch:word/media/one.png" in errors


def test_source_media_content_hash_mismatch_preserves_destination(tmp_path):
    document = Document(media={"one": MediaItem("one", b"actual bytes", "png", content_hash="wrong")})
    target = tmp_path / "preserved.docx"
    target.write_bytes(b"keep me")
    with pytest.raises(ValueError, match="source-media-hash-mismatch"):
        package.ecrire_docx(document, target)
    assert target.read_bytes() == b"keep me"


def test_manifest_duplicate_json_keys_are_rejected(tmp_path):
    parts = _parts()
    parts["pdfexact/render-manifest.json"] = '{"schema_version":1,"schema_version":1,"provenance":{"status":"incomplete"},"pages":{},"sources":{},"media":[]}'
    assert "invalid-render-manifest" in package.valider_package_ooxml(_archive(tmp_path, parts))


def test_manifest_cannot_claim_unknown_source_or_cross_page_target(tmp_path):
    parts = _parts()
    parts["pdfexact/render-manifest.json"] = json.dumps({
        "schema_version": 1, "provenance": {"status": "incomplete", "reason": "xml-source-mapping-unavailable"},
        "pages": {"7": [{"element_id": "output", "source_ids": ["absent"], "reason_codes": ["retained"]}]},
        "sources": {"source": {"element_id": "source", "page_index": 2, "coverage": {
            "relationship": "transformed", "target_ids": ["output"], "reason": "retained",
        }}}, "media": [],
    })
    errors = package.valider_package_ooxml(_archive(tmp_path, parts))
    assert any("absent" in error for error in errors)
    assert any("source" in error for error in errors)


def test_manifest_coverage_relationship_must_use_canonical_api_values(tmp_path):
    parts = _parts()
    parts["pdfexact/render-manifest.json"] = json.dumps({
        "schema_version": 1, "provenance": {"status": "incomplete", "reason": "xml-source-mapping-unavailable"},
        "pages": {"7": [{"element_id": "output", "source_ids": ["source"], "reason_codes": ["retained"]}]},
        "sources": {"source": {"element_id": "source", "page_index": 7, "coverage": {
            "relationship": "untraceable", "target_ids": ["output"], "reason": "retained",
        }}}, "media": [],
    })
    errors = package.valider_package_ooxml(_archive(tmp_path, parts))
    assert "unknown-manifest-coverage-relationship:source" in errors


def test_font_embedding_can_be_disabled_without_mutating_source_assets(tmp_path, monkeypatch):
    forbidden = Mock(side_effect=AssertionError("font embedding disabled"))
    monkeypatch.setattr(package, "_table_polices_xml", forbidden)
    document = _native_document()
    before = pickle.dumps(document)
    target = tmp_path / "fonts-disabled.docx"
    package.ecrire_docx(document, target, package_options={"embed_fonts": False})
    forbidden.assert_not_called()
    with zipfile.ZipFile(target) as archive:
        assert "word/fontTable.xml" not in archive.namelist()
    assert pickle.dumps(document) == before


def test_validation_cannot_be_disabled_for_atomic_publication(tmp_path):
    target = tmp_path / "absent.docx"
    with pytest.raises(ValueError, match="package-validation-required"):
        package.ecrire_docx(Document(), target, package_options=PackageOptions(validate_xml=False))
    assert not target.exists()


def test_identical_fonts_share_embedded_payload_but_keep_family_names_and_sources(tmp_path):
    from pdfexact.ir import FontAsset

    source = tmp_path / "source.ttf"
    source.write_bytes(b"font contents" * 8)
    document = Document()
    document.polices = {
        name: FontAsset(name, family, None, "ttf", False, chemin=source, reconnue=True)
        for name, family in (("First-Regular", 'First "Quoted" Family'), ("Second-Regular", "Second"))
    }
    before = pickle.dumps(document)
    target = tmp_path / "fonts.docx"
    package.ecrire_docx(document, target, package_options={"include_scene_manifest": True})
    with zipfile.ZipFile(target) as archive:
        assert len([name for name in archive.namelist() if name.startswith("word/fonts/")]) == 1
        fonts = ET.fromstring(archive.read("word/fontTable.xml"))
        assert {node.get(f"{{{W}}}name") for node in fonts} == {'First "Quoted" Family', "Second"}
        manifest = json.loads(archive.read("pdfexact/render-manifest.json"))
        assert set(next(iter(manifest["font_relations"].values()))) == {"First-Regular", "Second-Regular"}
    assert pickle.dumps(document) == before
