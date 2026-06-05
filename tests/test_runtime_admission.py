from proxy.services.runtime_admission import (
    count_active_jobs,
    evaluate_chat_admission,
    evaluate_memory_pressure,
    memory_snapshot,
)
from proxy.services.resource_governor import current_runtime_profile, enter_chat_mode, enter_indexing_mode


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
    assert result.memory_state == "CRITICAL"
    assert result.runtime_profile == "CHAT"


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
    assert result.memory_state == "GREEN"


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


def test_memory_pressure_profiles_green_yellow_red_critical():
    assert evaluate_memory_pressure({"ram_free_gb": 16.0, "swap_pct": 5.0}).state == "GREEN"
    assert evaluate_memory_pressure({"ram_free_gb": 10.0, "swap_pct": 5.0}).state == "YELLOW"
    assert evaluate_memory_pressure({"ram_free_gb": 7.0, "swap_pct": 5.0}).state == "RED"
    assert evaluate_memory_pressure({"ram_free_gb": 5.0, "swap_pct": 5.0}).state == "CRITICAL"
    assert evaluate_memory_pressure({"ram_free_gb": 16.0, "swap_pct": 80.0}).state == "CRITICAL"


def test_runtime_profile_is_carried_by_mode_transitions():
    state = {}
    enter_indexing_mode(state, reason="batch")
    assert current_runtime_profile(state) == "INDEX_LIGHT"

    enter_chat_mode(state, reason="done")
    assert current_runtime_profile(state) == "CHAT"


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
