#!/usr/bin/env python3
"""External transactional helper used by the Windows VPS patch updater."""

from __future__ import annotations

import argparse
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
    backup = state / "artifacts" / "patch-backups" / patch_id
    stop = runtime / "installers" / "windows" / "stop-light.ps1"
    start = runtime / "installers" / "windows" / "start-light.ps1"
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
                expected = entry.get("base_sha256")
                current = sha(target) if target.is_file() else None
                if current not in {expected, entry["sha256"]} and not (current is None and expected is None):
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
        env = os.environ.copy()
        env["LES_WINDOWS_STATE_ROOT"] = str(state)
        subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(start)], env=env, creationflags=0x00000008 | 0x00000200)
        if not health("http://127.0.0.1:8050/api/health") or not health("http://127.0.0.1:8051/healthz", 45):
            raise RuntimeError("ЛЕС не ответил после патча")
        state_file = state / "artifacts" / "vps-patch-state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps({"schema": "les.vps-patch-state.v1", "patch_id": patch_id, "commit": manifest["target_commit"]}, ensure_ascii=False, indent=2), encoding="utf-8")
        write_status(status, state="ready", stage="done", patch_id=patch_id, message="Обновление установлено", target_commit=manifest["target_commit"])
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
        env = os.environ.copy()
        env["LES_WINDOWS_STATE_ROOT"] = str(state)
        subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(start)], env=env, creationflags=0x00000008 | 0x00000200)
        write_status(status, state="failed", stage="rolled_back", patch_id=patch_id, message="Обновление отменено, предыдущая версия восстановлена", error=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
