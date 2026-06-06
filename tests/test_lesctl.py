from tools import lesctl


def test_lesctl_doctor_delegates_to_install(monkeypatch):
    calls = []
    monkeypatch.setattr(lesctl.install_les, "main", lambda argv: calls.append(argv) or 0)

    assert lesctl.main(["doctor", "--profile", "server-remote-model", "--json"]) == 0

    assert calls == [["--check", "--profile", "server-remote-model", "--json"]]


def test_lesctl_status_delegates_to_runtime(monkeypatch):
    calls = []
    monkeypatch.setattr(lesctl.les_runtime_control, "main", lambda argv: calls.append(argv) or 0)

    assert lesctl.main(["status"]) == 0

    assert calls == [["status"]]


def test_lesctl_start_builds_runtime_args(monkeypatch):
    calls = []
    monkeypatch.setattr(lesctl.les_runtime_control, "main", lambda argv: calls.append(argv) or 0)

    assert lesctl.main(["start", "--include-ui", "--no-indexer", "--memory-preflight"]) == 0

    assert calls == [["start-core", "--include-ui", "--no-indexer", "--memory-preflight"]]
