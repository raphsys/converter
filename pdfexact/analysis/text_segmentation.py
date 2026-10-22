"""Segmentation sémantique des lignes natives en paragraphes Word éditables.

Les lignes sont des unités d'observation uniquement. La sortie de ce module est
constituée de TextBox/FlowParagraph uniques par groupe sémantique; aucune ligne
ne devient un paragraphe Word indépendant.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from statistics import median
import warnings

from pdfexact.analysis.geometry import axis_overlap_ratio, intersection_area
from pdfexact.analysis.provenance import observation_is_preserved
from pdfexact.analysis.semantic import (
    commence_par_minuscule,
    ends_sentence,
    est_texte_de_corps,
    starts_list_marker,
    styles_compatibles,
)
from pdfexact.analysis.text_geometry import geometry_contract_for, line_has_text, paragraph_bbox_from_lines
from pdfexact.geometry import BBox
from pdfexact.ir import FlowParagraph, ImageEl, RasterEl, ShapeEl, TableEl, TextBox, element_source_ids
from pdfexact.layout.text_comprehension import (
    comprendre_segmentation_page,
    contexte_lignes_texte,
    hard_line_break,
)


def _default_line_direction(ligne):
    # Baselines and quads are directional evidence, even with a zero angle.
    return all(
        item.orientation == "horizontal" and not item.angle_deg and not item.curved
        and not item.baseline_points and not item.quad
        for item in (ligne, *ligne.spans)
    )


def _verified_line_ancestors(page, element, ligne):
    """Aliases nominate containers; their actual acquired rows prove membership."""
    from pdfexact.scene import ElementKind

    if page is None or getattr(ligne, "source_page_index", None) != page.index:
        return ()
    inventory = getattr(page, "source_inventory", {})
    registry = getattr(getattr(page, "element_registry", None), "elements", {})
    pending = list(element_source_ids(element))
    seen, ancestors = set(), []
    for ident in pending:
        if ident in seen:
            continue
        seen.add(ident)
        record = registry.get(ident)
        if record is not None and (record.kind is not ElementKind.TEXT or record.page_index != page.index
                                   or record.element_id != ident):
            continue
        source = inventory.get(ident)
        if source is None and record is not None:
            source = record.acquisition_raw if record.acquisition_raw is not None else record.raw
        if (type(source) not in (TextBox, FlowParagraph) or source.source_id != ident
                or getattr(source, "source_page_index", None) != page.index):
            continue
        if not any(observation_is_preserved(row, [ligne]) for row in source.lignes):
            continue
        ancestors.append(ident)
        pending.extend(element_source_ids(source))
    return tuple(ancestors)


def _ligne_unit(element, ligne, ordinal: int, owner_key: str, *, page=None):
    unit = deepcopy(element)
    unit.lignes = [deepcopy(ligne)]
    unit.bbox = ligne.bbox
    inherit_direction = _default_line_direction(ligne) and (
        element.orientation != "horizontal" or element.angle_deg or element.curved
    )
    copied_line = unit.lignes[0]
    for name in ("orientation", "angle_deg", "curved"):
        value = getattr(element if inherit_direction else ligne, name)
        setattr(unit, name, value)
        setattr(copied_line, name, value)
    if ligne.layout_frame_id:
        for name in ("layout_frame_id", "layout_frame_role", "layout_frame_strategy", "layout_frame_bbox"):
            setattr(unit, name, getattr(ligne, name))
    if ligne.layout_frame_role:
        unit.layout_frame_role = ligne.layout_frame_role
    if ligne.semantic_role:
        unit.semantic_role = ligne.semantic_role
    if isinstance(unit, FlowParagraph):
        unit.spans = list(unit.lignes[0].spans)
        unit.texte = "".join(span.texte for span in unit.spans)
    unit.source_ids = tuple(dict.fromkeys(
        value for value in (
            getattr(element, "source_id", None),
            *element_source_ids(ligne),
            *_verified_line_ancestors(page, element, ligne),
        ) if value
    ))
    unit.geometry = geometry_contract_for(unit)
    unit.presentation = dict(getattr(unit, "presentation", {}) or {})
    unit.presentation["segmentation_owner"] = owner_key
    if inherit_direction:
        unit.presentation["orientation_source"] = "source-block-fallback"
    return unit


def _fuser_groupe(group, *, validated_continuation=False):
    owners = {
        str((getattr(item, "presentation", {}) or {}).get("segmentation_owner", ""))
        for item in group
    }
    if len(owners) > 1 and not validated_continuation:
        return None
    lignes = []
    source_ids: list[str] = []
    for item in sorted(group, key=lambda value: (value.bbox.y0, value.bbox.x0)):
        lignes.extend(deepcopy(getattr(item, "lignes", ()) or ()))
        source_ids.extend(str(value) for value in getattr(item, "source_ids", ()) or ())
    if not lignes:
        return None
    lignes.sort(key=lambda value: (value.bbox.y0, value.bbox.x0))
    base = deepcopy(group[0])
    base.lignes = lignes
    base.bbox = paragraph_bbox_from_lines(lignes, fallback=base.bbox)
    visible_lines = [ligne for ligne in lignes if line_has_text(ligne)]
    frame_ids = {item.layout_frame_id for item in [*group, *visible_lines] if item.layout_frame_id}
    if len(frame_ids) > 1:
        base.layout_frame_id = None
        base.layout_frame_bbox = base.bbox
        for name in ("layout_frame_role", "layout_frame_strategy"):
            values = {getattr(item, name) for item in group}
            setattr(base, name, values.pop() if len(values) == 1 else None)
    base.source_ids = tuple(dict.fromkeys(source_ids))
    if base.source_ids:
        base.source_id = base.source_ids[0]
    base.geometry = geometry_contract_for(base)
    if isinstance(base, FlowParagraph):
        base.spans = [span for ligne in lignes for span in ligne.spans]
        base.texte = " ".join("".join(span.texte for span in ligne.spans) for ligne in lignes)
        first_span = next(span for span in base.spans if span.texte.strip())
        base.police, base.size_pt, base.couleur = first_span.police, first_span.size_pt, first_span.couleur
    base.presentation = dict(getattr(base, "presentation", {}) or {})
    base.presentation["semantic_group"] = "page-lines"
    base.presentation["line_count"] = len(visible_lines)
    base.presentation["segmentation_owners"] = sorted(owners)
    return base


def _owner(unit):
    return str((getattr(unit, "presentation", {}) or {}).get("segmentation_owner", ""))


def _groupes_ia(units, obstacles=(), protected=()):
    """Ask comprehension once per layout zone; a zone failure keeps the next ones.

    A zone holds every row of a detected frame, whatever its source block: the
    model decides paragraphs across blocks, and its groups are final. Without a
    decision the zone falls back to geometric segmentation per source block.
    """
    par_zone: dict[str, list] = {}
    for unit in units:
        par_zone.setdefault(unit.layout_frame_id or f"owner:{_owner(unit)}", []).append(unit)

    groupes_globaux, sans_decision = [], set()
    for zone, zone_units in par_zone.items():
        if len(zone_units) == 1:
            # One row has no boundary to decide: nothing for the model to understand.
            # It keeps the per-source-block segmentation, like undecided rows.
            zone_units[0].presentation["comprehension_ia"] = "sans-objet"
            sans_decision.add(id(zone_units[0]))
            continue
        groupes_locaux = _groupes_ia_local(zone_units, obstacles, protected)
        if groupes_locaux is None:
            sans_decision.update(id(unit) for unit in zone_units)
            for unit in zone_units:
                unit.presentation["comprehension_ia"] = "non-compris"
            continue
        for groupe in groupes_locaux:
            for unit in groupe:
                unit.presentation["ai_zone"] = zone
                unit.presentation["comprehension_ia"] = "compris"
        groupes_globaux.extend(groupes_locaux)
    # Undecided rows keep the per-source-block fallback: a block spanning two
    # zones is still segmented as one source.
    restants = [unit for unit in units if id(unit) in sans_decision]
    for owner in dict.fromkeys(_owner(unit) for unit in restants):
        owner_units = [unit for unit in restants if _owner(unit) == owner]
        groupes_globaux.extend(_segment_units(owner_units, obstacles, protected=protected))
    return groupes_globaux or None


def _groupes_ia_local(units, obstacles=(), protected=()):
    if not units:
        return None
    metadata = contexte_lignes_texte(units, metadonnees={
        "obstacles": [[b.x0, b.y0, b.x1, b.y1] for b in obstacles],
    })
    textes = [row["text"] for row in metadata["lines"]]
    decision = comprendre_segmentation_page(textes, metadonnees=metadata)
    if decision is None or not decision.line_groups:
        return None
    partition = [index for group in decision.line_groups for index in group]
    if (
        decision.action != "segment-page"
        or partition != list(range(len(units)))
        or any(tuple(sorted(group)) != tuple(group) for group in decision.line_groups)
        or any(tuple(group) != tuple(range(group[0], group[-1] + 1)) for group in decision.line_groups if group)
    ):
        warnings.warn("Segmentation IA invalide (couverture, ordre ou doublons); repli geometrique.", RuntimeWarning, stacklevel=2)
        return None
    groupes = []
    vus: set[int] = set()
    for indices in decision.line_groups:
        groupe = []
        for index in indices:
            if 0 <= index < len(units) and index not in vus:
                groupe.append(units[index])
                vus.add(index)
        if groupe:
            # AI cannot override an explicit separator or a geometric obstacle.
            groupes.extend(_segment_units(
                groupe, obstacles, ai_confirmed=decision.ai_used and not decision.fallback_used,
                protected=protected,
            ))
    for index, unit in enumerate(units):
        if index not in vus:
            groupes.append([unit])
    return groupes


def _style(unit):
    weights = Counter()
    for span in unit.lignes[0].spans:
        if span.texte.strip():
            key = (span.police.famille, span.police.gras, span.police.italique,
                   round(span.size_pt, 1), span.couleur)
            weights[key] += len(span.texte.strip())
    return weights.most_common(1)[0][0] if weights else (None, False, False, 0, None)


def _same_row(left, right):
    return axis_overlap_ratio(left.bbox, right.bbox, "y") >= 0.55


def _hard_frame_id(unit):
    frame_id = unit.layout_frame_id
    # _attacher_frames_texte uses this prefix for geometric, non-AI containers.
    return frame_id if frame_id and not frame_id.startswith("inferred:") else None


def _proven_body_continuity(previous, current):
    previous_text = "".join(span.texte for span in previous.lignes[0].spans)
    current_text = "".join(span.texte for span in current.lignes[0].spans)
    role = previous.semantic_role or previous.layout_frame_role
    return (
        previous.orientation == current.orientation == "horizontal"
        and not _same_row(previous, current)
        and previous.angle_deg == current.angle_deg
        and not previous.curved and not current.curved
        and role == (current.semantic_role or current.layout_frame_role)
        and role in {"text-column", "body", "text", "paragraph"}
        and styles_compatibles(previous, current)
        and est_texte_de_corps(previous_text) and est_texte_de_corps(current_text)
        and not ends_sentence(previous_text)
        and not starts_list_marker(previous_text) and not starts_list_marker(current_text)
        and commence_par_minuscule(current_text)
    )


def _connection_corridor(first, second, same_row):
    if same_row:
        left, right = sorted((first, second), key=lambda value: value.x0)
        corridor = BBox(left.x1, max(left.y0, right.y0), right.x0, min(left.y1, right.y1))
    else:
        corridor = BBox(max(first.x0, second.x0), first.y1, min(first.x1, second.x1), second.y0)
    return corridor if corridor.largeur > 0 and corridor.hauteur > 0 else None


def _crosses_validated(first, second, same_row, corridor, protected):
    for element in protected:
        bbox = element.bbox
        if corridor is not None and intersection_area(corridor, bbox) > 0:
            return True
        # An interleaved node also protects overlapping or touching text rows.
        if same_row:
            left, right = sorted((first, second), key=lambda value: value.x0)
            if (left.x0 < bbox.x0 < right.x0
                    and axis_overlap_ratio(left, bbox, "y") > 0
                    and axis_overlap_ratio(right, bbox, "y") > 0):
                return True
        elif (first.y0 < bbox.y0 < second.y0
              and axis_overlap_ratio(first, bbox, "x") > 0
              and axis_overlap_ratio(second, bbox, "x") > 0):
            return True
    return False


def _boundary(previous, current, step, obstacles, *, ai_confirmed=False, protected=(), last_frame_id=None):
    first, second = previous.bbox, current.bbox
    height = max(first.hauteur, second.hauteur, 1)
    if previous.orientation != current.orientation or previous.curved != current.curved:
        return "orientation-change"
    if previous.angle_deg != current.angle_deg:
        return "orientation-change"
    previous_id = previous.presentation.get("paragraph_id") if previous.presentation.get("paragraph_validated") else None
    current_id = current.presentation.get("paragraph_id") if current.presentation.get("paragraph_validated") else None
    if (previous_id or current_id) and previous_id != current_id:
        return "validated-paragraph"
    if (getattr(previous.lignes[-1], "boundary_after", None)
            or getattr(current.lignes[0], "boundary_before", None)):
        return "source-boundary"
    if hard_line_break(
        "".join(span.texte for span in previous.lignes[-1].spans),
        "".join(span.texte for span in current.lignes[0].spans),
    ):
        return "source-hard-break"
    previous_frame = _hard_frame_id(previous) or last_frame_id
    current_frame = _hard_frame_id(current)
    frame_change = previous_frame and current_frame and previous_frame != current_frame
    same_row = _same_row(previous, current)
    corridor = _connection_corridor(first, second, same_row)
    if _crosses_validated(first, second, same_row, corridor, protected):
        return "validated-paragraph"

    def contains(container, item):
        return (container.x0 <= item.x0 <= item.x1 <= container.x1
                and container.y0 <= item.y0 <= item.y1 <= container.y1)

    visual_obstacle = corridor is not None and any(
        intersection_area(corridor, obstacle) > 0
        and not (contains(obstacle, first) and contains(obstacle, second))
        for obstacle in obstacles
    )
    if current.presentation.get("blank_separator_before"):
        return "blank-separator"
    if starts_list_marker("".join(span.texte for span in current.lignes[0].spans)):
        return "list-item"
    role_a = previous.semantic_role or previous.layout_frame_role
    role_b = current.semantic_role or current.layout_frame_role
    headings = {"heading", "title", "subtitle", "header"}
    if role_a != role_b and (role_a in headings or role_b in headings):
        return "role-change"
    if same_row:
        left, right = sorted((first, second), key=lambda value: value.x0)
        if right.x0 - left.x1 > height * 3:
            return "horizontal-gap"
    elif second.y0 - first.y1 > max(height * 0.85, step * 0.85):
        return "vertical-gap"
    elif axis_overlap_ratio(first, second, "x") < 0.1:
        return "column-change"
    if visual_obstacle:
        return "visual-obstacle"
    # Frame changes are evidence, not semantic separators for proven prose.
    if frame_change and not _proven_body_continuity(previous, current):
        return "layout-frame-change"
    if same_row:
        return None
    previous_text = "".join(span.texte for span in previous.lignes[0].spans).rstrip()
    if second.x0 - first.x0 > height * 0.6 and ends_sentence(previous_text):
        return "paragraph-indent"
    style_a, style_b = _style(previous), _style(current)
    if style_a != style_b:
        size_change = abs(style_a[3] - style_b[3]) > max(style_a[3], style_b[3]) * 0.15
        aligned_differently = previous.lignes[0].alignement != current.lignes[0].alignement
        if (size_change or aligned_differently or ends_sentence(previous_text)
                or abs(second.x0 - first.x0) > height * 0.6):
            return "block-style-change"
    return None


def _segment_units(units, obstacles=(), *, ai_confirmed=False, protected=()):
    if not units:
        return []
    height = median(max(unit.bbox.hauteur, 1) for unit in units)
    steps = [b.bbox.y0 - a.bbox.y0 for a, b in zip(units, units[1:])
             if 0 < b.bbox.y0 - a.bbox.y0 <= height * 1.6]
    step = median(steps) if steps else height
    groups = [[units[0]]]
    frame_id = _hard_frame_id(units[0])
    for previous, current in zip(units, units[1:]):
        reason = _boundary(previous, current, step, obstacles, ai_confirmed=ai_confirmed,
                           protected=protected, last_frame_id=frame_id)
        current_frame = _hard_frame_id(current)
        if reason:
            current.presentation["boundary_before"] = reason
            groups.append([])
            frame_id = None
        groups[-1].append(current)
        frame_id = current_frame or frame_id
    return groups


def _join_source_fragments(groups, obstacles, protected=()):
    """A layout frame supports continuity, but never proves it on its own."""
    result = []
    for group in sorted(groups, key=lambda values: (values[0].bbox.y0, values[0].bbox.x0)):
        previous = result[-1][-1] if result else None
        first = group[0]
        candidates = [*(result[-1] if result else []), *group]
        continuation = (
            previous is not None
            and not any(unit.presentation.get("paragraph_validated") for unit in candidates)
            # Inside a zone judged by comprehension its paragraphs are final; the
            # junction between two zones was never judged and keeps its proof rules.
            and not (previous.presentation.get("ai_zone") is not None
                     and previous.presentation.get("ai_zone") == first.presentation.get("ai_zone"))
            and previous.presentation["segmentation_owner"] != first.presentation["segmentation_owner"]
            and all(unit.presentation.get("source_visible_line_count") == 1 for unit in candidates)
            and ((previous.layout_frame_id and previous.layout_frame_id == first.layout_frame_id)
                 or _proven_body_continuity(previous, first))
            and not first.presentation.get("boundary_before")
            and not ends_sentence("".join(span.texte for span in previous.lignes[0].spans))
            and _style(previous) == _style(first)
            and _boundary(previous, first, max(previous.bbox.hauteur, first.bbox.hauteur),
                          obstacles, protected=protected) is None
        )
        if continuation:
            result[-1].extend(group)
        else:
            result.append(group)
    return result


def _retain_blank_rows(source_lines, owner_units):
    """Bind raw whitespace to its source owner's visible units after grouping."""
    for ligne in source_lines:
        if line_has_text(ligne):
            continue
        same_row = [unit for unit in owner_units if axis_overlap_ratio(ligne.bbox, unit.bbox, "y") >= 0.55]
        if same_row:
            target = min(same_row, key=lambda unit: abs(unit.bbox.x0 - ligne.bbox.x0))
        else:
            target = next((unit for unit in owner_units if unit.bbox.y0 > ligne.bbox.y0), owner_units[-1])
        target.lignes.append(deepcopy(ligne))
        target.source_ids = tuple(dict.fromkeys((*target.source_ids, *element_source_ids(ligne))))


def segmenter_page_textes(page) -> None:
    """Segmente les blocs source non valides, puis joint les fragments continus.

    La comprehension IA est consultee par bloc source, avec repli geometrique
    local. Ses groupes respectent les cadres, separateurs et obstacles. Une
    fusion interblocs exige une continuite prouvee. Les paragraphes deja valides
    restent inchanges et protegent les frontieres de leurs voisins.
    """
    text_elements = [
        element
        for element in page.elements
        if isinstance(element, (TextBox, FlowParagraph)) and getattr(element, "lignes", ())
    ]
    if not text_elements:
        return
    protected = [element for element in text_elements if element.presentation.get("paragraph_validated")]
    if len(protected) == len(text_elements):
        return

    obstacles = tuple(
        element.bbox for element in page.elements
        if isinstance(element, (ImageEl, RasterEl, ShapeEl, TableEl))
        and element.bbox.largeur * element.bbox.hauteur < page.largeur_emu * page.hauteur_emu * 0.8
    )
    units = []
    blank_sources = []
    retained_blocks = set()
    ordinal = 0
    for element_index, element in enumerate(text_elements):
        source_lines = list(getattr(element, "lignes", ()))
        visible = [ligne for ligne in source_lines if line_has_text(ligne)]
        if element.presentation.get("paragraph_validated"):
            ordinal += len(visible)
            continue
        if not visible:
            retained_blocks.add(id(element))
            continue
        blanks = [ligne for ligne in source_lines if not line_has_text(ligne)
                  and not any(axis_overlap_ratio(ligne.bbox, other.bbox, "y") >= 0.55 for other in visible)]
        previous = None
        owner_units = []
        for ligne in sorted(visible, key=lambda value: (value.bbox.y0, value.bbox.x0)):
            unit = _ligne_unit(element, ligne, ordinal, f"element:{element_index}", page=page)
            unit.presentation["page_index"] = page.index
            unit.presentation["source_visible_line_count"] = len(visible)
            unit.presentation["source_spacing_before_emu"] = max(0, ligne.bbox.y0 - previous.bbox.y1) if previous else 0
            unit.presentation["blank_separator_before"] = bool(previous and any(
                previous.bbox.y0 < blank.bbox.y0 < ligne.bbox.y0 for blank in blanks))
            units.append(unit)
            owner_units.append(unit)
            ordinal += 1
            previous = ligne
        blank_sources.append((source_lines, owner_units))
    if not units:
        return

    units.sort(key=lambda value: (value.bbox.y0, value.bbox.x0))
    groupes = _groupes_ia(units, obstacles, protected)
    if groupes is None:
        groupes = []
        owners = dict.fromkeys(unit.presentation["segmentation_owner"] for unit in units)
        for owner in owners:
            local = [unit for unit in units if unit.presentation["segmentation_owner"] == owner]
            groupes.extend(_segment_units(local, obstacles, protected=protected))

    groupes = _join_source_fragments([*groupes, *([element] for element in protected)], obstacles, protected)
    # Keep separators as exact source children, without making them AI units or
    # changing the already established visible groups and their geometry.
    for source_lines, owner_units in blank_sources:
        _retain_blank_rows(source_lines, owner_units)
    fusionnes = [
        fusion
        for groupe in groupes
        if (fusion := (groupe[0] if groupe[0].presentation.get("paragraph_validated")
                       else _fuser_groupe(groupe, validated_continuation=True))) is not None
    ]
    used_ids = {
        value for element in text_elements
        for value in (element.source_id, element.presentation.get("paragraph_id")) if value
    }
    index = 0
    for element in fusionnes:
        if element.presentation.get("paragraph_validated"):
            continue
        while f"page:{page.index}:paragraph:{index}" in used_ids:
            index += 1
        paragraph_id = f"page:{page.index}:paragraph:{index}"
        used_ids.add(paragraph_id)
        index += 1
        element.source_id = paragraph_id
        element.presentation["paragraph_id"] = paragraph_id
        element.presentation["paragraph_validated"] = True
    text_node_ids = {id(element) for element in text_elements if id(element) not in retained_blocks}
    autres = [element for element in page.elements if id(element) not in text_node_ids]
    page.elements = sorted(
        [*autres, *fusionnes],
        key=lambda element: (
            getattr(getattr(element, "bbox", None), "y0", 0),
            getattr(getattr(element, "bbox", None), "x0", 0),
        ),
    )
