from __future__ import annotations

from proxy.services import process_status


def test_windows_liveness_uses_windows_probe_not_os_kill(monkeypatch):
    calls: list[int] = []

    monkeypatch.setattr(process_status, "_windows_pid_running", lambda pid: calls.append(pid) or True)
    monkeypatch.setattr(
        process_status,
        "_posix_pid_running",
        lambda _pid: (_ for _ in ()).throw(AssertionError("POSIX os.kill probe used on Windows")),
    )

    assert process_status.pid_running(31415, platform="nt") is True
    assert calls == [31415]


def test_invalid_pid_is_never_probed(monkeypatch):
    monkeypatch.setattr(
        process_status,
        "_windows_pid_running",
        lambda _pid: (_ for _ in ()).throw(AssertionError("invalid PID was probed")),
    )

    assert process_status.pid_running(0, platform="nt") is False
    assert process_status.pid_running(-1, platform="nt") is False
