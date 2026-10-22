"""Real owned subprocess cleanup with stdlib-only children, never a model."""

import json
import os
import sys
import time

import pytest

from pdfexact.layout import text_comprehension_local as local


@pytest.mark.parametrize("stubborn", [False, True])
def test_real_deadline_terminates_kills_if_needed_and_reaps_own_child(monkeypatch, stubborn):
    code = (
        "import json, signal, sys, time\n"
        + ("signal.signal(signal.SIGTERM, signal.SIG_IGN)\n" if stubborn else "")
        + "json.load(sys.stdin)\n"
        + "print(json.dumps({'stage':'fixture-wait','inference_invoked':False,"
        "'first_token_observed':False,'generated_tokens':0}), flush=True)\n"
        + "time.sleep(15)\n"
    )
    monkeypatch.setattr(local, "_commande_sonde_shadow", lambda: [sys.executable, "-I", "-B", "-c", code])
    started = time.monotonic()
    result = local._executer_sonde_shadow_isolee({"fixture": "no-model"}, timeout=0.8)
    assert time.monotonic() - started < 3
    assert result["runtime_attempt"] == "timeout" and result["failure_stage"] == "fixture-wait"
    assert result["inference_invoked"] is False and not result["first_token_observed"]
    worker = result["worker"]
    assert worker["terminated"] and worker["killed"] is stubborn
    assert worker["finished"] and not worker["alive"] and worker["returncode"] < 0
    with pytest.raises(ChildProcessError):
        os.waitpid(worker["pid"], os.WNOHANG)


def test_real_normal_completion_is_reaped_without_termination(monkeypatch):
    event = {"status": "fixture-completed", "runtime_attempt": "not-attempted",
             "inference_invoked": False, "first_token_observed": False}
    code = "import json,sys; json.load(sys.stdin); print(" + repr(json.dumps(event)) + ",flush=True)"
    monkeypatch.setattr(local, "_commande_sonde_shadow", lambda: [sys.executable, "-I", "-B", "-c", code])
    result = local._executer_sonde_shadow_isolee({}, timeout=2)
    assert result["status"] == "fixture-completed" and result["inference_invoked"] is False
    worker = result["worker"]
    assert worker["returncode"] == 0 and not worker["alive"]
    assert not worker["terminated"] and not worker["killed"]
    with pytest.raises(ChildProcessError):
        os.waitpid(worker["pid"], os.WNOHANG)


def test_timeout_without_any_child_milestone_preserves_uncertainty(monkeypatch):
    monkeypatch.setattr(local, "_commande_sonde_shadow", lambda: [
        sys.executable, "-I", "-B", "-c", "import time; time.sleep(15)"])
    result = local._executer_sonde_shadow_isolee({}, timeout=0.3)
    assert result["failure_stage"] == "unknown"
    assert result["inference_invoked"] is None and result["first_token_observed"] is None
    assert result["generated_tokens"] is None and not result["worker"]["alive"]


def test_memory_preflight_includes_runtime_overhead_and_reserve(monkeypatch, tmp_path):
    (tmp_path / "model.bin").write_bytes(b"synthetic-small-bundle")
    monkeypatch.setattr(local, "open", lambda *_args, **_kwargs: __import__("io").StringIO("MemAvailable: 1048576 kB\n"), raising=False)
    monkeypatch.setattr(local.Path, "read_text", lambda *_args, **_kwargs: "max")
    with pytest.raises(MemoryError, match="insufficient-memory"):
        local._memory_preflight(tmp_path)
