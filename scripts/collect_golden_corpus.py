#!/usr/bin/env python3
"""Collect golden evidence sequentially, without repair or certification."""
from __future__ import annotations

import argparse
from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.validate_golden_corpus import ARTIFACTS, FAMILIES, inspect_manifest


ROOT = Path(__file__).resolve().parents[1]
AUDIT_LIMITS = [
    "Existing element audit is partial, not exhaustive source/output certification.",
    "No complete XML-object mapping, discarded-source audit or output precision proof.",
    "Token sets do not prove order, multiplicity, short text or RTL/CJK completeness.",
    "Observed z-order, directed baseline, font metrics and editability are not all verified.",
    "No Phase5 repair, rollback or reader compatibility certification is performed.",
]


def snapshot(value):
    """Serialize contracts without repr fallbacks or lossy string coercion."""
    if isinstance(value, Enum):
        return snapshot(value.value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: snapshot(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        if any(not isinstance(key, (str, int)) for key in value):
            raise TypeError("unsupported snapshot mapping key")
        return {str(key): snapshot(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [snapshot(item) for item in value]
    raise TypeError(f"unsupported snapshot type: {type(value).__name__}")


def write_json(path: Path, value):
    data = json.dumps(snapshot(value), ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(data + "\n")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact_hashes(paths):
    result = {}
    for name, path in paths.items():
        try:
            result[name] = {"path": str(path), "sha256": file_hash(path)}
        except OSError as exc:
            result[name] = {"path": str(path), "sha256": None, "error": str(exc)}
    return result


def code_snapshot(root: Path = ROOT) -> dict:
    paths = sorted({*root.glob("pdfexact/**/*.py"), *root.glob("pdfexact/**/*.json"),
                    *root.glob("scripts/*.py"), *root.glob("tests/**/*.py"), root / "pyproject.toml"})
    hashes = {str(path.relative_to(root)): file_hash(path) for path in paths if path.is_file()}
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return {"sha256": digest, "files": hashes}


def plan_snapshot(plan) -> dict:
    result = snapshot(plan)
    result["schema"] = "pdfexact.golden-render-plan.v1"
    for items in result["pages"].values():
        for item in items:
            item["element_id"] = item["element"]["element_id"]
            item["mode"] = item["decision"]["mode"]
    return result


def bind_source_pages(document, scene, pages, source_sha256):
    """Bind original source indices, never selected-page enumeration, before writing."""
    expected = [page - 1 for page in pages]
    actual = [page.index for page in document.pages]
    if any(type(index) is not int for index in actual) or actual != expected:
        raise ValueError("extraction-source-page-order-or-identity-mismatch")
    scene_pages = scene.get("pages", [])
    if [page.get("index") for page in scene_pages] != actual:
        raise ValueError("scene-source-page-order-or-identity-mismatch")
    bindings = []
    for ordinal in range(len(pages)):
        page = document.pages[ordinal]
        scene_page = scene_pages[ordinal]
        for claimed in (getattr(page, "source_pdf_id", None), scene_page.get("source_pdf_id")):
            if claimed and claimed != source_sha256:
                raise ValueError("page-source-pdf-hash-mismatch")
        bindings.append({
            "source_sha256": source_sha256,
            "source_page_1based": pages[ordinal],
            "source_page_index_0based": pages[ordinal] - 1,
            "ir_source_pdf_id_actual": getattr(page, "source_pdf_id", None),
            "scene_source_pdf_id_actual": scene_page.get("source_pdf_id"),
            "selected_source_ordinal_1based": ordinal + 1,
            "ir_page_index_actual": actual[ordinal],
            "ir_scene_id": getattr(page, "scene_id", None),
            "scene_page_index_actual": scene_page["index"],
            "output_ordinal_1based_expected": ordinal + 1,
            "control_ordinal_1based_present": None,
            "output_ordinal_1based_observed": None,
            "source_to_output_content_binding": "UNVERIFIED",
            "planned_element_ids": None,
        })
    return bindings


def validate_requested_mapping(requested, bindings):
    if requested is None:
        return
    if not isinstance(requested, list) or len(requested) != len(bindings):
        raise ValueError("manifest-page-mapping-count-mismatch")
    for supplied, actual in zip(requested, bindings):
        if not isinstance(supplied, dict) or any(
            type(supplied.get(key)) is not int or supplied[key] != actual[key]
            for key in ("source_page_1based", "output_ordinal_1based_expected")
        ):
            raise ValueError("manifest-page-mapping-selection-mismatch")


def bind_control_ordinals(bindings, control):
    import pymupdf

    with pymupdf.open(control) as pdf:
        if pdf.page_count != len(bindings):
            raise ValueError("source-control-page-count-mismatch")
        for ordinal in range(pdf.page_count):
            bindings[ordinal]["control_ordinal_1based_present"] = ordinal + 1
    # Page existence is observed, but cannot prove source identity/content order.


def coverage_errors(document, scene: dict, plan) -> list[str]:
    bound = "document" in inspect.signature(plan.validate).parameters
    errors = list(plan.validate(document=document) if bound else plan.validate())
    if set(plan.pages) != {page.index for page in document.pages}:
        errors.append("source-plan-page-set-mismatch")
    planned_sources = {
        source for items in plan.pages.values() for item in items
        for source in item.element.source_ids
    }
    # Transformation/duplicate proofs belong to the central validator, not this runner.
    if getattr(plan, "source_coverage", None) is not None:
        planned_sources.update(plan.source_coverage)
    for page in scene["pages"]:
        for element in page["elements"]:
            if not element.get("source_ids"):
                errors.append("source-provenance-missing:" + element["element_id"])
            unresolved = set(element.get("source_ids", ())) - planned_sources
            terminal = element.get("verification_state") == "non-representable"
            explained = any(
                isinstance(event, dict) and event.get("reason")
                for event in element.get("decision_history", ())
            )
            if unresolved and not (terminal and explained):
                errors.append("uncovered-source:" + element["element_id"])
    return sorted(set(errors))


class ProductionPipeline:
    """Thin adapter to existing APIs; no alternate rendering implementation."""

    def prepare_options(self, options):
        from pdfexact.analysis.options import AnalysisOptions
        from pdfexact.extract.document import extraire

        if set(options) - {"analysis", "extract"}:
            raise ValueError("unknown collection option group")
        analysis = snapshot(AnalysisOptions(**options.get("analysis", {})))
        supplied = {"strict": True, "dpi": 150, **options.get("extract", {})}
        reserved = {"chemin_pdf", "pages", "bibliotheque", "rapport"}
        if reserved & supplied.keys():
            raise ValueError("reserved extraction argument")
        bound = inspect.signature(extraire).bind_partial(None, **supplied)
        bound.apply_defaults()
        extraction = {key: value for key, value in bound.arguments.items() if key not in reserved}
        return {"analysis": analysis, "extract": extraction}

    def extract(self, source, pages, options):
        from pdfexact.extract.document import extraire

        return extraire(source, pages=pages, **options["extract"])

    def scene(self, document):
        from pdfexact.scene import scene_from_legacy_document

        return document.scene if document.scene is not None else scene_from_legacy_document(document)

    def build_plan(self, document, options):
        from pdfexact.analysis.options import AnalysisOptions
        from pdfexact.render.render_plan import build_document_render_plan

        return build_document_render_plan(document, AnalysisOptions(**options["analysis"]))

    def write(self, document, destination, plan):
        from pdfexact.render.package import ecrire_docx

        return ecrire_docx(document, destination, native_rewriter=True, render_plan=plan)

    def audit(self, document, plan, source, control):
        from pdfexact.final_audit import construire_audit_elements

        # Observe the exact prepared elements, not a second semantic preparation.
        observed = replace(document, pages=[
            replace(page, elements=plan.elements_for_page(page.index)) for page in document.pages
        ])
        return construire_audit_elements(observed, control, source)


def _process(command, timeout):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return {"command": command, "exit_code": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": command, "exit_code": None, "error": str(exc)}


def render_control(docx: Path, directory: Path, *, executable="soffice", timeout=300):
    """Instrument the existing LibreOffice conversion pattern with an isolated profile."""
    version = _process([executable, "--version"], 30)
    version_text = version.get("stdout", "").strip() if version["exit_code"] == 0 else None
    output = directory / "control"
    output.mkdir()
    with tempfile.TemporaryDirectory(prefix="reader_profile_", dir=directory) as profile:
        command = [executable, "-env:UserInstallation=" + Path(profile).as_uri(),
                   "--headless", "--convert-to", "pdf", "--outdir", str(output), str(docx)]
        conversion = _process(command, timeout)
    produced = output / (docx.stem + ".pdf")
    return {
        "reader": "libreoffice", "reader_version": version_text,
        "version_probe": version, **conversion,
        "isolated_profile": True, "docx_sha256": file_hash(docx),
        "pdf_path": str(produced) if produced.is_file() else None,
        "pdf_sha256": file_hash(produced) if produced.is_file() else None,
    }


def _selected_source(source, selected, destination):
    import pymupdf

    with pymupdf.open(source) as pdf:
        if not pdf.is_pdf or pdf.page_count == 0:
            raise ValueError("invalid source PDF")
        pages = list(range(1, pdf.page_count + 1)) if selected is None else selected
        if not isinstance(pages, list) or not pages or any(
            not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= pdf.page_count
            for page in pages
        ) or len(set(pages)) != len(pages):
            raise ValueError("invalid source page selection")
        if pages == list(range(1, pdf.page_count + 1)):
            return pages, source
        with pymupdf.open() as subset:
            for page in pages:
                subset.insert_pdf(pdf, from_page=page - 1, to_page=page - 1)
            subset.save(destination)
    return pages, destination


def compare_pages(source, control):
    import pymupdf
    from tests.visual.harness import rendre_en_images, score_ssim

    with pymupdf.open(source) as pdf:
        source_count = pdf.page_count
    with pymupdf.open(control) as pdf:
        control_count = pdf.page_count
    if source_count != control_count:
        return {"source_pages": source_count, "control_pages": control_count,
                "status": "INCOMPLETE", "reason": "page-count-mismatch", "scores": []}
    sources = rendre_en_images(source)
    outputs = rendre_en_images(control)
    scores = []
    for index in range(source_count):
        same_size = sources[index].shape == outputs[index].shape
        scores.append({"page": index + 1, "same_pixel_dimensions": same_size,
                       "ssim": score_ssim(sources[index], outputs[index]) if same_size else None})
    return {"source_pages": source_count, "control_pages": control_count, "scores": scores,
            "status": "OBSERVED" if all(item["same_pixel_dimensions"] for item in scores) else "INCOMPLETE"}


def qualify_audit(audit):
    """Separate actually available proxies from unmeasured plan requirements."""
    raw = snapshot(audit)
    records = []
    required = (
        "token_order", "token_multiplicity", "quad", "directed_angle", "baseline",
        "font_family", "font_size", "font_style", "font_metrics", "visibility",
        "occlusion", "z_order", "overflow", "editability", "output_precision",
        "source_xml_binding",
    )
    for record in raw["records"]:
        text = record.get("kind") in {"TextBox", "FlowParagraph"}
        visual = record.get("kind") in {"ImageEl", "RasterEl", "ShapeEl", "TableEl"}
        missing = record.get("status") == "missing" or "output-page-missing" in record.get("causes", [])
        measured = {}
        for key in ("token_recall", "token_precision"):
            measured[key + "_set_proxy"] = record.get(key) if text and not missing else None
        measured["visual_region_similarity_proxy"] = record.get("token_recall") if visual and not missing else None
        has_bbox = text and not missing and (record.get("bbox_iou") or 0) > 0
        measured["bbox_iou"] = record.get("bbox_iou") if has_bbox else None
        measured["bbox_drift_pt"] = record.get("bbox_drift_pt") if has_bbox else None
        measured["reported_style_mismatches"] = record.get("style_mismatches") or None
        measured.update({name: None for name in required})
        records.append({
            "element_id": record["element_id"], "page_index": record.get("page_index"),
            "kind": record.get("kind"), "reported_status": record.get("status"),
            "status": record["status"] if record.get("status") in {"error", "missing"} else "unverified",
            "critical": record.get("status") in {"error", "missing"} or missing,
            "causes": record.get("causes", []), "measurements": measured,
            "available_measures": [key for key, value in measured.items() if value is not None],
            "unmeasured_requirements": list(required),
        })
    return {
        "schema": "pdfexact.golden-observational-audit.v1", "records": records,
        "raw_report": raw, "exhaustive": False, "limitations": list(AUDIT_LIMITS),
        "critical_records": [record["element_id"] for record in records if record["critical"]],
        "measurement_policy": "null means unmeasured; raw_report defaults are not validated measurements. Proxies do not prove plan criteria.",
    }


def collect_case(case, root, directory, pipeline, renderer, comparator, options, before):
    directory.mkdir()
    artifacts = {role: None for role in ARTIFACTS}
    evidence = {"case_id": case["case_id"], "family": case["family"],
                "family_confirmed": case.get("family_confirmed") is True,
                "family_evidence": case.get("family_evidence"), "artifacts": artifacts}
    metadata = {"case_id": case["case_id"], "code_snapshot_sha256_before": before["sha256"],
                "started_utc": datetime.now(timezone.utc).isoformat(), "requested_options": options,
                "limitations": list(AUDIT_LIMITS), "stages": []}
    source_paths, render_paths, bindings = {}, {}, []
    try:
        entry = case.get("artifacts", {}).get("source_pdf")
        descriptor = entry if isinstance(entry, dict) else {"path": entry}
        if not descriptor.get("path"):
            raise ValueError("source PDF not assigned")
        original = (root / descriptor["path"]).resolve()
        digest = file_hash(original)
        if descriptor.get("sha256") not in (None, digest):
            raise ValueError("source hash differs from manifest")
        source = directory / "source.pdf"
        shutil.copyfile(original, source)
        if file_hash(source) != digest:
            raise ValueError("source changed during copy")
        artifacts["source_pdf"] = {"path": str(source), "sha256": digest}
        metadata.update(original_source=str(original), original_source_manifest_path=descriptor["path"],
                        source_sha256=digest)
        pages, selected_source = _selected_source(source, case.get("source_pages"), directory / "selected_source.pdf")
        source_paths = {"original": original, "copy": source, "selected": selected_source}
        metadata["source_hashes_before"] = artifact_hashes(source_paths)
        evidence["source_pages"] = pages
        evidence["selected_source_pdf"] = {"path": str(selected_source), "sha256": file_hash(selected_source)}
        resolved = pipeline.prepare_options(options)
        metadata["effective_options"] = resolved
        metadata["limitations"].append("AnalysisOptions is not yet shared end-to-end with extraction.")
        metadata["stages"].append("extract")
        document = pipeline.extract(source, [page - 1 for page in pages], resolved)
        canonical_scene = pipeline.scene(document)
        scene = snapshot(canonical_scene.snapshot())
        bindings = bind_source_pages(document, scene, pages, digest)
        validate_requested_mapping(case.get("page_mapping"), bindings)
        scene["_collection"] = {"stage": "after-extraction-before-plan", "source_sha256": digest,
                                "options": resolved, "raw_acquisition_completeness": "not-proven"}
        if is_dataclass(canonical_scene):
            # Catch unsupported field values before the factory's diagnostic string fallback.
            write_json(directory / "scene_contract.json", snapshot(canonical_scene))
            scene["_collection"]["strict_contract_snapshot"] = "scene_contract.json"
        scene_path = directory / "scene.json"
        write_json(scene_path, scene)
        artifacts["scene_ir"] = str(scene_path)
        metadata["stages"].append("plan")
        plan = pipeline.build_plan(document, resolved)
        bind_source_pages(document, scene, pages, digest)
        errors = coverage_errors(document, scene, plan)
        if set(plan.pages) != {binding["ir_page_index_actual"] for binding in bindings}:
            errors.append("source-plan-page-binding-mismatch")
        for binding in bindings:
            binding["planned_element_ids"] = [
                item.element.element_id for item in plan.pages.get(binding["ir_page_index_actual"], [])
            ]
        planned = plan_snapshot(plan)
        plan_path = directory / "render_plan.json"
        write_json(plan_path, planned)
        artifacts["render_plan"] = str(plan_path)
        metadata["prewrite_errors"] = errors
        metadata["consumed_render_plan_sha256"] = file_hash(plan_path)
        if errors:
            raise ValueError("prewrite coverage/plan validation failed")
        docx = directory / "document.docx"
        metadata["stages"].append("write")
        result = pipeline.write(document, docx, plan)
        if docx.is_file():
            artifacts["docx"] = str(docx)
        write_json(directory / "writer_diagnostics.json", snapshot(getattr(result, "diagnostics", result)))
        if plan_snapshot(plan) != planned:
            raise ValueError("writer mutated the consumed render plan")
        bind_source_pages(document, scene, pages, digest)
        expected_docx_hash = file_hash(docx)
        render_paths = {"docx": docx}
        metadata["docx_sha256_before_render"] = expected_docx_hash
        metadata["stages"].append("render")
        rendered = renderer(docx, directory)
        evidence["control_render"] = rendered
        write_json(directory / "control_render.json", rendered)
        control = Path(rendered["pdf_path"]) if rendered.get("pdf_path") else None
        if control is not None:
            control.resolve().relative_to(directory.resolve())
        if control is not None and control.is_file():
            artifacts["control_pdf"] = str(control)
        if rendered.get("exit_code") != 0 or control is None or not control.is_file():
            raise ValueError("real DOCX control render unavailable")
        if file_hash(docx) != expected_docx_hash or rendered.get("docx_sha256") != expected_docx_hash:
            raise ValueError("control render input binding changed or missing")
        if rendered.get("pdf_sha256") != file_hash(control):
            raise ValueError("control render output hash binding missing or stale")
        render_paths = {"docx": docx, "control_pdf": control}
        metadata["render_hashes_before_audit"] = artifact_hashes(render_paths)
        bind_control_ordinals(bindings, control)
        metadata["page_comparison"] = comparator(selected_source, control)
        metadata["stages"].append("audit")
        audit = qualify_audit(pipeline.audit(document, plan, selected_source, control))
        audit["page_index_semantics"] = "Existing element audit enumerates output pages, not original source Page.index."
        for record in audit["records"]:
            output_index = record.get("page_index")
            binding = bindings[output_index] if type(output_index) is int and 0 <= output_index < len(bindings) else None
            record["page_binding"] = ({
                "output_ordinal_1based": output_index + 1,
                "expected_source_page_1based": binding["source_page_1based"],
                "ir_page_index_actual": binding["ir_page_index_actual"],
                "source_to_output_content_binding": "UNVERIFIED",
            } if binding is not None else None)
        expected_ids = {item.element.element_id for items in plan.pages.values() for item in items}
        observed_ids = {record["element_id"] for record in audit["records"]}
        audit["coverage"] = {"planned_ids": sorted(expected_ids), "observed_ids": sorted(observed_ids),
                             "missing_planned_ids": sorted(expected_ids - observed_ids),
                             "unexpected_ids": sorted(observed_ids - expected_ids)}
        audit["non_ok_records"] = [record["element_id"] for record in audit["records"] if record["status"] != "ok"]
        write_json(directory / "audit.json", audit)
        artifacts["audit_report"] = str(directory / "audit.json")
        if plan_snapshot(plan) != planned:
            raise ValueError("observational audit mutated the render plan")
    except Exception as exc:
        metadata["failure"] = {"type": type(exc).__name__, "message": str(exc)}
    metadata["source_hashes_after"] = artifact_hashes(source_paths)
    metadata["render_hashes_after_audit"] = artifact_hashes(render_paths)
    metadata["source_changed"] = (
        metadata["source_hashes_after"] != metadata["source_hashes_before"]
        if "source_hashes_before" in metadata else None
    )
    metadata["render_changed"] = (
        metadata["render_hashes_after_audit"] != metadata["render_hashes_before_audit"]
        if "render_hashes_before_audit" in metadata else None
    )
    if "docx_sha256_before_render" in metadata:
        docx_after = metadata["render_hashes_after_audit"].get("docx", {}).get("sha256")
        metadata["docx_sha256_after_observation"] = docx_after
        if docx_after != metadata["docx_sha256_before_render"]:
            metadata["render_changed"] = True
    if metadata["source_changed"] or metadata["render_changed"]:
        metadata.setdefault("failure", {"type": "ArtifactMutation", "message": "source or rendered artifacts changed during observation"})
    evidence["page_mapping"] = bindings
    metadata["page_mapping"] = bindings
    metadata["page_mapping_limit"] = "Source/IR indices are checked. Present control ordinals do not prove source/output content identity; observed content binding remains null/unverified."
    write_json(directory / "page_mapping.json", {"pages": bindings, "scope": metadata["page_mapping_limit"]})
    after = code_snapshot()
    metadata["code_snapshot_after"] = after
    metadata["code_changed"] = after != before
    metadata["completed_utc"] = datetime.now(timezone.utc).isoformat()
    verdict = {"status": "INCOMPLETE", "exhaustive_audit": False,
               "limitations": metadata["limitations"], "failure": metadata.get("failure"),
               "code_changed": metadata["code_changed"],
               "source_changed": metadata["source_changed"], "render_changed": metadata["render_changed"],
               "reason": "Observation only; exhaustive actual audit required before any OK verdict."}
    write_json(directory / "verdict.json", verdict)
    artifacts["verdict"] = str(directory / "verdict.json")
    # Relocatable evidence stays under this newly created collection directory.
    for role, entry in artifacts.items():
        if entry is not None:
            descriptor = entry if isinstance(entry, dict) else {"path": entry}
            path = Path(descriptor["path"])
            artifacts[role] = {"path": str(path.resolve().relative_to(directory.parent.resolve())),
                               "sha256": file_hash(path)}
    selected = evidence.get("selected_source_pdf")
    if selected is not None:
        selected["path"] = str(Path(selected["path"]).resolve().relative_to(directory.parent.resolve()))
    write_json(directory / "metadata.json", metadata)
    return evidence, metadata


def collect(manifest, root, destination, *, pipeline=None, renderer=render_control,
            comparator=compare_pages):
    # Identity validation is shared with the evidence inventory; no family inference.
    inspect_manifest({**manifest, "cases": [
        {**case, "artifacts": {}} for case in manifest.get("cases", [])
    ]}, root)
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    write_json(destination / "input_manifest.json", manifest)
    before = code_snapshot()
    write_json(destination / "code_before.json", before)
    pipeline = pipeline or ProductionPipeline()
    entries, details = [], []
    for index, case in enumerate(manifest["cases"], start=1):
        if code_snapshot() != before:
            details.append({"case_id": case["case_id"], "failure": "code-mutated-stop-before-next-case"})
            break
        options = manifest.get("collection_options", {})
        if "collection_options" in case:
            options = case["collection_options"]
        evidence, metadata = collect_case(case, root, destination / f"{index:03d}",
                                         pipeline, renderer, comparator, options, before)
        entries.append(evidence)
        details.append({"case_id": case["case_id"], "failure": metadata.get("failure"),
                        "code_changed": metadata["code_changed"]})
        if metadata["code_changed"]:
            break
    collected = {"schema": "pdfexact.golden-manifest.v1", "cases": entries,
                 "scope": "Sequential observation; no repairs or universal certification."}
    write_json(destination / "manifest.json", collected)
    inventory = inspect_manifest(collected, destination)
    write_json(destination / "inventory.json", inventory)
    summary = {"status": "INCOMPLETE", "requested_cases": len(manifest["cases"]),
               "collected_cases": len(entries), "cases": details, "exhaustive_audit": False,
               "limitations": AUDIT_LIMITS}
    write_json(destination / "collection.json", summary)
    return summary


def api_checkpoint():
    names = {
        "pdfexact.extract.document": ("extraire",),
        "pdfexact.scene": ("scene_from_legacy_document", "SceneDocument"),
        "pdfexact.render.render_plan": ("build_document_render_plan", "RenderPlan"),
        "pdfexact.render.package": ("ecrire_docx",),
        "pdfexact.render.native_contract": ("valider_contrat_word_native",),
        "pdfexact.final_audit": ("construire_audit_elements",),
    }
    before, apis = code_snapshot(), {}
    for module_name, attributes in names.items():
        try:
            module = importlib.import_module(module_name)
            apis[module_name] = {name: str(inspect.signature(getattr(module, name))) for name in attributes}
        except Exception as exc:
            apis[module_name] = {"error": type(exc).__name__ + ": " + str(exc)}
    probes = {}
    if not any("error" in item for item in apis.values()):
        try:
            from pdfexact.analysis.options import AnalysisOptions
            from pdfexact.geometry import BBox, pt_vers_emu
            from pdfexact.ir import Document, Page, ShapeEl
            from pdfexact.render.render_plan import RenderPlan
            from pdfexact.render.native_contract import valider_contrat_word_native

            shape = ShapeEl(BBox(0, 0, 100, 100), [], "000000", None, 0, source_id="probe-source")
            document = Document([Page(7, pt_vers_emu(200), pt_vers_emu(300), [shape])])
            empty = RenderPlan({7: []}, AnalysisOptions(), elements_by_page={7: []}, instructions_by_page={7: ()})
            report = valider_contrat_word_native(document, empty)
            probes["B1_empty_plan_nonempty_document"] = {
                "contract_conforme": report.conforme, "contract_report": snapshot(report),
                "document_bound_plan_errors": empty.validate(document=document),
                "writer_called": False,
            }
        except Exception as exc:
            probes["error"] = type(exc).__name__ + ": " + str(exc)
    after = code_snapshot()
    status = "API_UNAVAILABLE" if any("error" in item for item in apis.values()) else "API_CHECK_ONLY"
    return {"status": status, "conversion_executed": False,
            "checked_utc": datetime.now(timezone.utc).isoformat(), "apis": apis,
            "read_only_probes": probes, "code_before": before, "code_after": after,
            "code_changed": before != after, "limitations": AUDIT_LIMITS}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, nargs="?")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--check-api", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.check_api:
            args.out_dir.mkdir(parents=True, exist_ok=False)
            checkpoint = api_checkpoint()
            write_json(args.out_dir / "api_checkpoint.json", checkpoint)
            return 0 if checkpoint["status"] == "API_CHECK_ONLY" and not checkpoint["code_changed"] else 3
        if args.manifest is None:
            raise ValueError("manifest required unless --check-api")
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        root = (args.root or args.manifest.parent).resolve()
        collect(manifest, root, args.out_dir)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(2, f"golden collection: {exc}\n")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
