#!/usr/bin/env python3
"""Build, publish, or locally apply a bounded LES runtime patch."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.request import urlopen

from tools.release_classification import classify_release


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "les.vps-patch.v2"
FEED_SCHEMA = "les.vps-patch-feed.v1"
DEFAULT_ORIGIN = "https://github.com/proovcme/les_rag_public/releases/latest/download"
DESKTOP_MANIFEST_SCHEMA = "les.windows-update-shell.v1"
PATCH_OPERATION_REPLACE = "replace"
PATCH_OPERATION_DELETE = "delete"
DELETE_BRIDGE_HELPER = "tools/vps_patch_apply.py"
DELETE_MARKER = b""
ALLOWED_ROOTS = (
    "backend/",
    "proxy/",
    "qdrant_visualizer/",
    "sovushka/",
    "config/prompts/",
    "skills/",
    "docs/",
)
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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def windows_runtime_bytes(data: bytes) -> bytes:
    """Match text bytes staged by the Windows checkout used for the full installer."""
    return data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def normalize_path(value: str) -> str:
    path = PurePosixPath(str(value).replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe patch path: {value}")
    normalized = path.as_posix()
    if any(part in DENIED_PARTS for part in path.parts):
        raise ValueError(f"denied patch path: {value}")
    if not (normalized in ALLOWED_FILES or normalized.startswith(ALLOWED_ROOTS)):
        raise ValueError(f"path is outside patch allowlist: {value}")
    if normalized != "env.example" and Path(normalized).suffix.lower() not in {".py", ".json", ".yaml", ".yml", ".md", ".css", ".js", ".html", ".ps1"}:
        raise ValueError(f"unsupported patch file type: {value}")
    return normalized


def git_bytes(commit: str, path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"], cwd=ROOT, capture_output=True, check=False
    )
    return result.stdout if result.returncode == 0 else None


def version_contract(commit: str) -> dict:
    raw = git_bytes(commit, "config/version.json")
    if raw is None:
        raise ValueError("target commit has no config/version.json")
    try:
        contract = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError("target config/version.json is invalid") from exc
    product_version = str(contract.get("product_version") or "")
    build_number = int(contract.get("build_number") or 0)
    if contract.get("schema") != "les.version.v1" or not product_version or build_number <= 0:
        raise ValueError("target version contract is incomplete")
    return contract


def desktop_payload(
    manifest_path: Path,
    *,
    target_commit: str,
    contract: dict,
) -> tuple[dict, bytes]:
    manifest_path = Path(manifest_path).resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError("desktop build manifest is unreadable") from exc
    if manifest.get("schema") != DESKTOP_MANIFEST_SCHEMA:
        raise ValueError("desktop build manifest schema is unsupported")
    if (
        str(manifest.get("target_commit") or "") != target_commit
        or str(manifest.get("product_version") or "") != str(contract["product_version"])
        or int(manifest.get("build_number") or 0) != int(contract["build_number"])
        or str(manifest.get("desktop_version") or "") != str(contract.get("desktop_version") or "")
    ):
        raise ValueError("desktop build does not match target commit/version/build")
    binary_name = str(manifest.get("binary") or "")
    if binary_name != "les-desktop.exe":
        raise ValueError("desktop build manifest names an unexpected binary")
    binary_path = manifest_path.parent / binary_name
    if not binary_path.is_file():
        raise ValueError("attested les-desktop.exe is missing")
    binary = binary_path.read_bytes()
    if len(binary) > 64 * 1024 * 1024:
        raise ValueError("attested les-desktop.exe exceeds the updater size limit")
    target_hash = sha256_bytes(binary)
    base_hash = str(manifest.get("base_binary_sha256") or "").lower()
    if (
        target_hash != str(manifest.get("binary_sha256") or "").lower()
        or len(binary) != int(manifest.get("binary_bytes") or -1)
        or not re.fullmatch(r"[0-9a-f]{64}", base_hash)
    ):
        raise ValueError("desktop build SHA-256, size, or base identity is invalid")
    return (
        {
            "scope": "app",
            "path": "les-desktop.exe",
            "base_sha256": base_hash,
            "accepted_sha256": sorted({base_hash, target_hash}),
            "accepted_missing": False,
            "sha256": target_hash,
            "bytes": len(binary),
        },
        binary,
    )


def accepted_file_hashes(
    base_commit: str,
    target_commit: str,
    path: str,
    *,
    installed_runtime: Path | None = None,
) -> tuple[list[str], bool]:
    """Hashes of every committed file state on the bounded release ancestry.

    A user may have installed any earlier VPS patch.  Accepting only the full-release base and the
    newest target strands that user.  The ancestry is trusted release history, not arbitrary local
    content, so every exact intermediate state is safe to advance from.
    """
    states = committed_file_states(base_commit, target_commit, [path])[path]
    return accepted_hashes_from_states(
        states,
        path=path,
        installed_runtime=installed_runtime,
    )


def _batch_blob_bytes(blob_ids: set[str]) -> dict[str, bytes]:
    if not blob_ids:
        return {}
    ordered = sorted(blob_ids)
    process = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    output, error = process.communicate(
        b"".join(blob_id.encode("ascii") + b"\n" for blob_id in ordered)
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"git cat-file batch failed: {error.decode('utf-8', errors='replace').strip()}"
        )
    result: dict[str, bytes] = {}
    offset = 0
    for expected in ordered:
        header_end = output.find(b"\n", offset)
        if header_end < 0:
            raise RuntimeError("git cat-file batch returned a truncated header")
        parts = output[offset:header_end].decode("ascii", errors="strict").split()
        if len(parts) != 3 or parts[0] != expected or parts[1] != "blob":
            raise RuntimeError(f"git cat-file returned an unexpected object: {parts}")
        size = int(parts[2])
        start = header_end + 1
        end = start + size
        if end >= len(output) or output[end : end + 1] != b"\n":
            raise RuntimeError("git cat-file batch returned truncated blob bytes")
        result[expected] = output[start:end]
        offset = end + 1
    if offset != len(output):
        raise RuntimeError("git cat-file batch returned trailing bytes")
    return result


def committed_file_states(
    base_commit: str,
    target_commit: str,
    paths: list[str],
    *,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, list[bytes | None]]:
    commits = [
        base_commit,
        *subprocess.check_output(
            [
                "git",
                "rev-list",
                "--reverse",
                "--ancestry-path",
                f"{base_commit}..{target_commit}",
            ],
            cwd=ROOT,
            text=True,
        ).split(),
    ]
    blob_history: dict[str, list[str | None]] = {path: [] for path in paths}
    blob_ids: set[str] = set()
    for index, commit in enumerate(commits, start=1):
        raw = subprocess.check_output(
            ["git", "ls-tree", "-rz", "--full-tree", commit, "--", *paths],
            cwd=ROOT,
        )
        tree: dict[str, str] = {}
        for record in raw.split(b"\0"):
            if not record:
                continue
            metadata, raw_path = record.split(b"\t", 1)
            mode, kind, blob_id = metadata.decode("ascii").split()
            if kind != "blob" or not mode:
                continue
            path = raw_path.decode("utf-8", errors="surrogateescape")
            tree[path] = blob_id
            blob_ids.add(blob_id)
        for path in paths:
            blob_history[path].append(tree.get(path))
        if progress is not None:
            progress(
                {
                    "stage": "history",
                    "current": index,
                    "total": len(commits),
                }
            )
    blobs = _batch_blob_bytes(blob_ids)
    return {
        path: [blobs[blob_id] if blob_id is not None else None for blob_id in history]
        for path, history in blob_history.items()
    }


def accepted_hashes_from_states(
    states: list[bytes | None],
    *,
    path: str,
    installed_runtime: Path | None = None,
) -> tuple[list[str], bool]:
    hashes: set[str] = set()
    committed_states: list[bytes] = []
    missing = False
    for data in states:
        if data is None:
            missing = True
            continue
        committed_states.append(data)
        hashes.add(sha256_bytes(data))
        hashes.add(sha256_bytes(windows_runtime_bytes(data)))
    if installed_runtime is not None:
        installed = Path(installed_runtime) / Path(path)
        if installed.is_file():
            installed_data = installed.read_bytes()
            normalized_installed = installed_data.replace(b"\r\n", b"\n")
            if any(
                normalized_installed == state.replace(b"\r\n", b"\n")
                for state in committed_states
            ):
                hashes.add(sha256_bytes(installed_data))
    return sorted(hashes), missing


def build_patch(
    *,
    base: str,
    target: str,
    files: list[str],
    output: Path,
    origin: str,
    desktop_manifest: Path | None = None,
    installed_runtime: Path | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict:
    base_commit = subprocess.check_output(["git", "rev-parse", base], cwd=ROOT, text=True).strip()
    target_commit = subprocess.check_output(["git", "rev-parse", target], cwd=ROOT, text=True).strip()
    contract = version_contract(target_commit)
    normalized = sorted({normalize_path(path) for path in files})
    if not normalized:
        raise ValueError("patch file list is empty")
    committed_states = committed_file_states(
        base_commit,
        target_commit,
        normalized,
        progress=progress,
    )
    entries: list[dict] = []
    payload: dict[str, bytes] = {}
    for index, path in enumerate(normalized, start=1):
        states = committed_states[path]
        before = states[0]
        after = states[-1]
        if before == after:
            if progress is not None:
                progress({"stage": "files", "current": index, "total": len(normalized), "path": path})
            continue
        accepted_hashes, accepted_missing = accepted_hashes_from_states(
            states,
            path=path,
            installed_runtime=installed_runtime,
        )
        if after is None:
            if before is None:
                continue
            payload[path] = DELETE_MARKER
            entries.append(
                {
                    "operation": PATCH_OPERATION_DELETE,
                    "scope": "runtime",
                    "path": path,
                    "base_sha256": sha256_bytes(windows_runtime_bytes(before)),
                    "accepted_sha256": accepted_hashes,
                    "accepted_missing": True,
                    "sha256": sha256_bytes(DELETE_MARKER),
                    "bytes": 0,
                }
            )
            if progress is not None:
                progress({"stage": "files", "current": index, "total": len(normalized), "path": path})
            continue
        payload[path] = after
        entries.append(
            {
                "operation": PATCH_OPERATION_REPLACE,
                "scope": "runtime",
                "path": path,
                "base_sha256": sha256_bytes(windows_runtime_bytes(before)) if before is not None else None,
                "accepted_sha256": accepted_hashes,
                "accepted_missing": accepted_missing,
                "sha256": sha256_bytes(after),
                "bytes": len(after),
            }
        )
        if progress is not None:
            progress({"stage": "files", "current": index, "total": len(normalized), "path": path})
    if desktop_manifest is not None:
        desktop_entry, binary = desktop_payload(
            desktop_manifest,
            target_commit=target_commit,
            contract=contract,
        )
        payload["@app/les-desktop.exe"] = binary
        desktop_entry["operation"] = PATCH_OPERATION_REPLACE
        entries.append(desktop_entry)
    if any(entry["operation"] == PATCH_OPERATION_DELETE for entry in entries):
        helper = next(
            (entry for entry in entries if entry["path"] == DELETE_BRIDGE_HELPER),
            None,
        )
        if helper is None or helper["operation"] != PATCH_OPERATION_REPLACE:
            raise ValueError("delete patch must replace tools/vps_patch_apply.py")
    if not entries:
        raise ValueError("selected files have no changes")
    patch_id = f"{target_commit[:12]}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    manifest = {
        "schema": SCHEMA,
        "patch_id": patch_id,
        "base_commit": base_commit,
        "target_commit": target_commit,
        "product_version": contract["product_version"],
        "build_number": int(contract["build_number"]),
        "desktop_version": str(contract.get("desktop_version") or ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": entries,
    }
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"{patch_id}.zip"
    with tempfile.NamedTemporaryFile(dir=output, suffix=".zip", delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for path, data in payload.items():
                bundle.writestr(f"payload/{path}", data)
        temporary_path.replace(archive)
    finally:
        temporary_path.unlink(missing_ok=True)
    feed = {
        "schema": FEED_SCHEMA,
        "patch": manifest,
        "archive_url": f"{origin.rstrip('/')}/{archive.name}",
        "archive_sha256": sha256_file(archive),
        "archive_bytes": archive.stat().st_size,
    }
    (output / "latest.json").write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"archive": str(archive), "feed": str(output / "latest.json"), **feed}


def publish(output: Path, host: str, remote_root: str) -> None:
    subprocess.run(["ssh", host, "install", "-d", "-m", "0755", remote_root], check=True)
    archives = sorted(output.glob("*.zip"), key=lambda path: path.stat().st_mtime)
    if not archives or not (output / "latest.json").is_file():
        raise ValueError("patch output is incomplete")
    archive = archives[-1]
    subprocess.run(["scp", str(archive), f"{host}:{remote_root}/{archive.name}.part"], check=True)
    subprocess.run(["scp", str(output / "latest.json"), f"{host}:{remote_root}/latest.json.part"], check=True)
    remote = (
        f"chmod 0644 {remote_root}/{archive.name}.part {remote_root}/latest.json.part && "
        f"mv {remote_root}/{archive.name}.part {remote_root}/{archive.name} && "
        f"mv {remote_root}/latest.json.part {remote_root}/latest.json"
    )
    subprocess.run(["ssh", host, remote], check=True)


def _default_local_paths() -> tuple[Path, Path]:
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if not local_app_data:
        raise ValueError("LOCALAPPDATA is unavailable; pass --runtime and --state explicitly")
    root = Path(local_app_data)
    return root / "Programs" / "LES" / "runtime", root / "LES"


def _read_local_feed(output: Path) -> tuple[dict, dict, Path]:
    feed_path = Path(output).resolve() / "latest.json"
    try:
        feed = json.loads(feed_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"local patch feed is unreadable: {feed_path}") from exc
    patch = feed.get("patch")
    if feed.get("schema") != FEED_SCHEMA or not isinstance(patch, dict) or patch.get("schema") != SCHEMA:
        raise ValueError("local patch feed or manifest schema is unsupported")
    patch_id = str(patch.get("patch_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", patch_id):
        raise ValueError("local patch id is unsafe")
    archive_name = Path(urlparse(str(feed.get("archive_url") or "")).path).name
    archive = feed_path.parent / archive_name
    expected_sha = str(feed.get("archive_sha256") or "").lower()
    expected_bytes = feed.get("archive_bytes")
    if (
        not archive_name
        or not archive.is_file()
        or not re.fullmatch(r"[0-9a-f]{64}", expected_sha)
        or not isinstance(expected_bytes, int)
        or isinstance(expected_bytes, bool)
        or archive.stat().st_size != expected_bytes
        or sha256_file(archive) != expected_sha
    ):
        raise ValueError("local patch archive is missing or fails SHA-256/size verification")
    return feed, patch, archive


def apply_local(*, output: Path, runtime: Path, state: Path) -> dict:
    """Launch the normal Windows soft updater from a verified local package."""
    from proxy.services import update_service

    runtime = Path(runtime).resolve()
    state = Path(state).resolve()
    persistent_python = state / ".venv" / "Scripts" / "python.exe"
    if not runtime.is_dir() or not (runtime / "tools" / "windows_runtime.py").is_file():
        raise ValueError(f"installed LES runtime is incomplete: {runtime}")
    if not persistent_python.is_file():
        raise ValueError(f"persistent LES Python is missing: {persistent_python}")
    feed, patch, source_archive = _read_local_feed(output)
    patch_id = str(patch["patch_id"])
    update_dir = state / "artifacts" / "updates" / "local" / patch_id
    update_dir.mkdir(parents=True, exist_ok=True)
    archive = update_dir / "patch.zip"
    shutil.copy2(source_archive, archive)
    if sha256_file(archive) != str(feed["archive_sha256"]).lower():
        archive.unlink(missing_ok=True)
        raise ValueError("staged local patch archive fails SHA-256 verification")

    try:
        with zipfile.ZipFile(archive) as bundle:
            bundled = json.loads(bundle.read("manifest.json"))
            if bundled != patch:
                raise ValueError("manifest inside local archive does not match latest.json")
            expected = {
                "manifest.json",
                *(
                    f"payload/@app/{entry['path']}"
                    if str(entry.get("scope") or "runtime") == "app"
                    else f"payload/{entry['path']}"
                    for entry in bundled.get("files") or []
                ),
            }
            if set(bundle.namelist()) != expected:
                raise ValueError("local patch archive contains undeclared or missing payload files")
            helper, _, _ = update_service._stage_vps_patch_launcher(
                bundle,
                bundled,
                runtime=runtime,
                root=update_dir,
            )
    except (zipfile.BadZipFile, KeyError, ValueError, TypeError) as exc:
        raise ValueError(f"local patch archive is invalid: {exc}") from exc

    status = state / "artifacts" / "updates" / "vps-patch-status.json"
    status.parent.mkdir(parents=True, exist_ok=True)
    job = update_dir / "job.json"
    job_payload = {
        "runtime_root": str(runtime),
        "state_root": str(state),
        "archive": str(archive),
        "archive_sha256": str(feed["archive_sha256"]).lower(),
        "status_path": str(status),
        "patch_id": patch_id,
        "helper_task_name": "",
    }
    job.write_text(json.dumps(job_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    task_name, encoded = update_service._patch_task_command(
        helper,
        job,
        patch_id,
        python_executable=persistent_python,
    )
    job_payload["helper_task_name"] = task_name
    job.write_text(json.dumps(job_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    status.write_text(
        json.dumps(
            {
                "schema": "les.vps-patch-status.v1",
                "state": "starting",
                "stage": "local_verified",
                "patch_id": patch_id,
                "message": "Local soft package verified; updater task is starting",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    launched = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        cwd=str(update_dir),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        creationflags=0x08000000,
    )
    if launched.returncode != 0:
        detail = (launched.stderr or launched.stdout or "").strip()[-2000:]
        raise RuntimeError(f"Windows failed to launch the local updater task: {detail}")
    return {
        "ok": True,
        "mode": "local",
        "patch_id": patch_id,
        "target_commit": patch.get("target_commit"),
        "product_version": patch.get("product_version"),
        "build_number": patch.get("build_number"),
        "task_name": task_name,
        "job": str(job),
        "status": str(status),
    }


def _installed_commit(runtime: Path) -> str:
    stamp = Path(runtime) / ".les_deploy_stamp.json"
    try:
        payload = json.loads(stamp.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"installed LES deploy stamp is unreadable: {stamp}") from exc
    commit = str(payload.get("deployed_commit") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("installed LES deploy stamp has no exact commit")
    return commit


def _automatic_patch_files(base: str, target: str) -> list[str]:
    classification = classify_release(base, target, root=ROOT)
    if classification.kind == "full":
        details = "; ".join(
            f"{trigger.path} ({trigger.reason})"
            for trigger in classification.triggers[:20]
        )
        raise ValueError(
            f"full release required; unknown runtime paths block the soft-update package: {details}"
        )
    selected = list(classification.runtime_files)
    if not selected:
        raise ValueError("installed LES and target have no bounded runtime changes")
    return sorted(set(selected))


def wait_local_update(status_path: Path, *, timeout: float = 600.0) -> dict:
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        try:
            last = json.loads(Path(status_path).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError):
            time.sleep(1.0)
            continue
        if last.get("state") in {"ready", "failed"}:
            return last
        time.sleep(2.0)
    raise TimeoutError(f"local updater did not finish in {timeout:.0f}s; last status={last}")


def _local_runtime_live(runtime: Path) -> bool:
    try:
        with urlopen("http://127.0.0.1:8050/api/version", timeout=5) as response:  # noqa: S310
            payload = json.load(response)
    except (OSError, ValueError, TypeError):
        return False
    reported = str(payload.get("runtime_path") or "")
    return bool(
        reported
        and str(Path(reported).resolve()).casefold()
        == str(Path(runtime).resolve()).casefold()
    )


def _ensure_local_runtime_live(runtime: Path, state: Path) -> bool:
    """Bootstrap an offline installed LES as the current user before soft-update preflight."""
    if _local_runtime_live(runtime):
        return False
    python = Path(state) / ".venv" / "Scripts" / "python.exe"
    launcher = ROOT / "tools" / "windows_runtime.py"
    missing = [str(path) for path in (python, launcher) if not path.is_file()]
    if missing:
        raise RuntimeError("local LES bootstrap is incomplete: " + ", ".join(missing))
    environment = dict(os.environ)
    environment["LES_WINDOWS_STATE_ROOT"] = str(state)
    result = subprocess.run(
        [
            str(python),
            str(launcher),
            "start",
            "--runtime",
            str(runtime),
            "--state",
            str(state),
        ],
        cwd=str(runtime),
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=150,
        check=False,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    if result.returncode != 0 or not _local_runtime_live(runtime):
        detail = (result.stderr or result.stdout or "").strip()[-1200:]
        raise RuntimeError(f"local LES bootstrap failed: {detail or result.returncode}")
    return True


def update_local(*, output: Path, runtime: Path, state: Path, target: str = "HEAD") -> dict:
    base = _installed_commit(runtime)
    bootstrapped = _ensure_local_runtime_live(runtime, state)
    target_commit = subprocess.check_output(
        ["git", "rev-parse", target], cwd=ROOT, text=True
    ).strip()
    files = _automatic_patch_files(base, target_commit)
    package = build_patch(
        base=base,
        target=target_commit,
        files=files,
        output=output,
        origin=DEFAULT_ORIGIN,
        installed_runtime=runtime,
    )
    launched = apply_local(output=output, runtime=runtime, state=state)
    status = wait_local_update(Path(launched["status"]))
    if status.get("state") != "ready":
        raise RuntimeError(f"local updater failed: {status.get('error') or status.get('message')}")
    return {
        "ok": True,
        "mode": "update-local",
        "bootstrapped_runtime": bootstrapped,
        "files": files,
        "package": package,
        "status": status,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--base", required=True)
    build.add_argument("--target", default="HEAD")
    build.add_argument("--file", action="append", dest="files", required=True)
    build.add_argument("--output", type=Path, default=ROOT / "dist" / "vps-patch")
    build.add_argument("--origin", default=DEFAULT_ORIGIN)
    build.add_argument("--desktop-manifest", type=Path)
    build.add_argument("--installed-runtime", type=Path)
    publish_cmd = sub.add_parser("publish")
    publish_cmd.add_argument("--output", type=Path, default=ROOT / "dist" / "vps-patch")
    publish_cmd.add_argument("--host", default="root@185.185.71.196")
    publish_cmd.add_argument("--remote-root", default="/var/www/les-updates")
    local_cmd = sub.add_parser("apply-local")
    local_cmd.add_argument("--output", type=Path, default=ROOT / "dist" / "vps-patch")
    local_cmd.add_argument("--runtime", type=Path)
    local_cmd.add_argument("--state", type=Path)
    update_cmd = sub.add_parser("update-local")
    update_cmd.add_argument("--output", type=Path, default=ROOT / "dist" / "vps-patch")
    update_cmd.add_argument("--runtime", type=Path)
    update_cmd.add_argument("--state", type=Path)
    update_cmd.add_argument("--target", default="HEAD")
    args = parser.parse_args()
    if args.command == "build":
        print(
            json.dumps(
                build_patch(
                    base=args.base,
                    target=args.target,
                    files=args.files,
                    output=args.output,
                    origin=args.origin,
                    desktop_manifest=args.desktop_manifest,
                    installed_runtime=args.installed_runtime,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "publish":
        publish(args.output, args.host, args.remote_root)
        print(json.dumps({"ok": True, "published": True}, ensure_ascii=False))
    elif args.command == "apply-local":
        default_runtime, default_state = _default_local_paths()
        print(
            json.dumps(
                apply_local(
                    output=args.output,
                    runtime=args.runtime or default_runtime,
                    state=args.state or default_state,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        default_runtime, default_state = _default_local_paths()
        print(
            json.dumps(
                update_local(
                    output=args.output,
                    runtime=args.runtime or default_runtime,
                    state=args.state or default_state,
                    target=args.target,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
