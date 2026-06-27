"""Юнит-тест критериев basic_function_smoke: парсинг результатов + exit-логика (P0/P1/warn)."""
import time

from tools.basic_function_smoke import _r, compute_exit, failures


def _mk(name, severity, status):
    return {"name": name, "severity": severity, "status": status,
            "elapsed_ms": 1.0, "evidence": {}, "reason": ""}


def test_all_pass_exit_zero():
    res = [_mk("a", "P0", "pass"), _mk("b", "P1", "pass"), _mk("c", "P0", "warn")]
    assert compute_exit(res) == 0
    assert compute_exit(res, release=True) == 0


def test_p0_fail_always_exit_one():
    res = [_mk("a", "P0", "fail"), _mk("b", "P1", "pass")]
    assert compute_exit(res) == 1
    assert compute_exit(res, release=True) == 1
    assert failures(res, "P0") == ["a"]


def test_p1_fail_only_blocks_on_release():
    res = [_mk("a", "P0", "pass"), _mk("b", "P1", "fail")]
    assert compute_exit(res) == 0            # dev-сессия: P1 fail → warn, не валит
    assert compute_exit(res, release=True) == 1  # релиз: валит
    assert failures(res, "P1") == ["b"]


def test_warn_never_fails():
    res = [_mk("a", "P0", "warn"), _mk("b", "P1", "warn")]
    assert compute_exit(res) == 0
    assert compute_exit(res, release=True) == 0


def test_result_shape():
    r = _r("x", "P0", "pass", time.monotonic(), reason="ok", evidence={"k": 1})
    assert set(r) == {"name", "status", "severity", "elapsed_ms", "evidence", "reason"}
    assert r["name"] == "x" and r["severity"] == "P0" and r["status"] == "pass"
    assert r["evidence"] == {"k": 1} and r["reason"] == "ok"
