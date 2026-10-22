"""Composition des placements bitmap en objets visuels.

Les ressources PDF ne correspondent pas toujours aux objets visibles. Les
logiciels de mise en page decoupent frequemment une vignette en plusieurs
images contigues, ou ajoutent une bande de controle a une image principale.
Cette etape conserve les placements sources pour l'audit, mais produit un seul
objet visuel pour le renderer lorsque la geometrie prouve qu'ils forment une
composition continue.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image

from pdfexact.geometry import BBox, PageGeometry
from pdfexact.ir import ImageEl, MediaItem, RasterEl


@dataclass(frozen=True)
class _PlacementInfo:
    index: int
    element: ImageEl
    source_size: tuple[int, int] | None


def _area(box: BBox) -> int:
    return max(0, box.x1 - box.x0) * max(0, box.y1 - box.y0)


def _overlap_ratio(left: BBox, right: BBox) -> float:
    x0 = max(left.x0, right.x0)
    y0 = max(left.y0, right.y0)
    x1 = min(left.x1, right.x1)
    y1 = min(left.y1, right.y1)
    overlap = max(0, x1 - x0) * max(0, y1 - y0)
    return overlap / max(min(_area(left), _area(right)), 1)


def _union(left: BBox, right: BBox) -> BBox:
    return BBox(
        min(left.x0, right.x0),
        min(left.y0, right.y0),
        max(left.x1, right.x1),
        max(left.y1, right.y1),
    )


def _axis_gap(left: BBox, right: BBox) -> tuple[int, int]:
    return (
        max(0, max(left.x0, right.x0) - min(left.x1, right.x1)),
        max(0, max(left.y0, right.y0) - min(left.y1, right.y1)),
    )


def _source_dimensions(media: dict, media_ref: str) -> tuple[int, int] | None:
    item = media.get(media_ref)
    if item is None:
        return None
    try:
        with Image.open(BytesIO(item.donnees)) as image:
            return int(image.width), int(image.height)
    except Exception:  # noqa: BLE001 - an unreadable resource remains independent
        return None


def _is_thin_fragment(info: _PlacementInfo) -> bool:
    box = info.element.bbox
    placement_ratio = min(box.largeur, box.hauteur) / max(box.largeur, box.hauteur, 1)
    if placement_ratio <= 0.16:
        return True
    if info.source_size is None:
        return False
    width, height = info.source_size
    return min(width, height) / max(width, height, 1) <= 0.16


def _same_slice_family(left: _PlacementInfo, right: _PlacementInfo) -> bool:
    """Recognize repeated slices without depending on a document or XRef name."""
    if left.source_size is None or right.source_size is None:
        return False
    lw, lh = left.source_size
    rw, rh = right.source_size
    return abs(lw - rw) / max(lw, rw, 1) <= 0.08 and abs(lh - rh) / max(lh, rh, 1) <= 0.08


def _can_join(left: _PlacementInfo, right: _PlacementInfo) -> bool:
    if left.element.paint_group_id != right.element.paint_group_id:
        return False
    left_box, right_box = left.element.bbox, right.element.bbox
    gap_x, gap_y = _axis_gap(left_box, right_box)
    x_overlap = _overlap_ratio(
        BBox(left_box.x0, 0, left_box.x1, 1),
        BBox(right_box.x0, 0, right_box.x1, 1),
    )
    y_overlap = _overlap_ratio(
        BBox(0, left_box.y0, 1, left_box.y1),
        BBox(0, right_box.y0, 1, right_box.y1),
    )
    thin = _is_thin_fragment(left) or _is_thin_fragment(right)
    same_family = _same_slice_family(left, right)
    # Overlapping full images are independent paint layers, not image slices.
    if not thin and _overlap_ratio(left_box, right_box) > 0.10:
        return False

    # A strip attached to an image must share the corresponding axis and be
    # effectively contiguous. This handles masks, caps and header strips.
    if thin and gap_x <= 4 * 12700 and gap_y <= 4 * 12700:
        # Do not attach a thin image resource to a page-sized background merely
        # because the background happens to overlap it. The partner must have
        # a comparable extent on the shared axis, as a real fragment does.
        if left_box.largeur >= right_box.largeur:
            width_ratio = right_box.largeur / max(left_box.largeur, 1)
        else:
            width_ratio = left_box.largeur / max(right_box.largeur, 1)
        if left_box.hauteur >= right_box.hauteur:
            height_ratio = right_box.hauteur / max(left_box.hauteur, 1)
        else:
            height_ratio = left_box.hauteur / max(right_box.hauteur, 1)
        comparable_axis = (
            (x_overlap >= 0.65 and width_ratio >= 0.55)
            or (y_overlap >= 0.65 and height_ratio >= 0.55)
        )
        return comparable_axis

    # Repeated equal-sized slices are recognized only when they are aligned and
    # nearly touching. This avoids merging independent thumbnails separated by
    # normal layout spacing.
    if same_family and gap_y <= 2.5 * 12700 and x_overlap >= 0.82:
        return True
    if same_family and gap_x <= 2.5 * 12700 and y_overlap >= 0.82:
        return True
    return False


def _components(infos: list[_PlacementInfo]) -> list[list[_PlacementInfo]]:
    parent = list(range(len(infos)))

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def join(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left_index, left in enumerate(infos):
        for right_index in range(left_index + 1, len(infos)):
            if _can_join(left, infos[right_index]):
                join(left_index, right_index)

    groups: dict[int, list[_PlacementInfo]] = {}
    for index, info in enumerate(infos):
        groups.setdefault(find(index), []).append(info)
    return list(groups.values())


def _is_composition(group: list[_PlacementInfo], geometry: PageGeometry) -> bool:
    if len(group) < 2:
        return False
    sequences = [info.element.z_index for info in group]
    if all(sequence is not None for sequence in sequences):
        if max(sequences) - min(sequences) != len(sequences) - 1:
            return False
    union = group[0].element.bbox
    for info in group[1:]:
        union = _union(union, info.element.bbox)
    page_area = geometry.largeur_emu * geometry.hauteur_emu
    # A composition cannot silently become a whole-page screenshot. Large
    # page backgrounds remain independent and preserve their original media.
    if _area(union) > page_area * 0.30:
        return False
    return any(_is_thin_fragment(info) for info in group) or all(
        _same_slice_family(group[0], info) for info in group[1:]
    )


def composer_placements_visuels(
    page,
    elements: list[ImageEl],
    media: dict,
    geometry: PageGeometry,
    dpi: int = 240,
) -> list[ImageEl | RasterEl]:
    """Replace only proven contiguous image fragments with local composites.

    The original placements are kept in ``RasterEl.source_placements`` and
    ``source_xrefs``. The visible renderer receives one local raster for a
    composed region, preventing duplicate frames and diagnostic bboxes while
    preserving the page appearance and the canonical page coordinates.
    """
    infos = [
        _PlacementInfo(index, element, _source_dimensions(media, element.media_ref))
        for index, element in enumerate(elements)
    ]
    grouped: dict[int, list[_PlacementInfo]] = {}
    for group in _components(infos):
        if _is_composition(group, geometry):
            for info in group:
                grouped[info.index] = group

    output: list[ImageEl | RasterEl] = []
    emitted: set[int] = set()
    from pdfexact.fallback.rasterize import rasteriser_region

    for index, element in enumerate(elements):
        group = grouped.get(index)
        if group is None:
            output.append(element)
            continue
        if id(group) in emitted:
            continue
        emitted.add(id(group))
        union = group[0].element.bbox
        for info in group[1:]:
            union = _union(union, info.element.bbox)
        source_placements = tuple(
            info.element.placement_id or info.element.media_ref for info in group
        )
        source_xrefs = tuple(
            info.element.source_xref
            for info in group
            if info.element.source_xref is not None
        )
        sequences = [info.element.z_index for info in group]
        if all(sequence is not None for sequence in sequences):
            # Compose extracted RGBA placements, not a page screenshot that
            # could bake editable text or unrelated foreground paint into them.
            scale = dpi / (72 * 12700)
            canvas = Image.new("RGBA", (max(1, round(union.largeur * scale)), max(1, round(union.hauteur * scale))))
            for info in sorted(group, key=lambda info: info.element.z_index):
                box = info.element.bbox
                with Image.open(BytesIO(media[info.element.media_ref].donnees)) as source:
                    image = source.convert("RGBA").resize((max(1, round(box.largeur * scale)), max(1, round(box.hauteur * scale))))
                canvas.alpha_composite(image, (round((box.x0 - union.x0) * scale), round((box.y0 - union.y0) * scale)))
            stream = BytesIO()
            canvas.save(stream, format="PNG")
            media_ref = f"composition_p{page.number}_paint{min(sequences)}"
            media[media_ref] = MediaItem(media_ref, stream.getvalue(), "png")
            composite = RasterEl(union, media_ref, purpose="image-placement-composition", z_index=min(sequences))
        else:
            composite = rasteriser_region(
                page,
                union,
                media,
                dpi=dpi,
                purpose="image-placement-composition",
            )
        composite.source_placements = source_placements
        composite.source_xrefs = source_xrefs
        output.append(composite)
    return output
