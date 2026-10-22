"""Artefacts de diagnostic geometrique PDF -> PDF annote et DOCX vide.

Ce module ne reconstruit aucun contenu. Il materialise uniquement les boites
englobantes top-level de l'IR, avec le meme repere (origine en haut a gauche,
EMU) que le rendu page-exact.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re
import shutil
import zipfile
from xml.etree import ElementTree
from xml.parsers import expat
from xml.sax.saxutils import escape

import pymupdf

from pdfexact.geometry import (
    BBox, PageGeometry, emu_vers_pt, preserver_etat_page,
    pt_vers_emu, pt_vers_twips, quantifier_bbox,
)
from pdfexact.ir import (
    Document,
    FlowParagraph,
    ImageEl,
    LinkZone,
    Page,
    RasterEl,
    ShapeEl,
    TableEl,
    TextBox,
)
from pdfexact.render.package import ecrire_docx
from pdfexact.render.drawing import _ancre, _run_xml, forme_xml, image_xml
from pdfexact.render.word_native_rewriter import _frame_xml
from pdfexact.layout.paragraph_planner import lignes_du_bloc, planifier_paragraphe
from pdfexact.analysis.text_geometry import (
    block_alignment,
    geometry_kind,
    is_special_orientation,
)


@dataclass(frozen=True)
class BBoxRecord:
    """Une bbox top-level materialisee dans les deux artefacts."""

    page_index: int
    bbox: BBox
    kind: str
    color: tuple[float, float, float]
    line_bboxes: tuple[BBox, ...] = ()


_COLORS = {
    "text": (0.90, 0.05, 0.05),
    "image": (0.05, 0.25, 0.90),
    "shape": (0.05, 0.55, 0.15),
    "table": (0.60, 0.10, 0.70),
    "link": (0.95, 0.50, 0.02),
}


def _ensure_vml_namespaces(document_text: str) -> str:
    """Déclare les namespaces nécessaires aux fallbacks VML des textes verticaux."""
    root_start = document_text.find("<w:document")
    root_end = document_text.find(">", root_start)
    if root_start < 0 or root_end < 0:
        raise ValueError("document.xml invalide")
    root = document_text[root_start:root_end]
    additions = "".join(
        addition
        for prefix, addition in (
            ("xmlns:v=", ' xmlns:v="urn:schemas-microsoft-com:vml"'),
            ("xmlns:o=", ' xmlns:o="urn:schemas-microsoft-com:office:office"'),
            ("xmlns:w10=", ' xmlns:w10="urn:schemas-microsoft-com:office:word"'),
        )
        if prefix not in root
    )
    if not additions:
        return document_text
    return document_text[:root_start] + root + additions + document_text[root_end:]


def _kind(element) -> str | None:
    if isinstance(element, (TextBox, FlowParagraph)):
        return "text"
    if isinstance(element, RasterEl):
        return "image"
    if element.__class__.__name__ == "ImageEl":
        return "image"
    if isinstance(element, ShapeEl):
        return "shape"
    if isinstance(element, TableEl):
        return "table"
    if isinstance(element, LinkZone):
        return "link"
    return None


def _elements_for_page(page, render_plan=None) -> list[object]:
    if render_plan is not None:
        planned = render_plan.elements_for_page(page.index)
        if planned is not None:
            return list(planned)
    return list(page.elements)


def collect_bbox_records(document: Document, render_plan=None) -> list[BBoxRecord]:
    """Retourne une bbox par element top-level, sans descendre dans les lignes.

    Un TextBox/FlowParagraph reste donc un seul cadre de paragraphe. Les spans,
    lignes, glyphes et le contenu des images ne sont volontairement pas materialises.
    """
    records: list[BBoxRecord] = []
    for page in document.pages:
        for element in _elements_for_page(page, render_plan):
            kind = _kind(element)
            bbox = getattr(element, "bbox", None)
            if kind is None or bbox is None or bbox.largeur <= 0 or bbox.hauteur <= 0:
                continue
            records.append(
                BBoxRecord(
                    page_index=page.index,
                    bbox=bbox,
                    kind=kind,
                    color=_COLORS[kind],
                    line_bboxes=(
                        tuple(getattr(getattr(element, "geometry", None), "line_bboxes", ()) or ())
                        if kind == "text"
                        and geometry_kind(element) != "rectangular-flow"
                        else ()
                    ),
                )
            )
    return records


def _rect(page_bbox: BBox) -> pymupdf.Rect:
    return pymupdf.Rect(
        emu_vers_pt(page_bbox.x0),
        emu_vers_pt(page_bbox.y0),
        emu_vers_pt(page_bbox.x1),
        emu_vers_pt(page_bbox.y1),
    )


def annotate_pdf_bboxes(
    source_pdf,
    destination_pdf,
    document: Document,
    *,
    line_width_pt: float = 0.8,
    render_plan=None,
) -> list[BBoxRecord]:
    """Copie le PDF et dessine ses bboxes sans modifier son contenu."""
    records = collect_bbox_records(document, render_plan)
    source = pymupdf.open(source_pdf)
    try:
        by_page: dict[int, list[BBoxRecord]] = {}
        for record in records:
            by_page.setdefault(record.page_index, []).append(record)
        for page_index, page_records in by_page.items():
            page = source[page_index]
            geometry = PageGeometry.depuis_page(page)
            # Drawing on a rotated CropBox can add an offset in PyMuPDF. Write
            # in native space, then restore the original page state before saving.
            with preserver_etat_page(page):
                page.set_rotation(0)
                for record in page_records:
                    shape = page.new_shape()
                    if record.line_bboxes and len(record.line_bboxes) > 1:
                        points = []
                        for operation, values in _composition_path(record):
                            if operation in {"move", "line"}:
                                points.extend(
                                    pymupdf.Point(emu_vers_pt(x), emu_vers_pt(y))
                                    * geometry.derotation_matrix
                                    for x, y in values
                                )
                            elif operation == "close":
                                shape.draw_polyline(points)
                                shape.finish(color=record.color, fill=None, width=line_width_pt, closePath=True)
                                points = []
                    else:
                        shape.draw_rect(geometry.rect_affiche_vers_natif(_rect(record.bbox)))
                        shape.finish(color=record.color, fill=None, width=line_width_pt, closePath=True)
                    shape.commit(overlay=True)
        destination = Path(destination_pdf)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.save(destination, garbage=4, deflate=True)
    finally:
        source.close()
    return records


def _rectangle_path(bbox: BBox):
    """Construit un chemin rectangle pour que le DOCX n'ait aucun remplissage."""
    return [
        ("move", ((bbox.x0, bbox.y0),)),
        ("line", ((bbox.x1, bbox.y0),)),
        ("line", ((bbox.x1, bbox.y1),)),
        ("line", ((bbox.x0, bbox.y1),)),
        ("close", ()),
    ]


def _composition_rectangles(lines: list[BBox]) -> list[BBox]:
    """Relie les fragments d'une ligne et les rangs proches qui se recouvrent."""
    rectangles = set(lines)
    for index, first in enumerate(lines):
        for second in lines[index + 1:]:
            if second.y0 >= first.y1:
                break
            height = min(first.hauteur, second.hauteur)
            left, right = max(first.x0, second.x0), min(first.x1, second.x1)
            top, bottom = max(first.y0, second.y0), min(first.y1, second.y1)
            same_row = bottom > top and (
                bottom - top >= max(first.hauteur, second.hauteur) * 0.6
                or abs(first.y1 - second.y1) <= height * 0.25
            )
            if same_row and 0 < left - right <= height * 0.75:
                rectangles.add(BBox(right, top, left, bottom))

    # Row joins also participate in continuity, so small spaces between
    # fragments do not become holes in the leading below their shared baseline.
    rows = sorted(rectangles, key=lambda box: (box.y0, box.x0, box.y1, box.x1))
    for index, first in enumerate(rows):
        for second in rows[index + 1:]:
            gap = second.y0 - first.y1
            if gap > first.hauteur * 0.75:
                break
            left, right = max(first.x0, second.x0), min(first.x1, second.x1)
            # Only the shared horizontal interval can continue across leading;
            # extending the full row width would cover adjacent exclusions.
            if right > left and 0 < gap <= min(first.hauteur, second.hauteur) * 0.75:
                rectangles.add(BBox(left, first.y1, right, second.y0))
    return list(rectangles)


def _merged_intervals(intervals):
    merged = []
    for left, right in sorted(intervals):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    return merged


def _uncovered_intervals(intervals, covered):
    for left, right in intervals:
        for start, end in covered:
            if end <= left:
                continue
            if start >= right:
                break
            if start > left:
                yield left, start
            left = max(left, end)
            if left >= right:
                break
        if left < right:
            yield left, right


def _rectangle_union_path(rectangles: list[BBox]):
    """Trace les bords exposes de l'union, y compris les trous et composantes."""
    levels = sorted({y for box in rectangles for y in (box.y0, box.y1)})
    edges = {}

    def add_edge(first, second):
        edges.setdefault(first, set()).add(second)

    above = []
    for top, bottom in zip(levels, levels[1:] + levels[-1:]):
        below = _merged_intervals(
            (box.x0, box.x1) for box in rectangles if box.y0 <= top < box.y1
        )
        for left, right in _uncovered_intervals(below, above):
            add_edge((left, top), (right, top))
        for left, right in _uncovered_intervals(above, below):
            add_edge((right, top), (left, top))
        for left, right in below:
            add_edge((left, bottom), (left, top))
            add_edge((right, top), (right, bottom))
        above = below

    def direction(first, second):
        if first[1] == second[1]:
            return 0 if second[0] > first[0] else 2
        return 1 if second[1] > first[1] else 3

    path = []
    while edges:
        start = min(edges, key=lambda point: (point[1], point[0]))
        current, heading = start, 0
        points, positions, loops = [], {}, []
        while True:
            positions[current] = len(points)
            points.append(current)
            # Keep the interior on the right. At a corner-only contact this
            # closes each component separately instead of forming a figure eight.
            following = min(
                edges[current],
                key=lambda point: (1, 0, 3, 2)[(direction(current, point) - heading) % 4],
            )
            edges[current].remove(following)
            if not edges[current]:
                del edges[current]
            heading = direction(current, following)
            current = following
            # A hole can touch the exterior at a single vertex. Extract that
            # cycle without revisiting the vertex in the enclosing contour.
            if current in positions:
                offset = positions[current]
                loops.append(points[offset:])
                for point in points[offset:]:
                    del positions[point]
                points = points[:offset]
            if current == start:
                break
        for points in loops:
            corners = [
                point for previous, point, following in zip(
                    points[-1:] + points[:-1], points, points[1:] + points[:1]
                )
                if not (previous[0] == point[0] == following[0]
                        or previous[1] == point[1] == following[1])
            ]
            path.extend([
                ("move", (corners[0],)),
                *[("line", (point,)) for point in corners[1:]],
                ("close", ()),
            ])
    return path


def _composition_path(record: BBoxRecord):
    """Contour rectiligne ferme de chaque composante continue du paragraphe."""
    lines = sorted(
        (box for box in record.line_bboxes if box.largeur > 0 and box.hauteur > 0),
        key=lambda box: (box.y0, box.x0, box.y1, box.x1),
    )
    if len(lines) < 2:
        return _rectangle_path(record.bbox)
    return _rectangle_union_path(_composition_rectangles(lines))


def _frame_shape(record: BBoxRecord) -> ShapeEl:
    color = "{:02X}{:02X}{:02X}".format(
        round(record.color[0] * 255),
        round(record.color[1] * 255),
        round(record.color[2] * 255),
    )
    return ShapeEl(
        bbox=record.bbox,
        chemins=[_composition_path(record)],
        remplissage=None,
        contour=color,
        epaisseur_emu=pt_vers_emu(0.8),
    )


def _ordonner_non_textuels(elements: list) -> list:
    """Use source paint order; geometry is only a legacy fallback."""
    known = [element.z_index for element in elements if getattr(element, "z_index", None) is not None]
    if known:
        return sorted(enumerate(elements), key=lambda item: (
            item[1].z_index if getattr(item[1], "z_index", None) is not None else max(known) + 1 + item[0],
        ))
    formes = [
        element
        for element in elements
        if isinstance(element, (ShapeEl, RasterEl))
    ]

    def est_ombre(element) -> bool:
        if not isinstance(element, ImageEl):
            return False
        aire_element = max(element.bbox.largeur * element.bbox.hauteur, 1)
        marge = pt_vers_emu(3.0)
        return any(
            forme.bbox.x0 >= element.bbox.x0 - marge
            and forme.bbox.y0 >= element.bbox.y0 - marge
            and forme.bbox.x1 <= element.bbox.x1 + marge
            and forme.bbox.y1 <= element.bbox.y1 + marge
            and forme.bbox.largeur * forme.bbox.hauteur / aire_element >= 0.55
            for forme in formes
        )

    def couche(element) -> int:
        if est_ombre(element):
            return 0
        if isinstance(element, (RasterEl, ShapeEl)):
            return 1
        return 2

    return sorted(enumerate(elements), key=lambda item: (couche(item[1]), item[0]))


def _source_paint_index(element):
    from pdfexact.analysis.provenance import source_paint_index

    return source_paint_index(element)


def _paint_z(element, fallback):
    sequence = _source_paint_index(element)
    return 100 + 10 * sequence if sequence is not None else fallback


def _boxes_overlap(left, right):
    return min(left.x1, right.x1) > max(left.x0, right.x0) and min(left.y1, right.y1) > max(left.y0, right.y0)


def _text_paint_fragments(element, visuals):
    """Compatibility wrapper for the upstream paint transformation."""
    from pdfexact.analysis.semantic import text_paint_fragments

    return text_paint_fragments(element, visuals)


def _bbox_render_plan(document, supplied):
    from pdfexact.render.render_plan import RenderPlan, build_render_plan

    if isinstance(supplied, RenderPlan):
        plan = supplied
    else:
        # Older diagnostic callers pass a projection rather than a RenderPlan.
        projected = replace(document, pages=[replace(page, elements=_elements_for_page(page, supplied)) for page in document.pages])
        plan = build_render_plan(projected)
    errors = plan.validate(document) if isinstance(supplied, RenderPlan) else plan.validate()
    if set(plan.pages) != {page.index for page in document.pages}:
        errors = [*errors, "incomplete-plan-pages"]
    if errors:
        raise ValueError("invalid render plan: " + "; ".join(errors))
    return plan


def write_bbox_only_docx(document: Document, destination_docx, render_plan=None) -> list[BBoxRecord]:
    """Ecrit un DOCX vierge contenant seulement les cadres des bboxes."""
    records = collect_bbox_records(document, render_plan)
    records_by_page: dict[int, list[BBoxRecord]] = {}
    for record in records:
        records_by_page.setdefault(record.page_index, []).append(record)

    blank = Document(
        pages=[
            Page(
                index=page.index,
                largeur_emu=page.largeur_emu,
                hauteur_emu=page.hauteur_emu,
                coordinate_space=page.coordinate_space,
                orientation=page.orientation,
                format_name=page.format_name,
                rotation_pdf=page.rotation_pdf,
                native_width_pt=page.native_width_pt,
                native_height_pt=page.native_height_pt,
                elements=[_frame_shape(record) for record in records_by_page.get(page.index, [])],
            )
            for page in document.pages
        ],
        polices=dict(document.polices),
    )
    destination = Path(destination_docx)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ecrire_docx(blank, destination, native_rewriter=False)
    return records


def write_non_text_only_docx(document: Document, destination_docx) -> None:
    """Ecrit uniquement les elements non textuels aux positions extraites.

    Les medias sont reutilises tels quels; aucun TextBox, FlowParagraph, lien ou
    contenu de tableau n'est copie dans ce document de verification geometrique.
    """
    non_textuels = (ImageEl, RasterEl, ShapeEl)
    blank = Document(
        pages=[
            Page(
                index=page.index,
                largeur_emu=page.largeur_emu,
                hauteur_emu=page.hauteur_emu,
                coordinate_space=page.coordinate_space,
                orientation=page.orientation,
                format_name=page.format_name,
                rotation_pdf=page.rotation_pdf,
                native_width_pt=page.native_width_pt,
                native_height_pt=page.native_height_pt,
                elements=[
                    element for element in page.elements if isinstance(element, non_textuels)
                ],
            )
            for page in document.pages
        ],
        media=dict(document.media),
        polices=dict(document.polices),
    )
    destination = Path(destination_docx)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ecrire_docx(blank, destination, native_rewriter=False)


def write_non_text_with_bboxes_docx(document: Document, destination_docx) -> list[BBoxRecord]:
    """Ecrit les non-textes et superpose toutes les bboxes, sans texte extrait."""
    records = collect_bbox_records(document)
    non_textuels = (ImageEl, RasterEl, ShapeEl)
    pages = []
    for page in document.pages:
        # Ordre volontaire : cadres geometriques d'abord, objets ensuite. Les objets
        # sont legerement insetes pour rester visiblement a l'interieur de leur cadre.
        elements = [
            _frame_shape(record)
            for record in records
            if record.page_index == page.index
        ]
        page_non_textuels = [
            element for element in page.elements if isinstance(element, non_textuels)
        ]
        for _index, element in _ordonner_non_textuels(page_non_textuels):
            inset = pt_vers_emu(1.0)
            bbox = element.bbox
            if bbox.largeur > 2 * inset and bbox.hauteur > 2 * inset:
                element = replace(
                    element,
                    bbox=BBox(
                        bbox.x0 + inset,
                        bbox.y0 + inset,
                        bbox.x1 - inset,
                        bbox.y1 - inset,
                    ),
                )
            elements.append(element)
        pages.append(
            Page(
                index=page.index,
                largeur_emu=page.largeur_emu,
                hauteur_emu=page.hauteur_emu,
                coordinate_space=page.coordinate_space,
                orientation=page.orientation,
                format_name=page.format_name,
                rotation_pdf=page.rotation_pdf,
                native_width_pt=page.native_width_pt,
                native_height_pt=page.native_height_pt,
                elements=elements,
            )
        )
    blank = Document(
        pages=pages,
        media=dict(document.media),
        polices=dict(document.polices),
    )
    destination = Path(destination_docx)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ecrire_docx(blank, destination, native_rewriter=False)
    return records


def fill_existing_bbox_docx(
    bbox_docx,
    document: Document,
    destination_docx,
    render_plan=None,
) -> None:
    """Remplit un DOCX de bboxes existant sans reconstruire ses cadres.

    Le package source est la verite pour les bboxes. Cette fonction ajoute seulement
    les dessins et medias non textuels dans les paragraphes de page deja presents.
    """
    plan = _bbox_render_plan(document, render_plan)
    ns = {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
        "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
        "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    }
    for prefix, uri in ns.items():
        ElementTree.register_namespace(prefix, uri)

    base = Path(bbox_docx)
    destination = Path(destination_docx)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(base, "r") as source:
        parts = {name: source.read(name) for name in source.namelist()}

    document_text = _ensure_vml_namespaces(parts["word/document.xml"].decode("utf-8"))
    # The bbox DOCX is a diagnostic artifact. Its colored outline shapes must
    # never leak into the non-text or final document.
    document_text = re.sub(
        r'<wp:anchor\b(?=[^>]*>).*?<wps:wsp\b.*?</wp:anchor>',
        "",
        document_text,
        flags=re.DOTALL,
    )

    rels_xml = ElementTree.fromstring(parts["word/_rels/document.xml.rels"])
    rels_original = parts["word/_rels/document.xml.rels"]
    relation_additions: list[str] = []
    relation_ids = {
        int(item.attrib["Id"][3:])
        for item in rels_xml
        if item.attrib.get("Id", "").startswith("rId")
        and item.attrib["Id"][3:].isdigit()
    }
    next_relation = max(relation_ids, default=0) + 1
    next_drawing_id = 1000

    non_textuels = (ImageEl, RasterEl, ShapeEl)
    insertions: list[str] = []
    for page in document.pages:
        chunks: list[str] = []
        for instruction in plan.instructions_for_page(page.index):
            if instruction.container not in {"image", "shape"}:
                continue
            element = instruction.element
            anchor = instruction.anchor
            # Le document final doit reprendre la bbox source. L'inset appartient
            # uniquement au document de diagnostic des cadres, jamais au contenu.
            if isinstance(element, (ImageEl, RasterEl)):
                media = document.media[element.media_ref]
                target = f"media/{media.media_ref}.{media.extension}"
                existing = next(
                    (
                        item.attrib["Id"]
                        for item in rels_xml
                        if item.attrib.get("Target") == target
                    ),
                    None,
                )
                if existing is None:
                    relation_id = f"rId{next_relation}"
                    next_relation += 1
                    relation_additions.append(
                        '<Relationship '
                        f'Id="{relation_id}" '
                        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                        f'Target="{escape(target)}"/>'
                    )
                else:
                    relation_id = existing
                chunk = image_xml(element, next_drawing_id, anchor.z, relation_id, derriere=anchor.behind_doc, planned=True)
                parts[f"word/{target}"] = media.donnees
            else:
                chunk = forme_xml(element, next_drawing_id, anchor.z, derriere=anchor.behind_doc, planned=True)
            next_drawing_id += 1
            chunks.append(f"<w:r>{chunk}</w:r>")
        insertions.append(
            '<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="1" '
            'w:lineRule="exact"/></w:pPr>' + "".join(chunks) + '</w:p>'
        )

    parts["word/document.xml"] = _insert_native_paragraphs_by_section(document_text, insertions)
    if relation_additions:
        rels_text = rels_original.decode("utf-8")
        rels_text = rels_text.replace(
            "</Relationships>",
            "".join(relation_additions) + "</Relationships>",
        )
        parts["word/_rels/document.xml.rels"] = rels_text.encode("utf-8")
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as output:
        for name, data in parts.items():
            output.writestr(name, data)


def fill_existing_bbox_docx_from_non_text_docx(
    bbox_docx,
    non_text_docx,
    destination_docx,
) -> None:
    """Fusionne un DOCX non-textuel valide dans le DOCX de bboxes existant."""
    base = Path(bbox_docx)
    source_path = Path(non_text_docx)
    destination = Path(destination_docx)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(base, "r") as base_zip, zipfile.ZipFile(source_path, "r") as source_zip:
        parts = {name: base_zip.read(name) for name in base_zip.namelist()}
        source_document = source_zip.read("word/document.xml").decode("utf-8")
        source_rels = source_zip.read("word/_rels/document.xml.rels")

        rel_root = ElementTree.fromstring(source_rels)
        image_relations = {
            relation.attrib["Id"]: relation.attrib["Target"].lstrip("/")
            for relation in rel_root
            if relation.attrib.get("Type", "").endswith("/image")
        }
        base_rels = parts["word/_rels/document.xml.rels"].decode("utf-8")
        existing_ids = [
            int(value)
            for value in re.findall(r'Id="rId(\d+)"', base_rels)
        ]
        next_id = max(existing_ids, default=0) + 1
        relation_additions: list[str] = []
        relation_map: dict[str, str] = {}
        for old_id, target in image_relations.items():
            new_id = f"rId{next_id}"
            next_id += 1
            relation_map[old_id] = new_id
            relation_additions.append(
                '<Relationship '
                f'Id="{new_id}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                f'Target="{escape(target)}"/>'
            )
            media_name = f"word/{target}"
            if media_name not in parts:
                parts[media_name] = source_zip.read(media_name)

        drawing_runs = [
            run for run in re.findall(r"<w:r>.*?</w:r>", source_document, re.DOTALL)
            if "<w:drawing>" in run
        ]
        if not drawing_runs:
            raise ValueError("DOCX non-textuel source sans dessins")
        for old_id, new_id in relation_map.items():
            drawing_runs = [run.replace(f'r:embed="{old_id}"', f'r:embed="{new_id}"') for run in drawing_runs]

        bbox_document = parts["word/document.xml"].decode("utf-8")
        if bbox_document.count("</w:p>") < 1:
            raise ValueError("DOCX de bboxes sans paragraphe de page")
        insertion = "".join(drawing_runs)
        bbox_document = bbox_document.replace("</w:p>", insertion + "</w:p>", 1)
        parts["word/document.xml"] = bbox_document.encode("utf-8")
        if relation_additions:
            parts["word/_rels/document.xml.rels"] = base_rels.replace(
                "</Relationships>",
                "".join(relation_additions) + "</Relationships>",
            ).encode("utf-8")

    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as output:
        for name, data in parts.items():
            output.writestr(name, data)


def fill_existing_bbox_docx_with_text(
    bbox_docx,
    text_document: Document,
    destination_docx,
) -> None:
    """Ajoute les blocs texte dans les bboxes existantes comme paragraphes Word."""
    base = Path(bbox_docx)
    destination = Path(destination_docx)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(base, "r") as source:
        parts = {name: source.read(name) for name in source.namelist()}

    document_text = _ensure_vml_namespaces(parts["word/document.xml"].decode("utf-8"))
    if document_text.count("</w:p>") < len(text_document.pages):
        raise ValueError("DOCX de bboxes incompatible avec les pages texte")

    from pdfexact.render.package import GestionnaireRelations

    relations = GestionnaireRelations()
    insertions: list[str] = []
    identifiant = 2000
    for page in text_document.pages:
        chunks: list[str] = []
        for element in page.elements:
            if not isinstance(element, (TextBox, FlowParagraph)):
                continue
            chunk = _frame_xml(
                element,
                identifiant,
                2_100_000 + identifiant,
                relations,
            )
            identifiant += 1
            # Un run ne peut pas être enfant direct de w:body. Les cadres
            # DrawingML doivent rester dans un paragraphe Word valide.
            chunks.append(f"<w:p><w:r>{chunk}</w:r></w:p>")
        insertions.append("".join(chunks))

    morceaux = document_text.split("</w:p>")
    for index, insertion in enumerate(insertions):
        morceaux[index] += insertion
    parts["word/document.xml"] = "</w:p>".join(morceaux).encode("utf-8")

    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as output:
        for name, data in parts.items():
            output.writestr(name, data)


def _native_paragraph_runs(element, polices=None) -> str:
    """Construit un paragraphe Word fluide en conservant les styles des runs.

    Le plan partagé distingue les compositions affichées, dont les retours sont
    intentionnels, des paragraphes de flux, dont les lignes PDF sont réunies.
    Il conserve les styles des runs et n'applique un tracking correctif borné
    que lorsque la police Word provoquerait un débordement.
    """
    lignes = list(lignes_du_bloc(element))
    morceaux: list[str] = []
    plan = planifier_paragraphe(element, polices=polices)
    texte_precedent = ""
    for line_index, line in enumerate(lignes):
        spans = [span for span in line.spans if span.texte]
        if not spans:
            continue
        texte_ligne = "".join(span.texte for span in spans)
        join_action = (
            plan.action_between(line_index - 1)
            if line_index
            else "space"
        )
        if line_index and texte_precedent.strip() and texte_ligne.strip():
            precedent = texte_precedent
            courant = texte_ligne
            if join_action == "hyphen_join":
                if morceaux:
                    morceaux[-1] = re.sub(
                        r"(?:-|¬)(</w:t></w:r>)$", r"\1", morceaux[-1]
                    )
            elif join_action == "preserve_break":
                morceaux.append('<w:r><w:br/></w:r>')
            elif join_action == "paragraph_break":
                morceaux.append('<w:r><w:br/><w:br/></w:r>')
            elif (join_action != "no_space" and precedent and courant and not precedent[-1].isspace()
                  and not courant[0].isspace() and courant[0] not in ".,;:!?)]}%"):
                morceaux.append('<w:r><w:t xml:space="preserve"> </w:t></w:r>')

        if line_index:
            if join_action in {"preserve_break", "paragraph_break"} and (
                line.bbox.x0 > element.bbox.x0 + pt_vers_emu(0.5)
            ):
                morceaux.append('<w:r><w:tab/></w:r>')
        if line_index == 0 and line.bbox.x0 > element.bbox.x0 + pt_vers_emu(0.5):
            morceaux.append('<w:r><w:tab/></w:r>')

        morceaux.extend(
            _run_xml(
                replace(
                    span,
                    espacement_twips=(
                        0
                        if (
                            line_index < len(plan.line_width_scale_percent)
                            and plan.line_width_scale_percent[line_index] < 100
                        )
                        else int(span.espacement_twips or 0)
                        + (
                            plan.line_spacing_twips[line_index]
                            if line_index < len(plan.line_spacing_twips)
                            else 0
                        )
                    ),
                ),
                None,
                autoriser_espacement_negatif=True,
                largeur_pct=(
                    plan.line_width_scale_percent[line_index]
                    if line_index < len(plan.line_width_scale_percent)
                    else 100
                ),
            )
            for span in spans
            if span.texte
        )
        texte_precedent = texte_ligne
    return "".join(morceaux)


def _remove_orphan_text_bbox_anchors(document_text: str, text_document: Document) -> str:
    """Retire les contours rouges qui ne correspondent plus a un paragraphe.

    Le DOCX de bboxes est genere avant la deduplication et la fusion de la
    lettrine. Ces operations peuvent supprimer un bloc texte tout en laissant
    son contour rouge dans le package. Les autres cadres (images, formes,
    fond) sont conserves. Les ancres sont comparees dans le meme repere EMU.
    """
    kept: list[tuple[int, int, int, int]] = []
    for page in text_document.pages:
        for element in page.elements:
            if isinstance(element, (TextBox, FlowParagraph)):
                bbox = quantifier_bbox(element.bbox)
                kept.append((bbox.x0, bbox.y0, bbox.largeur, bbox.hauteur))

    # Le DOCX de diagnostic a ete quantifie lors de sa creation, tandis que le
    # catalogue est produit apres l'extraction. Quelques milliers d'EMU d'ecart
    # sont normaux et ne doivent pas transformer un cadre valide en cadre vide.
    tolerance_emu = pt_vers_emu(2.0)
    matched: set[int] = set()

    anchor_pattern = re.compile(r"<wp:anchor\b.*?</wp:anchor>", re.DOTALL)
    number_pattern = re.compile(r"<wp:posOffset>(-?\d+)</wp:posOffset>")
    extent_pattern = re.compile(r'<wp:extent cx="(\d+)" cy="(\d+)"')

    def replace_anchor(match: re.Match[str]) -> str:
        anchor = match.group(0)
        if "E60D0D" not in anchor.upper():
            return anchor
        positions = [int(value) for value in number_pattern.findall(anchor)]
        extent = extent_pattern.search(anchor)
        if len(positions) < 2 or extent is None:
            return anchor
        candidate = (positions[0], positions[1], int(extent.group(1)), int(extent.group(2)))
        for index, expected in enumerate(kept):
            if index in matched:
                continue
            if all(
                abs(actual - wanted) <= tolerance_emu
                for actual, wanted in zip(candidate, expected)
            ):
                matched.add(index)
                return anchor
        return ""

    return anchor_pattern.sub(replace_anchor, document_text)


def _native_paragraph_xml(
    element,
    *,
    occupied_bboxes: tuple[BBox, ...] = (),
    polices: dict | None = None,
) -> str:
    """Crée un paragraphe Word positionné par sa bbox, sans textbox DrawingML."""
    bbox = quantifier_bbox(element.bbox)
    lines = list(lignes_du_bloc(element))
    if not lines:
        return ""
    deltas = [
        current.bbox.y0 - previous.bbox.y0
        for previous, current in zip(lines, lines[1:])
        if current.bbox.y0 > previous.bbox.y0
    ]
    line_metrics = max(
        max(item.bbox.hauteur, item.hauteur_ligne_emu, 1)
        for item in lines
    )
    plan = planifier_paragraphe(element, polices=polices)
    line_count = max(len(lines), plan.estimated_line_count)
    line_step = max(min(deltas) if deltas else 0, line_metrics, 1)
    width = max(pt_vers_twips(emu_vers_pt(bbox.largeur)), 1)
    height_source = max(pt_vers_twips(emu_vers_pt(bbox.hauteur)), 1)
    line_metrics_twips = max(pt_vers_twips(emu_vers_pt(line_metrics)), 1)
    line_source_twips = max(pt_vers_twips(emu_vers_pt(line_step)), 1)
    # Le cadre doit contenir toutes les lignes apres reflow. Lorsque la
    # metrique PDF est legerement plus grande que la hauteur disponible,
    # l'interligne est reduit dans la limite de la hauteur typographique.
    line = max(
        min(line_source_twips, max(height_source // max(line_count, 1), 1)),
        line_metrics_twips,
    )
    height = max(height_source, line * line_count, 1)
    base_bbox = quantifier_bbox(element.bbox)
    if height > height_source and occupied_bboxes:
        marge = pt_vers_emu(0.5)
        limites = [
            other.y0 - marge
            for other in occupied_bboxes
            if other.y0 >= base_bbox.y1
            and min(base_bbox.x1, other.x1) > max(base_bbox.x0, other.x0)
        ]
        if limites:
            height = min(height, max(height_source, min(limites) - base_bbox.y0))
    x = max(pt_vers_twips(emu_vers_pt(bbox.x0)), 0)
    y = max(pt_vers_twips(emu_vers_pt(bbox.y0)), 0)
    runs = _native_paragraph_runs(element, polices=polices)
    if not runs:
        return ""
    special = is_special_orientation(element)
    direction = ""
    alignment = block_alignment(element)
    if special:
        # Les orientations non horizontales nécessitent le backend de cadre
        # éditable ; les paragraphes horizontaux restent des w:p natifs.
        return _frame_xml(element, 4000, 2_104_000, None)
    direction = ""
    tabs = ""
    if geometry_kind(element) != "rectangular-flow" or plan.preserve_lines:
        positions = sorted(
            {
                pt_vers_twips(emu_vers_pt(line.bbox.x0 - bbox.x0))
                for line in lines
                if line.bbox.x0 > bbox.x0 + pt_vers_emu(0.5)
            }
        )
        if positions:
            tabs = "<w:tabs>" + "".join(
                f'<w:tab w:val="left" w:pos="{max(position, 1)}"/>'
                for position in positions
            ) + "</w:tabs>"
    return (
        '<w:p><w:pPr>'
        f'<w:framePr w:w="{width}" w:h="{height}" w:x="{x}" w:y="{y}" '
        'w:hAnchor="page" w:vAnchor="page" w:wrap="none" w:anchorLock="0" '
        'w:hRule="atLeast"/>'
        f'<w:spacing w:before="0" w:after="0" w:line="{line}" w:lineRule="exact"/>'
        f'<w:jc w:val="{alignment}"/>'
        f'{tabs}'
        f'{direction}'
        '<w:keepLines/><w:widowControl/>'
        f'</w:pPr>{runs}</w:p>'
    )


def _insert_native_paragraphs_by_section(document_text: str, insertions: list[str]) -> bytes:
    """Insere les textes avant la fermeture de leur section de page source."""
    xml = document_text.encode("utf-8")
    word = "http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    body_path = [word + "document", word + "body"]
    paragraph_path = body_path + [word + "p"]
    section_path = paragraph_path + [word + "pPr", word + "sectPr"]
    path: list[str] = []
    boundaries: list[int] = []
    paragraph_start = 0
    parser = expat.ParserCreate(namespace_separator="}")

    def start_element(name, attributes):
        nonlocal paragraph_start
        path.append(name)
        if path == paragraph_path:
            paragraph_start = parser.CurrentByteIndex
        elif path == section_path:
            # The section ends with this paragraph, including its drawings.
            # Inserting after it would anchor the text on the following page.
            boundaries.append(paragraph_start)
        elif path == body_path + [word + "sectPr"]:
            boundaries.append(parser.CurrentByteIndex)

    parser.StartElementHandler = start_element
    parser.EndElementHandler = lambda name: path.pop()
    parser.Parse(xml, True)
    if len(boundaries) != len(insertions):
        raise ValueError("DOCX de bboxes incompatible avec les sections des pages texte")

    # Expat supplies byte offsets, allowing the existing XML and namespace
    # declarations to stay intact even when content contains non-ASCII text.
    chunks = []
    previous = 0
    for boundary, insertion in zip(boundaries, insertions):
        chunks.extend((xml[previous:boundary], insertion.encode("utf-8")))
        previous = boundary
    chunks.append(xml[previous:])
    return b"".join(chunks)


def _layered_native_paragraph_xml(element, identifiant, z, *, occupied_bboxes=(), polices=None):
    """A transparent native textbox shares the image/vector paint stack."""
    if is_special_orientation(element):
        return _frame_xml(element, identifiant, z, None)
    paragraph = _native_paragraph_xml(element, occupied_bboxes=occupied_bboxes, polices=polices)
    if not paragraph:
        return ""
    word = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    ElementTree.register_namespace("w", word)
    root = ElementTree.fromstring(f'<root xmlns:w="{word}">{paragraph}</root>')
    paragraph = root[0]
    properties = paragraph.find(f"{{{word}}}pPr")
    frame = properties.find(f"{{{word}}}framePr")
    if frame is not None:
        properties.remove(frame)
    content = ElementTree.tostring(paragraph, encoding="unicode")
    bbox = quantifier_bbox(element.bbox)
    graphic = (
        '<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        '<wps:wsp><wps:cNvSpPr txBox="1"/><wps:spPr>'
        f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{max(bbox.largeur, 1)}" cy="{max(bbox.hauteur, 1)}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln>'
        f'</wps:spPr><wps:txbx><w:txbxContent>{content}</w:txbxContent></wps:txbx>'
        '<wps:bodyPr rot="0" wrap="square" vertOverflow="overflow" horzOverflow="overflow" '
        'lIns="0" tIns="0" rIns="0" bIns="0" anchor="t"><a:noAutofit/></wps:bodyPr>'
        '</wps:wsp></a:graphicData></a:graphic>'
    )
    return _ancre(bbox, identifiant, z, f"Editable text {identifiant}", graphic)


def fill_existing_bbox_docx_with_native_paragraphs(
    bbox_docx,
    text_document: Document,
    destination_docx,
    render_plan=None,
) -> None:
    """Materialise le plan complet ou insere les textes dans le package fourni."""
    from pdfexact.render.render_plan import RenderPlan
    from pdfexact.render.text_backend import render_frame, render_native_paragraph

    plan = _bbox_render_plan(text_document, render_plan)
    base = Path(bbox_docx)
    destination = Path(destination_docx)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(render_plan, RenderPlan):
        ecrire_docx(
            text_document,
            destination,
            native_rewriter=True,
            render_plan=plan,
            package_options={"include_scene_manifest": True},
        )
        return
    with zipfile.ZipFile(base, "r") as source:
        parts = {name: source.read(name) for name in source.namelist()}

    document_text = _ensure_vml_namespaces(parts["word/document.xml"].decode("utf-8"))
    document_text = _remove_orphan_text_bbox_anchors(document_text, text_document)

    identifiant = 4000
    insertions: list[str] = []
    for page in text_document.pages:
        chunks: list[str] = []
        for instruction in plan.instructions_for_page(page.index):
            if instruction.text is None:
                continue
            if instruction.bbox_container in {"layered-frame", "dml-frame"}:
                frame = render_frame(instruction.text, instruction.element, identifiant, instruction.anchor.z, None,
                                     layered=instruction.bbox_container == "layered-frame", behind_doc=instruction.anchor.behind_doc)
                chunks.append(f'<w:p><w:r>{frame}</w:r></w:p>')
            else:
                chunks.append(render_native_paragraph(instruction.text))
            identifiant += 1
        insertions.append("".join(chunks))
    parts["word/document.xml"] = _insert_native_paragraphs_by_section(document_text, insertions)

    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as output:
        for name, data in parts.items():
            output.writestr(name, data)
