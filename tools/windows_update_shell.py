#!/usr/bin/env python3
"""Build and attest only the Windows Tauri shell used by application updater v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_SCHEMA = "les.windows-update-shell.v1"
CARGO_MANIFEST = ROOT / "desktop" / "tauri" / "src-tauri" / "Cargo.toml"
BUILT_EXE = ROOT / "desktop" / "tauri" / "src-tauri" / "target" / "release" / "les-desktop.exe"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def require_clean_pushed_branch() -> tuple[str, str]:
    branch = _git("branch", "--show-current")
    if not branch.startswith("codex/"):
        raise RuntimeError("Windows update shell must be built from an explicit codex/* branch")
    if _git("status", "--porcelain"):
        raise RuntimeError("Windows update shell requires a clean worktree")
    commit = _git("rev-parse", "HEAD")
    remote = _git("rev-parse", f"origin/{branch}")
    if commit != remote:
        raise RuntimeError(f"HEAD does not match origin/{branch}")
    return branch, commit


def version_contract() -> dict:
    payload = json.loads((ROOT / "config" / "version.json").read_text(encoding="utf-8"))
    if (
        payload.get("schema") != "les.version.v1"
        or not payload.get("product_version")
        or int(payload.get("build_number") or 0) <= 0
        or not payload.get("desktop_version")
    ):
        raise RuntimeError("config/version.json is incomplete")
    return payload


def build_shell(*, base_exe: Path, output: Path) -> dict:
    if not sys.platform.startswith("win"):
        raise RuntimeError("Windows update shell can only be built on Windows")
    base_exe = Path(base_exe).resolve()
    if base_exe.name.lower() != "les-desktop.exe" or not base_exe.is_file():
        raise RuntimeError("--base-exe must point to the currently installed les-desktop.exe")
    branch, commit = require_clean_pushed_branch()
    contract = version_contract()
    subprocess.run(
        ["uv", "run", "python", "tools/sync_version_contract.py", "--check"],
        cwd=ROOT,
        check=True,
        creationflags=0x08000000,
    )
    cargo = shutil.which("cargo")
    if not cargo:
        raise RuntimeError("cargo is not available")
    environment = dict(os.environ)
    subprocess.run(
        [cargo, "build", "--release", "--manifest-path", str(CARGO_MANIFEST)],
        cwd=ROOT,
        env=environment,
        check=True,
        creationflags=0x08000000,
    )
    if not BUILT_EXE.is_file():
        raise RuntimeError(f"cargo did not produce {BUILT_EXE}")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    binary = output / "les-desktop.exe"
    shutil.copy2(BUILT_EXE, binary)
    payload = {
        "schema": MANIFEST_SCHEMA,
        "branch": branch,
        "target_commit": commit,
        "product_version": contract["product_version"],
        "build_number": int(contract["build_number"]),
        "desktop_version": contract["desktop_version"],
        "binary": binary.name,
        "binary_sha256": sha256(binary),
        "binary_bytes": binary.stat().st_size,
        "base_binary_sha256": sha256(base_exe),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "build_kind": "cargo_shell_only",
        "installer_built": False,
        "baseline_built": False,
    }
    manifest = output / "les-desktop.update.json"
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**payload, "manifest": str(manifest)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-exe", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / "windows-update-shell",
    )
    args = parser.parse_args(argv)
    print(json.dumps(build_shell(base_exe=args.base_exe, output=args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
