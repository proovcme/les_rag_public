from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from tools import vps_patch_apply, windows_runtime, windows_update_engine

ROOT = Path(__file__).resolve().parents[1]


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
    monkeypatch.setattr(vps_patch_apply, "_start_runtime", lambda _runtime, _state: None)
    monkeypatch.setattr(vps_patch_apply, "_verify_smeta_baseline", lambda _runtime, _state: None)
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


def test_soft_updater_rejects_failed_baseline_preflight_before_runtime_mutation(
    tmp_path, monkeypatch
):
    runtime, state, job = _prepared_job(tmp_path)
    stopped = []
    monkeypatch.setattr(
        vps_patch_apply,
        "_verify_smeta_baseline",
        lambda *_args: (_ for _ in ()).throw(PermissionError("baseline ACL")),
    )
    monkeypatch.setattr(
        vps_patch_apply, "_stop_runtime", lambda *_args: stopped.append(True)
    )
    monkeypatch.setattr(vps_patch_apply, "remove_task", lambda _name: None)

    assert vps_patch_apply.apply_job(job) == 1

    status = json.loads(
        (state / "artifacts" / "updates" / "status.json").read_text(encoding="utf-8")
    )
    assert stopped == []
    assert status["stage"] == "rejected"
    assert (runtime / "proxy" / "example.py").read_bytes() == b"OLD = True\n"
    assert (runtime.parent / "les-desktop.exe").read_bytes() == b"old desktop"


def test_soft_updater_verifies_bundled_smeta_baseline_with_persistent_python(
    tmp_path, monkeypatch
):
    runtime = tmp_path / "runtime"
    state = tmp_path / "state"
    python = state / ".venv/Scripts/python.exe"
    tool = runtime / "tools/smeta_release_baseline.py"
    archive = runtime / "installers/windows/baseline/LES-smeta-baseline.zip"
    for path in (python, tool, archive):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    captured = {}

    def run_bounded(arguments, **kwargs):
        captured["arguments"] = arguments
        captured["kwargs"] = kwargs
        return 0

    monkeypatch.setattr(windows_update_engine, "run_bounded", run_bounded)

    vps_patch_apply._verify_smeta_baseline(runtime, state)

    assert captured["arguments"] == [
        str(python),
        str(tool),
        "repair",
        "--archive",
        str(archive),
        "--state-root",
        str(state),
    ]
    assert captured["kwargs"]["timeout"] == 300
    assert captured["kwargs"]["environment"]["LES_WINDOWS_STATE_ROOT"] == str(state)


def test_soft_updater_preflights_with_staged_baseline_tool(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    staged_runtime = tmp_path / "stage/runtime"
    state = tmp_path / "state"
    python = state / ".venv/Scripts/python.exe"
    installed_tool = runtime / "tools/smeta_release_baseline.py"
    staged_tool = staged_runtime / "tools/smeta_release_baseline.py"
    archive = runtime / "installers/windows/baseline/LES-smeta-baseline.zip"
    for path in (python, installed_tool, staged_tool, archive):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    captured = {}
    monkeypatch.setattr(
        windows_update_engine,
        "run_bounded",
        lambda arguments, **_kwargs: captured.setdefault("arguments", arguments) and 0,
    )

    vps_patch_apply._verify_smeta_baseline(
        runtime, state, staged_runtime=staged_runtime
    )

    assert captured["arguments"][1] == str(staged_tool)


def test_windows_updater_accepts_powershell_utf8_bom_job(tmp_path, monkeypatch):
    runtime, state, job = _prepared_job(tmp_path)
    job.write_text(job.read_text(encoding="utf-8"), encoding="utf-8-sig")
    _patch_windows_actions(monkeypatch)
    monkeypatch.setattr(
        vps_patch_apply,
        "_wait_ready",
        lambda *_args: {
            "contract": "direct_python_no_console_v2",
            "runtime_processes": ["pythonw.exe", "pythonw.exe"],
            "cmd_wrappers": 0,
        },
    )

    assert vps_patch_apply.apply_job(job) == 0
    assert (runtime / "proxy" / "example.py").read_bytes() == b"NEW = True\n"


def test_windows_updater_rolls_back_runtime_when_desktop_replace_is_locked(
    tmp_path, monkeypatch
):
    runtime, state, job = _prepared_job(tmp_path)
    _patch_windows_actions(monkeypatch)
    original_replace = vps_patch_apply._replace_with_retry

    def fail_desktop_update(source, target, **kwargs):
        if (
            target.name == "les-desktop.exe"
            and source.name.endswith(".les-update.tmp")
        ):
            raise PermissionError("desktop image is still locked")
        return original_replace(source, target, **kwargs)

    class HealthyUi:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(vps_patch_apply, "_replace_with_retry", fail_desktop_update)
    monkeypatch.setattr(
        vps_patch_apply.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: HealthyUi(),
    )

    assert vps_patch_apply.apply_job(job) == 1
    assert (runtime / "proxy" / "example.py").read_bytes() == b"OLD = True\n"
    assert not (runtime / "sovushka" / "new-state.js").exists()
    assert (runtime.parent / "les-desktop.exe").read_bytes() == b"old desktop"


def test_windows_atomic_replace_retries_transient_permission_error(
    tmp_path, monkeypatch
):
    source = tmp_path / "new.tmp"
    target = tmp_path / "app.exe"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    actual_replace = vps_patch_apply.os.replace
    attempts = 0

    def flaky_replace(left, right):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("image lock")
        actual_replace(left, right)

    monkeypatch.setattr(vps_patch_apply.os, "replace", flaky_replace)
    monkeypatch.setattr(vps_patch_apply.time, "sleep", lambda _seconds: None)

    vps_patch_apply._replace_with_retry(source, target, timeout=1)

    assert attempts == 3
    assert target.read_bytes() == b"new"


def test_status_publish_retries_concurrent_windows_reader(tmp_path, monkeypatch):
    status = tmp_path / "status.json"
    actual_replace = vps_patch_apply.os.replace
    attempts = 0

    def reader_lock(left, right):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("status reader still holds destination")
        actual_replace(left, right)

    monkeypatch.setattr(vps_patch_apply.os, "replace", reader_lock)
    monkeypatch.setattr(vps_patch_apply.time, "sleep", lambda _seconds: None)

    vps_patch_apply.write_status(
        status,
        state="applying",
        stage="smoke",
        message="Проверяю",
    )

    payload = json.loads(status.read_text(encoding="utf-8"))
    assert payload["stage"] == "smoke"
    assert attempts == 3


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


def test_windows_updater_retry_reuses_original_recovery_point(tmp_path, monkeypatch):
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

    assert first == second
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


def _hard_job(tmp_path: Path) -> tuple[Path, Path, Path]:
    install = tmp_path / "Programs" / "LES"
    state = tmp_path / "UserState" / "LES"
    runtime = install / "runtime"
    (runtime / "config").mkdir(parents=True)
    (runtime / "config" / "version.json").write_text(
        json.dumps(
            {
                "product_version": "0.25.19",
                "build_number": 492,
                "desktop_version": "5.1.492",
            }
        ),
        encoding="utf-8",
    )
    (runtime / "old-code.txt").write_text("old", encoding="utf-8")
    (install / "les-desktop.exe").write_bytes(b"old desktop")
    (state / "data").mkdir(parents=True)
    (state / "data" / "user.db").write_bytes(b"user-owned")
    installer = state / "artifacts" / "LES-Setup.exe"
    installer.parent.mkdir(parents=True)
    installer.write_bytes(b"verified installer")
    status = state / "artifacts" / "updates" / "hard-status.json"
    job = state / "artifacts" / "hard-job.json"
    job.write_text(
        json.dumps(
            {
                "schema": "les.windows-hard-update.v1",
                "update_id": "hard-contract",
                "installer": str(installer),
                "installer_sha256": windows_update_engine.sha256_file(installer),
                "install_root": str(install),
                "state_root": str(state),
                "status_path": str(status),
                "product_version": "0.25.20",
                "build_number": 493,
                "desktop_version": "5.1.493",
                "target_commit": "b" * 40,
                "branch": "codex/sovushka-ui-kit",
            }
        ),
        encoding="utf-8",
    )
    return install, state, job


def _mock_hard_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    *,
    smoke_error: str | None = None,
) -> None:
    monkeypatch.setattr(windows_update_engine, "probe_environment", lambda *_args: None)
    monkeypatch.setattr(windows_update_engine, "stop_runtime", lambda *_args: None)
    monkeypatch.setattr(windows_update_engine, "stop_desktop", lambda: None)
    monkeypatch.setattr(windows_update_engine, "initialize_state", lambda *_args: None)
    monkeypatch.setattr(windows_update_engine, "start_runtime", lambda *_args: None)
    monkeypatch.setattr(
        windows_update_engine,
        "start_desktop",
        lambda *_args: "LES-Update-Start-hard-contract",
    )
    monkeypatch.setattr(windows_update_engine, "remove_task", lambda *_args: None)

    def fake_run(arguments, *, cwd, **_kwargs):
        if str(arguments[0]).endswith("LES-Setup.exe"):
            install = Path(str(arguments[-1]).removeprefix("/D="))
            runtime = install / "runtime"
            (runtime / "config").mkdir(parents=True)
            (runtime / "config" / "version.json").write_text(
                json.dumps(
                    {
                        "product_version": "0.25.20",
                        "build_number": 493,
                        "desktop_version": "5.1.493",
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "new-code.txt").write_text("new", encoding="utf-8")
            (install / "les-desktop.exe").write_bytes(b"new desktop")
        return 0

    monkeypatch.setattr(windows_update_engine, "run_bounded", fake_run)
    if smoke_error:
        monkeypatch.setattr(
            windows_update_engine,
            "wait_ready",
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError(smoke_error)),
        )
    else:
        monkeypatch.setattr(
            windows_update_engine,
            "wait_ready",
            lambda **_kwargs: {"index_contract_compatible": True},
        )


def test_hard_update_replaces_complete_application_tree_and_keeps_state(tmp_path, monkeypatch):
    install, state, job = _hard_job(tmp_path)
    _mock_hard_lifecycle(monkeypatch)

    assert windows_update_engine.apply_hard_job(job) == 0

    status = json.loads(
        (state / "artifacts" / "updates" / "hard-status.json").read_text(
            encoding="utf-8"
        )
    )
    assert not (install / "runtime" / "old-code.txt").exists()
    assert (install / "runtime" / "new-code.txt").read_text(encoding="utf-8") == "new"
    assert (state / "data" / "user.db").read_bytes() == b"user-owned"
    recovery = Path(status["recovery_root"])
    assert (recovery / "runtime" / "old-code.txt").read_text(encoding="utf-8") == "old"
    assert status["application_tree_replaced"] is True
    assert status["user_data_untouched"] is True


def test_hard_update_restores_whole_previous_tree_when_smoke_fails(tmp_path, monkeypatch):
    install, state, job = _hard_job(tmp_path)
    _mock_hard_lifecycle(monkeypatch, smoke_error="identity smoke failed")

    assert windows_update_engine.apply_hard_job(job) == 1

    status = json.loads(
        (state / "artifacts" / "updates" / "hard-status.json").read_text(
            encoding="utf-8"
        )
    )
    assert (install / "runtime" / "old-code.txt").read_text(encoding="utf-8") == "old"
    assert not (install / "runtime" / "new-code.txt").exists()
    assert (state / "data" / "user.db").read_bytes() == b"user-owned"
    assert status["stage"] == "rolled_back"
    assert "identity smoke failed" in status["error"]


def test_hard_update_rejects_install_root_containing_user_state(tmp_path):
    install = tmp_path / "Programs" / "LES"
    state = install / "data" / "LES"
    with pytest.raises(RuntimeError, match="disjoint"):
        windows_update_engine.validate_boundary(install, state)


def test_windows_update_orchestration_is_python_owned_and_file_backed():
    source = (ROOT / "tools" / "windows_update_engine.py").read_text(encoding="utf-8")
    runtime_source = (ROOT / "tools" / "windows_runtime.py").read_text(encoding="utf-8")
    assert "application tree replaced" in source
    assert "stdout_path.open" in source
    assert "stderr_path.open" in source
    assert "capture_output=True" not in source
    assert "Get-CimInstance" not in source
    assert "Get-NetTCPConnection" not in source
    assert "uv sync" not in source
    assert "powershell.exe" not in runtime_source
    assert "subprocess.Popen" in runtime_source
    assert "PROCESS_CONTRACT = \"direct_python_no_console_v2\"" in runtime_source
    assert "tools/windows_env_doctor.py" in vps_patch_apply.ALLOWED_FILES
    assert "tools/les_runtime_control.py" in vps_patch_apply.ALLOWED_FILES


def test_windows_runtime_environment_keeps_ollama_embedding_contract(tmp_path):
    runtime = tmp_path / "runtime"
    state = tmp_path / "LES"
    state.mkdir()
    (state / ".env").write_text(
        "LES_LLM_PROVIDER=ollama\nOLLAMA_MODEL=qwen3.5:9b\n", encoding="utf-8"
    )

    environment = windows_runtime.runtime_environment(runtime, state)

    assert environment["LES_LLM_PROVIDER"] == "ollama"
    assert environment["OLLAMA_MODEL"] == "qwen3.5:9b"
    assert environment["MLX_URL"] == "http://127.0.0.1:11434"
    assert environment["EMBED_MODEL"] == "bge-m3:latest"
    assert environment["RERANKER_BACKEND"] == "sentence_transformers"
    assert environment["RAG_CHAT_RERANK_CANDIDATE_K"] == "16"
    assert environment["RERANK_MAX_TEXT_CHARS"] == "1200"


def test_windows_runtime_rejects_oversized_env_before_reading_it(tmp_path):
    runtime = tmp_path / "runtime"
    state = tmp_path / "LES"
    state.mkdir()
    env = state / ".env"
    with env.open("wb") as stream:
        stream.seek(windows_runtime.MAX_ENV_BYTES)
        stream.write(b"x")

    with pytest.raises(RuntimeError, match="LES_ENV_OVERSIZED"):
        windows_runtime.runtime_environment(runtime, state)


def test_windows_runtime_reports_early_proxy_exit_with_redacted_stderr(
    tmp_path, monkeypatch
):
    stderr = tmp_path / "proxy.err.log"
    stderr.write_text(
        "RuntimeError: contract mismatch token=super-secret", encoding="utf-8"
    )

    class Exited:
        def poll(self):
            return 7

    monkeypatch.setattr(windows_runtime.time, "sleep", lambda _seconds: None)
    with pytest.raises(RuntimeError, match="code=7") as caught:
        windows_runtime._wait_process_url(
            Exited(),
            "http://127.0.0.1:8050/api/version",
            1,
            label="proxy",
            stderr_path=stderr,
        )
    assert "contract mismatch" in str(caught.value)
    assert "super-secret" not in str(caught.value)
    assert "<redacted>" in str(caught.value)


def test_windows_update_ready_snapshot_checks_live_direct_pids(
    tmp_path, monkeypatch
):
    state = tmp_path / "LES"
    logs = state / "logs"
    logs.mkdir(parents=True)
    (logs / "windows-light-state.json").write_text(
        json.dumps(
            {
                "process_contract": "direct_python_no_console_v2",
                "proxy_pid": 101,
                "ui_pid": 202,
            }
        ),
        encoding="utf-8",
    )
    responses = {
        "http://127.0.0.1:8050/api/version": {
            "product_version": "0.25.22",
            "build_number": 495,
            "deployed_commit": "c" * 40,
        },
        "http://127.0.0.1:8050/api/health": {
            "rag": {
                "index_contract": {"compatible": True, "status": "compatible"},
                "qdrant": {"ok": True},
            }
        },
        "http://127.0.0.1:8050/api/lsr/gesn/10-01-001-01/expand?qty=1": {
            "code": "10-01-001-01",
            "qty": 1,
            "resources": [{"code": "1-100-01", "quantity": 1.0}],
        },
    }

    class HealthyUi:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        windows_update_engine,
        "_json_url",
        lambda url, timeout=5: responses[url],
    )
    monkeypatch.setattr(
        windows_update_engine,
        "_post_json_url",
        lambda url, payload, timeout=60: {
            "ranked": [{"rank": 1, "metadata": {"probe": "relevant"}}]
        },
    )
    monkeypatch.setattr(
        windows_update_engine.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: HealthyUi(),
    )
    monkeypatch.setattr(
        windows_update_engine,
        "_pid_running",
        lambda pid: pid in {101, 202},
    )

    snapshot, failure = windows_update_engine._ready_snapshot(
        expected_commit="c" * 40,
        expected_version="0.25.22",
        expected_build=495,
        state=state,
        health_timeout=15,
    )

    assert failure == ""
    assert snapshot is not None
    assert snapshot["process_contract"] == "direct_python_no_console_v2"
    assert snapshot["proxy_pid"] == 101
    assert snapshot["ui_pid"] == 202
    assert snapshot["smeta_baseline_ready"] is True
    assert snapshot["reranker_ready"] is True


def test_windows_update_ready_snapshot_rejects_unreadable_smeta_baseline(
    tmp_path, monkeypatch
):
    state = tmp_path / "LES"
    logs = state / "logs"
    logs.mkdir(parents=True)
    (logs / "windows-light-state.json").write_text(
        json.dumps(
            {
                "process_contract": "direct_python_no_console_v2",
                "proxy_pid": 101,
                "ui_pid": 202,
            }
        ),
        encoding="utf-8",
    )

    def json_probe(url, timeout=5):
        if url.endswith("/api/version"):
            return {
                "product_version": "0.27.9",
                "build_number": 526,
                "deployed_commit": "d" * 40,
            }
        if url.endswith("/api/health"):
            return {
                "rag": {
                    "index_contract": {"compatible": True},
                    "qdrant": {"ok": True},
                }
            }
        raise OSError("unable to open normative database")

    class HealthyUi:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(windows_update_engine, "_json_url", json_probe)
    monkeypatch.setattr(
        windows_update_engine.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: HealthyUi(),
    )
    monkeypatch.setattr(windows_update_engine, "_pid_running", lambda pid: True)

    snapshot, failure = windows_update_engine._ready_snapshot(
        expected_commit="d" * 40,
        expected_version="0.27.9",
        expected_build=526,
        state=state,
        health_timeout=15,
    )

    assert snapshot is None
    assert failure.startswith("smeta_baseline=OSError:")
