"""Text instructions compiled before rendering, with pure XML consumers."""
from dataclasses import dataclass
from copy import copy
from xml.dom import minidom

from pdfexact.geometry import emu_vers_pt
from pdfexact.layout.paragraph_planner import planifier_paragraphe
from pdfexact.render.geometry_adapter import prepare_text_geometry, twips
from pdfexact.render.orientation_backend import prepare_orientation
from pdfexact.render.text_runs import RunInstruction, prepare_runs, render_runs


@dataclass(frozen=True)
class TextInstructions:
    composition: object
    geometry: object
    orientation: object
    flow_runs: tuple
    frame_runs: tuple
    native_runs: tuple
    slices: tuple
    vertical_lines: tuple


def prepare_text_instructions(element, polices=None, occupied_bboxes=(), *, preserve_line_boundaries=False, column_right=None):
    from pdfexact.render.reflow import _lines, render_visible_lines
    from pdfexact.render.text_runs import leader_spans

    lines = sorted(render_visible_lines(element), key=lambda line: (line.bbox.y0, line.bbox.x0))
    # Legacy FlowParagraph objects may carry only flat runs.
    source = copy(element)
    source.lignes = lines
    if hasattr(source, "spans"):
        source.spans = [span for line in lines for span in line.spans]
    composition = planifier_paragraphe(source, polices=polices, column_right=column_right)
    if preserve_line_boundaries:
        from dataclasses import replace
        composition = replace(composition, preserve_lines=True)
    geometry, compact = prepare_text_geometry(source, lines, composition, occupied_bboxes)
    orientation = prepare_orientation(source, lines)
    measured = bool(polices)
    def slice_tokens(line):
        spans = [span for span in line.spans if span.texte]
        split = leader_spans(spans)
        if split is None:
            return tuple(RunInstruction(span) for span in spans)
        return (*(RunInstruction(span) for span in split[0]), RunInstruction(command="tab"),
                *(RunInstruction(span) for span in split[1]))

    slices = tuple(
        (max(twips(line.bbox.x0 - geometry.bbox.x0), 0), max(twips(geometry.bbox.x1 - line.bbox.x1), 0),
         max(twips(line.hauteur_ligne_emu), 1), slice_tokens(line))
        for line in lines
    )
    vertical_lines = tuple(
        (max(round(max((float(span.size_pt or 0) for span in line.spans if span.texte), default=8.0) * 1.12 * 20), 1),
         tuple(RunInstruction(span) for span in line.spans if span.texte))
        for line in lines
    )
    native_runs = prepare_runs(source, lines, composition, native=True, leaders=True)
    marker = getattr(source, "list_marker_source", None)
    if marker is not None:
        marker_runs = tuple(RunInstruction(span) for line in _lines(marker) for span in line.spans if span.texte)
        native_runs = (*marker_runs, *native_runs)
    return TextInstructions(
        composition, geometry, orientation,
        prepare_runs(source, lines, composition, adjust=compact, preserve=compact or preserve_line_boundaries, measured=measured),
        prepare_runs(source, lines, composition, adjust=True, preserve=preserve_line_boundaries, measured=measured, leaders=True),
        native_runs, slices, vertical_lines,
    )


def _list_xml(text, element, numbering):
    if numbering is None or not getattr(element, "list_marker", None):
        return "", ""
    num_id = numbering.num_id(element)
    geometry = text.geometry
    indent = f'<w:ind w:left="{geometry.list_left}" w:hanging="{geometry.list_left}"/>' if geometry.list_left else ""
    return f'<w:numPr><w:ilvl w:val="{geometry.list_level}"/><w:numId w:val="{num_id}"/></w:numPr>', indent


def render_flow(text, element, page, before_emu, relations, numbering=None):
    g = text.geometry
    runs = render_runs(text.flow_runs, relations)
    if not runs:
        return ""
    numbering_xml, list_indent = _list_xml(text, element, numbering)
    first_line = f'w:hanging="{g.list_left}"' if list_indent else 'w:firstLine="0"'
    return (
        '<w:p><w:pPr><w:keepLines/>' + numbering_xml
        + f'<w:spacing w:before="{max(twips(before_emu), 0)}" w:after="0" w:line="{g.line_height}" w:lineRule="exact"/>'
        + f'<w:ind w:left="{max(twips(g.bbox.x0), 0)}" w:right="{max(twips(page.largeur_emu - g.bbox.x1), 0)}" {first_line}/>'
        + f'<w:jc w:val="{g.alignment}"/></w:pPr>{runs}</w:p>'
    )


def _positioned_runs(instructions, width, relations):
    runs = render_runs(instructions, relations)
    if not runs:
        return ""
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with minidom.parseString(
        f'<runs xmlns:w="{namespace}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">{runs}</runs>'
    ) as document:
        if not any(node.firstChild and node.firstChild.data.strip()
                   for node in document.getElementsByTagNameNS(namespace, "t")):
            return runs
        if document.getElementsByTagNameNS(namespace, "tab"):
            raise ValueError("unsupported-fit-text:positioned-tab")
        group = 0
        # Fit one line jointly across styled runs, without fitting a line break
        # or assigning the entire frame width independently to every fragment.
        for run in list(document.getElementsByTagNameNS(namespace, "r")):
            properties = next((node for node in run.childNodes if node.localName == "rPr"), None)
            segments, content = [], []
            for node in run.childNodes:
                if node is properties:
                    continue
                if node.localName == "br":
                    if content:
                        segments.append((False, content))
                        content = []
                    segments.append((True, [node]))
                else:
                    content.append(node)
            if content:
                segments.append((False, content))
            for line_break, nodes in segments:
                fitted = run.cloneNode(False)
                if properties is not None:
                    fitted.appendChild(properties.cloneNode(True))
                for node in nodes:
                    fitted.appendChild(node.cloneNode(True))
                if not line_break and fitted.getElementsByTagNameNS(namespace, "t"):
                    props = next((node for node in fitted.childNodes if node.localName == "rPr"), None)
                    if props is None:
                        props = document.createElementNS(namespace, "w:rPr")
                        fitted.insertBefore(props, fitted.firstChild)
                    fit = document.createElementNS(namespace, "w:fitText")
                    fit.setAttributeNS(namespace, "w:val", str(width))
                    fit.setAttributeNS(namespace, "w:id", str(group))
                    props.appendChild(fit)
                run.parentNode.insertBefore(fitted, run)
                if line_break:
                    group += 1
            if segments:
                run.parentNode.removeChild(run)
        return "".join(node.toxml() for node in document.documentElement.childNodes)


def render_positioned(text, element, relations, numbering=None):
    g = text.geometry
    width = max(twips(g.bbox.largeur), 1)
    runs = _positioned_runs(text.flow_runs, width, relations)
    if not runs:
        return ""
    numbering_xml, indent = _list_xml(text, element, numbering)
    return (
        f'<w:p><w:pPr><w:keepLines/><w:framePr w:w="{width}" w:h="{g.frame_height}" w:x="{max(twips(g.bbox.x0), 0)}" w:y="{max(twips(g.bbox.y0), 0)}" '
        f'w:hAnchor="page" w:vAnchor="page" w:wrap="none" w:anchorLock="0" w:hRule="{g.frame_rule}"/>'
        + numbering_xml
        + f'<w:spacing w:before="0" w:after="0" w:line="{g.line_height}" w:lineRule="exact"/>'
        + indent + f'<w:jc w:val="{g.alignment}"/></w:pPr>{runs}</w:p>'
    )


def _tabs_xml(g, *, indents=True):
    """Tab stops: left stops for source indents, right stops for leader rows."""
    stops = [f'<w:tab w:val="left" w:pos="{max(position, 1)}"/>' for position in (g.tabs if indents else ())]
    stops += [f'<w:tab w:val="right" w:leader="{leader}" w:pos="{position}"/>' for position, leader in g.leader_tabs]
    return '<w:tabs>' + ''.join(stops) + '</w:tabs>' if stops else ""


def render_native_paragraph(text, relations=None, *, positioned=True):
    g = text.geometry
    runs = render_runs(text.native_runs, relations)
    if not runs:
        return ""
    frame = (
        f'<w:framePr w:w="{max(twips(g.bbox.largeur), 1)}" w:h="{g.native_height}" w:x="{max(twips(g.bbox.x0), 0)}" w:y="{max(twips(g.bbox.y0), 0)}" '
        'w:hAnchor="page" w:vAnchor="page" w:wrap="none" w:anchorLock="0" w:hRule="atLeast"/>'
    ) if positioned else ""
    tabs = _tabs_xml(g)
    return (
        f'<w:p><w:pPr><w:keepLines/>{frame}<w:widowControl/>{tabs}'
        f'<w:spacing w:before="0" w:after="0" w:line="{g.native_line_height}" w:lineRule="exact"/>'
        f'<w:jc w:val="{g.alignment}"/></w:pPr>{runs}</w:p>'
    )


def _vertical_content(text, relations):
    parts = []
    for index, (spacing, tokens) in enumerate(text.vertical_lines):
        runs = render_runs(tokens, relations)
        if runs:
            if index:
                parts.append('<w:r><w:br/></w:r>')
            parts.append(f'<w:p><w:pPr><w:keepLines/><w:spacing w:before="0" w:after="0" w:line="{spacing}" w:lineRule="exact"/></w:pPr>{runs}</w:p>')
    return "".join(parts)


def _frame_content(text, element, relations, numbering):
    g = text.geometry
    if text.orientation.vertical:
        return _vertical_content(text, relations)
    if g.kind in {"exclusion-flow", "variable-width-flow"}:
        leaders = _tabs_xml(g, indents=False)
        return "".join(
            f'<w:p><w:pPr><w:keepLines/>{leaders}<w:spacing w:before="0" w:after="0" w:line="{spacing}" w:lineRule="exact"/>'
            f'<w:ind w:left="{left}" w:right="{right}" w:firstLine="0"/>'
            f'<w:jc w:val="{g.alignment}"/></w:pPr>{render_runs(tokens, relations)}</w:p>'
            for left, right, spacing, tokens in text.slices if tokens
        )
    runs = render_runs(text.frame_runs, relations)
    numbering_xml, indent = _list_xml(text, element, numbering) if runs else ("", "")
    return (
        '<w:p><w:pPr><w:keepLines/>' + numbering_xml + _tabs_xml(g, indents=False)
        + f'<w:spacing w:before="0" w:after="0" w:line="{g.line_step}" w:lineRule="exact"/>'
        + indent + f'<w:jc w:val="{g.alignment}"/></w:pPr>{runs}</w:p>'
    ) if runs else ""


def render_vml(text, identifiant, z, relations, *, include_shape_type=True):
    bbox, orientation = text.geometry.bbox, text.orientation
    width, height = max(emu_vers_pt(bbox.largeur), 1.0), max(emu_vers_pt(bbox.hauteur), 1.0)
    inner_width, inner_height = (height, width) if orientation.vertical else (width, height)
    x = emu_vers_pt(max(bbox.x0, 0)) + (width - inner_width) / 2
    y = emu_vers_pt(max(bbox.y0, 0)) + (height - inner_height) / 2
    type_xml = '<v:shapetype id="_x0000_t202" coordsize="21600,21600" o:spt="202" path="m,l,21600r21600,l21600,xe"><v:stroke joinstyle="miter"/><v:path gradientshapeok="t" o:connecttype="rect"/></v:shapetype>' if include_shape_type else ""
    style = (
        f'position:absolute;margin-left:{x:.3f}pt;margin-top:{y:.3f}pt;width:{inner_width:.3f}pt;height:{inner_height:.3f}pt;'
        f'rotation:{orientation.vml_rotation};z-index:{max(z, 1)};'
        'mso-position-horizontal:absolute;mso-position-horizontal-relative:page;mso-position-vertical:absolute;mso-position-vertical-relative:page;'
        'mso-wrap-style:none;mso-wrap-distance-left:0;mso-wrap-distance-right:0;mso-wrap-distance-top:0;mso-wrap-distance-bottom:0;'
    )
    return (
        f'<w:pict>{type_xml}<v:shape id="vertical_text_{identifiant}" o:spid="_x0000_s{identifiant}" type="#_x0000_t202" o:allowincell="f" filled="f" stroked="f" style="{style}visibility:visible;">'
        '<v:textbox inset="0,0,0,0" style="mso-fit-shape-to-text:n;mso-word-wrap:off;">'
        f'<w:txbxContent>{_vertical_content(text, relations)}</w:txbxContent></v:textbox><w10:wrap type="none"/></v:shape></w:pict>'
    )


def render_frame(text, element, identifiant, z, relations, numbering=None, *, layered=False, include_vml_shape_type=True, behind_doc=False):
    from pdfexact.render.drawing import _ancre

    g, o = text.geometry, text.orientation
    native_layer = layered and not o.special
    content = render_native_paragraph(text, relations, positioned=False) if native_layer else _frame_content(text, element, relations, numbering)
    width = max(g.bbox.hauteur if o.vertical else g.bbox.largeur, 1)
    height = max(g.bbox.largeur if o.vertical else g.bbox.hauteur, 1)
    warp = f'<a:prstTxWarp prst="{o.warp}"><a:avLst/></a:prstTxWarp>' if o.warp else ""
    transform = '<a:xfrm>' if native_layer else '<a:xfrm rot="0">'
    body = (
        '<wps:bodyPr rot="0" wrap="square" vertOverflow="overflow" horzOverflow="overflow" '
        'lIns="0" tIns="0" rIns="0" bIns="0" anchor="t"><a:noAutofit/></wps:bodyPr>'
    ) if native_layer else (
        f'<wps:bodyPr rot="{o.body_rotation}" vert="{o.body_vertical}" wrap="none" vertOverflow="overflow" horzOverflow="overflow" '
        f'lIns="0" tIns="0" rIns="0" bIns="0" anchor="t">{warp}<a:noAutofit/></wps:bodyPr>'
    )
    graphic = (
        '<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        '<wps:wsp><wps:cNvSpPr txBox="1"/><wps:spPr>'
        f'{transform}<a:off x="0" y="0"/><a:ext cx="{width}" cy="{height}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></wps:spPr>'
        f'<wps:txbx><w:txbxContent>{content}</w:txbxContent></wps:txbx>{body}</wps:wsp></a:graphicData></a:graphic>'
    )
    drawing = _ancre(g.bbox, identifiant, z, f'Editable text {identifiant}', graphic, behind_doc)
    if not o.special:
        return drawing
    return (
        '<mc:AlternateContent><mc:Choice Requires="wps">' + drawing + '</mc:Choice><mc:Fallback>'
        + render_vml(text, identifiant, z, relations, include_shape_type=include_vml_shape_type)
        + '</mc:Fallback></mc:AlternateContent>'
    )
