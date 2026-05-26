from types import SimpleNamespace

from sovushka import lite_admin
from sovushka.lite_admin import lite_admin_html, local_runtime_action_allowed


def test_lite_admin_html_uses_static_admin_shell():
    html = lite_admin_html()

    assert "Л.Е.С. LITE ADMIN" in html
    assert "без NiceGUI client state" in html
    assert "/les/classic" in html
    assert "/api/indexing-mode" in html
    assert "/api/rag/parse-scheduler" in html
    assert "/api/runtime/dispatcher/status" in html
    assert "/api/runtime/dispatcher/reindex/start" in html
    assert "/api/runtime/dispatcher/reindex/pause" in html
    assert "/api/runtime/dispatcher/reindex/resume" in html
    assert "HVAC/FIRE AUTO" in html
    assert "start_guarded_reindex" not in html


def test_lite_admin_runtime_actions_are_loopback_only():
    assert local_runtime_action_allowed(is_loopback=True)
    assert not local_runtime_action_allowed(is_loopback=False)


def test_pid_running_treats_zombie_as_stopped(monkeypatch):
    monkeypatch.setattr(lite_admin.os, "kill", lambda pid, signal: None)
    monkeypatch.setattr(
        lite_admin.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="Z\n"),
    )

    assert not lite_admin._pid_running(123)


def test_guarded_reindex_status_reads_state(tmp_path, monkeypatch):
    monkeypatch.setattr(lite_admin, "_repo_root", lambda: tmp_path)
    state_dir = tmp_path / "artifacts" / "reindex_runs"
    state_dir.mkdir(parents=True)
    (state_dir / "reindex_state_ntd_fire_index__ntd_hvac_index.json").write_text(
        '{"completed":{"a":{},"b":{}},"runs":[{}],"updated_at":"now"}',
        encoding="utf-8",
    )

    status = lite_admin.guarded_reindex_status_payload()

    assert status["completed"] == 2
    assert status["remaining"] == 192
    assert status["running"] is False


def test_guarded_reindex_is_not_a_local_runtime_action():
    assert "start_guarded_reindex" not in lite_admin.LOCAL_RUNTIME_ACTIONS
