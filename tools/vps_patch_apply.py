#!/usr/bin/env python3
"""External transactional helper used by the Windows VPS patch updater."""

from __future__ import annotations

import argparse
import base64
import compileall
import hashlib
import json
import os
import shutil
import subprocess
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def entry_accepts_current(entry: dict, current: str | None) -> bool:
    expected = entry.get("base_sha256")
    accepted = {
        str(value).lower()
        for value in (entry.get("accepted_sha256") or [])
        if isinstance(value, str) and len(value) == 64
    }
    accepted.update(
        str(value).lower()
        for value in (expected, entry.get("sha256"))
        if value
    )
    return current in accepted or (
        current is None and (expected is None or bool(entry.get("accepted_missing")))
    )


def write_status(path: Path, **values) -> None:
    payload = {"schema": "les.vps-patch-status.v1", "updated_at": datetime.now(timezone.utc).isoformat(), **values}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def health(url: str, timeout: int = 90) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - loopback only
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


def ps_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def powershell(script: str, *, check: bool = True) -> subprocess.CompletedProcess:
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        timeout=45,
        check=check,
    )


def start_desktop(runtime: Path, patch_id: str) -> str:
    executable = runtime.parent / "les-desktop.exe"
    if not executable.is_file():
        raise RuntimeError(f"LES desktop executable is missing: {executable}")
    safe_id = "".join(char if char.isalnum() or char in "-_" else "-" for char in patch_id)[:32]
    task_name = f"LES-Patch-Start-{safe_id or 'update'}"
    subprocess.run(["taskkill.exe", "/IM", "les-desktop.exe", "/F"], check=False, capture_output=True)
    script = (
        "$ErrorActionPreference='Stop'; "
        f"$name={ps_literal(task_name)}; "
        "Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue; "
        f"$action=New-ScheduledTaskAction -Execute {ps_literal(str(executable))}; "
        "$trigger=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1); "
        "$principal=New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited; "
        "Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null; "
        "Start-ScheduledTask -TaskName $name"
    )
    powershell(script)
    return task_name


def remove_task(name: str) -> None:
    if not name:
        return
    powershell(
        f"Unregister-ScheduledTask -TaskName {ps_literal(name)} -Confirm:$false -ErrorAction SilentlyContinue",
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    args = parser.parse_args()
    job = json.loads(args.job.read_text(encoding="utf-8"))
    runtime = Path(job["runtime_root"]).resolve()
    state = Path(job["state_root"]).resolve()
    archive = Path(job["archive"]).resolve()
    status = Path(job["status_path"]).resolve()
    patch_id = str(job["patch_id"])
    helper_task_name = str(job.get("helper_task_name") or "")
    backup = state / "artifacts" / "patch-backups" / patch_id
    stop = runtime / "installers" / "windows" / "stop-light.ps1"
    manifest: dict = {}
    changed: list[Path] = []
    try:
        write_status(status, state="applying", stage="backup", patch_id=patch_id, message="Создаю резервную копию")
        with zipfile.ZipFile(archive) as bundle:
            manifest = json.loads(bundle.read("manifest.json"))
            for entry in manifest["files"]:
                rel = PurePosixPath(entry["path"])
                if rel.is_absolute() or ".." in rel.parts:
                    raise RuntimeError("unsafe path in patch")
                target = runtime / Path(*rel.parts)
                current = sha(target) if target.is_file() else None
                if not entry_accepts_current(entry, current):
                    raise RuntimeError(f"base checksum mismatch: {rel.as_posix()}")
                if target.is_file():
                    destination = backup / Path(*rel.parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, destination)
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(stop)], check=False)
        write_status(status, state="applying", stage="replace", patch_id=patch_id, message="Устанавливаю файлы")
        with zipfile.ZipFile(archive) as bundle:
            for entry in manifest["files"]:
                rel = PurePosixPath(entry["path"])
                target = runtime / Path(*rel.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                staged = target.with_suffix(target.suffix + ".patch")
                with bundle.open(f"payload/{rel.as_posix()}") as source, staged.open("wb") as output:
                    shutil.copyfileobj(source, output)
                if sha(staged) != entry["sha256"]:
                    raise RuntimeError(f"target checksum mismatch: {rel.as_posix()}")
                os.replace(staged, target)
                changed.append(target)
        compile_targets = (runtime / "backend", runtime / "proxy", runtime / "sovushka")
        root_modules = (runtime / "proxy_server.py", runtime / "sovushka_ng.py")
        if any(not compileall.compile_dir(str(path), quiet=1, force=True) for path in compile_targets) or any(
            path.is_file() and not compileall.compile_file(str(path), quiet=1, force=True) for path in root_modules
        ):
            raise RuntimeError("Python compile check failed")
        write_status(status, state="applying", stage="restart", patch_id=patch_id, message="Перезапускаю ЛЕС")
        desktop_task = start_desktop(runtime, patch_id)
        if not health("http://127.0.0.1:8050/api/health") or not health("http://127.0.0.1:8051/healthz", 45):
            raise RuntimeError("ЛЕС не ответил после патча")
        remove_task(desktop_task)
        state_file = state / "artifacts" / "vps-patch-state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps({"schema": "les.vps-patch-state.v1", "patch_id": patch_id, "commit": manifest["target_commit"]}, ensure_ascii=False, indent=2), encoding="utf-8")
        write_status(status, state="ready", stage="done", patch_id=patch_id, message="Обновление установлено", target_commit=manifest["target_commit"])
        remove_task(helper_task_name)
        return 0
    except Exception as exc:
        write_status(status, state="rollback", stage="restore", patch_id=patch_id, message="Возвращаю предыдущую версию", error=str(exc))
        for target in reversed(changed):
            rel = target.relative_to(runtime)
            saved = backup / rel
            if saved.is_file():
                shutil.copy2(saved, target)
            else:
                target.unlink(missing_ok=True)
        try:
            rollback_task = start_desktop(runtime, f"{patch_id}-rollback")
            rollback_ready = health("http://127.0.0.1:8050/api/health") and health(
                "http://127.0.0.1:8051/healthz", 45
            )
            remove_task(rollback_task)
        except Exception:
            rollback_ready = False
        write_status(
            status,
            state="failed",
            stage="rolled_back" if rollback_ready else "rollback_restart_failed",
            patch_id=patch_id,
            message=(
                "Обновление отменено, предыдущая версия восстановлена"
                if rollback_ready
                else "Файлы восстановлены, но ЛЕС не перезапустился автоматически"
            ),
            error=str(exc),
        )
        remove_task(helper_task_name)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
