#!/usr/bin/env python3
"""Detached transactional helper for a bounded LES Windows application update."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import py_compile
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import windows_update_engine
except ImportError:  # project import during tests and direct repo execution
    from tools import windows_update_engine


SCHEMA = "les.vps-patch.v2"
ALLOWED_ROOTS = ("backend/", "proxy/", "sovushka/", "config/prompts/", "skills/", "docs/")
ALLOWED_FILES = {
    "sovushka_ng.py",
    "proxy_server.py",
    "tools/vps_patch_apply.py",
    "tools/smeta_release_baseline.py",
    "tools/smeta_model_quality_benchmark.py",
    "tools/windows_update_engine.py",
    "tools/windows_runtime.py",
    "tools/windows_env_doctor.py",
    "tools/les_runtime_control.py",
    "config/version.json",
    "installers/windows/start-light.ps1",
    "installers/windows/stop-light.ps1",
    "installers/windows/runtime-process.ps1",
    "installers/windows/state.ps1",
    "installers/windows/app/bootstrap.ps1",
}
DENIED_PARTS = {"__pycache__", ".git", "migrations", "baseline", "desktop"}
ALLOWED_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".md", ".css", ".js", ".html", ".ps1"}
CREATE_NO_WINDOW = 0x08000000


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def entry_accepts_current(entry: dict[str, Any], current: str | None) -> bool:
    expected = entry.get("base_sha256")
    accepted = {
        str(value).lower()
        for value in (entry.get("accepted_sha256") or [])
        if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value)
    }
    accepted.update(
        str(value).lower()
        for value in (expected, entry.get("sha256"))
        if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value)
    )
    return current in accepted or (
        current is None and (expected is None or bool(entry.get("accepted_missing")))
    )


def write_status(path: Path, **values: Any) -> None:
    payload = {
        "schema": "les.vps-patch-status.v1",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **values,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _replace_with_retry(temporary, path, timeout=5)


def _creation_flags() -> int:
    return CREATE_NO_WINDOW if os.name == "nt" else 0


def ps_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def powershell(script: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        timeout=45,
        check=check,
        creationflags=_creation_flags(),
    )


def safe_relative_path(value: str) -> PurePosixPath:
    rel = PurePosixPath(str(value).replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise RuntimeError(f"unsafe path in update: {value}")
    normalized = rel.as_posix()
    if any(part in DENIED_PARTS for part in rel.parts):
        raise RuntimeError(f"denied update path: {value}")
    if not (normalized in ALLOWED_FILES or normalized.startswith(ALLOWED_ROOTS)):
        raise RuntimeError(f"path is outside update allowlist: {value}")
    if Path(normalized).suffix.lower() not in ALLOWED_SUFFIXES:
        raise RuntimeError(f"unsupported update file type: {value}")
    return rel


def entry_paths(
    entry: dict[str, Any], runtime: Path
) -> tuple[Path, str, Path]:
    scope = str(entry.get("scope") or "runtime")
    if scope == "app":
        if str(entry.get("path") or "") != "les-desktop.exe":
            raise RuntimeError("unknown Windows app payload")
        return (
            runtime.parent / "les-desktop.exe",
            "payload/@app/les-desktop.exe",
            Path("app") / "les-desktop.exe",
        )
    if scope != "runtime":
        raise RuntimeError(f"unknown Windows update scope: {scope}")
    rel = safe_relative_path(str(entry.get("path") or ""))
    return (
        runtime / Path(*rel.parts),
        f"payload/{rel.as_posix()}",
        Path("runtime") / Path(*rel.parts),
    )


def _validate_manifest(bundle: zipfile.ZipFile, runtime: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(bundle.read("manifest.json"))
    except (KeyError, ValueError, TypeError) as exc:
        raise RuntimeError(f"update manifest is unreadable: {exc}") from exc
    if manifest.get("schema") != SCHEMA:
        raise RuntimeError("unsupported Windows update schema")
    files = manifest.get("files")
    if not isinstance(files, list) or not files or len(files) > 200:
        raise RuntimeError("Windows update file list is invalid")
    if not re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("target_commit") or "")):
        raise RuntimeError("Windows update target commit is invalid")
    if not re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("base_commit") or "")):
        raise RuntimeError("Windows update base commit is invalid")
    if not str(manifest.get("product_version") or "") or int(manifest.get("build_number") or 0) <= 0:
        raise RuntimeError("Windows update identity is missing")

    expected_names = {"manifest.json"}
    seen: set[str] = set()
    total_bytes = 0
    for entry in files:
        if not isinstance(entry, dict):
            raise RuntimeError("Windows update contains an invalid file entry")
        target, archive_name, _ = entry_paths(entry, runtime)
        identity = f"{entry.get('scope') or 'runtime'}:{entry.get('path')}"
        if identity in seen:
            raise RuntimeError(f"duplicate file in Windows update: {identity}")
        seen.add(identity)
        target_hash = str(entry.get("sha256") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", target_hash):
            raise RuntimeError(f"target checksum is invalid: {identity}")
        size = entry.get("bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise RuntimeError(f"target size is invalid: {identity}")
        total_bytes += size
        if total_bytes > 128 * 1024 * 1024:
            raise RuntimeError("unpacked Windows update exceeds the size limit")
        expected_names.add(archive_name)
        try:
            if bundle.getinfo(archive_name).file_size != size:
                raise RuntimeError(f"declared payload size differs from ZIP entry: {identity}")
        except KeyError as exc:
            raise RuntimeError(f"Windows update payload is missing: {identity}") from exc
        current = sha(target) if target.is_file() else None
        if not entry_accepts_current(entry, current):
            raise RuntimeError(f"base checksum mismatch: {identity}")
    if set(bundle.namelist()) != expected_names:
        raise RuntimeError("Windows update archive has undeclared or missing files")
    return manifest


def _stage_payload(
    bundle: zipfile.ZipFile,
    manifest: dict[str, Any],
    stage: Path,
    runtime: Path,
) -> None:
    for entry in manifest["files"]:
        _, archive_name, backup_rel = entry_paths(entry, runtime)
        target = stage / backup_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with bundle.open(archive_name) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output)
        if target.stat().st_size != int(entry["bytes"]) or sha(target) != entry["sha256"]:
            raise RuntimeError(f"payload checksum mismatch: {entry.get('scope')}:{entry['path']}")
        if target.suffix.lower() == ".py":
            py_compile.compile(str(target), doraise=True)


def _acquire_lock(lock_path: Path) -> int:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(descriptor, str(os.getpid()).encode("ascii"))
            return descriptor
        except FileExistsError:
            try:
                pid = int(lock_path.read_text(encoding="ascii").strip())
                os.kill(pid, 0)
            except (OSError, ValueError):
                lock_path.unlink(missing_ok=True)
                continue
            raise RuntimeError(f"Windows update is already running (pid={pid})")
    raise RuntimeError("cannot acquire Windows update lock")


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".les-restore.tmp")
    shutil.copy2(source, temporary)
    _replace_with_retry(temporary, target)


def _replace_with_retry(source: Path, target: Path, *, timeout: float = 20.0) -> None:
    """Wait out transient Windows image/Defender locks without weakening atomicity."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)


def _reusable_backup(backup_root: Path, manifest: dict[str, Any]) -> Path | None:
    """Resume a crashed patch from its first complete recovery point."""
    if not backup_root.is_dir():
        return None
    for candidate in sorted(path for path in backup_root.iterdir() if path.is_dir()):
        try:
            saved = json.loads(
                (candidate / "manifest.json").read_text(encoding="utf-8-sig")
            )
        except (OSError, ValueError, TypeError):
            continue
        if (
            saved.get("schema") == SCHEMA
            and saved.get("patch_id") == manifest.get("patch_id")
            and saved.get("target_commit") == manifest.get("target_commit")
        ):
            return candidate
    return None


def _stop_runtime(runtime: Path, state: Path) -> None:
    windows_update_engine.stop_runtime(
        runtime,
        state,
        state / "logs" / "updates" / "soft-update",
    )


def _stop_desktop() -> None:
    windows_update_engine.stop_desktop()


_DESKTOP_TASK_ROOTS: dict[str, Path] = {}


def start_desktop(runtime: Path, patch_id: str) -> str:
    install_root = windows_update_engine.install_root_from_runtime(runtime)
    task_name = windows_update_engine.start_desktop(
        install_root,
        patch_id,
        runtime / "logs" / "updates" / "soft-update",
    )
    _DESKTOP_TASK_ROOTS[task_name] = install_root
    return task_name


def remove_task(name: str) -> None:
    if name:
        install_root = _DESKTOP_TASK_ROOTS.pop(name, Path.cwd())
        windows_update_engine.remove_task(
            name,
            install_root,
            install_root / "runtime" / "logs" / "updates" / "soft-update",
        )


def _start_runtime(runtime: Path, state: Path) -> None:
    windows_update_engine.probe_environment(
        runtime,
        state,
        state / "logs" / "updates" / "soft-update",
    )
    windows_update_engine.start_runtime(
        runtime,
        state,
        state / "logs" / "updates" / "soft-update",
    )


def _verify_smeta_baseline(
    runtime: Path, state: Path, *, staged_runtime: Path | None = None
) -> None:
    """Repair/verify the bundled immutable FSNB base before accepting a patch."""
    python = state / ".venv" / "Scripts" / "python.exe"
    tool = runtime / "tools" / "smeta_release_baseline.py"
    staged_tool = (staged_runtime or Path()) / "tools" / "smeta_release_baseline.py"
    if staged_runtime is not None and staged_tool.is_file():
        tool = staged_tool
    archive = runtime / "installers" / "windows" / "baseline" / "LES-smeta-baseline.zip"
    missing = [str(path) for path in (python, tool, archive) if not path.is_file()]
    if missing:
        raise RuntimeError("smeta baseline provisioner is incomplete: " + ", ".join(missing))
    environment = dict(os.environ)
    environment["LES_WINDOWS_STATE_ROOT"] = str(state)
    windows_update_engine.run_bounded(
        [
            str(python),
            str(tool),
            "repair",
            "--archive",
            str(archive),
            "--state-root",
            str(state),
        ],
        cwd=runtime,
        log_root=state / "logs" / "updates" / "soft-update",
        name="smeta-baseline",
        timeout=300,
        environment=environment,
        max_working_set_mb=768,
    )


def _json_url(url: str, timeout: float = 5) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - loopback only
        return json.load(response)


def evaluate_process_hygiene(
    runtime_state: dict[str, Any],
    process_snapshot: dict[str, Any],
) -> dict[str, Any]:
    if runtime_state.get("process_contract") != "direct_python_no_console_v1":
        raise RuntimeError("runtime process contract is not console-clean")
    required = {
        "proxy_pid": runtime_state.get("proxy_pid"),
        "ui_pid": runtime_state.get("ui_pid"),
    }
    if any(not value or int(value) <= 0 for value in required.values()):
        raise RuntimeError(f"runtime state has no required direct process PID: {required}")
    expected = {
        int(value)
        for value in (
            runtime_state.get("proxy_pid"),
            runtime_state.get("ui_pid"),
            runtime_state.get("lemonade_host_pid"),
        )
        if value and int(value) > 0
    }
    rows = process_snapshot.get("runtime_processes") or []
    actual = {int(row["pid"]): str(row["name"]).lower() for row in rows}
    missing = expected - set(actual)
    unexpected = {
        pid: name for pid, name in actual.items() if pid in expected and name not in {"python.exe", "pythonw.exe"}
    }
    wrappers = int(process_snapshot.get("cmd_wrappers") or 0)
    if missing:
        raise RuntimeError(f"runtime process disappeared: {sorted(missing)}")
    if unexpected:
        raise RuntimeError(f"runtime uses unexpected launchers: {unexpected}")
    if wrappers:
        raise RuntimeError(f"runtime left {wrappers} cmd.exe wrapper process(es)")
    return {
        "contract": "direct_python_no_console_v1",
        "runtime_processes": [actual[pid] for pid in sorted(expected)],
        "cmd_wrappers": 0,
    }


def _process_hygiene(state: Path) -> dict[str, Any]:
    state_file = state / "logs" / "windows-light-state.json"
    if not state_file.is_file():
        raise RuntimeError("windows-light-state.json is missing")
    runtime_state = json.loads(state_file.read_text(encoding="utf-8-sig"))
    pids = [
        int(value)
        for value in (
            runtime_state.get("proxy_pid"),
            runtime_state.get("ui_pid"),
            runtime_state.get("lemonade_host_pid"),
        )
        if value and int(value) > 0
    ]
    pid_literal = ",".join(str(value) for value in pids) or "0"
    script = (
        "$ErrorActionPreference='Stop'; "
        f"$ids=@({pid_literal}); "
        "$rows=@(Get-CimInstance Win32_Process | Where-Object {$ids -contains [int]$_.ProcessId} | "
        "ForEach-Object {[pscustomobject]@{pid=[int]$_.ProcessId;name=[string]$_.Name}}); "
        "$wrappers=@(Get-CimInstance Win32_Process | Where-Object {"
        "$_.Name -eq 'cmd.exe' -and $_.CommandLine -match 'proxy_server:app|sovushka_ng\\.py|lemonade_host\\.py'}).Count; "
        "[pscustomobject]@{runtime_processes=$rows;cmd_wrappers=$wrappers} | ConvertTo-Json -Depth 4 -Compress"
    )
    snapshot = json.loads(powershell(script).stdout)
    return evaluate_process_hygiene(runtime_state, snapshot)


def _wait_ready(manifest: dict[str, Any], state: Path, timeout: int = 180) -> dict[str, Any]:
    return windows_update_engine.wait_ready(
        expected_commit=str(manifest["target_commit"]),
        expected_version=str(manifest["product_version"]),
        expected_build=int(manifest["build_number"]),
        state=state,
        timeout=timeout,
    )


def _stamp(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_version": manifest["product_version"],
        "build_number": int(manifest["build_number"]),
        "desktop_version": manifest.get("desktop_version") or "",
        "les_version": manifest["product_version"],
        "app_version": manifest["product_version"],
        "deployed_commit": manifest["target_commit"],
        "deployed_branch": manifest.get("branch") or "internal-update",
        "deployed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "deployed_by": "local-updater",
        "deploy_method": "windows_application_update",
        "notes": [
            f"transactional Windows update {manifest['patch_id']}",
            f"{len(manifest['files'])} code files; user data untouched",
        ],
    }


def apply_job(job_path: Path) -> int:
    job = json.loads(Path(job_path).read_text(encoding="utf-8-sig"))
    runtime = Path(job["runtime_root"]).resolve()
    state = Path(job["state_root"]).resolve()
    archive = Path(job["archive"]).resolve()
    status = Path(job["status_path"]).resolve()
    patch_id = str(job["patch_id"])
    helper_task_name = str(job.get("helper_task_name") or "")
    expected_archive_sha = str(job.get("archive_sha256") or "")
    backup_root = state / "artifacts" / "patch-backups" / patch_id
    backup: Path | None = None
    manifest: dict[str, Any] = {}
    changed: list[tuple[Path, bool, Path]] = []
    desktop_task = ""
    previous_stamp: bytes | None = None
    runtime_stopped = False
    stamp_touched = False
    lock_path = status.with_name("apply.lock")
    lock_fd: int | None = None
    try:
        lock_fd = _acquire_lock(lock_path)
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", patch_id):
            raise RuntimeError("unsafe Windows update id")
        if not re.fullmatch(r"[0-9a-f]{64}", expected_archive_sha) or sha(archive) != expected_archive_sha:
            raise RuntimeError("prepared archive checksum mismatch")
        write_status(status, state="applying", stage="validate", patch_id=patch_id, message="Проверяю пакет")
        with zipfile.ZipFile(archive) as bundle, tempfile.TemporaryDirectory(
            prefix="les-windows-update-"
        ) as stage_dir:
            manifest = _validate_manifest(bundle, runtime)
            if str(manifest.get("patch_id") or "") != patch_id:
                raise RuntimeError("job and archive update ids differ")
            stage = Path(stage_dir)
            _stage_payload(bundle, manifest, stage, runtime)

            write_status(
                status,
                state="preflight",
                stage="smeta_baseline",
                patch_id=patch_id,
                message="Проверяю и подключаю базу ФСНБ до изменения версии LES",
            )
            _verify_smeta_baseline(runtime, state, staged_runtime=stage / "runtime")

            stamp_path = runtime / ".les_deploy_stamp.json"
            backup = _reusable_backup(backup_root, manifest)
            if backup is None:
                attempt = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                backup = backup_root / f"{attempt}-{os.getpid()}"
                backup.mkdir(parents=True, exist_ok=False)
                (backup / "manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                if stamp_path.is_file():
                    previous_stamp = stamp_path.read_bytes()
                    (backup / "previous_deploy_stamp.json").write_bytes(previous_stamp)
                for entry in manifest["files"]:
                    target, _, backup_rel = entry_paths(entry, runtime)
                    if target.is_file():
                        saved = backup / "files" / backup_rel
                        saved.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target, saved)
            else:
                saved_stamp = backup / "previous_deploy_stamp.json"
                if saved_stamp.is_file():
                    previous_stamp = saved_stamp.read_bytes()

            _stop_runtime(runtime, state)
            _stop_desktop()
            runtime_stopped = True
            write_status(
                status,
                state="applying",
                stage="replace",
                patch_id=patch_id,
                message=f"Устанавливаю {len(manifest['files'])} файлов",
            )
            for entry in manifest["files"]:
                target, _, backup_rel = entry_paths(entry, runtime)
                existed = target.is_file()
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + ".les-update.tmp")
                shutil.copy2(stage / backup_rel, temporary)
                _replace_with_retry(temporary, target)
                changed.append((target, existed, backup_rel))

        stamp_path = runtime / ".les_deploy_stamp.json"
        write_status(
            status,
            state="applying",
            stage="smeta_baseline",
            patch_id=patch_id,
            message="Проверяю и подключаю базу ФСНБ",
        )
        stamp_tmp = stamp_path.with_suffix(".tmp")
        stamp_tmp.write_text(json.dumps(_stamp(manifest), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(stamp_tmp, stamp_path)
        stamp_touched = True
        write_status(status, state="applying", stage="restart", patch_id=patch_id, message="Перезапускаю ЛЕС")
        _start_runtime(runtime, state)
        desktop_task = start_desktop(runtime, patch_id)
        process_hygiene = _wait_ready(manifest, state)
        remove_task(desktop_task)
        desktop_task = ""
        state_file = state / "artifacts" / "vps-patch-state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps(
                {
                    "schema": "les.vps-patch-state.v1",
                    "patch_id": patch_id,
                    "commit": manifest["target_commit"],
                    "product_version": manifest["product_version"],
                    "build_number": manifest["build_number"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        write_status(
            status,
            state="ready",
            stage="done",
            patch_id=patch_id,
            message="Обновление установлено",
            target_commit=manifest["target_commit"],
            product_version=manifest["product_version"],
            build_number=manifest["build_number"],
            changed_files=len(manifest["files"]),
            backup_root=str(backup),
            process_hygiene=process_hygiene,
            user_data_untouched=True,
        )
        remove_task(helper_task_name)
        return 0
    except Exception as exc:  # noqa: BLE001
        mutated = bool(changed) or stamp_touched
        restore_errors: list[str] = []
        if mutated:
            write_status(
                status,
                state="rollback",
                stage="restore",
                patch_id=patch_id,
                message="Возвращаю предыдущую версию",
                error=str(exc),
            )
            for target, existed, backup_rel in reversed(changed):
                if backup is None:
                    break
                saved = backup / "files" / backup_rel
                try:
                    if existed and saved.is_file():
                        _atomic_copy(saved, target)
                    elif not existed:
                        target.unlink(missing_ok=True)
                except Exception as restore_error:  # noqa: BLE001
                    restore_errors.append(f"{target}: {restore_error}")
            stamp_path = runtime / ".les_deploy_stamp.json"
            try:
                if previous_stamp is not None:
                    stamp_path.write_bytes(previous_stamp)
                else:
                    stamp_path.unlink(missing_ok=True)
            except Exception as restore_error:  # noqa: BLE001
                restore_errors.append(f"{stamp_path}: {restore_error}")
        rollback_ready = False
        if runtime_stopped and not restore_errors:
            try:
                if desktop_task:
                    remove_task(desktop_task)
                _start_runtime(runtime, state)
                rollback_task = start_desktop(runtime, f"{patch_id}-rollback")
                with urllib.request.urlopen(  # noqa: S310 - loopback only
                    "http://127.0.0.1:8051/healthz", timeout=30
                ) as response:
                    rollback_ready = response.status == 200
                remove_task(rollback_task)
            except Exception:
                rollback_ready = False
        write_status(
            status,
            state="failed",
            stage=(
                "rejected"
                if not mutated and not runtime_stopped
                else "rolled_back"
                if rollback_ready
                else "rollback_restart_failed"
            ),
            patch_id=patch_id,
            message=(
                "Обновление отклонено до изменения приложения"
                if not mutated and not runtime_stopped
                else "Обновление отменено, предыдущая версия восстановлена"
                if rollback_ready
                else "Файлы восстановлены, но ЛЕС не перезапустился автоматически"
            ),
            error=(
                str(exc)
                if not restore_errors
                else f"{exc}; rollback errors: {'; '.join(restore_errors)}"
            ),
            user_data_untouched=True,
        )
        remove_task(helper_task_name)
        return 1
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
            lock_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    args = parser.parse_args(argv)
    return apply_job(args.job)


if __name__ == "__main__":
    raise SystemExit(main())
