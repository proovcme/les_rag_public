"""Build the Windows installer — dist/LES-Setup.exe (or a portable zip).

Mirrors the macOS bundle (tools/build_macos_app.py): stage a clean code export
(no data/secrets — reuses build_release_artifacts.iter_files) plus the Windows
bootstrap, then package it.

If NSIS (``makensis``) is available, produces a per-user double-click installer
``dist/LES-Setup.exe`` whose shortcut runs ``installers/windows/app/launcher.vbs``
(hidden) → ``bootstrap.ps1`` (install uv → ``uv sync`` → ``lesctl init`` →
start-light → open browser). If NSIS is absent (e.g. building on macOS/Linux),
falls back to a portable zip and prints the makensis command to run on Windows.

    uv run python tools/build_windows_installer.py                  # exe or zip
    uv run python tools/build_windows_installer.py --version 0.3.0

Windows has no Apple MLX — the engine is cloud / ollama / lemonade, configured in
the Sovushka GUI; no model weights are bundled.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from tools.build_release_artifacts import iter_files

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
STAGE = DIST / "windows" / "LES"
NSI = ROOT / "installers" / "windows" / "app" / "LES.nsi"


def stage_runtime(dest: Path) -> int:
    """Copy the clean code export into ``dest``. Returns file count."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in iter_files():
        rel = path.relative_to(ROOT)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        count += 1
    return count


def build(version: str) -> Path:
    DIST.mkdir(exist_ok=True)
    count = stage_runtime(STAGE)
    print(f"[win] staged runtime files: {count} -> {STAGE}")

    makensis = shutil.which("makensis")
    if makensis:
        out = DIST / "LES-Setup.exe"
        if out.exists():
            out.unlink()
        rc = subprocess.run(
            [makensis, f"-DVERSION={version}", f"-DSRCDIR={STAGE}", str(NSI)],
            check=False,
        ).returncode
        if rc != 0:
            raise SystemExit("makensis failed")
        print(f"[win] built installer: {out}")
        return out

    # No NSIS here — ship a portable zip and tell the user how to make the .exe.
    zip_base = DIST / "LES-windows-portable"
    archive = shutil.make_archive(str(zip_base), "zip", root_dir=STAGE.parent, base_dir=STAGE.name)
    portable = Path(archive)
    print(f"[win] makensis not found — wrote portable bundle: {portable}")
    print("[win] to build LES-Setup.exe on Windows (NSIS installed):")
    print(f'      makensis -DVERSION={version} -DSRCDIR="{STAGE}" "{NSI}"')
    return portable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Windows LES installer.")
    parser.add_argument("--version", default="0.1.0")
    args = parser.parse_args(argv)

    artifact = build(args.version)
    print(artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
