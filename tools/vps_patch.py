#!/usr/bin/env python3
"""Build and publish a bounded LES runtime patch for the VPS HTTPS origin."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "les.vps-patch.v1"
FEED_SCHEMA = "les.vps-patch-feed.v1"
DEFAULT_ORIGIN = "https://les.ovc.me/updates"
ALLOWED_ROOTS = ("backend/", "proxy/", "sovushka/", "config/prompts/", "skills/", "docs/")
ALLOWED_FILES = {"sovushka_ng.py", "proxy_server.py"}
DENIED_PARTS = {"__pycache__", ".git", "migrations", "baseline", "installers", "desktop"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_path(value: str) -> str:
    path = PurePosixPath(str(value).replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe patch path: {value}")
    normalized = path.as_posix()
    if any(part in DENIED_PARTS for part in path.parts):
        raise ValueError(f"denied patch path: {value}")
    if not (normalized in ALLOWED_FILES or normalized.startswith(ALLOWED_ROOTS)):
        raise ValueError(f"path is outside patch allowlist: {value}")
    if Path(normalized).suffix.lower() not in {".py", ".json", ".yaml", ".yml", ".md", ".css", ".js", ".html"}:
        raise ValueError(f"unsupported patch file type: {value}")
    return normalized


def git_bytes(commit: str, path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"], cwd=ROOT, capture_output=True, check=False
    )
    return result.stdout if result.returncode == 0 else None


def build_patch(*, base: str, target: str, files: list[str], output: Path, origin: str) -> dict:
    base_commit = subprocess.check_output(["git", "rev-parse", base], cwd=ROOT, text=True).strip()
    target_commit = subprocess.check_output(["git", "rev-parse", target], cwd=ROOT, text=True).strip()
    normalized = sorted({normalize_path(path) for path in files})
    if not normalized:
        raise ValueError("patch file list is empty")
    entries: list[dict] = []
    payload: dict[str, bytes] = {}
    for path in normalized:
        before = git_bytes(base_commit, path)
        after = git_bytes(target_commit, path)
        if after is None:
            raise ValueError(f"deletions are not supported in fast patches: {path}")
        if before == after:
            continue
        payload[path] = after
        entries.append(
            {
                "path": path,
                "base_sha256": sha256_bytes(before) if before is not None else None,
                "sha256": sha256_bytes(after),
                "bytes": len(after),
            }
        )
    if not entries:
        raise ValueError("selected files have no changes")
    patch_id = f"{target_commit[:12]}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    manifest = {
        "schema": SCHEMA,
        "patch_id": patch_id,
        "base_commit": base_commit,
        "target_commit": target_commit,
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


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--base", required=True)
    build.add_argument("--target", default="HEAD")
    build.add_argument("--file", action="append", dest="files", required=True)
    build.add_argument("--output", type=Path, default=ROOT / "dist" / "vps-patch")
    build.add_argument("--origin", default=DEFAULT_ORIGIN)
    publish_cmd = sub.add_parser("publish")
    publish_cmd.add_argument("--output", type=Path, default=ROOT / "dist" / "vps-patch")
    publish_cmd.add_argument("--host", default="root@185.185.71.196")
    publish_cmd.add_argument("--remote-root", default="/var/www/les-updates")
    args = parser.parse_args()
    if args.command == "build":
        print(json.dumps(build_patch(base=args.base, target=args.target, files=args.files, output=args.output, origin=args.origin), ensure_ascii=False, indent=2))
    else:
        publish(args.output, args.host, args.remote_root)
        print(json.dumps({"ok": True, "published": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
