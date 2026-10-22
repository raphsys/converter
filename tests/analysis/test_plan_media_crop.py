from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from io import BytesIO

from PIL import Image
import pytest

from pdfexact.analysis.options import AnalysisOptions
from pdfexact.analysis.provenance import Evidence
from pdfexact.fallback.rasterize import segmenter_elements_visuels_page, verify_media_crop_partition
from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.ir import Document, ImageEl, MediaItem, Page, RasterEl
from pdfexact.render.render_plan import build_document_render_plan, build_page_render_plan, build_render_plan, build_scene_render_plan
from pdfexact.scene import capture_source_observations, record_source_transformation, scene_from_legacy_document


def cropped_document(element_type=ImageEl):
    image = Image.new("RGBA", (20, 30))
    image.putdata([
        ((x * 17) % 256, (y * 29) % 256, (x * y * 13) % 256, (x * 11 + y * 7) % 256)
        for y in range(image.height) for x in range(image.width)
    ])
    stream = BytesIO()
    image.save(stream, format="PNG")
    source = element_type(BBox(0, 0, u(200), u(200)), "source", source_id="source-image",
                          z_index=0, opacity=0.0, clip_bbox=BBox(u(10), u(15), u(190), u(185)),
                          clip_ids=("source-clip",))
    if isinstance(source, ImageEl):
        source.transform = (200.0, 0.0, 0.0, 200.0, 0.0, 0.0)
    page = Page(3, u(200), u(200), [source])
    media = {"source": MediaItem("source", stream.getvalue(), "png")}
    capture_source_observations(page, [source])
    outputs = segmenter_elements_visuels_page([source], media, page.largeur_emu, page.hauteur_emu)
    assert len(outputs) == 24
    proof = dict(outputs[0].evidence[-1].details)["proof"]
    assert verify_media_crop_partition(source, outputs, media, proof) == []
    record_source_transformation(page, [source], outputs, "source-media-segmentation", proof=proof)
    page.elements, page.discarded_elements = outputs, [source]
    return Document([page], media=media)


@pytest.mark.parametrize("builder", ["raw", "document", "page", "scene"])
@pytest.mark.parametrize("element_type", [ImageEl, RasterEl])
def test_measured_crop_partition_covers_parent_and_all_scheduled_tiles(builder, element_type):
    document = cropped_document(element_type)
    if builder == "raw":
        plan = build_render_plan(document)
    elif builder == "document":
        plan = build_document_render_plan(document)
    elif builder == "page":
        plan = build_page_render_plan(document.pages[0], document.pages[0].elements, document=document)
    else:
        plan = build_scene_render_plan(scene_from_legacy_document(document), media=document.media)
    assert plan.validate() == []
    assert plan.validate(document) == []
    assert len(plan.instructions_for_page(3)) == 24
    assert set(plan.source_coverage["source-image"].target_ids) == {
        instruction.element.source_id for instruction in plan.instructions_for_page(3)
    }
    assert plan.source_inventory["source-image"].verification_state.value == "detected"


@pytest.mark.parametrize("damage", ["absent", "flags-only", "gap", "overlap", "alpha", "clip", "z", "transform", "payload", "rehash-payload", "source-payload"])
def test_crop_consumer_recomputes_proof_against_actual_materialization(damage):
    document = cropped_document()
    plan = build_document_render_plan(document)
    assert plan.validate() == []
    instructions = plan.instructions_for_page(3)
    output = instructions[0].element
    proof = dict(output.evidence[-1].details)["proof"]
    if damage in {"absent", "flags-only"}:
        for instruction in instructions:
            instruction.element.evidence = [proof for proof in instruction.element.evidence if proof.kind != "media-crop-partition"]
            if damage == "flags-only":
                instruction.element.evidence.append(Evidence("media-crop-partition", "forged", None, (
                    ("proof", {"partition_verified": True, "pixel_equivalence_verified": True}),
                )))
    elif damage in {"gap", "overlap"}:
        for instruction in instructions:
            value = dict(instruction.element.evidence[-1].details)["proof"]
            bounds = value["outputs"][0]["pixel_bounds"]
            value["outputs"][0]["pixel_bounds"] = (bounds[0], bounds[1], bounds[2] - 1 if damage == "gap" else bounds[2] + 1, bounds[3])
    elif damage == "alpha":
        output.opacity = 1.0
    elif damage == "clip":
        output.clip_bbox = output.bbox
    elif damage == "z":
        output.z_index = 1
    elif damage == "transform":
        output.transform = (*output.transform[:4], output.transform[4] + 1, output.transform[5])
    elif damage == "source-payload":
        plan.media_snapshot["source"] = replace(plan.media_snapshot["source"], donnees=b"wrong source")
    else:
        item = plan.media_snapshot[output.media_ref]
        with Image.open(BytesIO(item.donnees)) as decoded:
            tile = decoded.convert("RGBA")
        tile.putpixel((0, 0), (255, 255, 255, 255))
        stream = BytesIO()
        tile.save(stream, format="PNG")
        payload = stream.getvalue()
        plan.media_snapshot[output.media_ref] = replace(item, donnees=payload)
        if damage == "rehash-payload":
            for instruction in instructions:
                value = dict(instruction.element.evidence[-1].details)["proof"]
                value["outputs"][0].update(payload_sha256=sha256(payload).hexdigest(), rgba_sha256=sha256(tile.tobytes()).hexdigest())
    assert any(error.startswith("unverified-media-crop:source-image:") for error in plan.validate())


def test_crop_validation_uses_current_document_media_not_its_snapshot():
    document = cropped_document()
    plan = build_document_render_plan(document)
    assert plan.validate(document) == []
    tile = document.pages[0].elements[0]
    document.media[tile.media_ref] = replace(document.media[tile.media_ref], donnees=b"changed after compilation")
    assert plan.validate() == []
    assert any("unverified-media-crop:source-image:" in error for error in plan.validate(document))


def test_crop_validation_is_pure_and_does_not_require_raster_fallback_for_native_images():
    document = cropped_document()
    plan = build_document_render_plan(document, AnalysisOptions(allow_local_raster_fallback=False))
    before = deepcopy((plan.source_inventory, plan.source_coverage, plan.media_snapshot, document))
    assert plan.validate(document) == plan.validate() == []
    assert (plan.source_inventory, plan.source_coverage, plan.media_snapshot, document) == before
