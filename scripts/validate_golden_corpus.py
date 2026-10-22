#!/usr/bin/env python3
"""Inventory the plan's golden evidence without rendering or repairing documents."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile


FAMILIES = (
    "brochure", "two-column-article", "form", "irregular-table", "vector-map",
    "skewed-scan", "vertical-text", "curved-text", "image-with-text",
    "type3-and-substitutions", "transparency-and-clipping", "rtl-cjk",
)
ARTIFACTS = (
    "source_pdf", "scene_ir", "render_plan", "docx", "control_pdf",
    "audit_report", "verdict",
)


def _json_shape(role: str, data: object) -> bool:
    if not isinstance(data, dict):
        return False
    if role == "scene_ir":
        pages = data.get("pages")
        return bool(pages) and isinstance(pages, list) and all(
            isinstance(page, dict) and isinstance(page.get("elements"), list)
            and all(isinstance(item, dict) and item.get("element_id")
                    and item.get("source_ids") for item in page["elements"])
            for page in pages
        )
    if role == "render_plan":
        pages = data.get("pages")
        return bool(pages) and isinstance(pages, dict) and all(
            isinstance(items, list) and all(
                isinstance(item, dict) and item.get("element_id") and item.get("mode")
                for item in items
            ) for items in pages.values()
        )
    if role == "audit_report":
        records = data.get("records")
        return bool(records) and isinstance(records, list) and all(
            isinstance(item, dict) and item.get("element_id") and item.get("status")
            for item in records
        )
    return isinstance(data.get("status"), str)


def inspect_artifact(role: str, entry: object, root: Path) -> dict:
    descriptor = entry if isinstance(entry, dict) else {"path": entry}
    name = descriptor.get("path")
    if not isinstance(name, str) or not name:
        return {"state": "MISSING", "reason": "no-artifact-path"}
    path = (root / name).resolve()
    result = {"path": str(path)}
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        result.update(sha256=digest.hexdigest(), bytes=path.stat().st_size)
        if descriptor.get("sha256") not in (None, result["sha256"]):
            raise ValueError("artifact-sha256-mismatch")
        if role in {"source_pdf", "control_pdf"}:
            import pymupdf

            with pymupdf.open(path) as pdf:
                if not pdf.is_pdf or pdf.page_count == 0:
                    raise ValueError("invalid-pdf")
                result["page_count"] = pdf.page_count
        elif role == "docx":
            with zipfile.ZipFile(path) as package:
                for part in ("[Content_Types].xml", "_rels/.rels", "word/document.xml"):
                    ET.fromstring(package.read(part))
                if package.testzip() is not None:
                    raise ValueError("corrupt-docx-package")
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not _json_shape(role, data):
                raise ValueError("wrong-artifact-structure")
            if role == "verdict":
                result["declared_status"] = data["status"]
        result["state"] = "PRESENT"
    except FileNotFoundError:
        result.update(state="MISSING", reason="file-not-found")
    except (OSError, ValueError, RuntimeError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        result.update(state="INVALID", reason=str(exc))
    return result


def inspect_case(case: dict, root: Path) -> dict:
    entries = case.get("artifacts", {})
    if not isinstance(entries, dict):
        raise ValueError("case artifacts must be an object")
    artifacts = {role: inspect_artifact(role, entries.get(role), root) for role in ARTIFACTS}
    missing = [role for role, item in artifacts.items() if item["state"] != "PRESENT"]
    reasons = ["missing-or-invalid:" + role for role in missing]
    if case.get("family_confirmed") is not True:
        reasons.append("family-membership-unconfirmed")
    render = case.get("control_render", {})
    if not isinstance(render, dict):
        render = {}
    docx_hash = artifacts["docx"].get("sha256")
    pdf_hash = artifacts["control_pdf"].get("sha256")
    rendered = bool(
        artifacts["docx"]["state"] == artifacts["control_pdf"]["state"] == "PRESENT"
        and render.get("fixture") is not True and render.get("simulated") is not True
        and render.get("exit_code") == 0
        and render.get("reader") and render.get("reader_version")
        and docx_hash == render.get("docx_sha256")
        and pdf_hash == render.get("pdf_sha256")
    )
    if not rendered:
        reasons.append("real-render-evidence-missing-or-unbound")
    source_pages = artifacts["source_pdf"].get("page_count")
    selected_pages = case.get("source_pages")
    if selected_pages is not None:
        if not isinstance(selected_pages, list) or not selected_pages or any(
            not isinstance(page, int) or isinstance(page, bool) or page < 1
            or (source_pages is not None and page > source_pages)
            for page in selected_pages
        ) or len(set(selected_pages)) != len(selected_pages):
            reasons.append("invalid-source-page-selection")
        else:
            source_pages = len(selected_pages)
    output_pages = artifacts["control_pdf"].get("page_count")
    if source_pages is not None and output_pages is not None and source_pages != output_pages:
        reasons.append("source-control-page-count-mismatch")
    declared = artifacts["verdict"].get("declared_status", "").upper()
    if declared in {"INCOMPLETE", "INCOMPL\u00c8TE", "FAILED", "FAIL", "ERROR"}:
        reasons.append("declared-verdict:" + declared)
    return {
        "case_id": case["case_id"], "family": case["family"],
        "status": "INCOMPLETE" if reasons else "READY_FOR_REVIEW",
        "present_artifact_count": len(ARTIFACTS) - len(missing),
        "artifacts": artifacts, "reasons": reasons,
        "render_evidence_bound": rendered,
        "scope": "Evidence inventory only; no visual or architectural certification.",
    }


def inspect_manifest(manifest: dict, root: Path) -> dict:
    if manifest.get("schema") != "pdfexact.golden-manifest.v1":
        raise ValueError("unsupported golden manifest schema")
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        raise ValueError("manifest cases must be a list")
    ids = set()
    results = []
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str) or not case["case_id"]:
            raise ValueError("each case needs a nonempty case_id")
        if case["case_id"] in ids or case.get("family") not in FAMILIES:
            raise ValueError("duplicate case_id or unknown golden family")
        ids.add(case["case_id"])
        results.append(inspect_case(case, root))
    covered = {case["family"] for case in results if case["status"] == "READY_FOR_REVIEW"}
    return {
        "schema": "pdfexact.golden-evidence-inventory.v1",
        "status": "READY_FOR_REVIEW" if covered == set(FAMILIES) and all(
            case["status"] == "READY_FOR_REVIEW" for case in results
        ) else "INCOMPLETE",
        "required_families": list(FAMILIES), "required_artifacts": list(ARTIFACTS),
        "families_without_complete_evidence": sorted(set(FAMILIES) - covered),
        "cases": results,
        "scope": "Completeness and fingerprints only. READY_FOR_REVIEW never means certified OK.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--root", type=Path, help="Artifact paths base; defaults to manifest directory.")
    parser.add_argument("--out", type=Path, help="New JSON report; an existing file is never overwritten.")
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be an object")
        result = inspect_manifest(manifest, (args.root or args.manifest.parent).resolve())
        output = json.dumps(result, ensure_ascii=True, indent=2) + "\n"
        if args.out:
            with args.out.open("x", encoding="utf-8") as stream:
                stream.write(output)
        else:
            print(output, end="")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"golden inventory: {exc}\n")
    return 0 if result["status"] == "READY_FOR_REVIEW" else 3


if __name__ == "__main__":
    raise SystemExit(main())
