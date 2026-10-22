"""Collective crop proofs compare acquired pixels, not trusted aliases/flags."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from io import BytesIO

import pymupdf
import pytest
from PIL import Image

from pdfexact.extract.document import _securiser_elements_visuels_page
from pdfexact.fallback.rasterize import verify_media_crop_partition
from pdfexact.geometry import BBox, pt_vers_emu
from pdfexact.ir import Document, FontRef, ImageEl, Line, MediaItem, Page, RasterEl, Span, TextBox
from pdfexact.scene import capture_source_observations, scene_from_legacy_document


def _png(image):
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _pixels(size=(17, 19), mode="RGBA"):
    image = Image.new("RGBA", size)
    image.putdata([((x * 31) % 256, (y * 47) % 256, (x + y) % 256, (x * y * 13) % 256)
                   for y in range(size[1]) for x in range(size[0])])
    return image.convert(mode)


def _case(size=(17, 19), *, raster=False, mode="RGBA", clipped=False):
    box = BBox(0, 0, pt_vers_emu(200), pt_vers_emu(300))
    common = dict(source_id="acquired-image", source_kind="pdf-native", z_index=0, opacity=0.0,
                  clip_ids=("clip-A",), paint_group_id="paint-A", parent_group_id="parent-A",
                  compositing={"blend_mode": "Normal", "group": {"isolated": True}},
                  attributes={"acquired-observation": {"keep": True}}, decision_history=[{"state": "detected"}])
    if clipped:
        common["clip_bbox"] = BBox(pt_vers_emu(20), pt_vers_emu(40), pt_vers_emu(175), pt_vers_emu(280))
    if raster:
        source = RasterEl(box, "source", source_component_ids=("raw-vector",), source_placements=("placement-A",),
                          source_xrefs=(7,), paint_sequences=(0,), fallback_reason="actual-vector-fallback", **common)
    else:
        source = ImageEl(box, "source", placement_id="placement-A", source_xref=7,
                         quad=((box.x0, box.y0), (box.x1, box.y0), (box.x1, box.y1), (box.x0, box.y1)),
                         transform=(200.0, 0.0, 0.0, 300.0, 0.0, 0.0), **common)
    source.alpha = 0.0
    media = {"source": MediaItem("source", _png(_pixels(size, mode)), "png", dpi=(144, 144))}
    page = Page(0, box.x1, box.y1, [source])
    return source, page, media


def _partition(**kwargs):
    source, page, media = _case(**kwargs)
    _securiser_elements_visuels_page(page, media)
    proof = next(event["proof"] for event in page.source_transformations if event["reason_code"] == "source-media-segmentation")
    return source, page, media, proof


@pytest.mark.parametrize("mode", ["RGBA", "RGB", "L", "P"])
def test_partition_recomposes_actual_rgba_and_keeps_acquired_source(mode):
    source, page, media, proof = _partition(mode=mode)
    assert len(page.elements) == 24
    assert proof["schema"] == "media-crop-partition-v1"
    assert proof["source"]["mode"] == mode
    assert proof["partition_verified"] is True and proof["pixel_equivalence_verified"] is True
    assert proof["reasons"] == []
    assert verify_media_crop_partition(page.source_inventory[source.source_id], page.elements, media, proof) == []
    assert source in page.discarded_elements
    assert page.source_inventory[source.source_id].bbox == source.bbox
    assert page.source_inventory[source.source_id].quad == source.quad
    assert media["source"].donnees == proof["source"]["payload"]
    canvas = Image.new("RGBA", (17, 19))
    for tile, entry in zip(page.elements, proof["outputs"]):
        decoded = Image.open(BytesIO(media[tile.media_ref].donnees))
        bounds = entry["pixel_bounds"]
        canvas.paste(decoded, bounds[:2])
        item = media[tile.media_ref]
        assert (item.native_width, item.native_height, item.color_mode) == (decoded.width, decoded.height, "RGBA")
        assert item.alpha is True and item.content_hash == entry["payload_sha256"]
        assert item.dpi == (144, 144) and item.media_kind == "composite-crop"
    original = Image.open(BytesIO(media["source"].donnees)).convert("RGBA")
    assert canvas.tobytes() == original.tobytes()
    if mode == "RGBA":
        assert canvas.getpixel((3, 0)) == (93, 0, 3, 0)


@pytest.mark.parametrize("size", [(1, 1), (1, 19), (17, 1), (2, 3), (3, 5), (4, 6)])
def test_tiny_media_partition_has_no_forced_pixel_overlap(size):
    source, page, media, proof = _partition(size=size)
    assert verify_media_crop_partition(source, page.elements, media, proof) == []
    assert sum(entry["width"] * entry["height"] for entry in proof["outputs"]) == size[0] * size[1]


@pytest.mark.parametrize("missing", ["element", "payload", "proof-entry"])
def test_missing_tile_cannot_be_covered_by_parent_source_alias(missing):
    source, page, media, proof = _partition()
    if missing == "element":
        page.elements.pop(0)
    elif missing == "payload":
        media.pop(page.elements[0].media_ref)
    else:
        proof["outputs"].pop(0)
    errors = verify_media_crop_partition(source, page.elements, media, proof)
    assert errors
    assert any("output-set" in error or "output-payload" in error or "pixel-hole" in error for error in errors)


@pytest.mark.parametrize("tamper", ["bytes", "rehash", "resize", "source"])
def test_payload_tampering_is_recomputed_even_with_verified_flags(tamper):
    source, page, media, proof = _partition()
    tile = page.elements[0]
    ref = "source" if tamper == "source" else tile.media_ref
    image = Image.open(BytesIO(media[ref].donnees)).convert("RGBA")
    if tamper == "resize":
        image = image.resize((image.width + 1, image.height))
    else:
        image.putpixel((0, 0), (255, 0, 255, 0))
    payload = _png(image)
    media[ref] = replace(media[ref], donnees=payload)
    if tamper == "rehash":
        proof["outputs"][0].update(payload_sha256=sha256(payload).hexdigest(), rgba_sha256=sha256(image.tobytes()).hexdigest())
    errors = verify_media_crop_partition(source, page.elements, media, proof)
    assert errors
    if tamper == "rehash":
        assert "media-crop-rgba-reconstruction-mismatch" in errors
    elif tamper == "resize":
        assert "media-crop-output-dimensions-mode-mismatch" in errors
    else:
        assert any("payload-mismatch" in error for error in errors)


@pytest.mark.parametrize("change", ["hole", "overlap"])
def test_partition_bounds_are_exhaustive_and_nonoverlapping(change):
    source, page, media, proof = _partition()
    bounds = list(proof["outputs"][0]["pixel_bounds"])
    bounds[2] += -1 if change == "hole" else 1
    proof["outputs"][0]["pixel_bounds"] = tuple(bounds)
    errors = verify_media_crop_partition(source, page.elements, media, proof)
    assert f"media-crop-pixel-{change}" in errors


def test_canonical_geometry_composes_transform_intersects_clip_preserves_zero_and_group():
    source, page, media, proof = _partition(clipped=True)
    first = page.elements[0]
    assert first.bbox == BBox(0, 0, round(source.bbox.largeur * 4 / 17), round(source.bbox.hauteur * 3 / 19))
    assert first.quad == ((first.bbox.x0, first.bbox.y0), (first.bbox.x1, first.bbox.y0),
                          (first.bbox.x1, first.bbox.y1), (first.bbox.x0, first.bbox.y1))
    assert first.transform == (200.0 * 4 / 17, 0.0, 0.0, 300.0 * 3 / 19, 0.0, 0.0)
    assert first.clip_bbox == BBox(pt_vers_emu(20), pt_vers_emu(40), first.bbox.x1, first.bbox.y1)
    for tile in page.elements:
        assert tile.alpha == tile.opacity == tile.z_index == 0
        assert tile.clip_ids == ("clip-A",) and tile.paint_group_id == "paint-A" and tile.parent_group_id == "parent-A"
        assert tile.attributes["crop_parent_id"] == source.source_id
        assert tile.placement_id == "placement-A" and tile.source_xref == 7
        assert tile.decision_history == page.source_inventory[source.source_id].decision_history
        assert tile.attributes["acquired-observation"] == {"keep": True}
    assert verify_media_crop_partition(source, page.elements, media, proof) == []
    source.compositing["group"]["isolated"] = False
    assert proof["source"]["geometry"]["compositing"]["group"]["isolated"] is True
    assert "media-crop-source-geometry-mismatch" in verify_media_crop_partition(source, page.elements, media, proof)


@pytest.mark.parametrize("field,value", [("z_index", 1), ("alpha", 1.0), ("opacity", 1.0),
                                         ("parent_group_id", "other"), ("clip_bbox", None),
                                         ("transform", (200, 0, 0, 300, 0, 0))])
def test_paint_or_geometry_tampering_is_not_a_valid_crop(field, value):
    source, page, media, proof = _partition(clipped=True)
    setattr(page.elements[0], field, value)
    assert "media-crop-output-geometry-mismatch" in verify_media_crop_partition(source, page.elements, media, proof)


def test_raster_tiles_keep_actual_upstream_component_ids_without_claiming_vector_equivalence():
    source, page, media, proof = _partition(raster=True, clipped=True)
    assert verify_media_crop_partition(source, page.elements, media, proof) == []
    for tile in page.elements:
        assert tile.source_component_ids == (source.source_id, "raw-vector")
        assert tile.source_placements == ("placement-A",) and tile.source_xrefs == (7,) and tile.paint_sequences == (0,)
        assert tile.fallback_reason == "actual-vector-fallback"
    assert proof["source"]["source_id"] == source.source_id
    assert proof["source"]["source_id"] != "raw-vector"


@pytest.mark.parametrize("ambiguous", ["rotate", "quad", "flattened-clip"])
def test_ambiguous_pixel_to_page_mapping_retains_source_with_explicit_reason(ambiguous):
    source, page, media = _case()
    if ambiguous == "rotate":
        source.transform = (0, 200, -300, 0, 300, 0)
    elif ambiguous == "quad":
        source.quad = ((0, 1), *source.quad[1:])
    else:
        source.transform = (400, 0, 0, 300, 0, 0)
    _securiser_elements_visuels_page(page, media)
    assert page.elements == [source] and not page.discarded_elements and not page.source_transformations
    assert source.attributes["crop_unverified_reasons"][0].startswith("ambiguous-")
    assert not source.evidence


def test_previously_inpainted_payload_is_not_acquired_source_equivalence():
    source, page, media = _case()
    capture_source_observations(page, [source])
    media["inpainted"] = MediaItem("inpainted", _png(Image.new("RGBA", (17, 19), "white")), "png")
    source.media_ref = "inpainted"
    _securiser_elements_visuels_page(page, media)
    assert page.elements == [source] and not page.discarded_elements and not page.source_transformations
    assert "media-crop-source-identity-mismatch" in source.attributes["crop_unverified_reasons"]
    assert page.source_inventory[source.source_id].media_ref == "source"


@pytest.mark.parametrize("malformation", [None, {}, {"outputs": [None]}, {"outputs": [{"source_id": []}]},
                                         {"outputs": [{"source_id": "tile", "pixel_bounds": None}]}])
def test_malformed_proof_fails_closed_without_throwing(malformation):
    source, page, media, proof = _partition()
    broken = deepcopy(proof)
    if malformation is None or malformation == {}:
        broken = malformation
    else:
        broken.update(malformation)
    assert verify_media_crop_partition(source, page.elements, media, broken)


def test_native_text_and_stable_canonical_scene_identity_survive_segmentation():
    source, page, media = _case()
    font = FontRef("native", "Helvetica", False, False)
    box = BBox(10, 10, 100, 100)
    text = TextBox(box, [Line(box, [Span("Native remains native", font, 10.0, "000000")], 90, 90)], source_kind="pdf-native")
    page.elements.append(text)
    _securiser_elements_visuels_page(page, media)
    assert page.elements[-1] is text and text.lignes[0].spans[0].texte == "Native remains native"
    scene = scene_from_legacy_document(Document([page], media=media))
    active_ids = {element.source_id for element in page.elements}
    assert active_ids.issubset(scene.registry.elements)
    assert source.source_id in scene.registry.elements


