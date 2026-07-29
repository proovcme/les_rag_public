#!/usr/bin/env python3
"""Build and publish a bounded LES runtime patch for the VPS HTTPS origin."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "les.vps-patch.v2"
FEED_SCHEMA = "les.vps-patch-feed.v1"
DEFAULT_ORIGIN = "https://les.ovc.me/updates"
DESKTOP_MANIFEST_SCHEMA = "les.windows-update-shell.v1"
ALLOWED_ROOTS = ("backend/", "proxy/", "sovushka/", "config/prompts/", "skills/", "docs/")
ALLOWED_FILES = {
    "sovushka_ng.py",
    "proxy_server.py",
    "tools/vps_patch_apply.py",
    "tools/windows_update_engine.py",
    "tools/windows_runtime.py",
    "tools/windows_env_doctor.py",
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
    if Path(normalized).suffix.lower() not in {".py", ".json", ".yaml", ".yml", ".md", ".css", ".js", ".html", ".ps1"}:
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


def accepted_file_hashes(base_commit: str, target_commit: str, path: str) -> tuple[list[str], bool]:
    """Hashes of every committed file state on the bounded release ancestry.

    A user may have installed any earlier VPS patch.  Accepting only the full-release base and the
    newest target strands that user.  The ancestry is trusted release history, not arbitrary local
    content, so every exact intermediate state is safe to advance from.
    """
    commits = subprocess.check_output(
        ["git", "rev-list", "--reverse", "--ancestry-path", f"{base_commit}..{target_commit}"],
        cwd=ROOT,
        text=True,
    ).split()
    hashes: set[str] = set()
    missing = False
    for commit in [base_commit, *commits]:
        data = git_bytes(commit, path)
        if data is None:
            missing = True
            continue
        hashes.add(sha256_bytes(data))
        hashes.add(sha256_bytes(windows_runtime_bytes(data)))
    return sorted(hashes), missing


def build_patch(
    *,
    base: str,
    target: str,
    files: list[str],
    output: Path,
    origin: str,
    desktop_manifest: Path | None = None,
) -> dict:
    base_commit = subprocess.check_output(["git", "rev-parse", base], cwd=ROOT, text=True).strip()
    target_commit = subprocess.check_output(["git", "rev-parse", target], cwd=ROOT, text=True).strip()
    contract = version_contract(target_commit)
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
        accepted_hashes, accepted_missing = accepted_file_hashes(base_commit, target_commit, path)
        entries.append(
            {
                "scope": "runtime",
                "path": path,
                "base_sha256": sha256_bytes(windows_runtime_bytes(before)) if before is not None else None,
                "accepted_sha256": accepted_hashes,
                "accepted_missing": accepted_missing,
                "sha256": sha256_bytes(after),
                "bytes": len(after),
            }
        )
    if desktop_manifest is not None:
        desktop_entry, binary = desktop_payload(
            desktop_manifest,
            target_commit=target_commit,
            contract=contract,
        )
        payload["@app/les-desktop.exe"] = binary
        entries.append(desktop_entry)
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
    publish_cmd = sub.add_parser("publish")
    publish_cmd.add_argument("--output", type=Path, default=ROOT / "dist" / "vps-patch")
    publish_cmd.add_argument("--host", default="root@185.185.71.196")
    publish_cmd.add_argument("--remote-root", default="/var/www/les-updates")
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
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        publish(args.output, args.host, args.remote_root)
        print(json.dumps({"ok": True, "published": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
