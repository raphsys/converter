"""Extraction des images bitmap.

Une même image peut être placée plusieurs fois. Elle n'est stockée qu'une fois dans
word/media/ et référencée autant de fois que nécessaire : c'est la différence entre un
docx de 2 Mo et un de 40 Mo.
"""
import hashlib
import warnings
from io import BytesIO

import pymupdf
from PIL import Image

from pdfexact.geometry import BBox, PageGeometry, bbox_depuis_rect, preserver_etat_page
from pdfexact.analysis.geometry import rect_area, rect_overlap_ratio
from pdfexact.ir import ImageEl, MediaItem, RasterEl
from pdfexact.extract.image_placement import (
    placement_metadata,
    probe_visible_bbox,
)
from pdfexact.extract.image_composition import composer_placements_visuels

EXTENSIONS_SUPPORTEES = {"png", "jpeg", "jpg"}
SEUIL_IMAGE_INLINE_PT2 = 1500.0


def _est_artefact_image(boite, dimensions: tuple[int, int] | None = None) -> bool:
    """Écarte les pseudo-images, sans supprimer les bandes bitmap réelles.

    La taille de placement ne suffit pas : certains PDF utilisent une vraie
    image de quelques pixels de large pour un filet blanc, une ombre ou un
    crédit vertical. Ces objets doivent rester disponibles pour la composition.
    Seules les ressources bitmap réellement dégénérées sont filtrées.
    """
    largeur_pt = boite.largeur / 12700.0
    hauteur_pt = boite.hauteur / 12700.0
    if dimensions is not None:
        source_largeur, source_hauteur = dimensions
        if source_largeur > 0 and source_hauteur > 0 and (
            source_largeur <= 2 or source_hauteur <= 2
        ):
            return True
        if largeur_pt < 4 or hauteur_pt < 4:
            return False
        if largeur_pt < 12 and hauteur_pt > 40:
            return False
    if largeur_pt < 4 or hauteur_pt < 4:
        return True
    if largeur_pt < 12 and hauteur_pt > 40:
        return True
    if hauteur_pt < 12 and largeur_pt > 150:
        return True
    return False


def _octets_et_extension(doc, xref, smask: int = 0) -> tuple[bytes, str]:
    """Retourne les octets de l'image, en la transcodant en PNG si le format est exotique."""
    extrait = doc.extract_image(xref)
    extension = extrait["ext"].lower()
    if extension in EXTENSIONS_SUPPORTEES:
        octets, extension = extrait["image"], extension
    else:
        # JPX, JBIG2, CCITT… : formats que Word ne sait pas lire. On repasse par un PNG.
        pixmap = pymupdf.Pixmap(doc, xref)
        if pixmap.n - pixmap.alpha >= 4:
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
        octets, extension = pixmap.tobytes("png"), "png"

    # Les masques PDF sont une propriete du placement/media, pas de la bbox.
    # PyMuPDF sait les combiner via Pixmap(base, mask) quand le PDF en fournit un.
    if smask:
        try:
            base_pixmap = pymupdf.Pixmap(doc, xref)
            mask_pixmap = pymupdf.Pixmap(doc, smask)
            octets = pymupdf.Pixmap(base_pixmap, mask_pixmap).tobytes("png")
            extension = "png"
        except Exception:  # noqa: BLE001
            pass
    # White is painted source content, not evidence of transparency. Only
    # the PDF's own alpha / soft mask may make resource pixels transparent.
    return octets, extension


def _bbox_image(rect, geometrie: PageGeometry | None = None):
    if geometrie is None:
        return bbox_depuis_rect(rect)
    return geometrie.bbox_depuis_rect_natif(rect)


def _graphic_paint_operations(page, *, recorded_groups: list[dict] | None = None) -> list[dict]:
    """Record independent graphics paint with its inherited clip/group stack."""
    if not hasattr(page, "this"):
        return []
    m = pymupdf.mupdf

    class ImageDevice(m.FzDevice2):
        def __init__(self):
            super().__init__()
            self.sequence = 0
            self.clips = []
            self.stack = []
            self.groups = []
            self.all_groups = []
            self.operations = []
            for name in (
                "fill_path", "stroke_path", "fill_text", "stroke_text", "ignore_text",
                "fill_shade", "fill_image", "fill_image_mask", "clip_path",
                "clip_stroke_path", "clip_text", "clip_stroke_text", "clip_image_mask", "pop_clip",
                "begin_group", "end_group",
            ):
                getattr(self, "use_virtual_" + name)()

        def paint(self, *args):
            for group in self.groups:
                group["unsupported_paint"] = True
            self.sequence += 1

        fill_shade = fill_image_mask = paint

        def text(self, *args):
            for group in self.groups:
                group["contains_text"] = True
            self.sequence += 1

        fill_text = stroke_text = ignore_text = text

        def push_clip(self, name, args, bounds):
            for group in self.groups:
                getattr(m, "fz_" + name)(group["device"], *args)
            self.clips.append((name, args, bounds))
            self.stack.append((name, args))

        def clip_path(self, ctx, path, even_odd, ctm, scissor):
            self.push_clip("clip_path", (
                m.FzPath(m.ll_fz_clone_path(path)), even_odd, m.FzMatrix(ctm), m.FzRect(scissor),
            ), pymupdf.Rect(m.ll_fz_bound_path(path, None, ctm)))

        def clip_stroke_path(self, ctx, path, stroke, ctm, scissor):
            self.push_clip("clip_stroke_path", (
                m.FzPath(m.ll_fz_clone_path(path)), m.FzStrokeState(m.ll_fz_keep_stroke_state(stroke)),
                m.FzMatrix(ctm), m.FzRect(scissor),
            ), pymupdf.Rect(m.ll_fz_bound_path(path, stroke, ctm)))

        def clip_text(self, ctx, text, ctm, scissor):
            self.push_clip("clip_text", (
                m.FzText(m.ll_fz_keep_text(text)), m.FzMatrix(ctm), m.FzRect(scissor),
            ), pymupdf.Rect(m.ll_fz_bound_text(text, None, ctm)))

        def clip_stroke_text(self, ctx, text, stroke, ctm, scissor):
            self.push_clip("clip_stroke_text", (
                m.FzText(m.ll_fz_keep_text(text)), m.FzStrokeState(m.ll_fz_keep_stroke_state(stroke)),
                m.FzMatrix(ctm), m.FzRect(scissor),
            ), pymupdf.Rect(m.ll_fz_bound_text(text, stroke, ctm)))

        def clip_image_mask(self, ctx, image, ctm, scissor):
            rect = pymupdf.Rect(0, 0, 1, 1) * pymupdf.Matrix(ctm.a, ctm.b, ctm.c, ctm.d, ctm.e, ctm.f)
            self.push_clip("clip_image_mask", (
                m.FzImage(m.ll_fz_keep_image(image)), m.FzMatrix(ctm), m.FzRect(scissor),
            ), rect)

        def pop_clip(self, *args):
            for group in self.groups:
                m.fz_pop_clip(group["device"])
            if self.clips:
                self.clips.pop()
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index][0] != "begin_group":
                    self.stack.pop(index)
                    break

        def begin_group(self, ctx, area, colorspace, isolated, knockout, blendmode, alpha):
            args = (
                m.FzRect(area), m.FzColorspace(m.ll_fz_keep_colorspace(colorspace)),
                isolated, knockout, blendmode, alpha,
            )
            for group in self.groups:
                m.fz_begin_group(group["device"], *args)
            display_list = m.FzDisplayList(m.FzRect(area))
            device = m.fz_new_list_device(display_list)
            for name, inherited in self.stack:
                getattr(m, "fz_" + name)(device, *inherited)
            m.fz_begin_group(device, *args)
            group = {
                "id": len(self.all_groups), "kind": "graphics_group", "args": args,
                "stack": list(self.stack), "clips": list(self.clips),
                "display_list": display_list, "device": device,
                "contains_text": False, "unsupported_paint": False,
                "sequences": [], "rect": None,
            }
            self.groups.append(group)
            self.all_groups.append(group)
            self.stack.append(("begin_group", args))

        def end_group(self, *args):
            for group in self.groups:
                m.fz_end_group(group["device"])
            group = self.groups.pop()
            device = group.pop("device")
            for name, _args in reversed(group["stack"]):
                if name == "begin_group":
                    m.fz_end_group(device)
                else:
                    m.fz_pop_clip(device)
            m.fz_close_device(device)
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index][0] == "begin_group":
                    self.stack.pop(index)
                    break

        def record(self, operation, painter):
            operation.update(seqno=self.sequence, clips=list(self.clips), stack=list(self.stack), groups=tuple(self.groups))
            for group in self.groups:
                painter(group["device"])
                group["sequences"].append(self.sequence)
                rect = pymupdf.Rect(operation["rect"])
                for _name, _args, clip in self.clips:
                    rect &= clip
                if not rect.is_empty:
                    group["rect"] = rect if group["rect"] is None else group["rect"] | rect
            display_list = m.FzDisplayList(m.FzRect(*operation["rect"]))
            device = m.fz_new_list_device(display_list)
            for name, args in self.stack:
                getattr(m, "fz_" + name)(device, *args)
            painter(device)
            for name, _args in reversed(self.stack):
                if name == "begin_group":
                    m.fz_end_group(device)
                else:
                    m.fz_pop_clip(device)
            m.fz_close_device(device)
            operation["display_list"] = display_list
            self.operations.append(operation)
            self.sequence += 1

        def path_paint(self, kind, path, stroke, even_odd, ctm, colorspace, color, alpha, params):
            path = m.FzPath(m.ll_fz_clone_path(path))
            stroke = m.FzStrokeState(m.ll_fz_keep_stroke_state(stroke)) if stroke else None
            ctm = m.FzMatrix(ctm)
            colorspace = m.FzColorspace(m.ll_fz_keep_colorspace(colorspace))
            params = m.FzColorParams(params)
            operation = {
                "kind": kind, "path": path, "stroke": stroke, "ctm": ctm,
                "rect": pymupdf.Rect(m.ll_fz_bound_path(path.m_internal, stroke.m_internal if stroke else None, ctm.internal())),
                "path_rect": pymupdf.Rect(m.ll_fz_bound_path(path.m_internal, None, ctm.internal())),
                "color": m.fz_convert_color(colorspace, color, m.fz_device_rgb(), m.FzColorspace(), params)[:3],
                "alpha": alpha, "even_odd": even_odd,
            }
            def painter(device):
                if stroke is None:
                    m.fz_fill_path(device, path, even_odd, ctm, colorspace, color, alpha, params)
                else:
                    m.fz_stroke_path(device, path, stroke, ctm, colorspace, color, alpha, params)
            self.record(operation, painter)

        def fill_path(self, ctx, path, even_odd, ctm, colorspace, color, alpha, params):
            self.path_paint("fill_path", path, None, even_odd, ctm, colorspace, color, alpha, params)

        def stroke_path(self, ctx, path, stroke, ctm, colorspace, color, alpha, params):
            self.path_paint("stroke_path", path, stroke, False, ctm, colorspace, color, alpha, params)

        def fill_image(self, ctx, image, ctm, alpha, params):
            matrix = pymupdf.Matrix(ctm.a, ctm.b, ctm.c, ctm.d, ctm.e, ctm.f)
            operation = {
                "kind": "fill_image",
                "rect": pymupdf.Rect(0, 0, 1, 1) * matrix,
                "matrix": matrix,
                "image": m.FzImage(m.ll_fz_keep_image(image)),
                "alpha": alpha,
                "params": m.FzColorParams(params),
            }
            self.record(operation, lambda device: m.fz_fill_image(
                device, operation["image"], m.FzMatrix(ctm), alpha, m.FzColorParams(params),
            ))

    device = ImageDevice()
    with preserver_etat_page(page):
        page.set_rotation(0)
        m.fz_run_page(page.this, device, m.FzMatrix(), m.FzCookie())
        m.fz_close_device(device)
    _assign_composite_groups(device.operations, device.all_groups)
    if recorded_groups is not None:
        recorded_groups.extend(device.all_groups)
    return device.operations


def _assign_composite_groups(operations, groups):
    covered = set()
    for group in groups:
        args = group["args"]
        effect = args[-1] != 1 or args[-2] != 0 or args[3]
        sequences = group["sequences"]
        if not effect or (sequences and all(sequence in covered for sequence in sequences)):
            continue
        if group["contains_text"]:
            group["limitation"] = "contains native text; exact group compositing is unsupported while keeping text editable"
        elif group["unsupported_paint"]:
            group["limitation"] = "contains unsupported graphics paint; exact group compositing is unsupported"
        elif not args[2] or args[-2] != 0:
            group["limitation"] = "requires a non-isolated or non-Normal backdrop; exact group compositing is unsupported"
        elif len(sequences) > 1 and group["rect"] is not None:
            group["seqno"] = min(sequences)
            for operation in operations:
                if group in operation["groups"]:
                    operation["composite_group"] = group
                    covered.add(operation["seqno"])




def _visible_paint_rect(operation, geometry):
    rect = pymupdf.Rect(operation["rect"])
    rect &= pymupdf.Rect(0, 0, geometry.largeur_pt, geometry.hauteur_pt) * geometry.derotation_matrix
    for _name, _args, bounds in operation["clips"]:
        rect &= bounds
    return rect


def _rectangular_fill(operation):
    if operation["kind"] != "fill_path" or not pymupdf.mupdf.fz_path_is_rect(operation["path"], operation["ctm"]):
        return False
    return all(
        name == "clip_path" and pymupdf.mupdf.fz_path_is_rect(args[0], args[2])
        for name, args, _bounds in operation["clips"]
    )


def _graphic_requires_raster(operation):
    if operation.get("composite_group") is not None:
        return True
    if any(name == "begin_group" and (args[-1] != 1 or args[-2] != 0) for name, args in operation["stack"]):
        return True
    if operation["clips"] and not _rectangular_fill(operation):
        # A full rectangular clip enclosing the graphic changes nothing.
        bounds = operation["rect"]
        return not all(
            name == "clip_path"
            and pymupdf.mupdf.fz_path_is_rect(args[0], args[2])
            and clip.contains(bounds)
            for name, args, clip in operation["clips"]
        )
    return bool(operation.get("even_odd") and not _rectangular_fill(operation))


def _render_image_paint(operation, geometry, rect, dpi=240):
    """Render one graphics operation, never unrelated page text, onto RGBA."""
    m = pymupdf.mupdf
    transform = geometry.rotation_matrix * pymupdf.Matrix(dpi / 72, dpi / 72)
    bounds = (rect * transform).irect
    pixmap = m.fz_new_pixmap_with_bbox(
        m.fz_device_rgb(), m.FzIrect(*bounds), m.FzSeparations(), 1,
    )
    m.fz_clear_pixmap(pixmap)
    device = m.fz_new_draw_device(m.FzMatrix(*tuple(transform)), pixmap)
    m.fz_run_display_list(operation["display_list"], device, m.FzMatrix(), m.FzRect(*rect), m.FzCookie())
    m.fz_close_device(device)
    return pymupdf.Pixmap(pixmap).tobytes("png")


def extraire_images(
    page, doc, media: dict, geometrie: PageGeometry | None = None
) -> list[ImageEl | RasterEl]:
    """Retourne les placements d'images de la page et enrichit le registre `media`.

    get_images() liste une entrée par référence dans les ressources de page, pas par
    image : une image placée deux fois y apparaît deux fois avec le même xref. Sans la
    déduplication ci-dessous, chaque placement serait compté une fois par entrée.
    """
    elements: list[ImageEl | RasterEl] = []
    geometrie_effective = geometrie or PageGeometry.depuis_page(page)
    groups = []
    graphics = _graphic_paint_operations(page, recorded_groups=groups)
    operations = [operation for operation in graphics if operation["kind"] == "fill_image"]
    for group in groups:
        if group.get("limitation"):
            warnings.warn(f"PDF transparency group on page {page.number}: {group['limitation']}", RuntimeWarning, stacklevel=2)
    placements_by_xref = {}
    if operations:
        # TextPage/get_image_info can omit translucent placements. Match the
        # actual native image objects, not a text-page visibility approximation.
        m = pymupdf.mupdf
        pdf = m.pdf_document_from_fz_document(doc.this)
        image_xrefs = {}
        for xref, _smask in {(entry[0], entry[1]) for entry in page.get_images(full=True)}:
            image = m.pdf_load_image(pdf, m.pdf_new_indirect(pdf, xref, 0))
            image_xrefs[image.m_internal_value()] = xref
        for operation in operations:
            xref = image_xrefs.get(operation["image"].m_internal_value())
            operation["source_xref"] = xref
            if xref is not None:
                placements_by_xref.setdefault(xref, []).append(operation)

    for xref, smask in sorted({(entree[0], entree[1]) for entree in page.get_images(full=True)}):
        media_ref = f"image{xref}"
        dimensions = None

        if media_ref not in media:
            try:
                extrait = doc.extract_image(xref)
                dimensions = (int(extrait.get("width", 0)), int(extrait.get("height", 0)))
                octets, extension = _octets_et_extension(doc, xref, smask=smask)
            except Exception:  # noqa: BLE001 — une image illisible ne doit pas tout arrêter
                continue
            media[media_ref] = MediaItem(
                media_ref=media_ref, donnees=octets, extension=extension
            )
        else:
            try:
                extrait = doc.extract_image(xref)
                dimensions = (int(extrait.get("width", 0)), int(extrait.get("height", 0)))
            except Exception:  # noqa: BLE001
                dimensions = None

        candidates = placements_by_xref.get(xref, [])
        placements = [(operation["rect"], operation["matrix"]) for operation in candidates] if candidates else page.get_image_rects(xref, transform=True)
        for placement_index, placement in enumerate(placements):
            if isinstance(placement, tuple):
                rect, matrix = placement
            else:
                rect, matrix = placement, None
            boite = _bbox_image(rect, geometrie)
            metadata = placement_metadata(page, xref, placement_index, rect, matrix, geometrie_effective)
            operation = candidates[placement_index] if placement_index < len(candidates) else None
            if operation is not None and operation.get("composite_group") is not None:
                continue
            # get_image_rects is the primary source. The rendered-page probe is only
            # allowed to replace it when the PDF matrix and the visible occurrence
            # disagree; ordinary and synthetic PDFs keep the exact native result.
            # Tiny decoration resources are not useful feature-match candidates;
            # skipping them also keeps the generic witness bounded on slide PDFs.
            probe_candidate = (
                operation is None
                and
                boite.largeur >= 20 * 12700
                and boite.hauteur >= 20 * 12700
                and not _est_artefact_image(boite, dimensions)
                and (
                    dimensions is None
                    or min(dimensions) >= 24
                )
            )
            if probe_candidate:
                visible = probe_visible_bbox(page, media[media_ref].donnees, geometrie_effective, boite)
                if visible is not None:
                    visible_bbox, confidence = visible
                    if confidence >= 0.35:
                        boite = visible_bbox
            placement_media_ref = media_ref
            clip_bbox = None
            if operation is not None:
                visible_rect = _visible_paint_rect(operation, geometrie_effective)
                if visible_rect.is_empty:
                    continue
                matrix = operation["matrix"]
                transformed = (
                    geometrie_effective.rotation != 0
                    or abs(matrix.b) > 1e-5 or abs(matrix.c) > 1e-5
                    or matrix.a < 0 or matrix.d < 0
                )
                clipped = any(abs(a - b) > 1e-4 for a, b in zip(visible_rect, operation["rect"]))
                if clipped or transformed or operation["alpha"] != 1 or operation["clips"] or operation["stack"]:
                    # Even a clip with an unchanged envelope may contain holes.
                    placement_media_ref = f"{media_ref}_p{page.number}_paint{operation['seqno']}"
                    media[placement_media_ref] = MediaItem(
                        placement_media_ref,
                        _render_image_paint(operation, geometrie_effective, visible_rect),
                        "png",
                    )
                    boite = geometrie_effective.bbox_depuis_rect_natif(visible_rect)
                    clip_bbox = boite if operation["clips"] or clipped else None
                quad = [pymupdf.Point(x, y) * matrix for x, y in ((0, 0), (1, 0), (1, 1), (0, 1))]
                metadata["quad"] = tuple(
                    (round(p.x * 12700), round(p.y * 12700))
                    for p in (point * geometrie_effective.rotation_matrix for point in quad)
                )
            if (
                boite.largeur > 0
                and boite.hauteur > 0
                and not _est_artefact_image(boite, dimensions)
            ):
                elements.append(
                    ImageEl(
                        bbox=boite,
                        media_ref=placement_media_ref,
                        placement_id=metadata["placement_id"],
                        source_xref=xref,
                        quad=metadata["quad"],
                        transform=metadata["transform"],
                        z_index=operation["seqno"] if operation is not None else None,
                        clip_bbox=clip_bbox,
                        paint_group_id=f"page:{page.number}:paint-group:{operation['groups'][-1]['id']}" if operation is not None and operation["groups"] else None,
                    )
                )

    elements = composer_placements_visuels(
        page,
        elements,
        media,
        geometrie_effective,
    )
    emitted_groups = set()
    for operation in graphics:
        group = operation.get("composite_group")
        if group is not None:
            if group["id"] in emitted_groups:
                continue
            emitted_groups.add(group["id"])
            rect = _visible_paint_rect(group, geometrie_effective)
            if rect.is_empty:
                continue
            media_ref = f"graphics_p{page.number}_group{group['id']}"
            media[media_ref] = MediaItem(media_ref, _render_image_paint(group, geometrie_effective, rect), "png")
            elements.append(RasterEl(
                geometrie_effective.bbox_depuis_rect_natif(rect), media_ref,
                purpose="source-graphics-group", z_index=group["seqno"],
                source_placements=tuple(f"page:{page.number}:paint:{sequence}" for sequence in group["sequences"]),
                source_xrefs=tuple(child["source_xref"] for child in graphics if child.get("composite_group") is group and child.get("source_xref") is not None),
                paint_group_id=f"page:{page.number}:paint-group:{group['id']}",
                paint_sequences=tuple(group["sequences"]),
            ))
            continue
        if operation["kind"] == "fill_image":
            raster = operation.get("source_xref") is None
        else:
            raster = _graphic_requires_raster(operation)
        if not raster:
            continue
        rect = _visible_paint_rect(operation, geometrie_effective)
        if rect.is_empty:
            continue
        media_ref = f"graphics_p{page.number}_paint{operation['seqno']}"
        media[media_ref] = MediaItem(media_ref, _render_image_paint(operation, geometrie_effective, rect), "png")
        elements.append(RasterEl(geometrie_effective.bbox_depuis_rect_natif(rect), media_ref, purpose="source-graphics-paint", z_index=operation["seqno"]))
    return elements


def extraire_images_rasterisees(
    page,
    doc,
    media: dict,
    dpi: int = 200,
    geometrie: PageGeometry | None = None,
    supprimer_texte_natif: bool = False,
) -> list[ImageEl | RasterEl]:
    """Capture chaque placement d'image tel qu'il est rendu sur la page.

    Contrairement à `extract_image`, cette voie respecte la matrice de placement PDF
    (rotation, retournement, recadrage). Elle est plus lourde mais adaptée au reflow, où
    la fidélité des figures/formules prime sur la déduplication binaire.
    """
    from pdfexact.fallback.rasterize import (
        rasteriser_region,
        rasteriser_region_sans_texte,
        rasteriser_regions_segmentees,
        rasteriser_regions_segmentees_sans_texte,
    )

    elements: list[ImageEl | RasterEl] = []
    vus: set[tuple[int, int, int, int]] = set()
    for xref in sorted({entree[0] for entree in page.get_images(full=True)}):
        try:
            extrait = doc.extract_image(xref)
            dimensions = (int(extrait.get("width", 0)), int(extrait.get("height", 0)))
        except Exception:  # noqa: BLE001
            dimensions = None
        for rect in page.get_image_rects(xref):
            boite = _bbox_image(rect, geometrie)
            cle = (boite.x0, boite.y0, boite.x1, boite.y1)
            if (
                boite.largeur <= 0
                or boite.hauteur <= 0
                or _est_artefact_image(boite, dimensions)
                or cle in vus
            ):
                continue
            vus.add(cle)
            if supprimer_texte_natif and _zone_contient_texte_natif(page, boite, geometrie):
                try:
                    octets_test, _extension_test = _octets_et_extension(doc, xref)
                except Exception:  # noqa: BLE001
                    octets_test = None
                if _image_ressemble_fragment_texte_octets(octets_test, boite, page, geometrie):
                    continue
            dpi_image = max(dpi, 300) if _est_image_page(boite, geometrie, page) else dpi
            if _est_image_page(boite, geometrie, page):
                if supprimer_texte_natif:
                    elements.extend(
                        rasteriser_regions_segmentees_sans_texte(
                            page, boite, media, dpi=dpi_image, geometrie=geometrie
                        )
                    )
                else:
                    elements.extend(rasteriser_regions_segmentees(page, boite, media, dpi=dpi_image))
            elif supprimer_texte_natif:
                elements.append(
                    rasteriser_region_sans_texte(
                        page, boite, media, dpi=dpi_image, geometrie=geometrie
                    )
                )
            else:
                elements.append(rasteriser_region(page, boite, media, dpi=dpi_image))
    return elements


def _est_image_page(boite: BBox, geometrie: PageGeometry | None, page) -> bool:
    geometrie = geometrie or PageGeometry.depuis_page(page)
    page_bbox = BBox(0, 0, geometrie.largeur_emu, geometrie.hauteur_emu)
    # Les scans du document occupent souvent environ 80 % de la page, avec une
    # marge blanche ajoutée par le PDF. La couverture et les dimensions sont testées
    # séparément pour ne pas rater un scan entouré de marges importantes.
    return (
        _bbox_source_ratio(boite, page_bbox) >= 0.72
        or (
            boite.largeur >= geometrie.largeur_emu * 0.80
            and boite.hauteur >= geometrie.hauteur_emu * 0.80
        )
    )


def _aire(boite) -> float:
    return rect_area(boite)


def _ratio_intersection(a, b) -> float:
    return rect_overlap_ratio(a, b)


def _bbox_intersection(a: BBox, b: BBox) -> int:
    x0 = max(a.x0, b.x0)
    y0 = max(a.y0, b.y0)
    x1 = min(a.x1, b.x1)
    y1 = min(a.y1, b.y1)
    return max(0, x1 - x0) * max(0, y1 - y0)


def _bbox_source_ratio(a: BBox, b: BBox) -> float:
    return _bbox_intersection(a, b) / max(a.largeur * a.hauteur, 1)


def _couverture_par_zones(zone: BBox, zones: list[tuple[float, float, float, float]]) -> float:
    """Mesure la part d'une zone déjà occupée par plusieurs placements contigus."""
    cible = (
        zone.x0 / 12700.0,
        zone.y0 / 12700.0,
        zone.x1 / 12700.0,
        zone.y1 / 12700.0,
    )
    aire_cible = _aire(cible)
    if not aire_cible:
        return 0.0
    couverture = 0.0
    for existante in zones:
        x0 = max(cible[0], existante[0])
        y0 = max(cible[1], existante[1])
        x1 = min(cible[2], existante[2])
        y1 = min(cible[3], existante[3])
        couverture += max(0.0, x1 - x0) * max(0.0, y1 - y0)
    return min(1.0, couverture / aire_cible)


def _zone_contient_texte_natif(page, zone: BBox, geometrie: PageGeometry | None, minimum: int = 2) -> bool:
    geometrie = geometrie or PageGeometry.depuis_page(page)
    touches = 0
    for bloc in page.get_text("dict").get("blocks", []):
        if bloc.get("type") != 0:
            continue
        for ligne in bloc.get("lines", []):
            texte = "".join(span.get("text", "") for span in ligne.get("spans", [])).strip()
            if not texte:
                continue
            bbox = geometrie.bbox_depuis_rect_natif(pymupdf.Rect(ligne.get("bbox", (0, 0, 0, 0))))
            centre_x = (bbox.x0 + bbox.x1) // 2
            centre_y = (bbox.y0 + bbox.y1) // 2
            if zone.x0 <= centre_x <= zone.x1 and zone.y0 <= centre_y <= zone.y1:
                touches += 1
            elif _bbox_source_ratio(bbox, zone) >= 0.45:
                touches += 1
            if touches >= minimum:
                return True
    return False


def _image_inline_ressemble_fragment_texte(bloc: dict, boite: BBox, page, geometrie: PageGeometry | None) -> bool:
    """Détecte les images inline qui ne sont qu'une capture parasite de texte déjà natif."""
    return _image_ressemble_fragment_texte_octets(
        bloc.get("image"),
        boite,
        page,
        geometrie,
    )


def _image_ressemble_fragment_texte_octets(
    donnees: bytes | None,
    boite: BBox,
    page,
    geometrie: PageGeometry | None,
) -> bool:
    """Détecte les images qui ne sont qu'une capture parasite de texte déjà natif."""
    largeur_pt = boite.largeur / 12700.0
    hauteur_pt = boite.hauteur / 12700.0
    aire_pt2 = largeur_pt * hauteur_pt
    if aire_pt2 > 18000 or largeur_pt > 190 or hauteur_pt > 170:
        return False
    if not _zone_contient_texte_natif(page, boite, geometrie, minimum=2):
        return False

    if not donnees:
        return False
    try:
        image = Image.open(BytesIO(donnees)).convert("RGB")
        image.thumbnail((96, 96))
    except Exception:  # noqa: BLE001
        return False

    pixels = list(image.getdata())
    if not pixels:
        return False
    blancs_gris = 0
    colores = 0
    for r, g, b in pixels:
        ecart = max(r, g, b) - min(r, g, b)
        luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
        if luminance >= 210 and ecart <= 28:
            blancs_gris += 1
        if ecart >= 45 and luminance <= 235:
            colores += 1
    total = len(pixels)
    return blancs_gris / total >= 0.90 and colores / total <= 0.04


def extraire_images_inline(
    page,
    media: dict,
    deja_posees: list[ImageEl] | None = None,
    geometrie: PageGeometry | None = None,
) -> list[ImageEl | RasterEl]:
    """Extrait les gros blocs image inline visibles dans le flux PDF.

    Plusieurs PDF anciens dessinent les figures, équations ou même des bouts de texte
    avec l'opérateur PDF inline image (BI/EI). `page.get_images()` ne les liste pas.
    On ne prend ici que les blocs assez grands pour éviter de dupliquer les glyphes
    bitmap qui doivent être remplacés par du vrai texte OCR.
    """
    elements: list[ImageEl | RasterEl] = []
    boites_deja_posees = [
        (
            image.bbox.x0 / 12700.0,
            image.bbox.y0 / 12700.0,
            image.bbox.x1 / 12700.0,
            image.bbox.y1 / 12700.0,
        )
        for image in (deja_posees or [])
    ]

    for index, bloc in enumerate(page.get_text("dict").get("blocks", []), start=1):
        if bloc.get("type") != 1:
            continue
        boite_points = tuple(float(v) for v in bloc.get("bbox", (0, 0, 0, 0)))
        boite = _bbox_image(pymupdf.Rect(*boite_points), geometrie)
        boite_affiche_points = (
            boite.x0 / 12700.0,
            boite.y0 / 12700.0,
            boite.x1 / 12700.0,
            boite.y1 / 12700.0,
        )
        if _aire(boite_affiche_points) < SEUIL_IMAGE_INLINE_PT2:
            continue
        if _couverture_par_zones(boite, boites_deja_posees) >= 0.80:
            continue
        if any(_ratio_intersection(boite_affiche_points, existante) > 0.8 for existante in boites_deja_posees):
            continue

        donnees = bloc.get("image")
        extension = (bloc.get("ext") or "png").lower()
        if not donnees:
            continue
        if extension not in EXTENSIONS_SUPPORTEES:
            extension = "png"

        empreinte = hashlib.sha1(donnees).hexdigest()[:16]
        media_ref = f"inline{page.number + 1}_{index}_{empreinte}"
        if media_ref not in media:
            media[media_ref] = MediaItem(
                media_ref=media_ref, donnees=donnees, extension=extension
            )

        if boite.largeur > 0 and boite.hauteur > 0 and not _est_artefact_image(boite):
            elements.append(ImageEl(bbox=boite, media_ref=media_ref))

    return elements


def extraire_images_inline_rasterisees(
    page,
    media: dict,
    deja_posees: list[ImageEl] | None = None,
    dpi: int = 200,
    geometrie: PageGeometry | None = None,
    supprimer_texte_natif: bool = False,
) -> list[ImageEl | RasterEl]:
    """Capture les grosses images inline telles qu'elles apparaissent sur la page.

    Les octets bruts des images inline PDF peuvent avoir une orientation interne
    différente de la matrice d'affichage. En reflow on préfère donc rasteriser la zone
    visible, comme pour les images XRef.
    """
    from pdfexact.fallback.rasterize import (
        rasteriser_region,
        rasteriser_region_sans_texte,
        rasteriser_regions_segmentees,
        rasteriser_regions_segmentees_sans_texte,
    )

    elements: list[ImageEl] = []
    boites_deja_posees = [
        (
            image.bbox.x0 / 12700.0,
            image.bbox.y0 / 12700.0,
            image.bbox.x1 / 12700.0,
            image.bbox.y1 / 12700.0,
        )
        for image in (deja_posees or [])
    ]
    vus: set[tuple[int, int, int, int]] = set()

    for bloc in page.get_text("dict").get("blocks", []):
        if bloc.get("type") != 1:
            continue
        boite_points = tuple(float(v) for v in bloc.get("bbox", (0, 0, 0, 0)))
        boite = _bbox_image(pymupdf.Rect(*boite_points), geometrie)
        boite_affiche_points = (
            boite.x0 / 12700.0,
            boite.y0 / 12700.0,
            boite.x1 / 12700.0,
            boite.y1 / 12700.0,
        )
        if _aire(boite_affiche_points) < SEUIL_IMAGE_INLINE_PT2:
            continue
        if _couverture_par_zones(boite, boites_deja_posees) >= 0.80:
            continue
        if any(_ratio_intersection(boite_affiche_points, existante) > 0.8 for existante in boites_deja_posees):
            continue

        cle = (boite.x0, boite.y0, boite.x1, boite.y1)
        if (
            boite.largeur <= 0
            or boite.hauteur <= 0
            or _est_artefact_image(boite)
            or cle in vus
        ):
            continue
        if supprimer_texte_natif and _image_inline_ressemble_fragment_texte(bloc, boite, page, geometrie):
            continue
        vus.add(cle)
        if _est_image_page(boite, geometrie, page):
            if supprimer_texte_natif:
                elements.extend(
                    rasteriser_regions_segmentees_sans_texte(
                        page, boite, media, dpi=max(dpi, 300), geometrie=geometrie
                    )
                )
            else:
                elements.extend(rasteriser_regions_segmentees(page, boite, media, dpi=max(dpi, 300)))
        elif supprimer_texte_natif:
            elements.append(
                rasteriser_region_sans_texte(
                    page, boite, media, dpi=dpi, geometrie=geometrie
                )
            )
        else:
            elements.append(rasteriser_region(page, boite, media, dpi=dpi))

    return elements
