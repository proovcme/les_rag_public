"""Юнит-тест критериев basic_function_smoke: парсинг результатов + exit-логика (P0/P1/warn)."""
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tools.basic_function_smoke import (
    DEFAULT_CHAT_TIMEOUT,
    _chat,
    _r,
    check_chat_glossary,
    check_chat_project_noscope,
    check_diagnostics,
    check_health,
    compute_exit,
    failures,
)


def test_default_chat_timeout_covers_local_9b_release_probe():
    assert DEFAULT_CHAT_TIMEOUT == 90.0


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


def test_chat_uses_explicit_bounded_timeout():
    class Client:
        def __init__(self):
            self.call = None

        def post(self, url, **kwargs):
            self.call = (url, kwargs)
            return object()

    client = Client()
    _chat(client, "http://example.test", "вопрос", timeout=12.5)

    assert client.call == (
        "http://example.test/api/chat",
        {"json": {"question": "вопрос"}, "timeout": 12.5},
    )


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


class _Client:
    def __init__(self, response):
        self.response = response

    def get(self, _url):
        return self.response

    def post(self, _url, **_kwargs):
        return self.response


def test_health_error_is_a_p0_failure_not_a_reachable_pass():
    result = check_health(_Client(_Response(200, {"status": "error"})), "http://example.test")

    assert result["status"] == "fail"
    assert result["severity"] == "P0"


def test_health_degraded_is_explicit_warning():
    result = check_health(_Client(_Response(200, {"status": "degraded"})), "http://example.test")

    assert result["status"] == "warn"
    assert result["reason"] == "runtime degraded"


def test_diagnostics_error_is_not_hidden_by_http_200():
    result = check_diagnostics(_Client(_Response(200, {"overall": "err"})), "http://example.test")

    assert result["status"] == "fail"
    assert result["severity"] == "P1"


def test_glossary_smoke_requires_route_and_version_trace():
    payload = {
        "answer": "ОЖР — общий журнал работ.",
        "query_route": {"channel": "glossary"},
        "version_info": {},
    }
    result = check_chat_glossary(_Client(_Response(200, payload)), "http://example.test", timeout=1)

    assert result["status"] == "pass"


def test_glossary_smoke_accepts_current_nested_version_trace():
    payload = {
        "answer": "ОЖР — общий журнал работ.",
        "query_route": {"channel": "glossary"},
        "versions": {"version_info": {}},
    }
    result = check_chat_glossary(_Client(_Response(200, payload)), "http://example.test", timeout=1)

    assert result["status"] == "pass"


def test_project_noscope_smoke_rejects_glossary_hijack():
    payload = {
        "answer": "Нерелевантное определение.",
        "query_route": {"channel": "glossary"},
        "version_info": {},
    }
    result = check_chat_project_noscope(_Client(_Response(200, payload)), "http://example.test", timeout=1)

    assert result["status"] == "fail"


@pytest.mark.skipif(shutil.which("make") is None, reason="Makefile contract is checked on Unix runners")
def test_ship_paths_escalate_smoke_p1_to_release():
    root = Path(__file__).resolve().parents[1]
    for target in ("ship-check", "ship-full-check"):
        plan = subprocess.run(
            ["make", "-n", target], cwd=root, text=True, capture_output=True, check=True,
        ).stdout
        assert "tools/basic_function_smoke.py --release" in plan
