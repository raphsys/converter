"""Prepared text runs and their OOXML materialization."""
from dataclasses import dataclass, replace

from pdfexact.geometry import emu_vers_pt, pt_vers_emu


@dataclass(frozen=True)
class RunInstruction:
    span: object | None = None
    command: str = ""
    width_percent: int = 100


def _adjusted_spans(line):
    spans = list(line.spans)
    count = len("".join(str(span.texte or "") for span in spans).replace("\n", "").replace("\r", ""))
    if count < 2 or line.bbox.largeur <= 0:
        return spans
    estimated = sum(len(str(span.texte or "").replace("\n", "").replace("\r", "")) * float(span.size_pt) * (0.57 if span.police.gras else 0.53) for span in spans)
    excess = estimated - emu_vers_pt(line.bbox.largeur)
    correction = (-2 if count >= 80 else -1) if excess <= 0.15 and count >= 48 else max(-8, min(0, round(-excess * 20 / max(count - 1, 1)))) if excess > 0.15 else 0
    return [replace(span, espacement_twips=int(span.espacement_twips or 0) + correction) for span in spans]


def leader_spans(spans):
    """Split a leader row into (label spans, page spans); None for other rows.

    The leader glyphs are dropped: a right tab stop with the same leader draws
    them at any font width, so the page number stays on the source edge."""
    from pdfexact.analysis.line_structure import LEADER_RE

    text = "".join(span.texte for span in spans)
    match = LEADER_RE.match(text)
    if match is None:
        return None
    label_end = match.start("label") + len(match.group("label").rstrip())
    page_start, page_end = match.start("page"), match.end("page")

    def cut(start, end):
        kept, offset = [], 0
        for span in spans:
            low, high = max(start, offset), min(end, offset + len(span.texte))
            if low < high:
                kept.append(replace(span, texte=span.texte[low - offset:high - offset]))
            offset += len(span.texte)
        return kept

    return cut(0, label_end), cut(page_start, page_end)


def prepare_runs(element, lines, composition, *, native=False, adjust=False, preserve=False, measured=False, leaders=False):
    result = []
    previous = ""
    for index, line in enumerate(lines):
        spans = [replace(span) for span in line.spans if span.texte]
        if not spans:
            continue
        current = "".join(span.texte for span in spans)
        action = composition.action_between(index - 1) if native else (composition.joins[index - 1] if index and index - 1 < len(composition.joins) else "space")
        if preserve:
            action = "preserve_break"
        if index:
            if action == "hyphen_join" and result and result[-1].span is not None:
                last = result[-1]
                if last.span.texte.endswith(("-", "\u00ac")):
                    result[-1] = replace(last, span=replace(last.span, texte=last.span.texte[:-1]))
            elif action in {"preserve_break", "paragraph_break"}:
                result.extend([RunInstruction(command="break")] * (2 if action == "paragraph_break" else 1))
            elif (action != "no_space" and previous and current and not previous[-1].isspace()
                  and not current[0].isspace() and current[0] not in ".,;:!?)]}%"
                  and (native or not previous.rstrip().endswith(("-", "/")))):
                result.append(RunInstruction(command="space"))
        if native:
            indent = line.bbox.x0 > element.bbox.x0 + pt_vers_emu(0.5) and (not index or action in {"preserve_break", "paragraph_break"})
        else:
            indent = line.bbox.x0 - element.bbox.x0 > pt_vers_emu(3) and not getattr(element, "list_marker", None)
            if adjust and not measured:
                adjusted = _adjusted_spans(line)
                spans = [span for span in adjusted if span.texte]
        if indent:
            result.append(RunInstruction(command="tab"))
        scale = composition.line_width_scale_percent[index] if (native or measured) and index < len(composition.line_width_scale_percent) else 100
        spacing = composition.line_spacing_twips[index] if (native or measured) and index < len(composition.line_spacing_twips) else 0
        split = leader_spans(spans) if leaders else None
        groups = ((split[0], RunInstruction(command="tab"), split[1]) if split else (spans,))
        for group in groups:
            if isinstance(group, RunInstruction):
                result.append(group)
                continue
            for span in group:
                result.append(RunInstruction(replace(span, espacement_twips=0 if scale != 100 else int(span.espacement_twips or 0) + spacing), width_percent=scale))
        previous = current
    return tuple(result)


def render_runs(instructions, relations=None):
    from pdfexact.render.drawing import _run_xml

    commands = {
        "break": "<w:r><w:br/></w:r>",
        "tab": "<w:r><w:tab/></w:r>",
        "space": '<w:r><w:t xml:space="preserve"> </w:t></w:r>',
    }
    return "".join(
        _run_xml(item.span, relations, autoriser_espacement_negatif=True, largeur_pct=item.width_percent)
        if item.span is not None else commands[item.command]
        for item in instructions
    )
