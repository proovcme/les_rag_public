from types import SimpleNamespace

from sovushka import lite_admin
from sovushka.lite_admin import lite_admin_html, local_runtime_action_allowed


def test_lite_admin_html_uses_static_admin_shell():
    html = lite_admin_html()

    assert "Л.Е.С. LITE ADMIN" in html
    assert "без NiceGUI client state" in html
    assert "/les/classic" in html
    assert "/api/indexing-mode" in html
    assert "/api/rag/watch/status" in html
    assert "/api/rag/watch/reindex-plan" in html
    assert "/api/runtime/dispatcher/status" in html
    assert "/api/runtime/dispatcher/reindex/start" in html
    assert "/api/runtime/dispatcher/reindex/pause" in html
    assert "/api/runtime/dispatcher/reindex/resume" in html
    assert "/api/runtime/dispatcher/mlx/unload" in html
    assert "Dispatcher / Reindex" in html
    assert "Watcher" in html
    assert "Memory" in html
    assert "CAD/BIM JSON" in html
    assert "speckleBaseUrl" in html
    assert "speckleGraphqlUrl" in html
    assert "speckleToken" in html
    assert "speckleSourceType" in html
    assert "Excel / Power BI" in html
    assert "source_type" in html
    assert "SAVE SPECKLE" in html
    assert "CHECK SPECKLE" in html
    assert "IMPORT JSON GRAPH" in html
    assert "SYNC CAD/BIM" in html
    assert "/api/speckle/status" in html
    assert "/api/cad-bim/import" in html
    assert "RAG_Content/CAD_BIM" in html
    assert "External Providers" in html
    assert "openrouterBaseUrl" in html
    assert "openrouterKey" in html
    assert "openaiBaseUrl" in html
    assert "openaiKey" in html
    assert "SAVE PROVIDERS" in html
    assert "openrouter_api_key_clear" in html
    assert "openai_api_key_clear" in html
    assert "Е.Ж.И.К. Mail" in html
    assert "trusted-сети" in html
    assert "IMPORT+INDEX" in html
    assert "mailCount" in html
    assert 'value="50"' in html
    assert "mailHost" in html
    assert "/api/mail/import-imap" in html
    assert "background: true" in html
    assert "max_messages: maxMessages" in html
    assert "parse_limit: parseLimit" in html
    assert "parse_batches: parseBatches" in html
    assert "/api/jobs/summary?limit=8" in html
    assert "/api/mail/import-apple-mail" in html
    assert 'const isLocalUi = location.port === "8051";' in html
    assert "Local Launchd" not in html
    assert ".innerHTML" not in html
    assert "start_guarded_reindex" not in html


def test_lite_admin_runtime_actions_allow_loopback_or_trusted_network():
    assert local_runtime_action_allowed(is_loopback=True)
    assert not local_runtime_action_allowed(is_loopback=False)
    assert local_runtime_action_allowed(is_loopback=False, is_trusted_network=True)


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
