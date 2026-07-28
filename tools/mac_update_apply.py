#!/usr/bin/env python3
"""Detached transactional helper for a prepared LES Mac runtime update."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA = "les.mac-update.v1"
DENIED_PARTS = {
    ".env",
    ".git",
    "__pycache__",
    "data",
    "storage",
    "RAG_Content",
    "local_private_archive",
    "dist",
    "installers",
    "desktop",
}
ALLOWED_ROOTS = (
    "proxy/",
    "backend/",
    "sovushka/",
    "tools/",
    "config/",
    "skills/",
)
ALLOWED_FILES = {"sovushka_ng.py", "proxy_server.py", "mlx_host.py"}
ALLOWED_SUFFIXES = {".py", ".yaml", ".yml", ".json", ".md", ".txt"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_relative_path(value: str) -> PurePosixPath:
    rel = PurePosixPath(str(value).replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise RuntimeError(f"unsafe update path: {value}")
    if any(part in DENIED_PARTS for part in rel.parts):
        raise RuntimeError(f"denied update path: {value}")
    normalized = rel.as_posix()
    if not (
        normalized in ALLOWED_FILES or normalized.startswith(ALLOWED_ROOTS)
    ) or Path(normalized).suffix.lower() not in ALLOWED_SUFFIXES:
        raise RuntimeError(f"path is outside the runtime allowlist: {value}")
    return rel


def write_status(path: Path, **values: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "les.mac-update-status.v1",
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **values,
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _current_hash(path: Path) -> str | None:
    return sha256_file(path) if path.is_file() else None


def _entry_accepts_current(entry: dict[str, Any], current: str | None) -> bool:
    target = str(entry.get("sha256") or "") or None
    base = str(entry.get("base_sha256") or "") or None
    accepted = {
        str(value).lower()
        for value in (entry.get("accepted_sha256") or [])
        if len(str(value)) == 64
    }
    return current in {base, target, *accepted} or (
        current is None and bool(entry.get("accepted_missing"))
    )


def _acquire_lock(lock_path: Path) -> int:
    """Acquire the apply lock, recovering only a demonstrably stale PID."""
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
            raise RuntimeError(f"Mac update is already running (pid={pid})")
    raise RuntimeError("cannot acquire Mac update lock")


def _restart(services: list[str]) -> None:
    uid = os.getuid()
    for service in services:
        subprocess.run(
            ["launchctl", "kickstart", "-k", f"gui/{uid}/{service}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )


def _json_url(url: str, timeout: float = 5) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - loopback only
        return json.load(response)


def _wait_ready(manifest: dict[str, Any], timeout: int = 90) -> None:
    deadline = time.monotonic() + timeout
    expected_commit = str(manifest["target_commit"])
    expected_version = str(manifest["product_version"])
    expected_build = int(manifest["build_number"])
    last = "services did not answer"
    while time.monotonic() < deadline:
        try:
            version = _json_url("http://127.0.0.1:8050/api/version")
            health = _json_url("http://127.0.0.1:8050/api/health")
            with urllib.request.urlopen(  # noqa: S310 - loopback only
                "http://127.0.0.1:8051/healthz", timeout=5
            ) as response:
                ui_ok = response.status == 200
            actual_commit = str(version.get("deployed_commit") or "")
            same_commit = expected_commit.startswith(actual_commit) or actual_commit.startswith(
                expected_commit[:8]
            )
            contract = ((health.get("rag") or {}).get("index_contract") or {})
            if (
                str(version.get("product_version") or "") == expected_version
                and int(version.get("build_number") or 0) == expected_build
                and same_commit
                and ui_ok
                and contract.get("compatible") is True
            ):
                return
            last = (
                f"version={version.get('product_version')}/{version.get('build_number')}, "
                f"commit={actual_commit}, ui={ui_ok}, contract={contract.get('status')}"
            )
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
        time.sleep(1)
    raise RuntimeError(f"Mac update smoke did not converge: {last}")


def _stamp(
    manifest: dict[str, Any],
    runtime: Path,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bundle = {
        str(entry["path"]): _current_hash(runtime / Path(*safe_relative_path(entry["path"]).parts))
        for entry in manifest["files"]
        if entry.get("operation") != "delete"
    }
    previous_bundle = (previous or {}).get("file_hash_bundle")
    merged_bundle = dict(previous_bundle) if isinstance(previous_bundle, dict) else {}
    for entry in manifest["files"]:
        path = str(entry["path"])
        if entry.get("operation") == "delete":
            merged_bundle.pop(path, None)
        elif bundle.get(path):
            merged_bundle[path] = str(bundle[path])[:16]
    return {
        "product_version": manifest["product_version"],
        "build_number": int(manifest["build_number"]),
        "desktop_version": manifest.get("desktop_version") or "",
        "les_version": manifest["product_version"],
        "app_version": manifest["product_version"],
        "harness_version": manifest.get("harness_version") or "",
        "deployed_commit": manifest["target_commit"],
        "deployed_branch": manifest.get("branch") or "codex/audit-rag",
        "deployed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "deployed_by": "local",
        "deploy_method": "mac_update_bundle",
        "file_hash_bundle": merged_bundle,
        "notes": [
            f"transactional Mac update {manifest['update_id']}",
            f"{len(manifest['files'])} code files; user data untouched",
        ],
    }


def apply_job(job_path: Path) -> int:
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    runtime = Path(job["runtime_root"]).resolve()
    archive = Path(job["archive"]).resolve()
    status_path = Path(job["status_path"]).resolve()
    recovery_root = Path(job["recovery_root"]).resolve()
    expected_archive_sha = str(job["archive_sha256"])
    lock_path = status_path.with_name("apply.lock")
    lock_fd: int | None = None
    backup: Path | None = None
    manifest: dict[str, Any] = {}
    previous_stamp: bytes | None = None
    previous_stamp_payload: dict[str, Any] = {}
    changed: list[tuple[Path, bool]] = []
    try:
        lock_fd = _acquire_lock(lock_path)
        if sha256_file(archive) != expected_archive_sha:
            raise RuntimeError("prepared archive checksum mismatch")
        write_status(status_path, state="applying", stage="validate", message="Проверяю пакет")
        with zipfile.ZipFile(archive) as bundle:
            manifest = json.loads(bundle.read("manifest.json"))
            if manifest.get("schema") != SCHEMA:
                raise RuntimeError("unsupported Mac update schema")
            expected_names = {"manifest.json"}
            for entry in manifest.get("files") or []:
                rel = safe_relative_path(entry["path"])
                if entry.get("operation") != "delete":
                    expected_names.add(f"payload/{rel.as_posix()}")
            if set(bundle.namelist()) != expected_names:
                raise RuntimeError("Mac update archive has undeclared files")
            for entry in manifest["files"]:
                rel = safe_relative_path(entry["path"])
                target = runtime / Path(*rel.parts)
                if not _entry_accepts_current(entry, _current_hash(target)):
                    raise RuntimeError(f"runtime file differs from prepared base: {rel.as_posix()}")

            update_id = str(manifest["update_id"])
            attempt = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = recovery_root / f"{update_id}-{attempt}-{os.getpid()}"
            backup.mkdir(parents=True, exist_ok=False)
            stamp_path = runtime / ".les_deploy_stamp.json"
            if stamp_path.is_file():
                previous_stamp = stamp_path.read_bytes()
                try:
                    previous_stamp_payload = json.loads(previous_stamp)
                except (ValueError, TypeError):
                    previous_stamp_payload = {}
            (backup / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if previous_stamp is not None:
                (backup / "previous_deploy_stamp.json").write_bytes(previous_stamp)
            with tempfile.TemporaryDirectory(prefix="les-mac-update-") as stage_dir:
                stage = Path(stage_dir)
                for entry in manifest["files"]:
                    if entry.get("operation") == "delete":
                        continue
                    rel = safe_relative_path(entry["path"])
                    staged = stage / Path(*rel.parts)
                    staged.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(f"payload/{rel.as_posix()}") as source, staged.open("wb") as out:
                        shutil.copyfileobj(source, out)
                    if sha256_file(staged) != entry["sha256"]:
                        raise RuntimeError(f"payload checksum mismatch: {rel.as_posix()}")

                write_status(
                    status_path,
                    state="applying",
                    stage="replace",
                    update_id=update_id,
                    message=f"Устанавливаю {len(manifest['files'])} файлов",
                )
                for entry in manifest["files"]:
                    rel = safe_relative_path(entry["path"])
                    target = runtime / Path(*rel.parts)
                    existed = target.is_file()
                    if existed:
                        saved = backup / "files" / Path(*rel.parts)
                        saved.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target, saved)
                    changed.append((target, existed))
                    if entry.get("operation") == "delete":
                        target.unlink(missing_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_name(target.name + ".les-update.tmp")
                    shutil.copy2(stage / Path(*rel.parts), temporary)
                    os.replace(temporary, target)

        stamp_tmp = runtime / ".les_deploy_stamp.json.tmp"
        stamp_tmp.write_text(
            json.dumps(
                _stamp(manifest, runtime, previous_stamp_payload),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(stamp_tmp, runtime / ".les_deploy_stamp.json")
        write_status(
            status_path,
            state="applying",
            stage="restart",
            update_id=manifest["update_id"],
            message="Перезапускаю ЛЕС",
        )
        _restart(list(manifest.get("services") or []))
        _wait_ready(manifest)
        write_status(
            status_path,
            state="ready",
            stage="done",
            update_id=manifest["update_id"],
            target_commit=manifest["target_commit"],
            product_version=manifest["product_version"],
            build_number=manifest["build_number"],
            changed_files=len(manifest["files"]),
            backup_root=str(backup),
            message="Обновление установлено",
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        write_status(
            status_path,
            state="rollback",
            stage="restore",
            message="Возвращаю предыдущую версию",
            error=str(exc),
        )
        if backup is not None:
            for target, existed in reversed(changed):
                rel = target.relative_to(runtime)
                saved = backup / "files" / rel
                if existed and saved.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(saved, target)
                elif not existed:
                    target.unlink(missing_ok=True)
            stamp_path = runtime / ".les_deploy_stamp.json"
            if previous_stamp is not None:
                stamp_path.write_bytes(previous_stamp)
            else:
                stamp_path.unlink(missing_ok=True)
        rollback_ready = False
        try:
            _restart(list(manifest.get("services") or []))
            with urllib.request.urlopen(  # noqa: S310 - loopback only
                "http://127.0.0.1:8051/healthz", timeout=30
            ) as response:
                rollback_ready = response.status == 200
        except Exception:
            rollback_ready = False
        write_status(
            status_path,
            state="failed",
            stage="rolled_back" if rollback_ready else "rollback_restart_failed",
            message=(
                "Обновление отменено, предыдущая версия восстановлена"
                if rollback_ready
                else "Файлы восстановлены, но ЛЕС не перезапустился автоматически"
            ),
            error=str(exc),
        )
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
