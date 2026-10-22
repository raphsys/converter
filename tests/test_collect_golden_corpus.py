from dataclasses import dataclass, field
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pymupdf
import pytest

from scripts.collect_golden_corpus import (
    collect, compare_pages, plan_snapshot, qualify_audit, render_control, snapshot,
)


@dataclass
class Element:
    element_id: str
    source_ids: tuple[str, ...]


@dataclass
class Decision:
    mode: str = "positioned-text"
    reason_codes: tuple[str, ...] = ("fixture",)


@dataclass
class Planned:
    element: Element
    decision: Decision = field(default_factory=Decision)
    materialization: tuple[str, ...] = ("fixture-instruction",)


@dataclass
class Plan:
    pages: dict
    options: dict
    instructions_by_page: dict

    def validate(self):
        return []


@dataclass
class Audit:
    records: list


@pytest.fixture(autouse=True)
def stable_test_code_snapshot(monkeypatch):
    monkeypatch.setattr("scripts.collect_golden_corpus.code_snapshot", lambda: {"sha256": "fixture-code", "files": {}})


class Pipeline:
    def __init__(self, events=None, *, empty=False, discarded=False, mutate=False):
        self.events = events if events is not None else []
        self.empty, self.discarded, self.mutate = empty, discarded, mutate
        self.plans, self.written_plans = [], []

    def prepare_options(self, options):
        return {"analysis": {"target_reader": "word"}, "extract": {"strict": True}, **options}

    def extract(self, source, pages, options):
        self.events.append("extract")
        return SimpleNamespace(pages=[SimpleNamespace(index=page) for page in pages])

    def scene(self, document):
        self.events.append("scene")
        pages = [{"index": page.index, "elements": [
            {"element_id": f"p{page.index}", "source_ids": [f"source:{page.index}"],
             "verification_state": "detected", "decision_history": [], "z_order": 0, "opacity": 0}
        ]} for page in document.pages]
        if self.discarded:
            pages[0]["elements"].append({"element_id": "lost", "source_ids": ["lost-source"],
                                         "verification_state": "warning", "decision_history": []})
        return SimpleNamespace(snapshot=lambda: {"pages": pages})

    def build_plan(self, document, options):
        self.events.append("plan")
        pages = {page.index: [] if self.empty else [Planned(Element(f"p{page.index}", (f"source:{page.index}",)))]
                 for page in document.pages}
        plan = Plan(pages, options, {page.index: ("fixture-instruction",) for page in document.pages})
        self.plans.append(plan)
        return plan

    def write(self, document, destination, plan):
        self.events.append("write")
        self.written_plans.append(plan)
        with zipfile.ZipFile(destination, "w") as package:
            for part in ("[Content_Types].xml", "_rels/.rels", "word/document.xml"):
                package.writestr(part, "<root/>")
        if self.mutate:
            plan.options["mutated"] = True
        return {"fixture": True, "not_real_render": True}

    def audit(self, document, plan, source, control):
        self.events.append("audit")
        with pymupdf.open(source) as pdf:
            assert pdf.page_count == len(document.pages)
        return Audit([{"element_id": f"p{page.index}", "status": "ok"} for page in document.pages])


def make_pdf(path, pages=1):
    with pymupdf.open() as pdf:
        for index in range(pages):
            page = pdf.new_page()
            page.insert_text((30, 30), f"Fixture page {index + 1}")
        pdf.save(path)


def manifest(source, *, pages=None, count=1):
    return {"schema": "pdfexact.golden-manifest.v1", "cases": [
        {"case_id": f"arbitrary-name-{index}", "family": "vertical-text", "family_confirmed": True,
         "artifacts": {"source_pdf": str(source)},
         **({"source_pages": pages} if pages is not None else {})}
        for index in range(count)
    ]}


def fixture_renderer(docx, directory):
    from scripts.collect_golden_corpus import file_hash

    source = directory / "selected_source.pdf"
    if not source.exists():
        source = directory / "source.pdf"
    control = directory / "fixture-control.pdf"
    control.write_bytes(source.read_bytes())
    return {"reader": "fixture-not-a-real-reader", "reader_version": "fixture",
            "exit_code": 0, "pdf_path": str(control), "docx_sha256": file_hash(docx),
            "pdf_sha256": file_hash(control), "fixture": True}


def read(path):
    return json.loads(path.read_text())


def test_sequential_collection_passes_exact_plan_and_never_certifies_fixture(tmp_path):
    source = tmp_path / "input.pdf"
    make_pdf(source)
    events = []
    pipeline = Pipeline(events)
    output = tmp_path / "new"
    collect(manifest(source, count=2), tmp_path, output, pipeline=pipeline, renderer=fixture_renderer)
    assert events == ["extract", "scene", "plan", "write", "audit"] * 2
    assert all(written is built for written, built in zip(pipeline.written_plans, pipeline.plans))
    assert read(output / "collection.json")["status"] == "INCOMPLETE"
    assert read(output / "inventory.json")["status"] == "INCOMPLETE"
    assert read(output / "inventory.json")["cases"][0]["render_evidence_bound"] is False
    for number in ("001", "002"):
        directory = output / number
        assert read(directory / "audit.json")["exhaustive"] is False
        assert read(directory / "verdict.json")["status"] == "INCOMPLETE"
        scene = read(directory / "scene.json")
        assert scene["pages"][0]["elements"][0]["opacity"] == 0
        assert read(directory / "render_plan.json") == plan_snapshot(pipeline.plans[int(number) - 1])
        metadata = read(directory / "metadata.json")
        assert metadata["source_sha256"] and not metadata["code_changed"]
        assert metadata["source_changed"] is False and metadata["render_changed"] is False
        assert metadata["page_comparison"]["scores"][0]["ssim"] == pytest.approx(1)


def test_missing_control_preserves_docx_and_explicit_incomplete(tmp_path):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    pipeline = Pipeline()
    output = tmp_path / "missing"
    renderer = lambda *args: {"reader": "libreoffice", "exit_code": 0, "pdf_path": None}
    collect(manifest(source), tmp_path, output, pipeline=pipeline, renderer=renderer)
    case = read(output / "manifest.json")["cases"][0]
    assert (output / case["artifacts"]["docx"]["path"]).is_file()
    assert case["artifacts"]["control_pdf"] is None
    assert case["artifacts"]["audit_report"] is None
    assert "audit" not in pipeline.events
    assert "unavailable" in read(output / "001/metadata.json")["failure"]["message"]


@pytest.mark.parametrize("missing", ["empty", "discarded"])
def test_uncovered_source_blocks_writer_even_if_plan_validate_accepts(tmp_path, missing):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    pipeline = Pipeline(**{missing: True})
    output = tmp_path / "blocked"
    collect(manifest(source), tmp_path, output, pipeline=pipeline, renderer=fixture_renderer)
    assert not pipeline.written_plans
    metadata = read(output / "001/metadata.json")
    assert any(error.startswith("uncovered-source:") for error in metadata["prewrite_errors"])
    assert read(output / "001/render_plan.json")["pages"] is not None


def test_selected_noncontiguous_pages_keep_source_and_correct_audit_selection(tmp_path):
    source = tmp_path / "source.pdf"
    make_pdf(source, 4)
    output = tmp_path / "selected"
    pipeline = Pipeline()
    collect(manifest(source, pages=[4, 2]), tmp_path, output, pipeline=pipeline, renderer=fixture_renderer)
    assert list(pipeline.plans[0].pages) == [3, 1]
    with pymupdf.open(output / "001/source.pdf") as pdf:
        assert pdf.page_count == 4
    with pymupdf.open(output / "001/selected_source.pdf") as pdf:
        assert pdf.page_count == 2
        assert "page 4" in pdf[0].get_text()
        assert "page 2" in pdf[1].get_text()
    assert read(output / "001/metadata.json")["page_comparison"]["source_pages"] == 2
    assert "source-control-page-count-mismatch" not in read(output / "inventory.json")["cases"][0]["reasons"]
    bindings = read(output / "001/page_mapping.json")["pages"]
    assert [item["source_page_1based"] for item in bindings] == [4, 2]
    assert [item["ir_page_index_actual"] for item in bindings] == [3, 1]
    assert [item["output_ordinal_1based_expected"] for item in bindings] == [1, 2]
    assert [item["control_ordinal_1based_present"] for item in bindings] == [1, 2]
    assert all(item["output_ordinal_1based_observed"] is None for item in bindings)
    assert all(item["source_to_output_content_binding"] == "UNVERIFIED" for item in bindings)


@pytest.mark.parametrize("indices", [[0, 1], [3, 3], [1, 3], [3], [3, 1, 0]])
def test_rebased_duplicate_reordered_missing_or_extra_pages_block_writer(tmp_path, indices):
    source = tmp_path / "source.pdf"
    make_pdf(source, 4)
    pipeline = Pipeline()
    pipeline.extract = lambda *args: SimpleNamespace(pages=[SimpleNamespace(index=index) for index in indices])
    output = tmp_path / "bad-binding"
    collect(manifest(source, pages=[4, 2]), tmp_path, output, pipeline=pipeline, renderer=fixture_renderer)
    assert not pipeline.written_plans
    assert "page-order-or-identity" in read(output / "001/metadata.json")["failure"]["message"]


def test_scene_page_indices_cannot_rebase_source_binding(tmp_path):
    source = tmp_path / "source.pdf"
    make_pdf(source, 4)
    pipeline = Pipeline()
    scene = pipeline.scene

    def rebased(document):
        data = scene(document).snapshot()
        data["pages"][0]["index"] = 0
        return SimpleNamespace(snapshot=lambda: data)

    pipeline.scene = rebased
    output = tmp_path / "scene-binding"
    collect(manifest(source, pages=[4, 2]), tmp_path, output, pipeline=pipeline, renderer=fixture_renderer)
    assert not pipeline.written_plans
    assert "scene-source-page" in read(output / "001/metadata.json")["failure"]["message"]


def test_stale_requested_mapping_blocks_writer(tmp_path):
    source = tmp_path / "source.pdf"
    make_pdf(source, 4)
    data = manifest(source, pages=[4, 2])
    data["cases"][0]["page_mapping"] = [
        {"source_page_1based": 2, "output_ordinal_1based_expected": 1},
        {"source_page_1based": 4, "output_ordinal_1based_expected": 2},
    ]
    pipeline = Pipeline()
    output = tmp_path / "stale-mapping"
    collect(data, tmp_path, output, pipeline=pipeline, renderer=fixture_renderer)
    assert not pipeline.written_plans
    assert "manifest-page-mapping" in read(output / "001/metadata.json")["failure"]["message"]


def test_extra_control_page_blocks_audit_without_truncation(tmp_path):
    from scripts.collect_golden_corpus import file_hash

    source = tmp_path / "source.pdf"
    make_pdf(source)
    pipeline = Pipeline()

    def extra_page(docx, directory):
        result = fixture_renderer(docx, directory)
        path = Path(result["pdf_path"])
        path.unlink()
        make_pdf(path, 2)
        result["pdf_sha256"] = file_hash(path)
        return result

    output = tmp_path / "extra-control"
    collect(manifest(source), tmp_path, output, pipeline=pipeline, renderer=extra_page)
    assert "audit" not in pipeline.events
    assert "page-count-mismatch" in read(output / "001/metadata.json")["failure"]["message"]


def test_relative_artifacts_remain_valid_when_collection_is_relocated(tmp_path):
    from scripts.validate_golden_corpus import inspect_manifest

    source = tmp_path / "source.pdf"
    make_pdf(source, 4)
    output = tmp_path / "original-location"
    collect(manifest(source, pages=[4, 2]), tmp_path, output, pipeline=Pipeline(), renderer=fixture_renderer)
    saved = read(output / "manifest.json")
    case = saved["cases"][0]
    for item in case["artifacts"].values():
        assert not Path(item["path"]).is_absolute()
        assert item["sha256"]
    assert case["selected_source_pdf"]["path"] == "001/selected_source.pdf"
    moved = tmp_path / "relocated"
    output.rename(moved)
    inventory = inspect_manifest(saved, moved)
    assert inventory["cases"][0]["present_artifact_count"] == 7
    assert inventory["cases"][0]["status"] == "INCOMPLETE"


def test_incorrect_page_source_hash_blocks_writer(tmp_path):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    pipeline = Pipeline()
    pipeline.extract = lambda *args: SimpleNamespace(pages=[SimpleNamespace(index=0, source_pdf_id="stale")])
    output = tmp_path / "bad-source-id"
    collect(manifest(source), tmp_path, output, pipeline=pipeline, renderer=fixture_renderer)
    assert not pipeline.written_plans
    assert "source-pdf-hash-mismatch" in read(output / "001/metadata.json")["failure"]["message"]


def test_writer_cannot_change_source_page_order_before_reader(tmp_path):
    source = tmp_path / "source.pdf"
    make_pdf(source, 4)
    pipeline = Pipeline()
    write = pipeline.write

    def mutate_document(document, destination, plan):
        result = write(document, destination, plan)
        document.pages.reverse()
        return result

    pipeline.write = mutate_document
    output = tmp_path / "writer-source-order"
    collect(manifest(source, pages=[4, 2]), tmp_path, output, pipeline=pipeline, renderer=fixture_renderer)
    assert "render" not in pipeline.events
    assert "page-order-or-identity" in read(output / "001/metadata.json")["failure"]["message"]


def test_control_outside_owned_collection_is_rejected_without_losing_verdict(tmp_path):
    from scripts.collect_golden_corpus import file_hash

    source = tmp_path / "source.pdf"
    make_pdf(source)
    outside = tmp_path / "foreign-control.pdf"
    make_pdf(outside)
    pipeline = Pipeline()

    def foreign(docx, directory):
        return {"reader": "fixture", "reader_version": "fixture", "exit_code": 0,
                "fixture": True, "pdf_path": str(outside), "pdf_sha256": file_hash(outside),
                "docx_sha256": file_hash(docx)}

    output = tmp_path / "foreign-output"
    collect(manifest(source), tmp_path, output, pipeline=pipeline, renderer=foreign)
    assert "audit" not in pipeline.events
    assert read(output / "001/verdict.json")["status"] == "INCOMPLETE"
    assert read(output / "manifest.json")["cases"][0]["artifacts"]["control_pdf"] is None


def test_page_comparison_does_not_truncate_extra_or_missing_pages(tmp_path):
    source, control = tmp_path / "source.pdf", tmp_path / "control.pdf"
    make_pdf(source)
    make_pdf(control, 2)
    for first, second in ((source, control), (control, source)):
        result = compare_pages(first, second)
        assert result["status"] == "INCOMPLETE"
        assert result["reason"] == "page-count-mismatch"
        assert result["scores"] == []


def test_writer_mutation_is_reported_and_cannot_replace_saved_plan(tmp_path):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    output = tmp_path / "mutated"
    pipeline = Pipeline(mutate=True)
    collect(manifest(source), tmp_path, output, pipeline=pipeline, renderer=fixture_renderer)
    assert "render" not in read(output / "001/metadata.json")["stages"]
    assert "mutated" in read(output / "001/metadata.json")["failure"]["message"]
    assert "mutated" not in read(output / "001/render_plan.json")["options"]


def test_code_mutation_stops_before_next_case(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    calls = iter([{"sha256": "before"}, {"sha256": "before"}, {"sha256": "after"}])
    monkeypatch.setattr("scripts.collect_golden_corpus.code_snapshot", lambda: next(calls))
    output = tmp_path / "changed"
    result = collect(manifest(source, count=2), tmp_path, output, pipeline=Pipeline(), renderer=fixture_renderer)
    assert result["requested_cases"] == 2 and result["collected_cases"] == 1
    assert not (output / "002").exists()
    assert read(output / "001/verdict.json")["code_changed"] is True


def test_existing_outputs_and_bad_source_hash_are_preserved(tmp_path):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    data = manifest(source)
    data["cases"][0]["artifacts"]["source_pdf"] = {"path": str(source), "sha256": "incorrect"}
    output = tmp_path / "out"
    collect(data, tmp_path, output, pipeline=Pipeline(), renderer=fixture_renderer)
    previous = (output / "collection.json").read_bytes()
    with pytest.raises(FileExistsError):
        collect(data, tmp_path, output, pipeline=Pipeline(), renderer=fixture_renderer)
    assert (output / "collection.json").read_bytes() == previous
    assert "hash" in read(output / "001/metadata.json")["failure"]["message"]


def test_real_reader_wrapper_records_commands_version_isolation_and_failure(tmp_path, monkeypatch):
    docx = tmp_path / "document.docx"
    docx.write_bytes(b"fixture")
    commands = []

    def process(command, timeout):
        commands.append(command)
        return {"command": command, "exit_code": 0,
                "stdout": "LibreOffice fixture" if "--version" in command else "", "stderr": ""}

    monkeypatch.setattr("scripts.collect_golden_corpus._process", process)
    evidence = render_control(docx, tmp_path)
    assert evidence["reader_version"] == "LibreOffice fixture"
    assert commands[0][-1] == "--version"
    assert any(arg.startswith("-env:UserInstallation=file:") for arg in commands[1])
    assert evidence["pdf_path"] is None and evidence["isolated_profile"]


def test_snapshot_rejects_unknown_objects_instead_of_hiding_contract_loss():
    with pytest.raises(TypeError, match="unsupported snapshot type"):
        snapshot(SimpleNamespace(untracked_metadata=True))


def test_document_bound_coverage_is_delegated_and_saved(tmp_path):
    from scripts.collect_golden_corpus import coverage_errors

    document = SimpleNamespace(pages=[SimpleNamespace(index=0)])
    scene = {"pages": [{"elements": [{"element_id": "original", "source_ids": ["original"]}]}]}

    @dataclass
    class CoveredPlan(Plan):
        source_coverage: dict = field(default_factory=dict)

        def validate(self, document=None):
            assert document is not None
            return []

    plan = CoveredPlan({0: [Planned(Element("replacement", ("replacement",)))]}, {}, {},
                       {"original": {"target_ids": ["replacement"], "relationship": "transformed", "reason": "proof"}})
    assert coverage_errors(document, scene, plan) == []
    assert plan_snapshot(plan)["source_coverage"]["original"]["reason"] == "proof"


def test_stale_render_hashes_prevent_audit(tmp_path):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    output = tmp_path / "stale"
    pipeline = Pipeline()

    def renderer(docx, directory):
        rendered = fixture_renderer(docx, directory)
        rendered["pdf_sha256"] = "stale"
        return rendered

    collect(manifest(source), tmp_path, output, pipeline=pipeline, renderer=renderer)
    assert "audit" not in pipeline.events
    assert "hash binding" in read(output / "001/metadata.json")["failure"]["message"]


def test_existing_scene_plan_and_writer_apis_on_small_ir_fixture(tmp_path, monkeypatch):
    from scripts.collect_golden_corpus import ProductionPipeline
    from pdfexact.geometry import BBox, pt_vers_emu
    from pdfexact.ir import Document, Page, ShapeEl

    source = tmp_path / "source.pdf"
    make_pdf(source)
    shape = ShapeEl(BBox(0, 0, pt_vers_emu(20), pt_vers_emu(20)), [], "000000", None, 0,
                    source_id="shape", source_ids=("shape",), source_kind="vector", z_index=0, alpha=0)
    document = Document([Page(0, pt_vers_emu(595), pt_vers_emu(842), [shape])])
    pipeline = ProductionPipeline()
    monkeypatch.setattr(pipeline, "extract", lambda *args: document)
    monkeypatch.setattr(pipeline, "audit", lambda *args: Audit([{"element_id": "shape", "status": "ok"}]))
    output = tmp_path / "api-fixture"
    collect(manifest(source), tmp_path, output, pipeline=pipeline, renderer=fixture_renderer)
    metadata = read(output / "001/metadata.json")
    assert "failure" not in metadata
    assert metadata["prewrite_errors"] == []
    assert (output / "001/document.docx").is_file()
    assert (output / "001/scene_contract.json").is_file()
    assert read(output / "001/scene.json")["pages"][0]["elements"][0]["opacity"] == 0
    planned = read(output / "001/render_plan.json")
    assert planned["source_inventory"]["shape"]["source_ids"] == ["shape"]
    assert planned["source_coverage"]["shape"]["target_ids"] == ["shape"]
    assert read(output / "001/verdict.json")["status"] == "INCOMPLETE"


def test_audit_defaults_and_visual_scores_are_not_unmeasured_perfect_metrics():
    report = Audit([
        {"element_id": "missing", "kind": "TextBox", "status": "missing",
         "token_recall": 1, "token_precision": 1, "bbox_iou": 1,
         "editable": True, "visible": True, "causes": ["output-page-missing"]},
        {"element_id": "visual", "kind": "ShapeEl", "status": "ok",
         "token_recall": 1, "token_precision": 1, "editable": True},
        {"element_id": "text", "kind": "TextBox", "status": "ok",
         "token_recall": 1, "token_precision": 1, "bbox_iou": 0, "bbox_drift_pt": 0,
         "style_mismatches": [], "visible": True, "editable": True},
    ])
    result = qualify_audit(report)
    assert result["exhaustive"] is False
    missing, visual, text = result["records"]
    assert missing["critical"] and result["critical_records"] == ["missing"]
    assert missing["measurements"]["token_recall_set_proxy"] is None
    assert visual["measurements"]["visual_region_similarity_proxy"] == 1
    assert visual["measurements"]["token_recall_set_proxy"] is None
    assert text["measurements"]["token_recall_set_proxy"] == 1
    assert text["status"] == "unverified"
    for record in result["records"]:
        assert record["measurements"]["editability"] is None
        assert record["measurements"]["visibility"] is None
        assert record["measurements"]["font_metrics"] is None
        assert record["measurements"]["token_order"] is None
    assert text["measurements"]["bbox_iou"] is None
    assert text["measurements"]["reported_style_mismatches"] is None


def test_observation_detects_source_and_render_artifact_mutation(tmp_path):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    output = tmp_path / "tampered"

    class MutatingAudit(Pipeline):
        def audit(self, document, plan, selected_source, control):
            source.write_bytes(b"source changed")
            control.write_bytes(b"control changed")
            return Audit([{"element_id": "p0", "status": "ok"}])

    collect(manifest(source), tmp_path, output, pipeline=MutatingAudit(), renderer=fixture_renderer)
    verdict = read(output / "001/verdict.json")
    assert verdict["source_changed"] is True and verdict["render_changed"] is True
    assert verdict["failure"]["type"] == "ArtifactMutation"
    assert verdict["status"] == "INCOMPLETE"
