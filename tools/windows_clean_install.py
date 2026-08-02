#!/usr/bin/env python3
"""Transactional per-user LES clean removal/install orchestration for Legion."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools import windows_runtime
from proxy.services import update_service


CREATE_NO_WINDOW = 0x08000000
SCHEMA = "les.windows-clean-install.v1"


def _write_status(path: Path, **values: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SCHEMA,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **values,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _docker() -> Path | None:
    discovered = shutil.which("docker.exe") or shutil.which("docker")
    if discovered:
        return Path(discovered)
    candidate = (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Docker"
        / "Docker"
        / "resources"
        / "bin"
        / "docker.exe"
    )
    return candidate if candidate.is_file() else None


def _run_quiet(arguments: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        arguments,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def _stop_desktop(app_root: Path) -> bool:
    """Stop les-desktop only when its executable path is under app_root."""
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                "$ErrorActionPreference='Stop'; "
                f"$root='{str(app_root).replace(chr(39), chr(39) * 2)}'; "
                "$rows=@(Get-CimInstance Win32_Process -Filter \"Name = 'les-desktop.exe'\"); "
                "$stopped=$false; "
                "foreach($row in $rows){ "
                "  $path=[string]$row.ExecutablePath; "
                "  if($path -and $path.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)){ "
                "    Stop-Process -Id ([int]$row.ProcessId) -Force -ErrorAction SilentlyContinue; "
                "    $stopped=$true "
                "  } "
                "}; "
                "if($stopped){'stopped'}else{'absent'}"
            ),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return "stopped" in (completed.stdout or "")


def remove(*, app_root: Path, state_root: Path, status: Path) -> dict[str, Any]:
    local = Path(os.environ["LOCALAPPDATA"]).resolve()
    app_root = app_root.resolve()
    state_root = state_root.resolve()
    for label, target in (("app", app_root), ("state", state_root)):
        try:
            target.relative_to(local)
        except ValueError as exc:
            raise RuntimeError(f"unsafe {label} root outside LOCALAPPDATA: {target}") from exc
    _write_status(status, state="running", stage="stop", message="Stopping LES")
    if state_root.is_dir() and app_root.is_dir():
        runtime = app_root / "resources" / "runtime"
        if not (runtime / "config" / "version.json").is_file():
            runtime = app_root / "runtime"
        if (runtime / "config" / "version.json").is_file():
            windows_runtime.stop(state_root, runtime=runtime)
    desktop_stopped = _stop_desktop(app_root) if app_root.is_dir() else False

    docker = _docker()
    container_removed = False
    volume_removed = False
    if docker is not None:
        container = _run_quiet([str(docker), "rm", "-f", "les-light-qdrant"])
        container_removed = container.returncode == 0
        volume = _run_quiet([str(docker), "volume", "rm", "les-qdrant-data"])
        volume_removed = volume.returncode == 0
    else:
        container_removed = False
        volume_removed = False

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    removed_root = local / f"LES-removed-{stamp}"
    removed_root.mkdir(parents=False, exist_ok=False)
    _write_status(status, state="running", stage="remove", message="Removing canonical LES roots")
    if app_root.exists():
        os.replace(app_root, removed_root / "app")
    if state_root.exists():
        os.replace(state_root, removed_root / "state")
    result = {
        "state": "ready",
        "stage": "removed",
        "canonical_app_absent": not app_root.exists(),
        "canonical_state_absent": not state_root.exists(),
        "desktop_stopped": desktop_stopped,
        "qdrant_container_removed": container_removed,
        "qdrant_volume_removed": volume_removed,
        "docker_available": docker is not None,
        "removed_root": str(removed_root),
    }
    if not result["canonical_app_absent"] or not result["canonical_state_absent"]:
        raise RuntimeError("canonical LES roots remain after clean removal")
    _write_status(status, **result)
    return result


def launch_remove(*, app_root: Path, state_root: Path, status: Path) -> dict[str, Any]:
    update_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    arguments = (
        f'"{Path(__file__).resolve()}" remove-worker '
        f'--app-root "{app_root}" --state-root "{state_root}" --status "{status}"'
    )
    task_name, encoded = update_service._detached_task_command(
        Path(__file__).resolve(),
        arguments,
        update_id,
        prefix="LES-Clean-Remove",
        python_executable=Path(sys.executable),
    )
    status.unlink(missing_ok=True)
    launched = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
        check=False,
        creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if launched.returncode != 0:
        raise RuntimeError(f"clean removal task launch failed: {launched.stderr.strip()[-800:]}")
    deadline = time.monotonic() + 180
    payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            payload = json.loads(status.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError):
            time.sleep(0.5)
            continue
        if payload.get("state") in {"ready", "failed"}:
            break
        time.sleep(0.5)
    _run_quiet(["schtasks.exe", "/Delete", "/TN", task_name, "/F"])
    if payload.get("state") != "ready":
        raise RuntimeError(f"clean removal failed: {payload.get('error') or payload or 'timeout'}")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("remove", "remove-worker"))
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    parser.add_argument("--app-root", type=Path, default=local / "Programs" / "LES")
    parser.add_argument("--state-root", type=Path, default=local / "LES")
    parser.add_argument("--status", type=Path, default=local / "LES-clean-install-status.json")
    args = parser.parse_args(argv)
    try:
        operation = remove if args.command == "remove-worker" else launch_remove
        result = operation(app_root=args.app_root, state_root=args.state_root, status=args.status)
    except Exception as exc:  # noqa: BLE001 - terminal machine-readable operation boundary
        _write_status(args.status, state="failed", stage="remove", error=str(exc))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
