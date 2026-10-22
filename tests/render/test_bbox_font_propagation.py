from dataclasses import replace
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
import zipfile

from fontTools.ttLib import TTFont
import pytest

from pdfexact.geometry import BBox, pt_vers_emu
from pdfexact.ir import Document, FontAsset, FontRef, Line, Page, Span, TextBox
from pdfexact.render.bbox_debug import (
    fill_existing_bbox_docx_with_native_paragraphs,
    write_bbox_only_docx,
)
from pdfexact.render.fonts_embed import obfusquer_police


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
RELS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
FONT = Path(__file__).parents[2] / "pdfexact/fonts/DejaVuSans.ttf"


def _document(asset):
    bbox = BBox(pt_vers_emu(40), pt_vers_emu(60), pt_vers_emu(200), pt_vers_emu(80))
    line = Line(
        bbox,
        [Span("Editable native text", FontRef(asset.font_id, asset.famille, False, False), 10, "000000")],
        bbox.hauteur,
        bbox.largeur,
    )
    return Document(
        pages=[Page(0, pt_vers_emu(400), pt_vers_emu(500), [TextBox(bbox, [line])])],
        polices={asset.font_id: asset},
    )


def _asset(path=FONT):
    return FontAsset("OpaqueSource", "Resolved Sans", b"raw source CFF, not a Word font", "cff", True, chemin=path, reconnue=True)


def _embedded_fonts(path):
    with zipfile.ZipFile(path) as archive:
        table = ElementTree.fromstring(archive.read("word/fontTable.xml"))
        rels = ElementTree.fromstring(archive.read("word/_rels/fontTable.xml.rels"))
        targets = {rel.get("Id"): rel.get("Target") for rel in rels}
        result = {}
        for font in table:
            for style in font:
                result[(font.get(W + "name"), style.tag.removeprefix(W))] = obfusquer_police(
                    archive.read("word/" + targets[style.get(R + "id")]), style.get(W + "fontKey")
                )
        document_rels = ElementTree.fromstring(archive.read("word/_rels/document.xml.rels"))
        assert any(rel.get("Target") == "fontTable.xml" and rel.get("Type") == R[1:-1] + "/fontTable" for rel in document_rels)
        assert all(rel.tag == RELS + "Relationship" for rel in rels)
        return result


@pytest.mark.parametrize("embedding_rights", [0, 4, 8, 0x100])
def test_bbox_skeleton_embeds_resolved_sfnt_without_changing_rights_or_source_cff(
    tmp_path, embedding_rights
):
    resolved = tmp_path / "resolved.ttf"
    with TTFont(FONT) as font:
        font["OS/2"].fsType = embedding_rights
        font.save(resolved)
    asset = _asset(resolved)
    document = _document(asset)
    path = tmp_path / "skeleton.docx"

    write_bbox_only_docx(document, path)

    embedded = _embedded_fonts(path)
    assert list(embedded) == [("Resolved Sans", "embedRegular")]
    data = embedded[("Resolved Sans", "embedRegular")]
    assert data == resolved.read_bytes()
    assert data != asset.donnees
    with TTFont(BytesIO(data)) as font:
        assert font["OS/2"].fsType == embedding_rights
        assert "glyf" in font
    assert document.polices == {asset.font_id: asset}


def test_bbox_skeleton_deduplicates_alias_family_and_preserves_distinct_styles(tmp_path):
    regular = _asset()
    document = _document(regular)
    alias = replace(regular, font_id="SecondSource")
    bold = replace(regular, font_id="ThirdSource-Bold", chemin=FONT.with_name("DejaVuSans-Bold.ttf"))
    document.polices.update({alias.font_id: alias, bold.font_id: bold})
    path = tmp_path / "aliases.docx"

    write_bbox_only_docx(document, path)

    embedded = _embedded_fonts(path)
    assert set(embedded) == {("Resolved Sans", "embedRegular"), ("Resolved Sans", "embedBold")}
    assert embedded[("Resolved Sans", "embedRegular")] == FONT.read_bytes()
    assert embedded[("Resolved Sans", "embedBold")] == bold.chemin.read_bytes()


def test_raw_cff_without_resolved_word_font_is_not_mislabeled_as_sfnt(tmp_path):
    path = tmp_path / "unresolved.docx"

    write_bbox_only_docx(_document(replace(_asset(), chemin=None, reconnue=False)), path)

    with zipfile.ZipFile(path) as archive:
        assert not any(name.startswith("word/fonts/") for name in archive.namelist())


def test_native_fill_keeps_skeleton_font_table_relationships_and_binaries(tmp_path):
    document = _document(_asset())
    skeleton = tmp_path / "skeleton.docx"
    filled = tmp_path / "filled.docx"
    write_bbox_only_docx(document, skeleton)

    fill_existing_bbox_docx_with_native_paragraphs(skeleton, document, filled)

    assert _embedded_fonts(filled) == _embedded_fonts(skeleton)
    with zipfile.ZipFile(skeleton) as before, zipfile.ZipFile(filled) as after:
        for name in before.namelist():
            if name.startswith("word/fonts/") or "fontTable" in name:
                assert after.read(name) == before.read(name)
        root = ElementTree.fromstring(after.read("word/document.xml"))
        assert "Editable native text" in "".join(node.text or "" for node in root.iter(W + "t"))
