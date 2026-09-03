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
ALLOWED_ROOTS = (
    "backend/",
    "proxy/",
    "qdrant_visualizer/",
    "sovushka/",
    "config/prompts/",
    "skills/",
    "docs/",
)
DELETE_ALLOWED_ROOTS = ALLOWED_ROOTS
DELETE_BRIDGE_HELPER = "tools/vps_patch_apply.py"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
ALLOWED_FILES = {
    "env.example",
    "sovushka_ng.py",
    "proxy_server.py",
    "installers/windows/runtime-entrypoints.json",
    "tools/activate_smeta_rag_generation.py",
    "tools/build_smeta_norm_rag.py",
    "tools/build_smeta_structured_base.py",
    "tools/gesn_update_from_fgis.py",
    "tools/install_les.py",
    "tools/rebuild_active_smeta_rag.py",
    "tools/smeta_generation_coordinator.py",
    "tools/smeta_generation_lease.py",
    "tools/vps_patch.py",
    "tools/vps_patch_apply.py",
    "tools/smeta_release_baseline.py",
    "tools/smeta_model_quality_benchmark.py",
    "tools/windows_update_engine.py",
    "tools/windows_runtime.py",
    "tools/windows_env_doctor.py",
    "tools/les_runtime_control.py",
    "tools/live_workbook_acceptance.py",
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


def patch_entry_operation(entry: dict[str, Any]) -> str:
    operation = str(entry.get("operation") or "replace")
    if operation not in {"replace", "delete"}:
        raise RuntimeError("unknown Windows update file operation")
    return operation


def entry_accepts_current(
    entry: dict[str, Any],
    current: str | None,
    *,
    normalized_current: str | None = None,
) -> bool:
    operation = patch_entry_operation(entry)
    expected = entry.get("base_sha256")
    accepted = {
        str(value).lower()
        for value in (entry.get("accepted_sha256") or [])
        if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value)
    }
    accepted.update(
        str(value).lower()
        for value in (
            expected,
            entry.get("sha256") if operation == "replace" else None,
        )
        if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value)
    )
    return current in accepted or normalized_current in accepted or (
        current is None and (expected is None or bool(entry.get("accepted_missing")))
    )


def normalized_text_sha(path: Path) -> str | None:
    """Hash exact text content while treating Windows CRLF as canonical LF."""
    if path.suffix.lower() not in ALLOWED_SUFFIXES or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


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
    if normalized != "env.example" and Path(normalized).suffix.lower() not in ALLOWED_SUFFIXES:
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


def _validate_manifest(
    bundle: zipfile.ZipFile, runtime: Path
) -> tuple[dict[str, Any], dict[str, str | None]]:
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
    delete_present = False
    helper_bridge_present = False
    validated_targets: dict[str, str | None] = {}
    for entry in files:
        if not isinstance(entry, dict):
            raise RuntimeError("Windows update contains an invalid file entry")
        operation = patch_entry_operation(entry)
        target, archive_name, _ = entry_paths(entry, runtime)
        identity = f"{entry.get('scope') or 'runtime'}:{entry.get('path')}"
        if identity in seen:
            raise RuntimeError(f"duplicate file in Windows update: {identity}")
        seen.add(identity)
        normalized = str(entry.get("path") or "").replace("\\", "/")
        scope = str(entry.get("scope") or "runtime")
        if operation == "delete":
            delete_present = True
            if scope != "runtime" or not normalized.startswith(DELETE_ALLOWED_ROOTS):
                raise RuntimeError(f"delete targets a protected Windows file: {identity}")
        elif scope == "runtime" and normalized == DELETE_BRIDGE_HELPER:
            helper_bridge_present = True
        target_hash = str(entry.get("sha256") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", target_hash):
            raise RuntimeError(f"target checksum is invalid: {identity}")
        size = entry.get("bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise RuntimeError(f"target size is invalid: {identity}")
        if operation == "delete" and (size != 0 or target_hash != EMPTY_SHA256):
            raise RuntimeError(f"delete marker is invalid: {identity}")
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
        normalized_current = (
            normalized_text_sha(target) if scope == "runtime" else None
        )
        if not entry_accepts_current(
            entry,
            current,
            normalized_current=normalized_current,
        ):
            raise RuntimeError(f"base checksum mismatch: {identity}")
        validated_targets[identity] = current
    if delete_present and not helper_bridge_present:
        raise RuntimeError("delete update is missing the target helper bridge")
    if set(bundle.namelist()) != expected_names:
        raise RuntimeError("Windows update archive has undeclared or missing files")
    return manifest, validated_targets


def _entry_identity(entry: dict[str, Any]) -> str:
    return f"{entry.get('scope') or 'runtime'}:{entry.get('path')}"


def _assert_targets_unchanged(
    manifest: dict[str, Any],
    runtime: Path,
    validated_targets: dict[str, str | None],
) -> None:
    for entry in manifest["files"]:
        target, _, _ = entry_paths(entry, runtime)
        identity = _entry_identity(entry)
        current = sha(target) if target.is_file() else None
        if current != validated_targets[identity]:
            raise RuntimeError(f"runtime target changed during update: {identity}")


def _reusable_backup_matches(
    backup: Path,
    manifest: dict[str, Any],
    runtime: Path,
    validated_targets: dict[str, str | None],
) -> bool:
    """A resumed recovery point must cover every entry not already at target state."""
    for entry in manifest["files"]:
        identity = _entry_identity(entry)
        current = validated_targets[identity]
        operation = patch_entry_operation(entry)
        target_matches = current is None if operation == "delete" else current == entry["sha256"]
        _, _, backup_rel = entry_paths(entry, runtime)
        saved = backup / "files" / backup_rel
        if target_matches:
            accepted_original = {
                str(value).lower()
                for value in (
                    entry.get("base_sha256"),
                    *(entry.get("accepted_sha256") or []),
                )
                if value
            }
            if saved.exists() and (
                not saved.is_file() or sha(saved) not in accepted_original
            ):
                return False
            continue
        if current is None:
            if saved.exists():
                return False
        elif not saved.is_file() or sha(saved) != current:
            return False
    return True


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
        if patch_entry_operation(entry) == "replace" and target.suffix.lower() == ".py":
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


def _unlink_with_retry(path: Path, *, timeout: float = 15.0) -> None:
    """Wait out a transient Windows reader lock before deleting one exact file."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            path.unlink(missing_ok=True)
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


def _wait_restored_ready(previous_stamp: dict[str, Any], state: Path) -> dict[str, Any]:
    commit = str(previous_stamp.get("deployed_commit") or "")
    version = str(previous_stamp.get("product_version") or "")
    build = int(previous_stamp.get("build_number") or 0)
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or not version or build <= 0:
        raise RuntimeError("previous deploy stamp cannot prove restored identity")
    return windows_update_engine.wait_ready(
        expected_commit=commit,
        expected_version=version,
        expected_build=build,
        state=state,
        timeout=120,
    )


def _restore_file_set(
    manifest: dict[str, Any], runtime: Path, source_root: Path
) -> None:
    for entry in manifest["files"]:
        target, _, backup_rel = entry_paths(entry, runtime)
        saved = source_root / "files" / backup_rel
        if saved.is_file():
            _atomic_copy(saved, target)
        else:
            _unlink_with_retry(target)


def rollback_accepted_patch(
    *,
    runtime: Path,
    state: Path,
    backup_root: Path,
    expected_target_commit: str,
) -> dict[str, Any]:
    """Rollback a successful soft patch, preserving the accepted target on failure."""
    runtime = Path(runtime).resolve()
    state = Path(state).resolve()
    backup = Path(backup_root).resolve()
    allowed = (state / "artifacts" / "patch-backups").resolve()
    if backup == allowed or allowed not in backup.parents:
        raise RuntimeError("soft rollback backup is outside the persistent recovery root")
    if re.fullmatch(r"[0-9a-f]{40}", expected_target_commit) is None:
        raise RuntimeError("soft rollback target identity is invalid")
    try:
        manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8-sig"))
        current_stamp = json.loads(
            (runtime / ".les_deploy_stamp.json").read_text(encoding="utf-8-sig")
        )
        previous_stamp_bytes = (backup / "previous_deploy_stamp.json").read_bytes()
        previous_stamp = json.loads(previous_stamp_bytes.decode("utf-8-sig"))
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        raise RuntimeError("soft rollback recovery metadata is unreadable") from exc
    if (
        manifest.get("schema") != SCHEMA
        or manifest.get("target_commit") != expected_target_commit
        or current_stamp.get("deployed_commit") != expected_target_commit
    ):
        raise RuntimeError("soft rollback target identity does not match accepted update")

    for entry in manifest.get("files") or []:
        target, _, backup_rel = entry_paths(entry, runtime)
        operation = patch_entry_operation(entry)
        current = sha(target) if target.is_file() else None
        target_ok = current is None if operation == "delete" else current == entry.get("sha256")
        if not target_ok:
            raise RuntimeError(f"soft rollback target state changed: {_entry_identity(entry)}")
        saved = backup / "files" / backup_rel
        if saved.is_file():
            accepted = {
                str(value).lower()
                for value in (
                    entry.get("base_sha256"),
                    *(entry.get("accepted_sha256") or []),
                )
                if value
            }
            if sha(saved) not in accepted:
                raise RuntimeError(f"soft rollback backup checksum changed: {_entry_identity(entry)}")
        elif entry.get("accepted_missing") is not True:
            raise RuntimeError(f"soft rollback backup is incomplete: {_entry_identity(entry)}")

    candidate = backup / "accepted-rollback-candidate"
    if candidate.exists():
        raise RuntimeError("soft rollback candidate recovery already exists")
    (candidate / "files").mkdir(parents=True)
    for entry in manifest["files"]:
        target, _, backup_rel = entry_paths(entry, runtime)
        if target.is_file():
            saved = candidate / "files" / backup_rel
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
    (candidate / "target_deploy_stamp.json").write_bytes(
        (runtime / ".les_deploy_stamp.json").read_bytes()
    )

    stopped = False
    desktop_task = ""
    try:
        _stop_runtime(runtime, state)
        _stop_desktop()
        stopped = True
        _restore_file_set(manifest, runtime, backup)
        (runtime / ".les_deploy_stamp.json").write_bytes(previous_stamp_bytes)
        _start_runtime(runtime, state)
        desktop_task = start_desktop(runtime, f"{manifest['patch_id']}-accepted-rollback")
        smoke = _wait_restored_ready(previous_stamp, state)
        remove_task(desktop_task)
        desktop_task = ""
        shutil.rmtree(candidate)
        return {
            "state": "rolled_back",
            "restored_commit": previous_stamp["deployed_commit"],
            "target_commit": expected_target_commit,
            "smoke": smoke,
            "user_data_untouched": True,
        }
    except Exception:
        if stopped:
            try:
                if desktop_task:
                    remove_task(desktop_task)
                _stop_runtime(runtime, state)
                _stop_desktop()
                _restore_file_set(manifest, runtime, candidate)
                (runtime / ".les_deploy_stamp.json").write_bytes(
                    (candidate / "target_deploy_stamp.json").read_bytes()
                )
                _start_runtime(runtime, state)
                retry_task = start_desktop(runtime, f"{manifest['patch_id']}-rollback-recovery")
                remove_task(retry_task)
            except Exception:
                pass
        raise


def _verify_smeta_baseline(
    runtime: Path, state: Path, *, staged_runtime: Path | None = None
) -> None:
    """Accept a readable mechanical baseline; external search availability is independent."""
    del runtime, state, staged_runtime  # identity kept for call-site compatibility
    if _wait_live_smeta_baseline_ready():
        return
    raise RuntimeError(
        "baseline_unreadable: soft update requires a live mechanical smeta "
        "baseline; use hard recovery or clean install instead of hidden repair"
    )


def _live_smeta_baseline_ready() -> bool:
    """Accept old and new runtimes on the exact mechanical expand contract."""
    try:
        expansion = _json_url(
            "http://127.0.0.1:8050/api/lsr/gesn/10-01-001-01/expand?qty=1",
            timeout=10,
        )
    except (OSError, ValueError, TypeError):
        return False
    resources = expansion.get("resources") if isinstance(expansion, dict) else None
    return bool(isinstance(resources, list) and resources)


def _wait_live_smeta_baseline_ready(*, timeout: float = 90.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _live_smeta_baseline_ready():
            return True
        time.sleep(2)
    return False


def _json_url(url: str, timeout: float = 5) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - loopback only
        return json.load(response)


def evaluate_process_hygiene(
    runtime_state: dict[str, Any],
    process_snapshot: dict[str, Any],
) -> dict[str, Any]:
    if runtime_state.get("process_contract") not in {
        "direct_python_no_console_v1",
        "direct_python_no_console_v2",
    }:
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
    replaced_files = 0
    deleted_files = 0
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
            manifest, validated_targets = _validate_manifest(bundle, runtime)
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
            _assert_targets_unchanged(manifest, runtime, validated_targets)

            stamp_path = runtime / ".les_deploy_stamp.json"
            backup = _reusable_backup(backup_root, manifest)
            if backup is not None and not _reusable_backup_matches(
                backup, manifest, runtime, validated_targets
            ):
                backup = None
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
                        identity = _entry_identity(entry)
                        if sha(saved) != validated_targets[identity]:
                            raise RuntimeError(
                                f"runtime target changed while backing up: {identity}"
                            )
            else:
                saved_stamp = backup / "previous_deploy_stamp.json"
                if saved_stamp.is_file():
                    previous_stamp = saved_stamp.read_bytes()

            _assert_targets_unchanged(manifest, runtime, validated_targets)
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
                identity = _entry_identity(entry)
                current = sha(target) if target.is_file() else None
                if current != validated_targets[identity]:
                    raise RuntimeError(
                        f"runtime target changed before mutation: {identity}"
                    )
                operation = patch_entry_operation(entry)
                original_existed = (backup / "files" / backup_rel).is_file()
                if operation == "delete":
                    changed.append((target, original_existed, backup_rel))
                    if target.is_file():
                        _unlink_with_retry(target)
                    deleted_files += 1
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_name(target.name + ".les-update.tmp")
                    shutil.copy2(stage / backup_rel, temporary)
                    _replace_with_retry(temporary, target)
                    changed.append((target, original_existed, backup_rel))
                    replaced_files += 1

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
            replaced_files=replaced_files,
            deleted_files=deleted_files,
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
