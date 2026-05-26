from proxy.services.runtime_admission import (
    count_active_jobs,
    evaluate_chat_admission,
    memory_snapshot,
)


def test_memory_snapshot_prefers_explicit_free_memory():
    snapshot = memory_snapshot({
        "ram_total": 24.0,
        "ram_used": 20.0,
        "ram_free_gb": 6.5,
        "swap_used_gb": 1.2,
        "swap_pct": 12,
    })

    assert snapshot["ram_free_gb"] == 6.5
    assert snapshot["ram_used_gb"] == 20.0
    assert snapshot["swap_used_gb"] == 1.2
    assert snapshot["swap_pct"] == 12.0


def test_chat_admission_blocks_high_swap_and_low_free_memory():
    result = evaluate_chat_admission(
        current_mode={"mode": "chat"},
        metrics_cache={"ram_free_gb": 5.0, "swap_used_gb": 2.4, "swap_pct": 86.0},
        min_free_gb=8.0,
        max_swap_pct=60.0,
        max_swap_used_gb=2.0,
        swap_relief_free_gb=12.0,
    )

    assert result.allowed is False
    assert result.status_code == 503
    assert "ram_free_gb=5.0 < 8.0" in result.reason
    assert "swap_pct=86.0 > 60.0" in result.reason


def test_chat_admission_allows_stale_macos_swap_when_ram_is_plentiful():
    result = evaluate_chat_admission(
        current_mode={"mode": "chat"},
        metrics_cache={"ram_free_gb": 16.0, "swap_used_gb": 1.5, "swap_pct": 72.0},
        min_free_gb=8.0,
        max_swap_pct=60.0,
        max_swap_used_gb=2.0,
        swap_relief_free_gb=12.0,
    )

    assert result.allowed is True


def test_chat_admission_blocks_indexing_mode_before_memory_checks():
    result = evaluate_chat_admission(
        current_mode={"mode": "indexing"},
        metrics_cache={},
        min_free_gb=8.0,
        max_swap_pct=60.0,
    )

    assert result.allowed is False
    assert result.status_code == 409
    assert "Indexing mode is active" in result.reason


def test_chat_admission_blocks_active_jobs_and_busy_llm():
    result = evaluate_chat_admission(
        current_mode={"mode": "chat"},
        metrics_cache={"ram_free_gb": 16.0, "swap_pct": 5.0},
        active_jobs=2,
        llm_available=False,
        min_free_gb=8.0,
        max_swap_pct=60.0,
    )

    assert result.allowed is False
    assert result.status_code == 429
    assert "active_jobs=2" in result.reason
    assert "llm_generation_slots=0" in result.reason


def test_active_job_count_deduplicates_durable_and_memory_jobs():
    class FakeJobs:
        def list_active_ids(self, limit=500):
            return ["same", "durable-only"]

    count = count_active_jobs(
        FakeJobs(),
        {
            "same": {"status": "RUNNING"},
            "memory-only": {"status": "PARSING"},
            "done": {"status": "COMPLETED"},
        },
    )

    assert count == 3
