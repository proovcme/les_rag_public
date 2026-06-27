from tools import lesctl


def test_lesctl_doctor_runs_health_report(monkeypatch):
    # W7.2: `doctor` по умолчанию запускает health-отчёт (les_doctor), НЕ install_les.
    doctor_calls = []
    install_calls = []
    monkeypatch.setattr(lesctl.les_doctor, "main", lambda argv: doctor_calls.append(argv) or 0)
    monkeypatch.setattr(lesctl.install_les, "main", lambda argv: install_calls.append(argv) or 0)

    assert lesctl.main(["doctor", "--json"]) == 0

    assert doctor_calls == [["--json"]]
    assert install_calls == []  # без --profile-check в install не делегирует


def test_lesctl_doctor_profile_check_delegates_to_install(monkeypatch):
    # Старая платформенная проверка профиля доступна как `doctor --profile-check`.
    calls = []
    monkeypatch.setattr(lesctl.install_les, "main", lambda argv: calls.append(argv) or 0)

    assert lesctl.main(
        ["doctor", "--profile-check", "--profile", "server-remote-model", "--json"]
    ) == 0

    assert calls == [["--check", "--profile", "server-remote-model", "--json"]]


def test_lesctl_init_creates_dirs_and_env(monkeypatch):
    calls = []
    monkeypatch.setattr(lesctl.install_les, "main", lambda argv: calls.append(argv) or 0)

    assert lesctl.main(["init", "--profile", "server-remote-model", "--json"]) == 0

    assert calls == [["--check", "--create-dirs", "--init-env", "--profile", "server-remote-model", "--json"]]


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


def test_lesctl_docker_profile_uses_compose(monkeypatch):
    calls = []
    monkeypatch.setattr(lesctl, "_run", lambda argv: calls.append(argv) or 0)

    assert lesctl.main(["start", "--profile", "linux-docker"]) == 0

    assert calls
    command = calls[0]
    assert command[:3] == ["docker", "compose", "-f"]
    assert "installers/linux/docker-compose.yml" in command[3]
    assert command[-5:] == ["up", "-d", "qdrant", "proxy", "ui"]


def test_lesctl_systemd_profile_uses_user_units(monkeypatch):
    calls = []
    monkeypatch.setattr(lesctl, "_run", lambda argv: calls.append(argv) or 0)

    assert lesctl.main(["restart", "--profile", "linux-systemd"]) == 0

    assert calls == [["systemctl", "--user", "restart", "les-proxy", "les-ui"]]
