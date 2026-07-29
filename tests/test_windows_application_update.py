from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from tools import vps_patch_apply


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _prepared_job(
    tmp_path: Path,
    *,
    extra_archive_entry: bool = False,
) -> tuple[Path, Path, Path]:
    runtime = tmp_path / "app" / "runtime"
    state = tmp_path / "state"
    current = runtime / "proxy" / "example.py"
    current.parent.mkdir(parents=True)
    current.write_bytes(b"OLD = True\n")
    desktop = runtime.parent / "les-desktop.exe"
    desktop.write_bytes(b"old desktop")
    user_data = state / "data" / "user-owned.db"
    user_data.parent.mkdir(parents=True)
    user_data.write_bytes(b"never replace me")
    previous_stamp = {"deployed_commit": "a" * 40, "product_version": "0.25.17"}
    (runtime / ".les_deploy_stamp.json").write_text(
        json.dumps(previous_stamp), encoding="utf-8"
    )
    files = [
        {
            "path": "proxy/example.py",
            "base_sha256": _sha(b"OLD = True\n"),
            "accepted_sha256": [_sha(b"OLD = True\n")],
            "accepted_missing": False,
            "sha256": _sha(b"NEW = True\n"),
            "bytes": len(b"NEW = True\n"),
        },
        {
            "path": "sovushka/new-state.js",
            "base_sha256": None,
            "accepted_sha256": [],
            "accepted_missing": True,
            "sha256": _sha(b"export const READY = true;\n"),
            "bytes": len(b"export const READY = true;\n"),
        },
        {
            "scope": "app",
            "path": "les-desktop.exe",
            "base_sha256": _sha(b"old desktop"),
            "accepted_sha256": [_sha(b"old desktop")],
            "accepted_missing": False,
            "sha256": _sha(b"new desktop"),
            "bytes": len(b"new desktop"),
        },
    ]
    manifest = {
        "schema": "les.vps-patch.v2",
        "patch_id": "behavior-update",
        "base_commit": "a" * 40,
        "target_commit": "b" * 40,
        "product_version": "0.25.18",
        "build_number": 491,
        "desktop_version": "5.1.491",
        "files": files,
    }
    archive = tmp_path / "behavior-update.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest))
        bundle.writestr("payload/proxy/example.py", b"NEW = True\n")
        bundle.writestr("payload/sovushka/new-state.js", b"export const READY = true;\n")
        bundle.writestr("payload/@app/les-desktop.exe", b"new desktop")
        if extra_archive_entry:
            bundle.writestr("payload/undeclared.txt", b"surprise")
    job = tmp_path / "job.json"
    job.write_text(
        json.dumps(
            {
                "runtime_root": str(runtime),
                "state_root": str(state),
                "archive": str(archive),
                "archive_sha256": vps_patch_apply.sha(archive),
                "status_path": str(state / "artifacts" / "updates" / "status.json"),
                "patch_id": "behavior-update",
                "helper_task_name": "LES-Patch-behavior-update",
            }
        ),
        encoding="utf-8",
    )
    return runtime, state, job


def _patch_windows_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vps_patch_apply, "_stop_runtime", lambda _runtime, _state: None)
    monkeypatch.setattr(vps_patch_apply, "_stop_desktop", lambda: None)
    monkeypatch.setattr(
        vps_patch_apply, "start_desktop", lambda _runtime, patch_id: f"task-{patch_id}"
    )
    monkeypatch.setattr(vps_patch_apply, "remove_task", lambda _name: None)


def test_windows_updater_applies_atomically_without_build_or_test(tmp_path, monkeypatch):
    runtime, state, job = _prepared_job(tmp_path)
    _patch_windows_actions(monkeypatch)
    monkeypatch.setattr(
        vps_patch_apply,
        "_wait_ready",
        lambda _manifest, _state: {
            "contract": "direct_python_no_console_v1",
            "runtime_processes": ["pythonw.exe", "pythonw.exe"],
            "cmd_wrappers": 0,
        },
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("apply must not run build, pytest, make, or shell wrappers")
        ),
    )

    result = vps_patch_apply.apply_job(job)
    status = json.loads(
        (state / "artifacts" / "updates" / "status.json").read_text(encoding="utf-8")
    )

    assert result == 0
    assert (runtime / "proxy" / "example.py").read_bytes() == b"NEW = True\n"
    assert (runtime / "sovushka" / "new-state.js").read_bytes() == b"export const READY = true;\n"
    assert (runtime.parent / "les-desktop.exe").read_bytes() == b"new desktop"
    assert (state / "data" / "user-owned.db").read_bytes() == b"never replace me"
    assert status["state"] == "ready"
    assert status["target_commit"] == "b" * 40
    assert status["product_version"] == "0.25.18"
    assert status["build_number"] == 491
    assert status["process_hygiene"]["cmd_wrappers"] == 0
    backup = Path(status["backup_root"])
    assert (backup / "files" / "runtime" / "proxy" / "example.py").read_bytes() == b"OLD = True\n"
    assert (backup / "files" / "app" / "les-desktop.exe").read_bytes() == b"old desktop"


def test_windows_updater_rolls_back_all_files_when_smoke_fails(tmp_path, monkeypatch):
    runtime, state, job = _prepared_job(tmp_path)
    previous_stamp = (runtime / ".les_deploy_stamp.json").read_bytes()
    _patch_windows_actions(monkeypatch)
    monkeypatch.setattr(
        vps_patch_apply,
        "_wait_ready",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("identity smoke failed")),
    )

    class HealthyUi:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(vps_patch_apply.urllib.request, "urlopen", lambda *_a, **_k: HealthyUi())

    result = vps_patch_apply.apply_job(job)
    status = json.loads(
        (state / "artifacts" / "updates" / "status.json").read_text(encoding="utf-8")
    )

    assert result == 1
    assert (runtime / "proxy" / "example.py").read_bytes() == b"OLD = True\n"
    assert not (runtime / "sovushka" / "new-state.js").exists()
    assert (runtime.parent / "les-desktop.exe").read_bytes() == b"old desktop"
    assert (runtime / ".les_deploy_stamp.json").read_bytes() == previous_stamp
    assert (state / "data" / "user-owned.db").read_bytes() == b"never replace me"
    assert status["state"] == "failed"
    assert status["stage"] == "rolled_back"
    assert "identity smoke failed" in status["error"]


def test_windows_updater_retry_uses_a_new_recovery_point(tmp_path, monkeypatch):
    runtime, state, job = _prepared_job(tmp_path)
    _patch_windows_actions(monkeypatch)
    monkeypatch.setattr(
        vps_patch_apply,
        "_wait_ready",
        lambda *_args: {
            "contract": "direct_python_no_console_v1",
            "runtime_processes": ["pythonw.exe"],
            "cmd_wrappers": 0,
        },
    )

    assert vps_patch_apply.apply_job(job) == 0
    first = json.loads(
        (state / "artifacts" / "updates" / "status.json").read_text(encoding="utf-8")
    )["backup_root"]
    assert vps_patch_apply.apply_job(job) == 0
    second = json.loads(
        (state / "artifacts" / "updates" / "status.json").read_text(encoding="utf-8")
    )["backup_root"]

    assert first != second
    assert Path(first).is_dir()
    assert Path(second).is_dir()
    assert (runtime.parent / "les-desktop.exe").read_bytes() == b"new desktop"


def test_windows_updater_rejects_undeclared_archive_content_before_stop(tmp_path, monkeypatch):
    runtime, state, job = _prepared_job(tmp_path, extra_archive_entry=True)
    stopped = False

    def mark_stopped(_runtime, _state):
        nonlocal stopped
        stopped = True

    monkeypatch.setattr(vps_patch_apply, "_stop_runtime", mark_stopped)
    monkeypatch.setattr(vps_patch_apply, "start_desktop", lambda *_args: "rollback")
    monkeypatch.setattr(vps_patch_apply, "remove_task", lambda _name: None)
    monkeypatch.setattr(
        vps_patch_apply.urllib.request,
        "urlopen",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("not running")),
    )

    assert vps_patch_apply.apply_job(job) == 1
    assert stopped is False
    assert (runtime / "proxy" / "example.py").read_bytes() == b"OLD = True\n"
    assert (state / "data" / "user-owned.db").read_bytes() == b"never replace me"


def test_windows_updater_process_hygiene_is_behaviorally_enforced():
    runtime_state = {
        "process_contract": "direct_python_no_console_v1",
        "proxy_pid": 10,
        "ui_pid": 11,
        "lemonade_host_pid": None,
    }
    good = {
        "runtime_processes": [
            {"pid": 10, "name": "python.exe"},
            {"pid": 11, "name": "pythonw.exe"},
        ],
        "cmd_wrappers": 0,
    }
    assert vps_patch_apply.evaluate_process_hygiene(runtime_state, good)["cmd_wrappers"] == 0

    with pytest.raises(RuntimeError, match="cmd.exe"):
        vps_patch_apply.evaluate_process_hygiene(
            runtime_state, {**good, "cmd_wrappers": 1}
        )
    with pytest.raises(RuntimeError, match="unexpected launchers"):
        vps_patch_apply.evaluate_process_hygiene(
            runtime_state,
            {
                "runtime_processes": [
                    {"pid": 10, "name": "cmd.exe"},
                    {"pid": 11, "name": "pythonw.exe"},
                ],
                "cmd_wrappers": 0,
            },
        )
