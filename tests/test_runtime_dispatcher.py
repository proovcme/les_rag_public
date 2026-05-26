import json
from types import SimpleNamespace

import pytest

from proxy.services.runtime_dispatcher import DEFAULT_DATASETS, DispatcherError, RuntimeDispatcher
from tools.les_runtime_control import MemoryPreflight, ServiceStatus


def _preflight(ram_free=8.0, swap_pct=10.0):
    return MemoryPreflight(
        ram_free_gb=ram_free,
        ram_total_gb=24.0,
        swap_pct=swap_pct,
        top_processes=[],
        kill_candidates=[],
        min_free_gb=4.0,
        min_rss_mb=700.0,
    )


def _services(_keys):
    return [
        ServiceStatus(
            key="proxy",
            title="les-proxy",
            label="me.ovc.les.proxy",
            loaded=True,
            running=True,
            pid=101,
            port=8050,
            port_pid=101,
            health="ok",
            detail="HTTP 200",
        )
    ]


def _dispatcher(tmp_path, *, preflight=None, pid_running=lambda _pid: False, popen=None):
    return RuntimeDispatcher(
        root=tmp_path,
        current_mode={"mode": "chat", "runtime_profile": "CHAT"},
        metrics_cache={},
        memory_preflight_fn=lambda **_kwargs: preflight or _preflight(),
        service_status_fn=_services,
        popen_factory=popen or (lambda *args, **kwargs: SimpleNamespace(pid=222)),
        pid_running_fn=pid_running,
    )


def _write_state(root, completed=0, total=3):
    state_dir = root / "artifacts" / "reindex_runs"
    state_dir.mkdir(parents=True)
    state_path = state_dir / "reindex_state_ntd_fire_index__ntd_hvac_index.json"
    state_path.write_text(
        json.dumps(
            {
                "datasets": DEFAULT_DATASETS,
                "db_path": str(root / "missing.db"),
                "completed": {f"doc-{i}": {} for i in range(completed)},
                "runs": [{"run_dir": "run"}],
                "updated_at": "now",
            }
        ),
        encoding="utf-8",
    )
    log_path = state_dir / "run.out"
    log_path.write_text(
        json.dumps(
            {
                "event": "plan",
                "target_docs": total - completed,
                "completed_in_state": completed,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return state_path, log_path


def test_dispatcher_status_without_campaign(tmp_path):
    dispatcher = _dispatcher(tmp_path)

    status = dispatcher.status_payload()

    assert status["component"] == "runtime_dispatcher"
    assert status["policy"] == "wait_only"
    assert status["reindex"]["running"] is False
    assert status["reindex"]["state_exists"] is False
    assert status["actions"]["can_start"] is True
    assert status["services"][0]["key"] == "proxy"


def test_dispatcher_public_reindex_status_payload(tmp_path):
    state_path, log_path = _write_state(tmp_path, completed=2, total=3)
    pid_file = tmp_path / "artifacts" / "reindex_runs" / "guarded_reindex_hvac_fire.pid.json"
    pid_file.write_text(
        json.dumps({"pid": 123, "state_file": str(state_path), "log_path": str(log_path)}),
        encoding="utf-8",
    )
    dispatcher = _dispatcher(tmp_path, pid_running=lambda pid: pid == 123)

    status = dispatcher.reindex_status_payload()

    assert status["running"] is True
    assert status["completed"] == 2
    assert status["remaining"] == 1


def test_dispatcher_detects_zombie_or_stale_pid(tmp_path):
    state_path, log_path = _write_state(tmp_path, completed=1, total=3)
    pid_file = tmp_path / "artifacts" / "reindex_runs" / "guarded_reindex_hvac_fire.pid.json"
    pid_file.write_text(
        json.dumps({"pid": 123, "state_file": str(state_path), "log_path": str(log_path)}),
        encoding="utf-8",
    )
    dispatcher = _dispatcher(tmp_path, pid_running=lambda _pid: False)

    status = dispatcher.status_payload()

    assert status["reindex"]["running"] is False
    assert status["reindex"]["stale_pid"] is True
    assert status["reindex"]["remaining"] == 2
    assert status["actions"]["can_resume"] is True


def test_dispatcher_start_returns_existing_running_campaign(tmp_path):
    state_path, log_path = _write_state(tmp_path, completed=1, total=3)
    pid_file = tmp_path / "artifacts" / "reindex_runs" / "guarded_reindex_hvac_fire.pid.json"
    pid_file.write_text(
        json.dumps({"pid": 123, "state_file": str(state_path), "log_path": str(log_path)}),
        encoding="utf-8",
    )
    dispatcher = _dispatcher(tmp_path, pid_running=lambda pid: pid == 123)

    result = dispatcher.start_reindex()

    assert result["status"] == "already_running"
    assert result["reindex"]["pid"] == 123


def test_dispatcher_blocks_start_when_memory_guard_fails(tmp_path):
    dispatcher = _dispatcher(tmp_path, preflight=_preflight(ram_free=2.0, swap_pct=90.0))

    with pytest.raises(DispatcherError) as exc:
        dispatcher.start_reindex(min_free_gb=4.0, max_swap_pct=85.0)

    assert exc.value.status_code == 503
    assert "ram_free_gb=2.0 < 4.0" in exc.value.detail
    assert "swap_pct=90.0 > 85.0" in exc.value.detail


def test_dispatcher_resume_uses_existing_state_and_clears_stop_file(tmp_path):
    state_path, _log_path = _write_state(tmp_path, completed=1, total=3)
    stop_file = tmp_path / "artifacts" / "reindex_runs" / "guarded_reindex_hvac_fire.stop.json"
    stop_file.write_text('{"reason":"test"}', encoding="utf-8")
    calls = []

    def fake_popen(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(pid=456)

    dispatcher = _dispatcher(tmp_path, popen=fake_popen)

    result = dispatcher.resume_reindex()

    assert result["status"] == "resumed"
    assert not stop_file.exists()
    assert calls
    assert "--state-file" in calls[0][0]
    assert str(state_path) in calls[0][0]
    assert "--stop-file" in calls[0][0]
