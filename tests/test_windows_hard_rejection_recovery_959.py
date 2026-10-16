"""A rejected hard update must not strand the previous, already-stopped application."""
import hashlib
import json
from pathlib import Path

import pytest

from tools import windows_update_engine as engine

OLD_COMMIT = "9ae36a57714c6c9ba6d1b4cfbd68159d055200cc"


def fixture_job(tmp_path):
    install, state = tmp_path / "Programs/LES", tmp_path / "UserState/LES"
    runtime = install / "runtime"
    (runtime / "config").mkdir(parents=True)
    version = {"product_version": "0.31.229", "build_number": 957, "desktop_version": "5.1.957"}
    (runtime / "config/version.json").write_text(json.dumps(version))
    (runtime / ".les_deploy_stamp.json").write_text(json.dumps({**version, "deployed_commit": OLD_COMMIT}))
    (runtime / "old_code.txt").write_bytes(b"unchanged old runtime")
    (install / "les-desktop.exe").write_bytes(b"old native813")
    (state / "data").mkdir(parents=True)
    (state / "data/user-owned.db").write_bytes(b"fixture-only opaque state")
    installer = tmp_path / "exact-setup.exe"
    installer.write_bytes(b"must not be executed")
    status = tmp_path / "hard-status.json"
    job = tmp_path / "hard-job.json"
    job.write_text(json.dumps({"schema": engine.HARD_JOB_SCHEMA, "update_id": "rejected-native-recovery",
        "install_root": str(install), "state_root": str(state), "installer": str(installer),
        "installer_sha256": hashlib.sha256(installer.read_bytes()).hexdigest(), "status_path": str(status),
        "target_commit": "b" * 40, "product_version": "0.31.230", "build_number": 958, "desktop_version": "5.1.958"}))
    return install, state, runtime, job, status


def mocked_lifecycle(monkeypatch, install, events, *, restart_fails=False):
    monkeypatch.setattr(engine, "probe_environment", lambda *_args: None)
    monkeypatch.setattr(engine, "stop_runtime", lambda *_args: events.append("stop_runtime"))
    monkeypatch.setattr(engine, "stop_desktop", lambda: events.append("stop_desktop"))
    monkeypatch.setattr(engine, "application_tree_lock_owners", lambda _install: [
        {"pid": 10768, "name": "cmd.exe", "cwd": str(install), "exe": "C:/Windows/System32/cmd.exe"}])
    monkeypatch.setattr(engine, "run_bounded", lambda *_args, **_kwargs: pytest.fail("Rejected installer must not run"))
    monkeypatch.setattr(engine, "start_runtime", lambda *_args: pytest.fail("Previous native must retain its own bootstrap launch"))

    def start_native(*_args):
        events.append("native_restart")
        if restart_fails:
            raise RuntimeError("native restart failed")
        assert _args[0] == install
        return "rejected-old-native-task"

    def ready(**kwargs):
        events.append("ready")
        assert kwargs["expected_commit"] == OLD_COMMIT
        assert kwargs["expected_version"] == "0.31.229"
        assert kwargs["expected_build"] == 957
        return {"previous_runtime_ready": True}

    monkeypatch.setattr(engine, "start_desktop", start_native)
    monkeypatch.setattr(engine, "wait_ready", ready)
    monkeypatch.setattr(engine, "remove_task", lambda *_args: events.append("remove_task"))


def test_foreign_cwd_rejection_restarts_previous_native_without_touching_application_or_data(tmp_path, monkeypatch):
    install, state, runtime, job, status = fixture_job(tmp_path)
    events = []
    mocked_lifecycle(monkeypatch, install, events)
    assert engine.apply_hard_job(job) == 1
    assert events == ["stop_runtime", "stop_desktop", "native_restart", "ready", "remove_task"]
    assert (runtime / "old_code.txt").read_bytes() == b"unchanged old runtime"
    assert (install / "les-desktop.exe").read_bytes() == b"old native813"
    assert (state / "data/user-owned.db").read_bytes() == b"fixture-only opaque state"
    assert not list(install.parent.glob("LES.recovery-*"))
    result = json.loads(status.read_text())
    assert result["state"] == "failed" and "APPLICATION_TREE_LOCKED" in result["error"]
    assert result["stage"] == "rejected_previous_restarted"
    assert result["previous_application_restarted"] is True
    assert result["previous_application_recovery"] == {"previous_runtime_ready": True}


def test_original_lock_error_survives_previous_native_recovery_failure(tmp_path, monkeypatch):
    install, state, runtime, job, status = fixture_job(tmp_path)
    events = []
    mocked_lifecycle(monkeypatch, install, events, restart_fails=True)
    assert engine.apply_hard_job(job) == 1
    result = json.loads(status.read_text())
    assert "APPLICATION_TREE_LOCKED" in result["error"]
    assert "native restart failed" in result["previous_application_recovery_error"]
    assert result["stage"] == "rejected_previous_restart_failed"
    assert result["previous_application_restarted"] is False
    assert (state / "data/user-owned.db").read_bytes() == b"fixture-only opaque state"


def test_pre_stop_checksum_rejection_does_not_start_or_stop_previous_application(tmp_path, monkeypatch):
    install, state, runtime, job, status = fixture_job(tmp_path)
    events = []
    mocked_lifecycle(monkeypatch, install, events)
    payload = json.loads(job.read_text())
    payload["installer_sha256"] = "0" * 64
    job.write_text(json.dumps(payload))
    assert engine.apply_hard_job(job) == 1
    assert events == []
    assert json.loads(status.read_text())["stage"] == "rejected"


@pytest.mark.parametrize("identity_change", ["native", "stamp", "version", "missing_stamp"])
def test_previous_identity_must_still_match_before_restarting(tmp_path, monkeypatch, identity_change):
    install, state, runtime, job, status = fixture_job(tmp_path)
    events = []
    mocked_lifecycle(monkeypatch, install, events)
    owners = engine.application_tree_lock_owners

    def change_previous_identity(path):
        if identity_change == "native":
            (install / "les-desktop.exe").write_bytes(b"foreign changed native")
        elif identity_change == "stamp":
            stamp = json.loads((runtime / ".les_deploy_stamp.json").read_text())
            stamp["deployed_commit"] = "c" * 40
            (runtime / ".les_deploy_stamp.json").write_text(json.dumps(stamp))
        elif identity_change == "version":
            (runtime / "config/version.json").write_text(json.dumps({"product_version": "0.31.999", "build_number": 999}))
        return owners(path)

    if identity_change == "missing_stamp":
        (runtime / ".les_deploy_stamp.json").unlink()
    monkeypatch.setattr(engine, "application_tree_lock_owners", change_previous_identity)
    assert engine.apply_hard_job(job) == 1
    assert "native_restart" not in events
    result = json.loads(status.read_text())
    assert "APPLICATION_TREE_LOCKED" in result["error"]
    assert "PREVIOUS_APPLICATION_IDENTITY_UNPROVEN" in result["previous_application_recovery_error"]
    assert result["previous_application_restarted"] is False
