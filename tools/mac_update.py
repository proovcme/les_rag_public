#!/usr/bin/env python3
"""Build a small, content-addressed Mac runtime update from committed Git state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from tools import deploy_to_runtime, patch_release


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.getenv("LES_RUNTIME_HOME", "/Users/ovc/LES")).resolve()
UPDATE_ROOT = Path(
    os.getenv("LES_MAC_UPDATE_ROOT", str(RUNTIME.parent / "LES_update_cache" / "mac"))
).resolve()
BRANCH = "codex/audit-rag"
SCHEMA = "les.mac-update.v1"
FEED_SCHEMA = "les.mac-update-feed.v1"
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
ALLOWED_ROOTS = ("proxy/", "backend/", "sovushka/", "tools/", "config/", "skills/")
ALLOWED_FILES = {"sovushka_ng.py", "proxy_server.py", "mlx_host.py"}
ALLOWED_SUFFIXES = {".py", ".yaml", ".yml", ".json", ".md", ".txt"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_path(value: str) -> str:
    rel = PurePosixPath(str(value).replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise ValueError(f"unsafe Mac update path: {value}")
    normalized = rel.as_posix()
    if any(part in DENIED_PARTS for part in rel.parts):
        raise ValueError(f"denied Mac update path: {value}")
    if not (
        normalized in ALLOWED_FILES or normalized.startswith(ALLOWED_ROOTS)
    ) or Path(normalized).suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"path is outside the runtime allowlist: {value}")
    return normalized


def git_bytes(commit: str, path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def _resolve_commit(value: str) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", value], cwd=ROOT, text=True
    ).strip()


def _runtime_base_commit(runtime: Path) -> str:
    payload = _runtime_stamp(runtime)
    commit = str(payload.get("deployed_commit") or "").strip()
    if not commit or commit == "unknown":
        raise RuntimeError("Mac runtime deploy stamp has no base commit")
    return _resolve_commit(commit)


def _runtime_stamp(runtime: Path) -> dict[str, Any]:
    stamp = runtime / ".les_deploy_stamp.json"
    try:
        payload = json.loads(stamp.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("Mac runtime deploy stamp is missing or unreadable") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Mac runtime deploy stamp has invalid shape")
    return payload


def _stamped_runtime_hashes(runtime: Path, stamp: dict[str, Any]) -> dict[str, str]:
    """Return only full hashes whose prefix is explicitly owned by deploy stamp."""
    bundle = stamp.get("file_hash_bundle")
    if not isinstance(bundle, dict):
        return {}
    accepted: dict[str, str] = {}
    for raw_path, raw_prefix in bundle.items():
        try:
            path = normalize_path(str(raw_path))
        except ValueError:
            continue
        prefix = str(raw_prefix or "").strip().lower()
        target = runtime / Path(*PurePosixPath(path).parts)
        if len(prefix) < 16 or not target.is_file():
            continue
        current = sha256_file(target)
        if current.startswith(prefix):
            accepted[path] = current
    return accepted


def _changed_entries(base: str, target: str) -> list[tuple[str, str]]:
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", base, target],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    output = subprocess.check_output(
        ["git", "diff", "--name-status", "--find-renames", f"{base}..{target}"],
        cwd=ROOT,
        text=True,
    )
    entries: list[tuple[str, str]] = []
    for line in output.splitlines():
        fields = line.split("\t")
        status = fields[0]
        candidates = (
            [("delete", fields[1]), ("replace", fields[2])]
            if status.startswith("R")
            else [(("delete" if status.startswith("D") else "replace"), fields[-1])]
        )
        for operation, raw_path in candidates:
            try:
                entries.append((operation, normalize_path(raw_path)))
            except ValueError:
                # Non-runtime files are deliberately absent from the package.
                continue
    return sorted(set(entries), key=lambda item: item[1])


def build_update(
    *,
    base: str,
    target: str,
    output: Path = UPDATE_ROOT,
    contract: dict[str, Any] | None = None,
    accepted_runtime_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    base_commit = _resolve_commit(base)
    target_commit = _resolve_commit(target)
    contract = contract or patch_release.load_contract()
    accepted_runtime_hashes = accepted_runtime_hashes or {}
    changes = _changed_entries(base_commit, target_commit)
    if not changes:
        raise ValueError("Mac update has no deployable changes")

    files: list[dict[str, Any]] = []
    payload: dict[str, bytes] = {}
    services: set[str] = set()
    for operation, path in changes:
        before = git_bytes(base_commit, path)
        after = git_bytes(target_commit, path)
        if operation == "delete":
            if before is None:
                continue
        elif after is None:
            raise ValueError(f"target file is missing from Git: {path}")
        if before == after:
            continue
        entry = {
            "operation": operation,
            "path": path,
            "base_sha256": sha256_bytes(before) if before is not None else None,
            "accepted_missing": before is None,
            "sha256": sha256_bytes(after) if after is not None else None,
            "bytes": len(after) if after is not None else 0,
        }
        accepted_current = str(accepted_runtime_hashes.get(path) or "")
        if accepted_current and accepted_current not in {
            entry["base_sha256"],
            entry["sha256"],
        }:
            entry["accepted_sha256"] = [accepted_current]
        files.append(entry)
        if after is not None:
            payload[path] = after
        if service := deploy_to_runtime._service_for_path(path):
            services.add(service)
    if not files:
        raise ValueError("Mac update has no changed runtime files")

    update_id = f"{target_commit[:12]}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    manifest = {
        "schema": SCHEMA,
        "update_id": update_id,
        "branch": BRANCH,
        "base_commit": base_commit,
        "target_commit": target_commit,
        "product_version": str(contract["product_version"]),
        "build_number": int(contract["build_number"]),
        "desktop_version": str(contract.get("desktop_version") or ""),
        "harness_version": str(contract.get("harness_schema_version") or ""),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "services": sorted(services),
        "files": files,
        "user_data_untouched": True,
        "published": False,
    }
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"{update_id}.zip"
    with tempfile.NamedTemporaryFile(dir=output, suffix=".zip", delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
            for path, data in payload.items():
                bundle.writestr(f"payload/{path}", data)
        os.replace(temporary_path, archive)
    finally:
        temporary_path.unlink(missing_ok=True)

    helper = output / "mac_update_apply.py"
    helper_tmp = helper.with_suffix(".py.tmp")
    helper_tmp.write_bytes((ROOT / "tools" / "mac_update_apply.py").read_bytes())
    os.replace(helper_tmp, helper)
    feed = {
        "schema": FEED_SCHEMA,
        "update": manifest,
        "archive": str(archive),
        "archive_sha256": sha256_file(archive),
        "archive_bytes": archive.stat().st_size,
        "helper": str(helper),
        "helper_sha256": sha256_file(helper),
        "prepared_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "published": False,
    }
    feed_path = output / "latest.json"
    feed_tmp = feed_path.with_suffix(".json.tmp")
    feed_tmp.write_text(
        json.dumps(feed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(feed_tmp, feed_path)
    return {"feed": str(feed_path), **feed}


def prepare() -> dict[str, Any]:
    target = patch_release.require_clean_pushed_branch(BRANCH)
    stamp = _runtime_stamp(RUNTIME)
    base = _runtime_base_commit(RUNTIME)
    return build_update(
        base=base,
        target=target,
        accepted_runtime_hashes=_stamped_runtime_hashes(RUNTIME, stamp),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "inspect", "apply", "status"))
    args = parser.parse_args(argv)
    if args.command == "prepare":
        result = prepare()
    elif args.command == "inspect":
        result = json.loads((UPDATE_ROOT / "latest.json").read_text(encoding="utf-8"))
    else:
        # Reuse the same runtime-side validator and launcher as the UI button.
        # The module normally derives its root from the installed runtime; the
        # CLI runs from the repository, so bind both roots explicitly.
        from proxy.services import update_service

        update_service.runtime_root = lambda: RUNTIME
        update_service.mac_update_root = lambda: UPDATE_ROOT
        update_service.mac_update_status_path = lambda: UPDATE_ROOT / "status.json"
        result = (
            update_service.launch_mac_update()
            if args.command == "apply"
            else update_service.read_mac_update_status()
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
