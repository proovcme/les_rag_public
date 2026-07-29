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
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
    os.replace(temporary, path)


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
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                creationflags=creation_flags(),
            )
            raise RuntimeError(f"{name} timed out after {timeout}s") from exc
    if code not in accepted:
        detail = stderr_path.read_text(encoding="utf-8", errors="replace")[-1200:]
        raise RuntimeError(f"{name} failed ({code}): {detail.strip() or 'see log'}")
    return code


def stop_desktop() -> None:
    subprocess.run(
        ["taskkill.exe", "/IM", "les-desktop.exe", "/F"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        creationflags=creation_flags(),
    )


def stop_runtime(runtime: Path, state: Path, log_root: Path) -> None:
    stop = runtime / "installers" / "windows" / "stop-light.ps1"
    if not stop.is_file():
        raise RuntimeError(f"runtime stop entrypoint is missing: {stop}")
    environment = dict(os.environ)
    environment["LES_WINDOWS_STATE_ROOT"] = str(state)
    run_bounded(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(stop),
            "-ProxyPort",
            "8050",
            "-UiPort",
            "8051",
        ],
        cwd=runtime,
        log_root=log_root,
        name="stop-runtime",
        timeout=45,
        environment=environment,
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
    start = runtime / "installers" / "windows" / "start-light.ps1"
    if not start.is_file():
        raise RuntimeError(f"runtime start entrypoint is missing: {start}")
    environment = dict(os.environ)
    environment["LES_WINDOWS_STATE_ROOT"] = str(state)
    environment["LES_ENV_PATH"] = str(state / ".env")
    environment["UV_PROJECT_ENVIRONMENT"] = str(state / ".venv")
    run_bounded(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(start),
            "-ProxyPort",
            "8050",
            "-UiPort",
            "8051",
        ],
        cwd=runtime,
        log_root=log_root,
        name="start-runtime",
        timeout=120,
        environment=environment,
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


def wait_ready(
    *,
    expected_commit: str,
    expected_version: str,
    expected_build: int,
    state: Path,
    timeout: int = 90,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last = "services did not answer"
    while time.monotonic() < deadline:
        try:
            version = _json_url("http://127.0.0.1:8050/api/version")
            health = _json_url("http://127.0.0.1:8050/api/health")
            with urllib.request.urlopen(  # noqa: S310
                "http://127.0.0.1:8051/healthz", timeout=5
            ) as response:
                ui_ok = response.status == 200
            actual_commit = str(version.get("deployed_commit") or "")
            same_commit = len(actual_commit) >= 8 and (
                expected_commit.startswith(actual_commit)
                or actual_commit.startswith(expected_commit[:8])
            )
            contract = ((health.get("rag") or {}).get("index_contract") or {})
            runtime_state = json.loads(
                (state / "logs" / "windows-light-state.json").read_text(
                    encoding="utf-8-sig"
                )
            )
            direct = (
                runtime_state.get("process_contract") == "direct_python_no_console_v1"
                and int(runtime_state.get("proxy_pid") or 0) > 0
                and int(runtime_state.get("ui_pid") or 0) > 0
            )
            if (
                str(version.get("product_version") or "") == expected_version
                and int(version.get("build_number") or 0) == expected_build
                and same_commit
                and ui_ok
                and contract.get("compatible") is True
                and direct
            ):
                return {
                    "product_version": expected_version,
                    "build_number": expected_build,
                    "deployed_commit": actual_commit,
                    "index_contract_compatible": True,
                    "process_contract": "direct_python_no_console_v1",
                }
            last = (
                f"version={version.get('product_version')}/{version.get('build_number')}, "
                f"commit={actual_commit}, ui={ui_ok}, "
                f"contract={contract.get('status')}, direct={direct}"
            )
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
        time.sleep(1)
    raise RuntimeError(f"Windows update smoke did not converge: {last}")


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
    job = _validate_job(json.loads(job_path.read_text(encoding="utf-8")))
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    args = parser.parse_args(argv)
    return apply_hard_job(args.job)


if __name__ == "__main__":
    raise SystemExit(main())
