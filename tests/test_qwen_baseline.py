import json

from tools import qwen_baseline as baseline
from tools.rag_golden_set import GoldenCase


def test_active_profile_trace_reads_embedding_block():
    trace = baseline.active_profile_trace(
        {
            "embedding": {
                "profile": "qwen",
                "collection": "les_rag_qwen3_06b",
                "meta_db": "./data/les_meta_qwen.db",
            }
        }
    )

    assert trace["profile"] == "qwen"
    assert trace["collection"] == "les_rag_qwen3_06b"


def test_active_profile_trace_falls_back_to_health_qdrant_collection():
    trace = baseline.active_profile_trace(
        {"rag": {"qdrant": {"collection": "les_rag_qwen3_06b"}}}
    )

    assert trace["profile"] == ""
    assert trace["collection"] == "les_rag_qwen3_06b"


def test_chat_payload_disables_cache_and_reranker_explicitly():
    case = GoldenCase(id="c1", question="q", dataset_filter="NTD")

    payload = baseline.chat_payload(
        case,
        reranker_enabled=False,
        semantic_cache_enabled=False,
        validation_enabled=False,
        session_id="baseline-1",
    )

    assert payload == {
        "question": "q",
        "dataset_filter": "NTD",
        "reranker_enabled": False,
        "semantic_cache_enabled": False,
        "validation_enabled": False,
        "session_id": "baseline-1",
    }


def test_emit_result_jsonl_is_machine_readable():
    result = baseline.BaselineResult("c1", "retrieval", True, "passed", 0.1, sources=("doc",))

    line = baseline.emit_result(result, jsonl=True)

    assert json.loads(line)["case_id"] == "c1"


def test_emit_result_marks_guarded_stop():
    result = baseline.BaselineResult("c1", "chat", True, "GUARDED_STOP: ram_free_gb=4.3 < 8.0", 0.1, guarded_stop=True)

    line = baseline.emit_result(result, jsonl=False)

    assert line.startswith("[GUARD]")
    assert "GUARDED_STOP" in line


def test_guarded_stop_detail_detects_admission_rejection():
    result = baseline.HttpResult(503, '{"detail":"ram_free_gb=4.3 < 8.0"}', 0.1)

    assert baseline.guarded_stop_detail(result) == "ram_free_gb=4.3 < 8.0"


def test_preflight_fails_on_high_swap_and_low_memory():
    result = baseline.evaluate_preflight(
        metrics={"system": {"ram_total": 24.0, "ram_used": 19.0, "swap_pct": 86.0}},
        indexing_mode={"active": False, "chat_generation_allowed": True},
        jobs_summary={"active_count": 0},
        min_free_gb=8.0,
        max_swap_pct=60.0,
        ui_status=200,
    )

    assert result.ok is False
    assert "ram_free_gb=5.0 < 8.0" in result.detail
    assert "swap_pct=86.0 > 60.0" in result.detail


def test_preflight_fails_on_active_jobs_and_ui_timeout():
    result = baseline.evaluate_preflight(
        metrics={"system": {"ram_total": 24.0, "ram_used": 8.0, "swap_pct": 10.0}},
        indexing_mode={"active": False, "chat_generation_allowed": True},
        jobs_summary={"active_count": 1},
        min_free_gb=8.0,
        max_swap_pct=60.0,
        ui_status=0,
    )

    assert result.ok is False
    assert "active_jobs=1" in result.detail
    assert "ui_status=0" in result.detail


def test_preflight_can_skip_ui_check():
    result = baseline.evaluate_preflight(
        metrics={"system": {"ram_total": 24.0, "ram_used": 8.0, "swap_pct": 10.0}},
        indexing_mode={"active": False, "chat_generation_allowed": True},
        jobs_summary={"active_count": 0},
        min_free_gb=8.0,
        max_swap_pct=60.0,
        ui_status=None,
        require_ui=False,
    )

    assert result.ok is True


def test_chat_case_evaluation_reports_missing_source_hint():
    case = GoldenCase(id="c1", question="q", source_any=("СП 1",))

    class FakeClient:
        def request(self, method, path, payload=None):
            return baseline.HttpResult(
                200,
                json.dumps({"answer": "answer", "crag_status": "VERIFIED", "sources": ["other.pdf"]}),
                0.1,
            )

    result = baseline.run_chat_case(
        FakeClient(),
        case,
        reranker_enabled=False,
        semantic_cache_enabled=False,
        validation_enabled=True,
        session_id="baseline-1",
    )

    assert result.ok is False
    assert "missing source hint" in result.detail


def test_chat_case_treats_runtime_guard_as_guarded_stop():
    case = GoldenCase(id="c1", question="q")

    class FakeClient:
        def request(self, method, path, payload=None):
            return baseline.HttpResult(503, '{"detail":"ram_free_gb=4.3 < 8.0"}', 0.1)

    result = baseline.run_chat_case(
        FakeClient(),
        case,
        reranker_enabled=False,
        semantic_cache_enabled=False,
        validation_enabled=True,
        session_id="baseline-1",
    )

    assert result.ok is True
    assert result.guarded_stop is True
    assert "GUARDED_STOP" in result.detail


def test_parse_args_supports_guarded_run_options():
    args = baseline.parse_args([
        "--max-cases",
        "1",
        "--stop-on-guard",
        "--unload-after-case",
        "--wait-memory-after-unload",
        "--validation",
        "off",
    ])

    assert args.max_cases == 1
    assert args.stop_on_guard is True
    assert args.unload_after_case is True
    assert args.wait_memory_after_unload is True
    assert args.validation == "off"


def test_parse_args_supports_case_id_filter():
    args = baseline.parse_args(["--case-id", "a", "--case-id", "b"])

    assert args.case_id == ["a", "b"]


def test_wait_for_mlx_memory_accepts_recovered_memory(monkeypatch):
    calls = iter(
        [
            (True, {"ram_free_gb": 6.0, "swap_pct": 0.0}, "low"),
            (True, {"ram_free_gb": 8.2, "swap_pct": 0.0}, "ok"),
        ]
    )
    monkeypatch.setattr(baseline, "mlx_host_memory", lambda *args, **kwargs: next(calls))
    monkeypatch.setattr(baseline.time, "sleep", lambda seconds: None)

    ok, detail = baseline.wait_for_mlx_memory(
        "http://mlx",
        min_free_gb=8.0,
        max_swap_pct=60.0,
        timeout=10.0,
        poll_interval=0.1,
    )

    assert ok is True
    assert "ram_free_gb=8.2" in detail


def test_wait_for_mlx_memory_rejects_high_swap(monkeypatch):
    monkeypatch.setattr(
        baseline,
        "mlx_host_memory",
        lambda *args, **kwargs: (True, {"ram_free_gb": 12.0, "swap_pct": 90.0}, "high swap"),
    )
    monkeypatch.setattr(baseline.time, "sleep", lambda seconds: None)
    times = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(baseline.time, "time", lambda: next(times))

    ok, detail = baseline.wait_for_mlx_memory(
        "http://mlx",
        min_free_gb=8.0,
        max_swap_pct=60.0,
        timeout=1.0,
        poll_interval=0.1,
    )

    assert ok is False
    assert "swap_pct=90.0" in detail
