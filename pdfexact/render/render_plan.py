"""Construction du plan de rendu unique a partir de la scene canonique."""
from __future__ import annotations

from dataclasses import dataclass, replace
from copy import copy, deepcopy

from pdfexact.analysis.decisions import RenderDecision, decider_mode_universel, verifier_decision
from pdfexact.analysis.options import AnalysisOptions
from pdfexact.analysis.semantic import annotate_semantic_features, text_paint_fragments
from pdfexact.analysis.provenance import observation_is_preserved, observation_nodes, observation_signature, source_paint_index
from pdfexact.analysis.ocr_correspondence import (
    RELATIONSHIP as OCR_OBSERVATION_RELATIONSHIP,
    page_binding_for,
    source_snapshot_matches,
    verify_ocr_native_correspondence,
)
from pdfexact.scene import ElementKind, ElementRecord, SceneDocument, enregistrer_decision, scene_from_legacy_document
from pdfexact.render.reflow import prepare_document_elements
from pdfexact.geometry import quantifier_bbox, pt_vers_emu
from pdfexact.render.text_backend import prepare_text_instructions
from pdfexact.analysis.text_geometry import (
    geometry_contract_for,
    geometry_kind,
    line_has_text,
    line_has_whitespace_paint,
    orientation_of,
    paragraph_bbox_from_lines,
)


@dataclass(frozen=True)
class AnchorSpec:
    z: int
    behind_doc: bool = False


@dataclass(frozen=True)
class RenderInstruction:
    element: object
    kind: ElementKind
    container: str
    anchor: AnchorSpec
    text: object | None = None
    before_emu: int = 0
    bbox_container: str = ""
    paint_order: tuple[int, int] = (0, 0)
    instruction_id: str = ""


@dataclass(frozen=True)
class Materialization:
    fragments: tuple[RenderInstruction, ...]


@dataclass(frozen=True)
class SourceCoverage:
    target_ids: tuple[str, ...]
    relationship: str
    reason: str


@dataclass(frozen=True)
class PlannedElement:
    page_index: int
    source_index: int
    element: ElementRecord
    decision: RenderDecision
    materialization: Materialization | None = None


@dataclass
class RenderPlan:
    pages: dict[int, list[PlannedElement]]
    options: AnalysisOptions
    divergences: list[str] | None = None
    elements_by_page: dict[int, list[object]] | None = None
    instructions_by_page: dict[int, tuple[RenderInstruction, ...]] | None = None
    source_inventory: dict[str, ElementRecord] | None = None
    source_coverage: dict[str, SourceCoverage] | None = None
    media_snapshot: dict[str, object] | None = None

    def instructions_for_page(self, page_index: int) -> tuple[RenderInstruction, ...]:
        if self.instructions_by_page is None or page_index not in self.instructions_by_page:
            raise ValueError(f"missing-materialization-schedule:{page_index}")
        return self.instructions_by_page[page_index]

    def for_page(self, page_index: int) -> list[PlannedElement]:
        return self.pages.get(page_index, [])

    def for_index(self, page_index: int, source_index: int) -> PlannedElement | None:
        return next(
            (
                item
                for item in self.for_page(page_index)
                if item.source_index == source_index
            ),
            None,
        )

    def decision_for(self, page_index: int, source_index: int) -> RenderDecision | None:
        item = self.for_index(page_index, source_index)
        return item.decision if item else None

    def elements_for_page(self, page_index: int) -> list[object] | None:
        if self.elements_by_page is None:
            return None
        return self.elements_by_page.get(page_index)

    def for_element(self, element_id: str) -> PlannedElement | None:
        return next(
            (item for page in self.pages.values() for item in page if item.element.element_id == element_id),
            None,
        )

    def validate(self, document=None) -> list[str]:
        """Pure validation of source coverage and the compiled materialization."""
        errors: list[str] = []
        seen: set[str] = set()
        instruction_ids: set[str] = set()
        targets = {}
        for page_index, items in self.pages.items():
            indices = [item.source_index for item in items]
            expected = self.elements_for_page(page_index)
            if expected is not None and sorted(indices) != list(range(len(expected))):
                errors.append(f"incomplete-plan-coverage:{page_index}")
            if len(indices) != len(set(indices)):
                errors.append(f"duplicate-plan-index:{page_index}")
            for item in items:
                record = item.element
                targets[record.element_id] = item
                if item.page_index != page_index or record.page_index != page_index:
                    errors.append(f"plan-page-mismatch:{page_index}:{item.source_index}")
                if record.element_id in seen:
                    errors.append(f"duplicate-plan-element:{record.element_id}")
                seen.add(record.element_id)
                if item.materialization is None or not item.materialization.fragments:
                    errors.append(f"missing-materialization:{record.element_id}")
                else:
                    for instruction in item.materialization.fragments:
                        if not instruction.instruction_id or instruction.instruction_id in instruction_ids:
                            errors.append(f"invalid-materialization-id:{record.element_id}")
                        instruction_ids.add(instruction.instruction_id)
                        if instruction.kind is not record.kind:
                            errors.append(f"materialization-kind-mismatch:{record.element_id}")
                        if instruction.kind is ElementKind.TEXT and instruction.text is None:
                            errors.append(f"missing-text-instructions:{record.element_id}")
                        elif instruction.kind is ElementKind.TEXT and not instruction.text.native_runs:
                            errors.append(f"empty-text-materialization:{record.element_id}")
                        if instruction.container == "unsupported":
                            errors.append(f"unsupported-materialization:{record.element_id}")
                errors.extend(f"{page_index}:{item.source_index}:{error}" for error in verifier_decision(item.decision, record))
            compiled = [instruction for item in items if item.materialization for instruction in item.materialization.fragments]
            scheduled = (self.instructions_by_page or {}).get(page_index, ())
            if sorted(map(id, compiled)) != sorted(map(id, scheduled)):
                errors.append(f"incomplete-materialization-schedule:{page_index}")
        inventory = self.source_inventory or {}
        coverage = self.source_coverage or {}
        acquired_lines = _acquired_text_line_order(inventory)
        for item in targets.values():
            if item.element.kind is not ElementKind.TEXT or item.materialization is None:
                continue
            errors.extend(_text_component_order_errors(
                item, (self.instructions_by_page or {}).get(item.page_index, ()), inventory, acquired_lines,
            ))
        media = getattr(document, "media", {}) if document is not None else self.media_snapshot or {}
        if targets and not inventory:
            errors.append("missing-source-inventory")
        for source_id, source in inventory.items():
            outcome = coverage.get(source_id)
            if outcome is None:
                errors.append(f"uncovered-source:{source_id}")
                continue
            if not outcome.reason:
                errors.append(f"missing-coverage-reason:{source_id}")
            if outcome.relationship not in {"retained", "transformed", "duplicate", "raster-replacement", "non-representable", OCR_OBSERVATION_RELATIONSHIP}:
                errors.append(f"unknown-coverage-relationship:{source_id}")
            if outcome.relationship == "non-representable":
                if not _explicit_nonrepresentable(source) or outcome.target_ids:
                    errors.append(f"unproven-nonrepresentable:{source_id}")
                continue
            mapped = [targets[target] for target in outcome.target_ids if target in targets]
            if not mapped or len(mapped) != len(outcome.target_ids):
                errors.append(f"missing-coverage-target:{source_id}")
                continue
            if any(item.page_index != source.page_index for item in mapped):
                errors.append(f"coverage-page-mismatch:{source_id}")
            fragment_ids = {id(instruction) for item in mapped if item.materialization
                            for instruction in item.materialization.fragments}
            outputs = [instruction.element for instruction in (self.instructions_by_page or {}).get(source.page_index, ())
                       if id(instruction) in fragment_ids]
            if outcome.relationship == OCR_OBSERVATION_RELATIONSHIP:
                errors.extend(f"unverified-ocr-native-correspondence:{source_id}:{error}"
                              for error in _ocr_correspondence_errors(source, mapped, inventory))
                continue
            crop_errors = _media_crop_partition_errors(source, outputs, media)
            if crop_errors is not None:
                errors.extend(f"unverified-media-crop:{source_id}:{error}" for error in crop_errors)
                continue
            if outcome.relationship == "raster-replacement":
                if not all(_raster_replacement_traceable(source, item, inventory, self.options) for item in mapped):
                    errors.append(f"untraceable-raster-replacement:{source_id}")
                # Producer provenance is not a measurement of output pixels.
                errors.append(f"unverified-raster-replacement:{source_id}")
                continue
            equivalent = outcome.relationship == "duplicate"
            if equivalent and not _duplicate_proven(source, inventory):
                errors.append(f"unverified-duplicate:{source_id}")
            if equivalent:
                pair = _duplicate_parent(source, inventory)
                if pair and not any(pair[1].element_id in item.element.source_ids or pair[1].element_id == item.element.element_id for item in mapped):
                    errors.append(f"duplicate-winner-not-materialized:{source_id}")
            if not observation_is_preserved(source.raw, outputs, equivalent=equivalent):
                errors.append(f"unverified-source-transform:{source_id}")
        for source_id in set(coverage) - set(inventory):
            errors.append(f"unknown-coverage-source:{source_id}")
        if document is not None:
            expected_pages = {page.index for page in document.pages}
            if set(self.pages) != expected_pages:
                errors.append("incomplete-plan-pages")
            current_sources = _document_source_nodes(document, errors)
            for source_id, raw in current_sources.items():
                stored = inventory.get(source_id)
                if stored is None:
                    errors.append(f"missing-source-inventory:{source_id}")
                elif (observation_signature(raw) != observation_signature(stored.raw or stored)
                      and not _expanded_text_source(stored.raw, raw)
                      and not _attached_list_marker_source(stored.raw, raw, inventory)):
                    errors.append(f"source-mutated-after-plan:{source_id}")
            errors.extend(_ocr_document_snapshot_errors(document, current_sources, inventory, coverage, targets))
        return list(dict.fromkeys(errors))


def _acquired_text_line_order(inventory):
    from pdfexact.ir import Line
    from pdfexact.analysis.provenance import observation_children

    # Inventory entries mirror descendants as independent snapshots. Traverse
    # each acquired tree once, retaining its structural order and multiplicity.
    descendants = {getattr(node, "source_id", None) for source in inventory.values()
                   for child in observation_children(source.raw) for node in observation_nodes(child)}
    ordered = [node.source_id for ident, source in inventory.items() if ident not in descendants
               for node in observation_nodes(source.raw) if type(node) is Line]
    # Later container snapshots can mirror an already acquired Line. Only the
    # source expectation is deduplicated; every live occurrence is checked.
    return list(dict.fromkeys(ordered))


def _text_component_order_errors(item, schedule, inventory, acquired_lines):
    from pdfexact.ir import Line

    fragments = {id(instruction) for instruction in item.materialization.fragments}
    outputs = [instruction.element for instruction in schedule if id(instruction) in fragments]
    bound = getattr(item.element.raw, "list_marker_source", None)
    attached = [getattr(output, "list_marker_source", None) for output in outputs]
    attached = [child for child in attached if child is not None]
    auxiliary_lines = ()
    if bound is not None:
        ident = getattr(bound, "source_id", None)
        source = inventory.get(ident)
        if (source is None or source.page_index != item.page_index or len(attached) != 1
                or type(bound) is not type(source.raw)
                or not observation_is_preserved(source.raw, [bound])
                or type(attached[0]) is not type(source.raw)
                or getattr(attached[0], "source_id", None) != ident
                or not observation_is_preserved(source.raw, attached)):
            return [f"unverified-text-auxiliary:{item.element.element_id}"]
        auxiliary_lines = tuple(node.source_id for node in observation_nodes(source.raw) if type(node) is Line)
    elif attached:
        return [f"unbound-text-auxiliary:{item.element.element_id}"]
    actual = [node.source_id for output in outputs for node in observation_nodes(output)
              if type(node) is Line and node.source_id not in auxiliary_lines]
    expected = [ident for ident in acquired_lines if ident in actual and ident not in auxiliary_lines]
    return [] if actual == expected else [f"text-component-order:{item.element.element_id}"]


def _expanded_text_source(source, output):
    from pdfexact.ir import FlowParagraph, TextBox

    return (isinstance(source, (TextBox, FlowParagraph)) and isinstance(output, (TextBox, FlowParagraph))
            and len(output.lignes) > len(source.lignes)
            and observation_is_preserved(source, [output]))


def _attached_list_marker_source(source, output, inventory):
    """Prepared bodies keep their identity when a proven marker is attached."""
    from pdfexact.analysis.geometry import union_many
    from pdfexact.ir import FlowParagraph, TextBox

    marker = getattr(output, "list_marker_source", None)
    if (marker is None or getattr(source, "list_marker_source", None) is not None
            or getattr(output, "transformation", None) != "list-marker-attachment"
            or not isinstance(source, (TextBox, FlowParagraph)) or type(output) is not type(source)
            or len(output.lignes) != len(source.lignes)):
        return False
    # The marker must be an acquired source, and it alone explains the new extent.
    stored = inventory.get(getattr(marker, "source_id", None))
    return (stored is not None and type(stored.raw) is type(marker)
            and observation_is_preserved(stored.raw, [marker])
            and output.bbox == union_many((source.bbox, marker.bbox))
            and observation_is_preserved(source, [output]))


def _document_source_nodes(document, errors):
    """Read existing identities only; validation never repairs the document."""
    if any((getattr(node, "source_id", None) is None and getattr(node, "element_id", None) is None)
           or getattr(node, "source_kind", None) is None
           or getattr(node, "source_page_index", None) is None
           for page in document.pages for root in [*page.elements, *getattr(page, "discarded_elements", ())]
           for node in observation_nodes(root)):
        from pdfexact.scene import capture_source_observations

        document = deepcopy(document)
        for page in document.pages:
            capture_source_observations(page, [*page.elements, *getattr(page, "discarded_elements", ())])
    result = {}
    for page in document.pages:
        roots = [*page.elements, *getattr(page, "discarded_elements", ()), *getattr(page, "source_inventory", {}).values()]
        for root in roots:
            raw = getattr(root, "raw", None) or root
            for node in observation_nodes(raw):
                source_id = getattr(node, "source_id", None) or getattr(node, "element_id", None)
                if source_id is None:
                    errors.append(f"unidentified-source:{page.index}:{type(node).__name__}")
                else:
                    existing = result.get(str(source_id))
                    if (existing is not None and observation_signature(existing) != observation_signature(node)
                            and not _expanded_text_source(node, existing)):
                        errors.append(f"conflicting-source-identity:{source_id}")
                    result.setdefault(str(source_id), node)
    scene = getattr(document, "scene", None)
    if scene is not None:
        for record in scene.all_elements():
            result.setdefault(record.element_id, record.raw or record)
    registry = getattr(document, "element_registry", None)
    for source_id, record in getattr(registry, "elements", {}).items():
        result.setdefault(source_id, record.raw or record)
    return result


def _inventory_for_document(document):
    from pdfexact.scene import capture_source_observations, element_record_from_legacy

    previous = {}
    if getattr(document, "scene", None) is not None:
        previous.update((record.element_id, record) for record in document.scene.all_elements())
    previous.update(getattr(getattr(document, "element_registry", None), "elements", {}))
    # Records link back to whole registries; copy each stable graph only once.
    previous = deepcopy(previous)
    for page in document.pages:
        capture_source_observations(page, [*page.elements, *getattr(page, "discarded_elements", ())])
    scene = scene_from_legacy_document(document)
    inventory = deepcopy({record.element_id: record for record in scene.all_elements()})
    for source_id, record in previous.items():
        if source_id not in inventory:
            inventory[source_id] = record
        else:
            current = inventory[source_id]
            current.evidence = deepcopy(record.evidence)
            current.decision_history = deepcopy(record.decision_history)
            current.verification_state = record.verification_state
            current.attributes.update(deepcopy(record.attributes))
    for page in document.pages:
        for source_id, raw in page.source_inventory.items():
            snapshot = element_record_from_legacy(deepcopy(raw), page.index, document=document)
            existing = inventory.get(source_id)
            if existing is not None:
                snapshot.attributes.update(deepcopy(existing.attributes))
                snapshot.decision_history = deepcopy(existing.decision_history)
                snapshot.verification_state = existing.verification_state
                snapshot.evidence = deepcopy(existing.evidence)
            inventory[source_id] = snapshot
        _bind_inventory_page(inventory, page)
    return inventory


def _bind_inventory_page(inventory, page):
    binding = page_binding_for(page)
    for record in inventory.values():
        if record.page_index == page.index:
            record.attributes.pop("source_page_binding", None)
            if binding is not None:
                record.attributes["source_page_binding"] = deepcopy(binding)


def _explicit_nonrepresentable(source):
    state = getattr(source.verification_state, "value", source.verification_state)
    if state != "non-representable":
        return None
    reason = next((str(entry["reason"]) for entry in source.decision_history
                   if entry.get("event") == "non-representable" and entry.get("reason")), None)
    if not reason or not any(proof.kind == "non-representable" and proof.source and proof.details for proof in source.evidence):
        return None
    return reason


def _duplicate_parent(source, inventory):
    for parent in inventory.values():
        if source.element_id == parent.element_id or source.element_id in parent.source_ids:
            target_id = parent.attributes.get("duplicate_of") or getattr(parent.raw, "duplicate_of", None)
            verified = parent.attributes.get("duplicate_verified", getattr(parent.raw, "duplicate_verified", False))
            if target_id and verified and target_id in inventory:
                return parent, inventory[target_id]
    return None


def _duplicate_proven(source, inventory):
    pair = _duplicate_parent(source, inventory)
    return bool(pair and pair[0].page_index == pair[1].page_index and pair[0].source_kind is pair[1].source_kind and
                observation_is_preserved(pair[0].raw, [pair[1].raw], equivalent=True))


def _media_crop_partition_errors(source, outputs, media):
    """Verify all scheduled crops together, never a tile or a boolean alone."""
    if not any(getattr(output, "attributes", {}).get("crop_parent_id") == source.element_id for output in outputs):
        return None
    from pdfexact.fallback.rasterize import verify_media_crop_partition

    if source.kind not in {ElementKind.IMAGE, ElementKind.RASTER_COMPOSITE} or source.raw is None:
        return ["invalid-media-crop-source"]
    proofs = []
    try:
        for output in outputs:
            candidates = []
            for evidence in getattr(output, "evidence", ()):
                if getattr(evidence, "kind", None) != "media-crop-partition":
                    continue
                proof = dict(evidence.details).get("proof")
                if not isinstance(proof, dict) or not isinstance(proof.get("source"), dict):
                    return ["invalid-media-crop-schema"]
                if proof["source"].get("source_id") == source.element_id:
                    candidates.append(proof)
            if len(candidates) != 1:
                return ["missing-or-ambiguous-media-crop-proof"]
            proofs.append(candidates[0])
        if any(proof != proofs[0] for proof in proofs[1:]):
            return ["conflicting-media-crop-proofs"]
        return verify_media_crop_partition(source.raw, outputs, media, proofs[0])
    except (AttributeError, KeyError, TypeError, ValueError):
        return ["invalid-media-crop-schema"]


def _raster_replacement_traceable(source, target, inventory, options):
    from pdfexact.analysis.decisions import RenderMode

    if (target.element.kind is not ElementKind.RASTER_COMPOSITE
            or target.decision.mode is not RenderMode.LOCAL_RASTER
            or not options.extra.get("allow_local_raster_fallback", options.allow_local_raster_fallback)):
        return False
    record = target.element
    replaced = record.attributes.get("replaces", ())
    for proof in record.evidence:
        if proof.kind != "raster-replacement" or not proof.source:
            continue
        details = dict(proof.details)
        ids = details.get("source_ids", ())
        related = any(source.element_id == source_id or source.element_id in inventory[source_id].source_ids
                      for source_id in ids if source_id in inventory)
        bbox = source.bbox
        contains = bbox is None or (record.bbox.x0 <= bbox.x0 <= bbox.x1 <= record.bbox.x1
                                   and record.bbox.y0 <= bbox.y0 <= bbox.y1 <= record.bbox.y1)
        if (related and set(ids) <= set(replaced) and details.get("output_id") == record.element_id
                and details.get("reason") and details.get("capture_method") == "source-page-region-render"
                and isinstance(details.get("dpi"), (int, float)) and details["dpi"] > 0 and contains):
            return True
    return False


def _ocr_proofs(source_id, targets):
    proofs = []
    for item in targets:
        for instruction in item.materialization.fragments if item.materialization else ():
            for evidence in getattr(instruction.element, "evidence", ()):
                if getattr(evidence, "kind", None) != "ocr-native-source-match":
                    continue
                try:
                    proof = dict(evidence.details).get("proof")
                    reference = proof.get("observation_ref") if isinstance(proof, dict) else None
                    if isinstance(reference, dict) and source_id in reference.get("node_ids", ()) and proof not in proofs:
                        proofs.append(proof)
                except (TypeError, ValueError):
                    continue
    return proofs


def _ocr_correspondence_targets(source_id, targets):
    proofs = _ocr_proofs(source_id, targets)
    if len(proofs) != 1 or not isinstance(proofs[0].get("native_ref"), dict):
        return ()
    line_id = proofs[0]["native_ref"].get("line_id")
    if not isinstance(line_id, str) or not line_id:
        return ()
    return tuple(item.element.element_id for item in targets if item.materialization and any(
        getattr(node, "source_id", None) == line_id
        for instruction in item.materialization.fragments for node in observation_nodes(instruction.element)
    ))


def _ocr_correspondence_errors(source, mapped, inventory):
    proofs = _ocr_proofs(source.element_id, mapped)
    if len(proofs) != 1:
        return ["missing-or-conflicting-correspondence-proof"]
    proof = proofs[0]
    reference = proof.get("observation_ref")
    root = inventory.get(reference.get("root_id")) if isinstance(reference, dict) else None
    if root is None:
        return ["unknown-source"]
    outputs = [instruction.element for item in mapped if item.materialization
               for instruction in item.materialization.fragments]
    return verify_ocr_native_correspondence(source, outputs, inventory, proof,
                                            selection_events=root.decision_history)


def _ocr_document_snapshot_errors(document, current_sources, inventory, coverage, targets):
    errors = []
    expected = {}
    pages = {page.index: page for page in document.pages}
    for source_id, outcome in coverage.items():
        if outcome.relationship != OCR_OBSERVATION_RELATIONSHIP or source_id not in inventory:
            continue
        source = inventory[source_id]
        page = pages.get(source.page_index)
        if page is None or page_binding_for(page) != source.attributes.get("source_page_binding"):
            errors.append(f"source-page-mutated-after-plan:{source.page_index}")
        mapped = [targets[target] for target in outcome.target_ids if target in targets]
        for proof in _ocr_proofs(source_id, mapped):
            for name in ("observation_ref", "native_ref"):
                reference = proof.get(name)
                if not isinstance(reference, dict) or not isinstance(reference.get("node_sha256"), dict):
                    continue
                # Native owner evidence is additive; acquired Line/Span data is not.
                ids = reference.get("node_ids", ()) if name == "observation_ref" else proof.get("selected_component_ids", ())
                if not isinstance(ids, (list, tuple)):
                    continue
                for ident in ids:
                    if isinstance(ident, str) and ident in reference["node_sha256"]:
                        expected[ident] = reference["node_sha256"][ident]
    for ident, digest in expected.items():
        if ident not in current_sources or not source_snapshot_matches(current_sources[ident], digest):
            errors.append(f"source-mutated-after-plan:{ident}")
    return errors


def _coverage_for_inventory(inventory, pages):
    targets = [item for items in pages.values() for item in items]
    coverage = {}
    for source_id, source in inventory.items():
        mapped = tuple(item.element.element_id for item in targets if source_id in item.element.source_ids or source_id == item.element.element_id)
        if _duplicate_parent(source, inventory) is not None:
            continue
        if mapped:
            crop_targets = [item for item in targets if item.element.element_id in mapped
                            and item.element.attributes.get("crop_parent_id") == source_id]
            raster_targets = [item for item in targets if item.element.element_id in mapped
                              and item.element.kind is ElementKind.RASTER_COMPOSITE and item.element.element_id != source_id]
            if crop_targets:
                coverage[source_id] = SourceCoverage(mapped, "transformed", "source-media-crop-partition")
            elif raster_targets:
                coverage[source_id] = SourceCoverage(mapped, "raster-replacement", "explicit-local-raster-replacement")
            else:
                coverage[source_id] = SourceCoverage(mapped, "retained" if source_id in mapped else "transformed", "source-components-preserved")
        elif reason := _explicit_nonrepresentable(source):
            coverage[source_id] = SourceCoverage((), "non-representable", reason)
        elif mapped := _ocr_correspondence_targets(source_id, targets):
            coverage[source_id] = SourceCoverage(mapped, OCR_OBSERVATION_RELATIONSHIP,
                                                 "acquired-ocr-observation-selected-native-components")
    for source_id, source in inventory.items():
        if source_id in coverage:
            continue
        pair = _duplicate_parent(source, inventory)
        if pair is not None and pair[1].element_id in coverage:
            target = coverage[pair[1].element_id]
            coverage[source_id] = SourceCoverage(target.target_ids, "duplicate", "exact-source-equivalence")
    return coverage


def _record_for_legacy(page, page_index: int, source_index: int, element: object, *, document=None) -> ElementRecord:
    from pdfexact.scene import element_record_from_legacy

    record = element_record_from_legacy(element, page_index, document=document)
    # These are analysis annotations on the canonical record, not another
    # acquisition/identity adapter.
    geometry = getattr(element, "geometry", None) or geometry_contract_for(element)
    record.attributes["geometry_kind"] = geometry.kind
    record.attributes["geometry_locked"] = bool(
        record.attributes.get("geometry_locked") or geometry.kind != "rectangular-flow"
    )
    record.orientation = orientation_of(element)
    return record


def _boundary_paint_fragments(element):
    lines = list(getattr(element, "lignes", ()) or ())
    visible = [line for line in lines if line_has_text(line)]
    if not visible:
        return [element]
    top, bottom = min(line.bbox.y0 for line in visible), max(line.bbox.y1 for line in visible)
    boundary = {id(line) for line in lines if line_has_whitespace_paint(line)
                and (line.bbox.y0 < top or line.bbox.y1 > bottom)}
    if not boundary:
        return [element]
    groups = []
    for line in lines:
        if id(line) in boundary or not groups or id(groups[-1][-1]) in boundary:
            groups.append([])
        groups[-1].append(line)
    children = {node.source_id for line in lines for node in observation_nodes(line)}
    fragments = []
    for group in groups:
        selected = {node.source_id for line in group for node in observation_nodes(line)}
        fragment = copy(element)
        fragment.lignes = group
        fragment.bbox = paragraph_bbox_from_lines(group, fallback=element.bbox)
        fragment.source_ids = tuple(ident for ident in element.source_ids if ident not in children or ident in selected)
        if hasattr(fragment, "spans"):
            fragment.spans = [span for line in group for span in line.spans]
            fragment.texte = " ".join(span.texte for span in fragment.spans)
        fragment.geometry = geometry_contract_for(fragment)
        fragments.append(fragment)
    return fragments


def _column_right(element, records):
    """Right edge of the text column holding ``element``.

    A column is a shared left edge: the median right edge of the page's rows
    starting where the block starts. The median ignores a lone full-width
    title above narrower columns."""
    from statistics import median

    lines = list(getattr(element, "lignes", ()) or ())
    if not lines:
        return None
    left = min(line.bbox.x0 for line in lines)
    tolerance = pt_vers_emu(3.0)
    edges = [line.bbox.x1 for record in records if record.kind is ElementKind.TEXT
             for line in (getattr(record.raw, "lignes", ()) or ())
             if abs(line.bbox.x0 - left) <= tolerance]
    return int(median(edges)) if edges else None


def _restore_fragment_metadata(source, payload):
    originals = {}
    for node in observation_nodes(source):
        ident = getattr(node, "source_id", None)
        if ident is not None:
            key = (type(node), ident)
            originals[key] = None if key in originals else node
    for node in list(observation_nodes(payload)):
        original = originals.get((type(node), getattr(node, "source_id", None)))
        if original is not None:
            # dataclasses.replace drops dynamically attached source metadata.
            # Existing values, actual children and declared fields stay intact.
            for name, value in vars(original).items():
                if not hasattr(node, name):
                    setattr(node, name, deepcopy(value))


def _compile_page(page, records, options, polices=None):
    import heapq

    from pdfexact.analysis.geometry import intersection_area
    from pdfexact.ir import FlowParagraph, Line, TextBox

    visuals = [record.raw for record in records if record.kind in {ElementKind.IMAGE, ElementKind.SHAPE, ElementKind.RASTER_COMPOSITE}]
    layered = any(
        source_paint_index(visual) is not None
        and any(record.kind is ElementKind.TEXT and intersection_area(visual.bbox, record.bbox) > 0 for record in records)
        for visual in visuals
    )
    known = [source_paint_index(record.raw) for record in records if source_paint_index(record.raw) is not None]
    last_paint = max(known, default=0)
    planned = []
    for index, record in enumerate(records):
        if layered and record.kind is ElementKind.TEXT:
            record.attributes["source_paint_layered"] = True
        decision = decider_mode_universel(record, options=options)
        enregistrer_decision(record, decision, "universal-render-plan")
        fragments = text_paint_fragments(record.raw, visuals) if layered and record.kind is ElementKind.TEXT else [record.raw]
        if record.kind is ElementKind.TEXT:
            fragments = [part for fragment in fragments for part in _boundary_paint_fragments(fragment)]
        instructions = []
        for fragment_index, fragment in enumerate(fragments):
            payload = deepcopy(fragment)
            if record.kind is ElementKind.TEXT:
                _restore_fragment_metadata(record.raw, payload)
            sequence = source_paint_index(payload)
            z = 100 + 10 * (sequence if sequence is not None else last_paint + index + 1)
            anchor = AnchorSpec(z)
            text = None
            bbox_container = ""
            if record.kind is ElementKind.TEXT:
                occupied = tuple(other.bbox for other in records if other is not record)
                text = prepare_text_instructions(payload, polices, occupied, preserve_line_boundaries=options.extra.get("preserve_line_boundaries", options.preserve_line_boundaries) == "always",
                                                 column_right=_column_right(payload, records))
                if layered:
                    container = "layered-frame"
                elif decision.mode.value in {"native-flow", "native-list"}:
                    container = "flow"
                elif text.orientation.name == "horizontal" and not text.orientation.warp and text.geometry.kind == "rectangular-flow" and "page-geometry-locked" not in decision.reason_codes:
                    container = "positioned"
                else:
                    container = "dml-frame"
                bbox_container = "layered-frame" if layered else "dml-frame" if text.orientation.special else "native-paragraph"
                if container != "flow" and options.extra.get("allow_anchored_frames") is False:
                    container = "unsupported"
            elif record.kind in {ElementKind.IMAGE, ElementKind.RASTER_COMPOSITE}:
                container = "image"
            elif record.kind is ElementKind.SHAPE:
                container = "shape"
                if not known:
                    overlay = bool(getattr(payload, "remplissage", None)) and payload.bbox.largeur >= page.largeur_emu * 0.70 and payload.bbox.hauteur <= pt_vers_emu(34) and payload.bbox.y0 <= pt_vers_emu(70)
                    anchor = AnchorSpec(z, not overlay)
            elif record.kind is ElementKind.TABLE:
                container = "table"
            elif record.kind is ElementKind.LINK:
                container = "link"
            else:
                container = "unsupported"
            acquisition_index = record.attributes.get("source_acquisition_index", index)
            instructions.append(RenderInstruction(payload, record.kind, container, anchor, text,
                                                  bbox_container=bbox_container, paint_order=(acquisition_index, fragment_index),
                                                  instruction_id=f"materialization:{record.element_id}:{fragment_index}"))
        planned.append(PlannedElement(page.index, index, record, decision, Materialization(tuple(instructions))))
    # Body flow retains its established reading order; all drawings share one
    # paint stack, including native text split at source paint barriers.
    flat = [instruction for item in planned for instruction in item.materialization.fragments]
    flow = sorted((instruction for instruction in flat if instruction.container == "flow"), key=lambda instruction: (instruction.element.bbox.y0, instruction.element.bbox.x0))
    before = {}
    bottom = 0
    for instruction in flow:
        before[id(instruction)] = max(0, instruction.element.bbox.y0 - bottom)
        bottom = max(bottom, instruction.element.bbox.y1)
    planned = [replace(item, materialization=Materialization(tuple(replace(instruction, before_emu=before.get(id(instruction), 0)) for instruction in item.materialization.fragments))) for item in planned]
    flat = [instruction for item in planned for instruction in item.materialization.fragments]
    anchors = sorted((instruction for instruction in flat if instruction.container in {"image", "shape", "link", "dml-frame", "layered-frame"}), key=lambda instruction: (instruction.anchor.z, *instruction.paint_order))
    flow = sorted((instruction for instruction in flat if instruction.container == "flow"), key=lambda instruction: (instruction.element.bbox.y0, instruction.element.bbox.x0))
    rest = [instruction for instruction in flat if instruction.container not in {"image", "shape", "link", "dml-frame", "layered-frame", "flow"}]
    preferred = [*anchors, *flow, *rest]
    positions = {id(instruction): index for index, instruction in enumerate(preferred)}
    after = [set() for _ in preferred]
    incoming = [0] * len(preferred)

    def precedes(left, right):
        if left != right and right not in after[left]:
            after[left].add(right)
            incoming[right] += 1

    # Une seule operation de peinture peut produire plusieurs vues : la sequence
    # acquise ne les distingue pas, donc seules les peintures reellement
    # distinctes se contraignent entre elles. L'ordre interne d'un groupe
    # appartient aux rangees sources ci-dessous.
    painted: list[tuple[tuple[int, ...], list]] = []
    for instruction in anchors:
        key = (instruction.anchor.z, *instruction.paint_order)
        if not painted or painted[-1][0] != key:
            painted.append((key, []))
        painted[-1][1].append(instruction)
    for (_, earlier), (_, later) in zip(painted, painted[1:]):
        for left in earlier:
            for right in later:
                precedes(positions[id(left)], positions[id(right)])

    # Read immutable acquired containers, not aliases, text or geometric guesses.
    sources = dict(getattr(page, "source_inventory", {}) or {})
    registries = [getattr(page, "element_registry", None)]
    for record in records:
        registries.extend((getattr(record, "_registry", None), *getattr(record, "_registries", ())))
    seen = set()
    for registry in registries:
        if registry is None or id(registry) in seen:
            continue
        seen.add(id(registry))
        for ident, record in registry.elements.items():
            if record.kind is ElementKind.TEXT and record.page_index == page.index:
                sources.setdefault(ident, record.acquisition_raw if record.acquisition_raw is not None else record.raw)
    rendered = {}
    for index, instruction in enumerate(preferred):
        if instruction.kind is ElementKind.TEXT:
            for node in observation_nodes(instruction.element):
                if type(node) is Line and node.source_id is not None:
                    rendered.setdefault(node.source_id, []).append((index, node))
    for ident, source in sources.items():
        if (type(source) not in (TextBox, FlowParagraph) or source.source_id != ident
                or getattr(source, "source_page_index", None) != page.index):
            continue
        ordered = []
        for row in source.lignes:
            matches = rendered.get(getattr(row, "source_id", None), ())
            if (type(row) is Line and len(matches) == 1
                    and getattr(row, "source_page_index", None) == page.index
                    and observation_is_preserved(row, [matches[0][1]])):
                ordered.append(matches[0][0])
        for left, right in zip(ordered, ordered[1:]):
            precedes(left, right)

    # Unknown ancestry keeps the old mode-specific order; known rows constrain it.
    ready = [index for index, count in enumerate(incoming) if count == 0]
    heapq.heapify(ready)
    schedule = []
    while ready:
        index = heapq.heappop(ready)
        schedule.append(preferred[index])
        for following in after[index]:
            incoming[following] -= 1
            if incoming[following] == 0:
                heapq.heappush(ready, following)
    if len(schedule) != len(preferred):
        raise ValueError("conflicting-source-component-and-paint-order")
    return planned, tuple(schedule)


def build_render_plan(document: object, options: AnalysisOptions | None = None) -> RenderPlan:
    """Construit les decisions une seule fois pour tous les elements legacy."""
    options = deepcopy(options or AnalysisOptions())
    document = deepcopy(document)
    inventory = _inventory_for_document(document)
    pages: dict[int, list[PlannedElement]] = {}
    schedules = {}
    for page in getattr(document, "pages", ()):
        page_plan = build_page_render_plan(page, list(page.elements), options, polices=getattr(document, "polices", None), source_inventory=inventory, document=document)
        pages[page.index] = page_plan.for_page(page.index)
        schedules[page.index] = page_plan.instructions_for_page(page.index)
    plan = RenderPlan(
        pages=pages,
        options=options,
        elements_by_page={page.index: list(page.elements) for page in getattr(document, "pages", ())},
        instructions_by_page=schedules,
        source_inventory=inventory,
        source_coverage=_coverage_for_inventory(inventory, pages),
        media_snapshot=deepcopy(getattr(document, "media", {})),
    )
    plan.validate()
    return plan


def build_page_render_plan(page: object, elements: list[object], options: AnalysisOptions | None = None, *, polices=None, source_inventory=None, document=None) -> RenderPlan:
    """Construit un plan sur la representation regroupée qui sera effectivement rendue."""
    options = deepcopy(options or AnalysisOptions())
    media_snapshot = deepcopy(getattr(document, "media", {}))
    if source_inventory is None:
        from pdfexact.ir import Document
        page, elements = deepcopy((page, elements))
        document = Document([page], polices=polices or {}, media=media_snapshot)
        source_inventory = _inventory_for_document(document)
    records = [_record_for_legacy(page, page.index, index, deepcopy(element), document=document) for index, element in enumerate(elements)]
    _annotate_page_geometry(records)
    annotate_semantic_features(records)
    planned, schedule = _compile_page(page, records, options, polices)
    plan = RenderPlan(
        pages={
            page.index: planned
        },
        options=options,
        elements_by_page={page.index: list(elements)},
        instructions_by_page={page.index: schedule},
        source_inventory={source_id: record for source_id, record in source_inventory.items() if record.page_index == page.index},
        source_coverage=_coverage_for_inventory(source_inventory, {page.index: planned}),
        media_snapshot=media_snapshot,
    )
    plan.validate()
    return plan


def build_scene_render_plan(scene: SceneDocument, options: AnalysisOptions | None = None, *, media=None) -> RenderPlan:
    from pdfexact.ir import Page

    options = deepcopy(options or AnalysisOptions())
    scene = deepcopy(scene)
    inventory = {record.element_id: deepcopy(record) for record in scene.all_elements()}
    for record in inventory.values():
        acquired = getattr(record, "acquisition_raw", None)
        if acquired is not None:
            record.raw = deepcopy(acquired)
    for page in scene.pages:
        _bind_inventory_page(inventory, page)
    pages: dict[int, list[PlannedElement]] = {}
    schedules = {}
    elements = {}
    for page in scene.pages:
        records = [deepcopy(record) for record in page.elements if not record.attributes.get("observation_only")
                   and not record.attributes.get("discarded_by_historical_pipeline")]
        for record in records:
            if record.raw is None:
                raise ValueError(f"missing-canonical-materialization-payload:{record.element_id}")
        _annotate_page_geometry(records)
        annotate_semantic_features(records)
        geometry = Page(page.index, page.width_emu, page.height_emu)
        planned, schedule = _compile_page(geometry, records, options)
        pages[page.index] = planned
        schedules[page.index] = schedule
        elements[page.index] = [record.raw for record in records]
    plan = RenderPlan(
        pages,
        options,
        elements_by_page=elements,
        instructions_by_page=schedules,
        source_inventory=inventory,
        source_coverage=_coverage_for_inventory(inventory, pages),
        media_snapshot=deepcopy(media or {}),
    )
    plan.validate()
    return plan


def build_document_render_plan(document: object, options: AnalysisOptions | None = None) -> RenderPlan:
    """Construit le plan final sur les éléments réellement rendus.

    La préparation sémantique est effectuée ici, avant le backend XML. Le plan
    contient donc la liste exacte des paragraphes, images, formes et tableaux que
    le renderer doit matérialiser; il n'a plus à regrouper pendant l'écriture.
    """
    options = deepcopy(options or AnalysisOptions())
    document = deepcopy(document)
    inventory = _inventory_for_document(document)
    prepared = prepare_document_elements(deepcopy(document), options)
    pages: dict[int, list[PlannedElement]] = {}
    schedules = {}
    for page in getattr(document, "pages", ()):
        page_plan = build_page_render_plan(page, prepared.get(page.index, []), options, polices=getattr(document, "polices", None), source_inventory=inventory, document=document)
        pages[page.index] = page_plan.for_page(page.index)
        schedules[page.index] = page_plan.instructions_for_page(page.index)
    plan = RenderPlan(pages=pages, options=options, elements_by_page=deepcopy(prepared), instructions_by_page=schedules,
                      source_inventory=inventory, source_coverage=_coverage_for_inventory(inventory, pages),
                      media_snapshot=deepcopy(getattr(document, "media", {})))
    plan.validate()
    return plan


def _annotate_page_geometry(records: list[ElementRecord]) -> None:
    """Mark pages whose text cannot safely enter the global Word body flow.

    A PDF page with several independent x-bands (columns, sidebars, captions)
    needs positioned containers.  The text inside each container remains a
    normal Word paragraph; only the page-level geometry is locked.
    """
    text = [record for record in records if record.kind is ElementKind.TEXT]
    if len(text) < 2:
        return
    x0_values = sorted({record.bbox.x0 for record in text})
    page_width = max((record.bbox.x1 for record in records), default=0)
    gap_threshold = max(1, int(page_width * 0.16))
    bands = 1
    for previous, current in zip(x0_values, x0_values[1:]):
        if current - previous >= gap_threshold:
            bands += 1
    if bands < 2:
        return
    for record in text:
        if record.attributes.get("layout_frame_id") or record.attributes.get("geometry_locked"):
            record.attributes["page_geometry_locked"] = True
