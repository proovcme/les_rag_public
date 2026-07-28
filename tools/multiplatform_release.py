#!/usr/bin/env python3
"""Build macOS, verify Windows on Legion, and publish one atomic LES release."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from tools import patch_release
from tools.build_tauri_app import build as build_tauri


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_checksum(path: Path) -> Path:
    target = path.with_suffix(path.suffix + ".sha256")
    target.write_text(f"{sha256(path)}  {path.name}\n", encoding="ascii")
    return target


def verify_macos_artifacts(app: Path, dmg: Path) -> dict[str, object]:
    if not app.is_dir() or not dmg.is_file():
        raise RuntimeError("macOS app or DMG is missing")
    patch_release.run(["codesign", "--verify", "--deep", "--strict", str(app)])
    patch_release.run(["hdiutil", "verify", str(dmg)])
    forbidden = [
        path
        for path in app.rglob("*")
        if path.name == ".env"
        or "local_private_archive" in path.parts
        or "data/qdrant" in path.as_posix()
    ]
    if forbidden:
        raise RuntimeError(
            "macOS bundle contains private/runtime state: "
            + ", ".join(str(path) for path in forbidden[:10])
        )
    return {
        "app": str(app),
        "dmg": str(dmg),
        "dmg_bytes": dmg.stat().st_size,
        "dmg_sha256": sha256(dmg),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", default="main")
    parser.add_argument("--legion-host", default="legion")
    parser.add_argument("--legion-root", default=r"C:\Users\Oleg\les_rag")
    parser.add_argument("--notes-file", type=Path, required=True)
    parser.add_argument("--smeta-baseline-archive", type=Path)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args(argv)
    if sys.platform != "darwin":
        raise RuntimeError("multiplatform release must start on the macOS release host")
    patch_release.require_tools(
        ("git", "uv", "make", "ssh", "scp", "npm", "cargo", "codesign", "hdiutil", *(("gh",) if args.publish else ()))
    )
    contract = patch_release.load_contract()
    commit = patch_release.require_clean_pushed_branch(args.branch)
    baseline = (args.smeta_baseline_archive or DIST / "LES-smeta-baseline.zip").resolve()
    from tools.smeta_release_baseline import create_archive, verify_archive

    if args.smeta_baseline_archive:
        verify_archive(baseline)
    else:
        create_archive(ROOT, baseline)
    build_tauri(
        str(contract["product_version"]),
        "app,dmg",
        build_number=int(contract["build_number"]),
    )
    app = DIST / "LES.app"
    dmg = DIST / "LES.dmg"
    mac = verify_macos_artifacts(app, dmg)
    checksum = write_checksum(dmg)
    if patch_release.output(["git", "status", "--porcelain"]):
        raise RuntimeError("macOS build changed tracked source files")
    command = [
        sys.executable,
        str(ROOT / "tools" / "patch_release.py"),
        "--branch",
        args.branch,
        "--legion-host",
        args.legion_host,
        "--legion-root",
        args.legion_root,
        "--notes-file",
        str(args.notes_file),
        "--smeta-baseline-archive",
        str(baseline),
        "--extra-asset",
        str(dmg),
        "--extra-asset",
        str(checksum),
    ]
    if args.publish:
        command.append("--publish")
    patch_release.run(command)
    summary = {
        "schema": "les.multiplatform-release.v1",
        "status": "published" if args.publish else "verified",
        "product_version": contract["product_version"],
        "build_number": contract["build_number"],
        "commit": commit,
        "macos": mac,
        "windows_summary": str(DIST / "windows-patch-release.json"),
    }
    (DIST / "multiplatform-release.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        print(f"multiplatform release failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
