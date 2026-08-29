"""Fast Programs-shaped Windows runtime gate that runs before NSIS compression."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import psutil


class PrebundleSmokeError(RuntimeError):
    """Raised when the staged Windows runtime cannot reach core readiness."""


def _windows_powershell_environment(base: dict[str, str]) -> dict[str, str]:
    """Return an environment whose module path is valid for Windows PowerShell 5.1."""

    environment = dict(base)
    for name in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "UV_CACHE_DIR"):
        environment.pop(name, None)
    user_profile = Path(environment.get("USERPROFILE", str(Path.home())))
    program_files = Path(environment.get("ProgramFiles", r"C:\Program Files"))
    system_root = Path(environment.get("SystemRoot", r"C:\Windows"))
    environment["PSModulePath"] = os.pathsep.join(
        (
            str(user_profile / "Documents/WindowsPowerShell/Modules"),
            str(program_files / "WindowsPowerShell/Modules"),
            str(system_root / "system32/WindowsPowerShell/v1.0/Modules"),
        )
    )
    return environment


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _wait_http(url: str, *, timeout_seconds: int = 20) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = "no response"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:  # noqa: S310
                if 200 <= response.status < 300:
                    return
                last_error = f"HTTP {response.status}"
        except Exception as error:  # bounded diagnostic loop
            last_error = str(error)
        time.sleep(0.25)
    raise PrebundleSmokeError(f"health probe failed for {url}: {last_error}")


def _bounded_log_tail(path: Path, *, lines: int = 40) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8-sig", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def _service_log_tails(runtime_state_path: Path) -> str:
    state = _read_json(runtime_state_path) or {}
    tails: list[str] = []
    for label, key in (("proxy", "proxy_log"), ("ui", "ui_log")):
        raw_path = state.get(key)
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        tail = _bounded_log_tail(Path(raw_path))
        if tail:
            tails.append(f"{label} log tail: {tail}")
    return "; ".join(tails)


def _validate_cleanup_root(test_root: Path, programs_root: Path) -> None:
    resolved = test_root.resolve()
    parent = programs_root.resolve()
    if resolved.parent != parent or not resolved.name.startswith("LES-prebundle-smoke-"):
        raise PrebundleSmokeError(f"refusing unsafe prebundle cleanup path: {resolved}")


def run_prebundle_smoke(
    runtime_root: Path,
    *,
    timeout_seconds: int = 300,
) -> dict[str, object]:
    """Copy and run one staged runtime below Programs with isolated persistent state."""

    if os.name != "nt":
        raise PrebundleSmokeError("Windows prebundle smoke requires Windows")
    source = Path(runtime_root).resolve()
    bootstrap_source = source / "installers/windows/app/bootstrap.ps1"
    if not bootstrap_source.is_file():
        raise PrebundleSmokeError(f"bootstrap not found: {bootstrap_source}")
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if not local_app_data:
        raise PrebundleSmokeError("LOCALAPPDATA is not defined")

    programs_root = Path(local_app_data).resolve() / "Programs"
    programs_root.mkdir(parents=True, exist_ok=True)
    test_root = programs_root / f"LES-prebundle-smoke-{uuid.uuid4().hex}"
    copied_runtime = test_root / "runtime"
    state_root = test_root / "state"
    process: subprocess.Popen[bytes] | None = None
    runtime_state: dict[str, Any] | None = None
    try:
        shutil.copytree(source, copied_runtime, symlinks=True)
        state_root.mkdir(parents=True)
        log_root = state_root / "logs"
        log_root.mkdir(parents=True)
        status_path = log_root / "bootstrap-status.json"
        runtime_state_path = log_root / "windows-light-state.json"
        environment = _windows_powershell_environment(dict(os.environ))
        environment.update(
            {
                "LES_WINDOWS_STATE_ROOT": str(state_root),
                "LES_RELEASE_SMOKE": "1",
                "LES_RELEASE_SMOKE_DISABLE_DOCKER": "1",
                "LES_TAURI_SHELL": "1",
                "LES_TAURI_ACTION": "start",
            }
        )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(copied_runtime / "installers/windows/app/bootstrap.ps1"),
            ],
            cwd=copied_runtime,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )

        deadline = time.monotonic() + timeout_seconds
        status: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            status = _read_json(status_path)
            if status and status.get("state") in {"ready", "failed"}:
                break
            time.sleep(0.25)
        if not status:
            raise PrebundleSmokeError("bootstrap did not create terminal status")
        if status.get("state") != "ready":
            code = str(status.get("code") or "bootstrap_failed")
            message = str(status.get("message") or "bootstrap failed")
            details = []
            bootstrap_tail = _bounded_log_tail(log_root / "bootstrap.log")
            if bootstrap_tail:
                details.append(f"bootstrap log tail: {bootstrap_tail}")
            service_tails = _service_log_tails(runtime_state_path)
            if service_tails:
                details.append(service_tails)
            detail = f"; {'; '.join(details)}" if details else ""
            raise PrebundleSmokeError(f"{code}: {message}{detail}")

        runtime_state = _read_json(runtime_state_path)
        if not runtime_state:
            raise PrebundleSmokeError("bootstrap ready without windows-light-state.json")
        if runtime_state.get("process_contract") != "direct_python_no_console_v1":
            raise PrebundleSmokeError("runtime process contract is not console-clean")
        proxy_port = int(runtime_state["proxy_port"])
        ui_port = int(runtime_state["ui_port"])
        proxy_pid = int(runtime_state["proxy_pid"])
        ui_pid = int(runtime_state["ui_pid"])
        for pid in (proxy_pid, ui_pid):
            try:
                process_name = psutil.Process(pid).name().casefold()
            except (psutil.Error, OSError) as error:
                raise PrebundleSmokeError(f"runtime process {pid} is unavailable: {error}") from error
            if process_name not in {"python.exe", "pythonw.exe"}:
                raise PrebundleSmokeError(
                    f"runtime process {pid} is an unexpected launcher: {process_name}"
                )
        _wait_http(f"http://127.0.0.1:{proxy_port}/api/health")
        _wait_http(f"http://127.0.0.1:{ui_port}/healthz")
        return {
            "ok": True,
            "test_root": str(test_root),
            "runtime_root": str(copied_runtime),
            "state_root": str(state_root),
            "proxy_port": proxy_port,
            "ui_port": ui_port,
            "proxy_pid": proxy_pid,
            "ui_pid": ui_pid,
        }
    finally:
        stop_script = copied_runtime / "installers/windows/stop-light.ps1"
        if stop_script.is_file():
            environment = _windows_powershell_environment(dict(os.environ))
            environment["LES_WINDOWS_STATE_ROOT"] = str(state_root)
            subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(stop_script),
                ],
                cwd=copied_runtime,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=30,
                check=False,
            )
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        if test_root.exists():
            _validate_cleanup_root(test_root, programs_root)
            shutil.rmtree(test_root)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    try:
        result = run_prebundle_smoke(
            args.runtime_root,
            timeout_seconds=args.timeout_seconds,
        )
    except PrebundleSmokeError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
