"""Opt-in, real CPU probes; exact expectations are deliberately not model scores."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import resource
from time import monotonic

import pytest

from pdfexact.layout import text_comprehension as comprehension
from pdfexact.layout.text_comprehension_local import creer_fournisseur_comprehension_texte_local


_CASES = [
    ("ru-continuation", "page-segmentation", (
        "Система получает входные данные и проверяет их",
        "перед обработкой и сохранением результата.",
    ), "line_groups", ((0, 1),)),
    ("zh-continuation", "page-segmentation", (
        "系统接收输入数据并检查其完整性，",
        "然后处理并保存结果。",
    ), "line_groups", ((0, 1),)),
    ("ja-continuation", "page-segmentation", (
        "システムは入力データの内容を確認してから、",
        "処理結果を保存します。",
    ), "line_groups", ((0, 1),)),
    ("ko-continuation", "page-segmentation", (
        "시스템은 입력 데이터의 내용을 확인한 후",
        "처리 결과를 저장합니다.",
    ), "line_groups", ((0, 1),)),
    ("ru-independent-labels", "page-segmentation", ("Давление", "Температура", "Скорость"), "line_groups", ((0,), (1,), (2,))),
    ("zh-independent-labels", "page-segmentation", ("压力", "温度", "速度"), "line_groups", ((0,), (1,), (2,))),
    ("ru-heading-boundary", "page-segmentation", (
        "Описание системы", "Система получает входные данные и проверяет их",
        "перед обработкой и сохранением результата.",
    ), "line_groups", ((0,), (1, 2))),
    ("ru-prose-line", "line", ("Это обычный русский текст который описывает работу системы и её ограничения.",), "action", "candidate-paragraph-line"),
    ("ru-label-line", "line", ("Температура",), "action", "preserve-line"),
    ("ru-label-group", "group", ("Давление", "Температура"), "action", "preserve-lines"),
    ("ru-prose-group", "group", ("Система получает входные данные и проверяет их", "перед обработкой и сохранением результата."), "action", "merge-paragraph"),
    ("zh-no-space", "paragraph-reflow", ("系统接收输入数据", "然后保存结果。"), "line_joins", ("no_space",)),
    ("ja-no-space", "paragraph-reflow", ("システムは入力データを", "確認して保存します。"), "line_joins", ("no_space",)),
    ("ko-space", "paragraph-reflow", ("시스템은 입력 데이터를", "확인한 후 저장합니다."), "line_joins", ("space",)),
    ("ru-hard-break", "paragraph-reflow", ("Первая строка\n", "Вторая строка"), "line_joins", ("preserve_break",)),
]

pytestmark = pytest.mark.skipif(
    not os.environ.get("PDFEXACT_TEST_LOCAL_CT2_ROOT"),
    reason="real CPU probes require explicit PDFEXACT_TEST_LOCAL_CT2_ROOT; no downloads",
)


@pytest.fixture(scope="module")
def cpu_probe(tmp_path_factory):
    started = monotonic()
    provider = creer_fournisseur_comprehension_texte_local(
        model_root=os.environ["PDFEXACT_TEST_LOCAL_CT2_ROOT"], timeout=30,
    )
    assert provider is not None, "explicit local bundle is missing or incompatible"
    digest = hashlib.sha256()
    with (provider.path / "model.bin").open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    report = {
        "runtime": {name: importlib.metadata.version(name) for name in ("ctranslate2", "tokenizers")},
        "model_sha256": digest.hexdigest(), "diagnostics": dict(provider.diagnostics),
        "quality_scope": "advisory small fixed probes; no calibrated confidence or general quality claim",
        "cases": [],
    }
    with comprehension.contexte_comprehension_texte():
        comprehension.configurer_fournisseur_comprehension_texte(provider)
        yield provider, report
    report["total_seconds"] = monotonic() - started
    report["process_peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    path = Path(os.environ.get("PDFEXACT_CT2_PROBE_REPORT", str(tmp_path_factory.mktemp("ct2") / "report.json")))
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"CPU probe report: {path}")


@pytest.mark.parametrize("case,kind,lines,field,expected", _CASES, ids=[item[0] for item in _CASES])
def test_real_local_cpu_decisions(cpu_probe, case, kind, lines, field, expected):
    provider, report = cpu_probe
    started = monotonic()
    before = tuple(lines)
    decision = provider(kind, lines, "text-column", {"frame_strategy": "word-text"})
    actual = getattr(decision, field) if decision is not None else None
    report["cases"].append({
        "id": case, "request_kind": kind, "source_lines": lines,
        "field": field, "expected": expected, "actual": actual,
        "matched": actual == expected, "wall_seconds": monotonic() - started,
        "diagnostics": dict(provider.diagnostics),
    })
    assert lines == before
    assert actual == expected, provider.diagnostics
