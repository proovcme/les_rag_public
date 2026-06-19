"""Offline tests for the LES desktop shell core (no GUI required)."""

from __future__ import annotations

import contextlib

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


def test_gui_unavailable_in_test_env():
    # pywebview is in the optional `desktop` extra and not installed for tests.
    assert les_shell.gui_available() is False


def test_main_no_gui_runs_headless(monkeypatch):
    monkeypatch.setattr(les_shell, "ensure_started", lambda: True)
    opened = []
    monkeypatch.setattr(les_shell.webbrowser, "open", lambda url: opened.append(url))
    assert les_shell.main(["--no-gui"]) == 0
    assert opened == [les_shell.UI_URL]


def test_open_logs_creates_dir_and_opens(monkeypatch, tmp_path):
    monkeypatch.setattr(les_shell, "_log_dir", lambda: tmp_path / "logs")
    ran = {}
    monkeypatch.setattr(les_shell.subprocess, "run", lambda cmd, check=False: ran.update(cmd=cmd))
    les_shell.open_logs()
    assert (tmp_path / "logs").is_dir()
    assert str(tmp_path / "logs") in ran["cmd"]
