"""Offline tests for the LES desktop shell core (no GUI required)."""

from __future__ import annotations

import contextlib
import json
import sys

from tools import les_shell


class _Resp:
    def __init__(self, status):
        self.status = status


@contextlib.contextmanager
def _ok(*_a, **_k):
    yield _Resp(200)


def test_healthy_true_and_false(monkeypatch):
    monkeypatch.setattr(les_shell.urllib.request, "urlopen", _ok)
    assert les_shell.healthy() is True

    def _boom(*_a, **_k):
        raise OSError("refused")

    monkeypatch.setattr(les_shell.urllib.request, "urlopen", _boom)
    assert les_shell.healthy() is False


def test_wait_healthy_gives_up(monkeypatch):
    monkeypatch.setattr(les_shell, "healthy", lambda *a, **k: False)
    sleeps = []
    monkeypatch.setattr(les_shell.time, "sleep", lambda s: sleeps.append(s))
    assert les_shell.wait_healthy(attempts=3, delay=0) is False
    assert len(sleeps) == 3


def test_ensure_started_skips_start_when_already_healthy(monkeypatch):
    monkeypatch.setattr(les_shell, "healthy", lambda *a, **k: True)
    started = []
    monkeypatch.setattr(les_shell, "start_stack", lambda: started.append(True))
    assert les_shell.ensure_started() is True
    assert started == []  # already up → no start


def test_ensure_started_starts_then_waits(monkeypatch):
    monkeypatch.setattr(les_shell, "healthy", lambda *a, **k: False)
    calls = {"start": 0, "wait": 0}

    def _start():
        calls["start"] += 1
        return True

    monkeypatch.setattr(les_shell, "start_stack", _start)
    monkeypatch.setattr(les_shell, "wait_healthy", lambda *a, **k: (calls.__setitem__("wait", 1) or True))
    assert les_shell.ensure_started() is True
    assert calls == {"start": 1, "wait": 1}


def test_start_stack_uses_runtime_control(monkeypatch):
    from tools import les_runtime_control as rc

    class _R:
        ok = True

    monkeypatch.setattr(rc, "start_core", lambda include_ui=False: [_R(), _R()])
    assert les_shell.start_stack() is True

    class _Bad:
        ok = False

    monkeypatch.setattr(rc, "start_core", lambda include_ui=False: [_Bad()])
    assert les_shell.start_stack() is False


def test_gui_unavailable_when_optional_dependency_is_missing(monkeypatch):
    # The full production environment may legitimately install the desktop
    # extra. Exercise the missing optional dependency explicitly instead of
    # assuming facts about whichever interpreter runs the suite.
    monkeypatch.setitem(sys.modules, "webview", None)
    assert les_shell.gui_available() is False


def test_main_no_gui_runs_headless(monkeypatch):
    monkeypatch.setattr(les_shell, "_runtime_ui_url", les_shell.UI_URL)
    monkeypatch.setattr(les_shell, "ensure_started", lambda: True)
    opened = []
    monkeypatch.setattr(les_shell.webbrowser, "open", lambda url: opened.append(url))
    assert les_shell.main(["--no-gui"]) == 0
    assert opened == [les_shell.current_ui_url()]


def test_start_stack_windows_uses_start_light(monkeypatch):
    monkeypatch.setattr(les_shell, "_platform", lambda: "windows")
    captured = {}

    class _R:
        returncode = 0

    def fake_run(cmd, check=False, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _R()

    monkeypatch.setattr(les_shell.subprocess, "run", fake_run)
    assert les_shell.start_stack() is True
    assert any("start-light.ps1" in str(part) for part in captured["cmd"])
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["text"] is True


def test_windows_runtime_state_updates_shell_urls(monkeypatch, tmp_path):
    state = tmp_path / "windows-light-state.json"
    state.write_text(
        json.dumps(
            {
                "ui_url": "http://127.0.0.1:8053/les",
                "ui_health_url": "http://127.0.0.1:8053/healthz",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(les_shell, "_windows_state_path", lambda: state)
    monkeypatch.setattr(les_shell, "_runtime_ui_url", les_shell.UI_URL)
    monkeypatch.setattr(les_shell, "_runtime_health_url", les_shell.HEALTH_URL)

    les_shell._load_windows_runtime_state()

    assert les_shell.current_ui_url() == "http://127.0.0.1:8053/les"
    assert les_shell.current_health_url() == "http://127.0.0.1:8053/healthz"


def test_stop_stack_windows_uses_stop_light(monkeypatch):
    monkeypatch.setattr(les_shell, "_platform", lambda: "windows")
    captured = {}
    monkeypatch.setattr(les_shell.subprocess, "run", lambda cmd, check=False: captured.update(cmd=cmd))
    les_shell.stop_stack()
    assert any("stop-light.ps1" in str(part) for part in captured["cmd"])


def test_start_stack_darwin_uses_runtime_control(monkeypatch):
    monkeypatch.setattr(les_shell, "_platform", lambda: "darwin")
    from tools import les_runtime_control as rc

    class _Ok:
        ok = True

    monkeypatch.setattr(rc, "start_core", lambda include_ui=False: [_Ok()])
    assert les_shell.start_stack() is True


def test_open_logs_creates_dir_and_opens(monkeypatch, tmp_path):
    monkeypatch.setattr(les_shell, "_log_dir", lambda: tmp_path / "logs")
    ran = {}
    monkeypatch.setattr(les_shell.subprocess, "run", lambda cmd, check=False: ran.update(cmd=cmd))
    les_shell.open_logs()
    assert (tmp_path / "logs").is_dir()
    assert str(tmp_path / "logs") in ran["cmd"]
