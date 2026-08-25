#!/usr/bin/env python3
"""Transactional Windows application installer shared by hard and soft updates.

The installer executable is an immutable payload, not the transaction owner.
This helper owns the lifecycle: validate -> stop -> replace -> bind persistent
state -> start -> smoke -> keep recovery point or restore it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import windows_runtime
except ImportError:
    from tools import windows_runtime


CREATE_NO_WINDOW = 0x08000000
HARD_JOB_SCHEMA = "les.windows-hard-update.v1"
HARD_STATUS_SCHEMA = "les.windows-hard-update-status.v1"
PERSISTENT_NAMES = ("data", "storage", "RAG_Content", "logs", "artifacts")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def creation_flags() -> int:
    return CREATE_NO_WINDOW if os.name == "nt" else 0


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    deadline = time.monotonic() + 5
    while True:
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def write_status(path: Path, **values: Any) -> None:
    write_json_atomic(
        path,
        {
            "schema": HARD_STATUS_SCHEMA,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **values,
        },
    )


def validate_boundary(install_root: Path, state_root: Path) -> tuple[Path, Path]:
    install = install_root.resolve()
    state = state_root.resolve()
    if install == state or install in state.parents or state in install.parents:
        raise RuntimeError("application and persistent state roots must be disjoint")
    if install == Path(install.anchor) or len(install.parts) < 4:
        raise RuntimeError(f"refusing broad application root: {install}")
    if install.name.casefold() != "les":
        raise RuntimeError(f"application root must end with LES: {install}")
    if not state.name.casefold() == "les":
        raise RuntimeError(f"persistent state root must end with LES: {state}")
    return install, state


def runtime_root(install_root: Path) -> Path:
    candidates = (
        install_root / "resources" / "runtime",
        install_root / "runtime",
    )
    for candidate in candidates:
        if (candidate / "config" / "version.json").is_file():
            return candidate
    raise RuntimeError(f"installed runtime is missing under {install_root}")


def install_root_from_runtime(runtime: Path) -> Path:
    candidates = (runtime.parent, runtime.parent.parent)
    for candidate in candidates:
        if (candidate / "les-desktop.exe").is_file():
            return candidate
    raise RuntimeError(f"application root is missing above {runtime}")


def run_bounded(
    arguments: list[str],
    *,
    cwd: Path,
    log_root: Path,
    name: str,
    timeout: int,
    environment: dict[str, str] | None = None,
    accepted_codes: set[int] | None = None,
    max_working_set_mb: int | None = None,
) -> int:
    """Run one exact child PID with file-backed output and a hard timeout."""
    log_root.mkdir(parents=True, exist_ok=True)
    stdout_path = log_root / f"{name}.out.log"
    stderr_path = log_root / f"{name}.err.log"
    accepted = accepted_codes or {0}
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(
            arguments,
            cwd=str(cwd),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            close_fds=True,
            creationflags=creation_flags(),
        )
        deadline = time.monotonic() + timeout
        code: int | None = None
        while time.monotonic() < deadline:
            code = process.poll()
            if code is not None:
                break
            if max_working_set_mb and _working_set_bytes(process.pid) > (
                max_working_set_mb * 1024 * 1024
            ):
                subprocess.run(
                    ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    creationflags=creation_flags(),
                )
                raise RuntimeError(
                    f"{name} exceeded {max_working_set_mb} MB working-set limit"
                )
            time.sleep(0.25)
        if code is None:
            subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                creationflags=creation_flags(),
            )
            raise RuntimeError(f"{name} timed out after {timeout}s")
    if code not in accepted:
        detail = stderr_path.read_text(encoding="utf-8", errors="replace")[-1200:]
        raise RuntimeError(f"{name} failed ({code}): {detail.strip() or 'see log'}")
    return code


def _working_set_bytes(pid: int) -> int:
    if os.name != "nt":
        return 0
    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    query = 0x1000 | 0x0010
    handle = ctypes.windll.kernel32.OpenProcess(query, False, pid)
    if not handle:
        return 0
    try:
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            handle,
            ctypes.byref(counters),
            counters.cb,
        )
        return int(counters.WorkingSetSize) if ok else 0
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def stop_desktop() -> None:
    deadline = time.monotonic() + 20
    while True:
        subprocess.run(
            ["taskkill.exe", "/IM", "les-desktop.exe", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=creation_flags(),
        )
        probe = subprocess.run(
            [
                "tasklist.exe",
                "/FI",
                "IMAGENAME eq les-desktop.exe",
                "/FO",
                "CSV",
                "/NH",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=creation_flags(),
        )
        output = probe.stdout.decode("utf-8", errors="replace").casefold()
        if "les-desktop.exe" not in output:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("les-desktop.exe did not exit within 20s")
        time.sleep(0.25)


def stop_runtime(runtime: Path, state: Path, log_root: Path) -> None:
    environment = dict(os.environ)
    environment["LES_WINDOWS_STATE_ROOT"] = str(state)
    run_bounded(
        [
            sys.executable,
            str(Path(windows_runtime.__file__).resolve()),
            "stop",
            "--runtime",
            str(runtime),
            "--state",
            str(state),
        ],
        cwd=runtime,
        log_root=log_root,
        name="stop-runtime",
        timeout=30,
        environment=environment,
        max_working_set_mb=256,
    )


def initialize_state(runtime: Path, state: Path, log_root: Path) -> None:
    helper = runtime / "installers" / "windows" / "state.ps1"
    if not helper.is_file():
        raise RuntimeError(f"state binding helper is missing: {helper}")
    command = (
        "$ErrorActionPreference='Stop'; "
        f". '{str(helper).replace(chr(39), chr(39) * 2)}'; "
        f"Initialize-LesWindowsState -RuntimeRoot '{str(runtime).replace(chr(39), chr(39) * 2)}' "
        f"-StateRoot '{str(state).replace(chr(39), chr(39) * 2)}' | ConvertTo-Json -Depth 5"
    )
    run_bounded(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=runtime,
        log_root=log_root,
        name="bind-state",
        timeout=90,
    )
    for name in PERSISTENT_NAMES:
        target = state / name
        link = runtime / name
        if not target.is_dir() or not link.exists():
            raise RuntimeError(f"persistent state binding is incomplete: {name}")


def probe_environment(runtime: Path, state: Path, log_root: Path) -> None:
    python = state / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        raise RuntimeError("persistent LES Python environment is missing")
    modules = ("fastapi", "nicegui", "qdrant_client", "uvicorn")
    code = (
        "import importlib.util,sys;"
        f"m=[n for n in {modules!r} if importlib.util.find_spec(n) is None];"
        "sys.exit('missing runtime modules: '+','.join(m) if m else 0)"
    )
    environment = dict(os.environ)
    environment["LES_WINDOWS_STATE_ROOT"] = str(state)
    environment["LES_ENV_PATH"] = str(state / ".env")
    environment["UV_PROJECT_ENVIRONMENT"] = str(state / ".venv")
    run_bounded(
        [str(python), "-c", code],
        cwd=runtime,
        log_root=log_root,
        name="runtime-probe",
        timeout=30,
        environment=environment,
    )


def start_runtime(runtime: Path, state: Path, log_root: Path) -> None:
    environment = dict(os.environ)
    environment["LES_WINDOWS_STATE_ROOT"] = str(state)
    run_bounded(
        [
            sys.executable,
            str(Path(windows_runtime.__file__).resolve()),
            "start",
            "--runtime",
            str(runtime),
            "--state",
            str(state),
            "--proxy-port",
            "8050",
            "--ui-port",
            "8051",
        ],
        cwd=runtime,
        log_root=log_root,
        name="start-runtime",
        timeout=180,
        environment=environment,
        max_working_set_mb=512,
    )


def _ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def start_desktop(install_root: Path, update_id: str, log_root: Path) -> str:
    executable = install_root / "les-desktop.exe"
    if not executable.is_file():
        raise RuntimeError(f"desktop executable is missing: {executable}")
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "-", update_id)[:32] or "update"
    task_name = f"LES-Update-Start-{safe_id}"
    command = (
        "$ErrorActionPreference='Stop'; "
        f"$name={_ps_literal(task_name)}; "
        "Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue; "
        f"$action=New-ScheduledTaskAction -Execute {_ps_literal(str(executable))}; "
        "$trigger=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1); "
        "$principal=New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited; "
        "Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null; "
        "Start-ScheduledTask -TaskName $name"
    )
    run_bounded(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            __import__("base64").b64encode(command.encode("utf-16le")).decode("ascii"),
        ],
        cwd=install_root,
        log_root=log_root,
        name="start-desktop",
        timeout=30,
    )
    return task_name


def remove_task(name: str, install_root: Path, log_root: Path) -> None:
    if not name:
        return
    command = (
        f"Unregister-ScheduledTask -TaskName {_ps_literal(name)} "
        "-Confirm:$false -ErrorAction SilentlyContinue"
    )
    try:
        run_bounded(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ],
            cwd=install_root if install_root.exists() else log_root,
            log_root=log_root,
            name="remove-desktop-task",
            timeout=20,
        )
    except Exception:
        pass


def _json_url(url: str, timeout: float = 5) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
        return json.load(response)


def _post_json_url(
    url: str,
    payload: dict[str, Any],
    timeout: float = 60,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.load(response)


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _working_set_bytes(pid) > 0
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _ready_snapshot(
    *,
    expected_commit: str,
    expected_version: str,
    expected_build: int,
    state: Path,
    health_timeout: float,
) -> tuple[dict[str, Any] | None, str]:
    """Probe cheap liveness first, then the deeper RAG contract once."""
    try:
        version = _json_url("http://127.0.0.1:8050/api/version", timeout=3)
    except Exception as exc:  # noqa: BLE001
        return None, f"api_version={type(exc).__name__}: {exc}"
    try:
        with urllib.request.urlopen(  # noqa: S310
            "http://127.0.0.1:8051/healthz", timeout=3
        ) as response:
            ui_ok = response.status == 200
    except Exception as exc:  # noqa: BLE001
        return None, f"ui_health={type(exc).__name__}: {exc}"
    try:
        runtime_state = json.loads(
            (state / "logs" / "windows-light-state.json").read_text(
                encoding="utf-8-sig"
            )
        )
    except Exception as exc:  # noqa: BLE001
        return None, f"runtime_state={type(exc).__name__}: {exc}"

    proxy_pid = int(runtime_state.get("proxy_pid") or 0)
    ui_pid = int(runtime_state.get("ui_pid") or 0)
    direct = (
        runtime_state.get("process_contract")
        in {"direct_python_no_console_v1", "direct_python_no_console_v2"}
        and _pid_running(proxy_pid)
        and _pid_running(ui_pid)
    )
    actual_commit = str(version.get("deployed_commit") or "")
    same_commit = len(actual_commit) >= 8 and (
        expected_commit.startswith(actual_commit)
        or actual_commit.startswith(expected_commit[:8])
    )
    identity_ok = (
        str(version.get("product_version") or "") == expected_version
        and int(version.get("build_number") or 0) == expected_build
        and same_commit
    )
    if not (identity_ok and ui_ok and direct):
        return (
            None,
            f"identity={identity_ok}, commit={actual_commit}, ui={ui_ok}, "
            f"direct={direct}, proxy_pid={proxy_pid}, ui_pid={ui_pid}",
        )

    try:
        health = _json_url(
            "http://127.0.0.1:8050/api/health",
            timeout=health_timeout,
        )
    except Exception as exc:  # noqa: BLE001
        return None, f"rag_health={type(exc).__name__}: {exc}"
    contract = ((health.get("rag") or {}).get("index_contract") or {})
    qdrant = ((health.get("rag") or {}).get("qdrant") or {})
    if contract.get("compatible") is not True or qdrant.get("ok") is not True:
        return (
            None,
            f"contract={contract.get('status')}, qdrant={qdrant.get('ok')}",
        )
    try:
        smeta_probe = _json_url(
            "http://127.0.0.1:8050/api/lsr/gesn/10-01-001-01/expand?qty=1",
            timeout=min(15.0, health_timeout),
        )
    except Exception as exc:  # noqa: BLE001
        return None, f"smeta_baseline={type(exc).__name__}: {exc}"
    if not smeta_probe.get("resources"):
        return None, "smeta_baseline=empty_resources"
    try:
        rerank = _post_json_url(
            "http://127.0.0.1:8050/api/rerank",
            {
                "query": "обновление ЛЕС",
                "chunks": [
                    {
                        "text": "ЛЕС обновлён и готов к работе",
                        "score": 1.0,
                        "metadata": {"probe": "relevant"},
                    },
                    {
                        "text": "нерелевантный контрольный фрагмент",
                        "score": 0.0,
                        "metadata": {"probe": "control"},
                    },
                ],
                "top_k": 1,
            },
            timeout=max(30.0, health_timeout),
        )
    except Exception as exc:  # noqa: BLE001
        return None, f"reranker={type(exc).__name__}: {exc}"
    if not rerank.get("ranked"):
        return None, "reranker=empty_result"
    return (
        {
            "product_version": expected_version,
            "build_number": expected_build,
            "deployed_commit": actual_commit,
            "index_contract_compatible": True,
            "qdrant_ready": True,
            "smeta_baseline_ready": True,
            "reranker_ready": True,
            "process_contract": str(runtime_state.get("process_contract")),
            "proxy_pid": proxy_pid,
            "ui_pid": ui_pid,
        },
        "",
    )


def wait_ready(
    *,
    expected_commit: str,
    expected_version: str,
    expected_build: int,
    state: Path,
    timeout: int = 180,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last = "services did not answer"
    consecutive = 0
    attempts = 0
    while time.monotonic() < deadline:
        attempts += 1
        remaining = max(1.0, deadline - time.monotonic())
        snapshot, failure = _ready_snapshot(
            expected_commit=expected_commit,
            expected_version=expected_version,
            expected_build=expected_build,
            state=state,
            health_timeout=min(15.0, remaining),
        )
        if snapshot is not None:
            consecutive += 1
            if consecutive >= 2:
                return {
                    **snapshot,
                    "stability_checks": consecutive,
                    "attempts": attempts,
                }
        else:
            consecutive = 0
            last = failure
        time.sleep(2)
    raise RuntimeError(
        f"Windows update smoke did not converge after {attempts} bounded probes: {last}"
    )


def _detach_state_junctions(runtime: Path) -> None:
    for name in PERSISTENT_NAMES:
        path = runtime / name
        is_junction = getattr(path, "is_junction", lambda: False)()
        if path.is_symlink() or is_junction:
            os.rmdir(path)


def _stamp(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_version": job["product_version"],
        "build_number": int(job["build_number"]),
        "desktop_version": job["desktop_version"],
        "les_version": job["product_version"],
        "app_version": job["product_version"],
        "deployed_commit": job["target_commit"],
        "deployed_branch": job.get("branch") or "release",
        "deployed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "deployed_by": "windows-update-engine",
        "deploy_method": "hard_application_tree_replace",
        "notes": [
            "installer payload executed by a bounded Python transaction",
            "application tree replaced; persistent LES state retained",
        ],
    }


def _validate_job(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != HARD_JOB_SCHEMA:
        raise RuntimeError("unsupported hard-update job schema")
    if not re.fullmatch(r"[0-9a-f]{40}", str(payload.get("target_commit") or "")):
        raise RuntimeError("hard-update target commit is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", str(payload.get("installer_sha256") or "")):
        raise RuntimeError("hard-update installer checksum is invalid")
    if not str(payload.get("product_version") or ""):
        raise RuntimeError("hard-update product version is missing")
    if int(payload.get("build_number") or 0) <= 0:
        raise RuntimeError("hard-update build number is invalid")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(payload.get("desktop_version") or "")):
        raise RuntimeError("hard-update desktop version is invalid")
    return payload


def apply_hard_job(job_path: Path) -> int:
    job = _validate_job(json.loads(job_path.read_text(encoding="utf-8-sig")))
    install, state = validate_boundary(
        Path(job["install_root"]),
        Path(job["state_root"]),
    )
    installer = Path(job["installer"]).resolve()
    status = Path(job["status_path"]).resolve()
    log_root = state / "logs" / "updates" / str(job["update_id"])
    lock_path = state / "artifacts" / "updates" / "application-update.lock"
    recovery = install.with_name(
        f"{install.name}.recovery-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    )
    old_runtime: Path | None = None
    new_runtime: Path | None = None
    moved_old = False
    desktop_task = ""
    lock_fd: int | None = None
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(lock_fd, str(os.getpid()).encode("ascii"))
        if not installer.is_file() or sha256_file(installer) != job["installer_sha256"]:
            raise RuntimeError("hard-update installer checksum mismatch")
        if not install.is_dir():
            raise RuntimeError(f"existing LES application is missing: {install}")
        old_runtime = runtime_root(install)
        probe_environment(old_runtime, state, log_root)
        state.mkdir(parents=True, exist_ok=True)
        preservation = state / "artifacts" / "updates" / "state-preservation.json"
        marker = {
            "schema": "les.windows-state-preservation.v1",
            "update_id": job["update_id"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        write_json_atomic(preservation, marker)

        write_status(
            status,
            state="applying",
            stage="stop",
            update_id=job["update_id"],
            message="Останавливаю текущую версию",
        )
        stop_runtime(old_runtime, state, log_root)
        stop_desktop()
        if recovery.exists():
            raise RuntimeError(f"recovery point already exists: {recovery}")
        os.replace(install, recovery)
        moved_old = True

        write_status(
            status,
            state="applying",
            stage="install",
            update_id=job["update_id"],
            message="Заменяю файлы приложения",
        )
        run_bounded(
            [str(installer), "/S", f"/D={install}"],
            cwd=installer.parent,
            log_root=log_root,
            name="installer",
            timeout=300,
        )
        new_runtime = runtime_root(install)
        version = json.loads(
            (new_runtime / "config" / "version.json").read_text(encoding="utf-8")
        )
        if (
            str(version.get("product_version")) != job["product_version"]
            or int(version.get("build_number") or 0) != int(job["build_number"])
            or str(version.get("desktop_version")) != job["desktop_version"]
        ):
            raise RuntimeError(f"installed identity differs from job: {version}")
        initialize_state(new_runtime, state, log_root)
        probe_environment(new_runtime, state, log_root)
        write_json_atomic(new_runtime / ".les_deploy_stamp.json", _stamp(job))

        write_status(
            status,
            state="applying",
            stage="start",
            update_id=job["update_id"],
            message="Запускаю и проверяю новую версию",
        )
        start_runtime(new_runtime, state, log_root)
        desktop_task = start_desktop(install, str(job["update_id"]), log_root)
        smoke = wait_ready(
            expected_commit=job["target_commit"],
            expected_version=job["product_version"],
            expected_build=int(job["build_number"]),
            state=state,
            timeout=120,
        )
        if json.loads(preservation.read_text(encoding="utf-8")) != marker:
            raise RuntimeError("persistent-state preservation marker changed")
        remove_task(desktop_task, install, log_root)
        desktop_task = ""
        write_status(
            status,
            state="ready",
            stage="done",
            update_id=job["update_id"],
            message="Выпуск установлен",
            product_version=job["product_version"],
            build_number=int(job["build_number"]),
            target_commit=job["target_commit"],
            recovery_root=str(recovery),
            smoke=smoke,
            application_tree_replaced=True,
            user_data_untouched=True,
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        rollback_ready = False
        if moved_old:
            try:
                if new_runtime is not None:
                    try:
                        stop_runtime(new_runtime, state, log_root)
                    except Exception:
                        pass
                    _detach_state_junctions(new_runtime)
                stop_desktop()
                if install.exists():
                    shutil.rmtree(install)
                os.replace(recovery, install)
                restored = runtime_root(install)
                start_runtime(restored, state, log_root)
                start_desktop(install, f"{job.get('update_id', 'hard')}-rollback", log_root)
                rollback_ready = True
            except Exception:
                rollback_ready = False
        write_status(
            status,
            state="failed",
            stage=(
                "rejected"
                if not moved_old
                else "rolled_back"
                if rollback_ready
                else "rollback_restart_failed"
            ),
            update_id=str(job.get("update_id") or ""),
            message=(
                "Установка отклонена до изменения приложения"
                if not moved_old
                else "Новая версия не прошла проверку; предыдущая восстановлена"
                if rollback_ready
                else "Файлы предыдущей версии восстановить автоматически не удалось"
            ),
            error=str(exc),
            user_data_untouched=True,
        )
        return 1
    finally:
        if desktop_task and install.exists():
            remove_task(desktop_task, install, log_root)
        helper_task = str(job.get("helper_task_name") or "")
        if helper_task:
            remove_task(helper_task, install if install.exists() else state, log_root)
        if lock_fd is not None:
            os.close(lock_fd)
            lock_path.unlink(missing_ok=True)


def resume_hard_job(job_path: Path) -> int:
    """Finish smoke/handoff after an interrupted hard job without reinstalling."""
    job = _validate_job(json.loads(job_path.read_text(encoding="utf-8-sig")))
    install, state = validate_boundary(
        Path(job["install_root"]),
        Path(job["state_root"]),
    )
    status = Path(job["status_path"]).resolve()
    log_root = state / "logs" / "updates" / f"{job['update_id']}-resume"
    runtime = runtime_root(install)
    version = json.loads(
        (runtime / "config" / "version.json").read_text(encoding="utf-8")
    )
    if (
        str(version.get("product_version")) != job["product_version"]
        or int(version.get("build_number") or 0) != int(job["build_number"])
        or str(version.get("desktop_version")) != job["desktop_version"]
    ):
        raise RuntimeError("installed tree does not match interrupted hard-update job")
    stamp = json.loads(
        (runtime / ".les_deploy_stamp.json").read_text(encoding="utf-8-sig")
    )
    if str(stamp.get("deployed_commit") or "") != job["target_commit"]:
        raise RuntimeError("installed deploy stamp does not match interrupted hard-update job")
    marker_path = state / "artifacts" / "updates" / "state-preservation.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8-sig"))
    if marker.get("update_id") != job["update_id"]:
        raise RuntimeError("persistent-state marker does not match interrupted hard-update job")

    lock_path = state / "artifacts" / "updates" / "application-update.lock"
    if lock_path.is_file():
        try:
            stale_pid = int(lock_path.read_text(encoding="ascii").strip())
        except ValueError:
            lock_path.unlink(missing_ok=True)
        else:
            alive = (
                _working_set_bytes(stale_pid) > 0
                if os.name == "nt"
                else _pid_alive(stale_pid)
            )
            if alive:
                raise RuntimeError(f"hard update is still running (pid={stale_pid})")
            lock_path.unlink(missing_ok=True)

    write_status(
        status,
        state="applying",
        stage="resume_smoke",
        update_id=job["update_id"],
        message="Проверяю уже установленное дерево",
    )
    try:
        _json_url("http://127.0.0.1:8050/api/version", timeout=5)
    except Exception:
        start_runtime(runtime, state, log_root)
    desktop_task = start_desktop(install, f"{job['update_id']}-resume", log_root)
    try:
        smoke = wait_ready(
            expected_commit=job["target_commit"],
            expected_version=job["product_version"],
            expected_build=int(job["build_number"]),
            state=state,
            timeout=120,
        )
    finally:
        remove_task(desktop_task, install, log_root)
    recoveries = sorted(
        install.parent.glob(f"{install.name}.recovery-*"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    recovery = recoveries[0] if recoveries else None
    write_status(
        status,
        state="ready",
        stage="done",
        update_id=job["update_id"],
        message="Выпуск установлен",
        product_version=job["product_version"],
        build_number=int(job["build_number"]),
        target_commit=job["target_commit"],
        recovery_root=str(recovery) if recovery else "",
        smoke=smoke,
        resumed_after_interruption=True,
        application_tree_replaced=True,
        user_data_untouched=True,
    )
    return 0


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--job", type=Path)
    mode.add_argument("--resume-job", type=Path)
    args = parser.parse_args(argv)
    return (
        resume_hard_job(args.resume_job)
        if args.resume_job is not None
        else apply_hard_job(args.job)
    )


if __name__ == "__main__":
    raise SystemExit(main())
