import json
import zipfile

import pymupdf
import pytest

from scripts.validate_golden_corpus import ARTIFACTS, FAMILIES, inspect_manifest, main


def _manifest(case):
    return {"schema": "pdfexact.golden-manifest.v1", "cases": [case]}


def _case(tmp_path):
    for name in ("source", "control"):
        with pymupdf.open() as pdf:
            pdf.new_page()
            pdf.save(tmp_path / f"{name}.pdf")
    with zipfile.ZipFile(tmp_path / "output.docx", "w") as package:
        for part in ("[Content_Types].xml", "_rels/.rels", "word/document.xml"):
            package.writestr(part, "<root/>")
    values = {
        "scene_ir": {"pages": [{"elements": [{"element_id": "text", "source_ids": ["pdf:1"]}]}]},
        "render_plan": {"pages": {"0": [{"element_id": "text", "mode": "native-flow"}]}},
        "audit_report": {"records": [{"element_id": "text", "status": "ok"}]},
        "verdict": {"status": "OK"},
    }
    for role, data in values.items():
        (tmp_path / f"{role}.json").write_text(json.dumps(data))
    return {
        "case_id": "witness", "family": "vertical-text", "family_confirmed": True,
        "artifacts": {"source_pdf": "source.pdf", "docx": "output.docx", "control_pdf": "control.pdf",
                      **{role: role + ".json" for role in values}},
    }


def test_missing_evidence_cannot_be_promoted_by_an_ok_verdict(tmp_path):
    case = _case(tmp_path)
    result = inspect_manifest(_manifest(case), tmp_path)
    witness = result["cases"][0]
    assert witness["present_artifact_count"] == len(ARTIFACTS)
    assert witness["status"] == "INCOMPLETE"
    assert "real-render-evidence-missing-or-unbound" in witness["reasons"]
    assert result["families_without_complete_evidence"] == sorted(FAMILIES)


def test_bound_render_evidence_is_ready_for_review_only(tmp_path):
    case = _case(tmp_path)
    inventory = inspect_manifest(_manifest(case), tmp_path)["cases"][0]
    case["control_render"] = {
        "exit_code": 0, "reader": "libreoffice", "reader_version": "test-witness",
        "docx_sha256": inventory["artifacts"]["docx"]["sha256"],
        "pdf_sha256": inventory["artifacts"]["control_pdf"]["sha256"],
    }
    result = inspect_manifest(_manifest(case), tmp_path)
    assert result["cases"][0]["status"] == "READY_FOR_REVIEW"
    assert result["status"] == "INCOMPLETE"
    assert "vertical-text" not in result["families_without_complete_evidence"]
    case["control_render"]["pdf_sha256"] = "stale-hash"
    assert inspect_manifest(_manifest(case), tmp_path)["cases"][0]["status"] == "INCOMPLETE"


def test_text_catalogue_is_not_a_canonical_scene(tmp_path):
    case = _case(tmp_path)
    (tmp_path / "scene_ir.json").write_text(json.dumps({"pages": [{"text_elements": []}]}))
    result = inspect_manifest(_manifest(case), tmp_path)["cases"][0]
    assert result["artifacts"]["scene_ir"]["state"] == "INVALID"
    assert "missing-or-invalid:scene_ir" in result["reasons"]


def test_extra_output_page_and_missing_artifact_are_not_hidden(tmp_path):
    case = _case(tmp_path)
    (tmp_path / "render_plan.json").unlink()
    with pymupdf.open() as pdf:
        pdf.new_page()
        pdf.new_page()
        pdf.save(tmp_path / "control.pdf")
    result = inspect_manifest(_manifest(case), tmp_path)["cases"][0]
    assert "source-control-page-count-mismatch" in result["reasons"]
    assert "missing-or-invalid:render_plan" in result["reasons"]


@pytest.mark.parametrize("change", ["family", "duplicate"])
def test_invalid_case_identity_is_rejected(tmp_path, change):
    case = _case(tmp_path)
    manifest = _manifest(case)
    if change == "family":
        case["family"] = "image-heavy"
    else:
        manifest["cases"].append(case)
    with pytest.raises(ValueError):
        inspect_manifest(manifest, tmp_path)


def test_cli_preserves_prior_reports_and_reports_incomplete(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(_manifest(_case(tmp_path))))
    report = tmp_path / "inventory.json"
    assert main([str(manifest), "--out", str(report)]) == 3
    original = report.read_bytes()
    with pytest.raises(SystemExit) as exc:
        main([str(manifest), "--out", str(report)])
    assert exc.value.code == 2
    assert report.read_bytes() == original
