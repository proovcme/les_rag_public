"""W5.4/5.5 — мост `/lite-api/*` и рантайм-роуты `/lite-runtime/*` после
удаления HTML-шеллов lite_chat/lite_admin. HTML больше нет; логика моста,
доверия и локальных действий должна остаться неизменной (внешний контур,
M5, smoke 12/12, вьювер CAD/BIM)."""
from types import SimpleNamespace

import pytest

from sovushka import lite_bridge
from sovushka.lite_bridge import (
    bridge_proxy_request,
    bridge_request_allowed,
    local_runtime_action_allowed,
    lite_pick_folder,
    register_lite_bridge_routes,
)


# ── мост /lite-api/* (бывш. lite_chat) ───────────────────────────────

def test_bridge_allows_auth_verify_without_existing_key():
    assert bridge_request_allowed("auth/verify", has_key=False, is_loopback=False)
    assert bridge_request_allowed("auth/trust", has_key=False, is_loopback=False)


def test_bridge_requires_key_for_remote_chat_requests():
    assert not bridge_request_allowed("chat", has_key=False, is_loopback=False)
    assert bridge_request_allowed("chat", has_key=True, is_loopback=False)


def test_bridge_allows_loopback_without_key_for_local_trusted_runtime():
    assert bridge_request_allowed("indexing-mode", has_key=False, is_loopback=True)


def test_loopback_uses_resolved_forwarded_client(monkeypatch):
    monkeypatch.setattr(lite_bridge, "client_ip_from_request", lambda request: "203.0.113.10")
    request = SimpleNamespace(headers={"x-forwarded-for": "203.0.113.10"}, client=SimpleNamespace(host="127.0.0.1"))
    assert not lite_bridge._client_is_loopback(request)


def test_bridge_allows_configured_trusted_network_without_key():
    assert bridge_request_allowed(
        "settings",
        has_key=False,
        is_loopback=False,
        is_trusted_network=True,
    )


def test_bridge_forwards_trusted_network_assertion(monkeypatch):
    monkeypatch.setattr(lite_bridge, "TRUSTED_NETWORK_ROLE", "admin")
    monkeypatch.setattr(lite_bridge, "TRUSTED_PROXY_HEADER", "x-les-trusted-network")
    monkeypatch.setattr(lite_bridge, "trusted_role_for_request", lambda request: "admin")
    monkeypatch.setattr(lite_bridge, "client_ip_from_request", lambda request: "10.10.10.98")

    request = SimpleNamespace(headers={"x-api-key": "stale"}, client=SimpleNamespace(host="10.10.10.98"))
    headers = lite_bridge._forward_headers(request)

    assert headers["X-API-Key"] == "stale"
    assert headers["x-les-trusted-network"] == "admin"
    assert headers["X-Forwarded-For"] == "10.10.10.98"


@pytest.mark.asyncio
async def test_bridge_auth_trust_uses_frontdoor_diagnostics(monkeypatch):
    monkeypatch.setattr(lite_bridge, "trust_diagnostics", lambda request: {"trusted": False, "client_ip": "203.0.113.10"})
    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))

    response = await bridge_proxy_request("auth/trust", request)

    assert response.status_code == 200
    assert b'"trusted":false' in response.body.replace(b" ", b"")
    assert b"203.0.113.10" in response.body


# ── локальные рантайм-действия /lite-runtime/* (бывш. lite_admin) ─────

def test_runtime_actions_allow_loopback_or_trusted_network():
    assert local_runtime_action_allowed(is_loopback=True)
    assert not local_runtime_action_allowed(is_loopback=False)
    assert local_runtime_action_allowed(is_loopback=False, is_trusted_network=True)


def test_windows_folder_picker_forces_utf8_stdout(monkeypatch):
    calls = {}

    def fake_run(args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="C:\\Users\\Oleg\\Лесной", stderr="")

    monkeypatch.setattr(lite_bridge, "_is_windows_host", lambda: True)
    monkeypatch.setattr(lite_bridge, "_is_macos_host", lambda: False)
    monkeypatch.setattr(lite_bridge.subprocess, "run", fake_run)

    result = lite_bridge._native_pick_folder(initial="", title="Выберите папку")

    assert result == {"status": "selected", "path": "C:\\Users\\Oleg\\Лесной"}
    assert calls["kwargs"]["encoding"] == "utf-8"
    assert calls["kwargs"]["errors"] == "replace"
    script = calls["args"][-1]
    assert "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8" in script


def test_native_folder_picker_uses_windows_folder_dialog(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(lite_bridge, "_is_windows_host", lambda: True)
    monkeypatch.setattr(lite_bridge, "_is_macos_host", lambda: False)

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="C:\\Data\\Project", stderr="")

    monkeypatch.setattr(lite_bridge.subprocess, "run", fake_run)

    result = lite_bridge._native_pick_folder(initial=str(tmp_path), title="Pick")

    assert result == {"status": "selected", "path": "C:\\Data\\Project"}
    assert calls[0][0][:4] == ["powershell", "-NoProfile", "-STA", "-ExecutionPolicy"]
    assert calls[0][1]["creationflags"] == 0x08000000
    assert "FolderBrowserDialog" in calls[0][0][-1]


def test_native_folder_picker_uses_macos_finder(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(lite_bridge, "_is_windows_host", lambda: False)
    monkeypatch.setattr(lite_bridge, "_is_macos_host", lambda: True)

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=f"{tmp_path}\n", stderr="")

    monkeypatch.setattr(lite_bridge.subprocess, "run", fake_run)

    result = lite_bridge._native_pick_folder(initial=str(tmp_path), title="Pick")

    assert result == {"status": "selected", "path": str(tmp_path)}
    assert calls[0][0][:2] == ["osascript", "-e"]
    assert "choose folder" in calls[0][0][-1]


@pytest.mark.asyncio
async def test_folder_picker_requires_loopback(monkeypatch):
    monkeypatch.setattr(lite_bridge, "_client_is_loopback", lambda request: False)
    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="10.10.10.20"))

    response = await lite_pick_folder(request)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_folder_picker_returns_selected_path_on_loopback(monkeypatch):
    monkeypatch.setattr(lite_bridge, "_client_is_loopback", lambda request: True)
    monkeypatch.setattr(
        lite_bridge,
        "_native_pick_folder",
        lambda **_kwargs: {"status": "selected", "path": "C:\\Data\\Project"},
    )
    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))

    response = await lite_pick_folder(request, initial="C:\\Data", title="Pick")

    assert response.status_code == 200
    assert b"C:\\\\Data\\\\Project" in response.body


def test_pid_running_treats_zombie_as_stopped(monkeypatch):
    monkeypatch.setattr(lite_bridge.os, "kill", lambda pid, signal: None)
    monkeypatch.setattr(
        lite_bridge.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="Z\n"),
    )
    assert not lite_bridge._pid_running(123)


def test_guarded_reindex_status_reads_state(tmp_path, monkeypatch):
    monkeypatch.setattr(lite_bridge, "_repo_root", lambda: tmp_path)
    state_dir = tmp_path / "artifacts" / "reindex_runs"
    state_dir.mkdir(parents=True)
    (state_dir / "reindex_state_ntd_fire_index__ntd_hvac_index.json").write_text(
        '{"completed":{"a":{},"b":{}},"runs":[{}],"updated_at":"now"}',
        encoding="utf-8",
    )

    status = lite_bridge.guarded_reindex_status_payload()
    assert status["completed"] == 2
    assert status["remaining"] == 192
    assert status["running"] is False


def test_guarded_reindex_is_not_a_local_runtime_action():
    assert "start_guarded_reindex" not in lite_bridge.LOCAL_RUNTIME_ACTIONS


def test_cad_bim_ifc_sample_dir_falls_back_to_standalone(tmp_path):
    standalone = tmp_path / "standalone" / "cad_bim_viewer" / "ifc-sample"
    standalone.mkdir(parents=True)
    assert lite_bridge._cad_bim_ifc_sample_dir(tmp_path) == standalone


def test_cad_bim_ifc_sample_dir_prefers_root_sample_dir(tmp_path):
    root_sample = tmp_path / "ifc_sample"
    standalone = tmp_path / "standalone" / "cad_bim_viewer" / "ifc-sample"
    root_sample.mkdir()
    standalone.mkdir(parents=True)
    assert lite_bridge._cad_bim_ifc_sample_dir(tmp_path) == root_sample


# ── контур: критические маршруты переживают удаление шеллов ───────────

def test_register_wires_bridge_runtime_viewer_and_redirects():
    """После удаления шеллов мост/рантайм/вьювер/редиректы должны остаться
    на приложении (контракт внешнего smoke 12/12 и вьювера CAD/BIM)."""
    from nicegui import app

    register_lite_bridge_routes()
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/lite-api/{path:path}" in paths           # мост
    assert "/lite-runtime/status" in paths            # рантайм-статус
    assert "/lite-runtime/action/{action}" in paths   # рантайм-действия
    assert "/lite-runtime/pick-folder" in paths       # локальный Explorer/Finder picker
    assert "/les/cad-bim-viewer" in paths             # страница вьювера
    assert "/" in paths and "/les" in paths           # редиректы шеллов
    # статика вьювера смонтирована
    mounts = {getattr(r, "path", "") for r in app.routes}
    assert any(p.startswith("/les/cad-bim-viewer") for p in mounts)
