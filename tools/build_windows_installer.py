"""Build the Tauri Windows installer on Windows, or a source bundle elsewhere.

Mirrors the macOS bundle (tools/build_macos_app.py): stage a clean code export
(no data/secrets — reuses build_release_artifacts.iter_files) plus the Windows
bootstrap, then package it.

The final ``LES-Setup.exe`` is produced by Tauri/NSIS on a Windows host. macOS
and Linux deliberately do not emit an old Python-shell EXE under the same name;
they stage a clean Windows/Tauri source bundle for transfer to the build host.

    uv run python tools/build_windows_installer.py                  # exe or zip
    uv run python tools/build_windows_installer.py --version 0.3.0

Windows has no Apple MLX — the engine is cloud / ollama / lemonade, configured in
the Sovushka GUI; no model weights are bundled.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from tools.build_release_artifacts import iter_files

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
STAGE = DIST / "windows" / "LES"


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


def build(version: str, build_number: int | None = None) -> Path:
    if sys.platform.startswith("win"):
        from tools.build_tauri_app import build as build_tauri

        build_tauri(version, "nsis", build_number=build_number)
        target = DIST / "LES-Setup.exe"
        if not target.exists():
            raise SystemExit("Tauri NSIS build finished without LES-Setup.exe")
        return target

    DIST.mkdir(exist_ok=True)
    count = stage_runtime(STAGE)
    print(f"[win] staged runtime files: {count} -> {STAGE}")

    zip_base = DIST / "LES-windows-tauri-source"
    archive = shutil.make_archive(str(zip_base), "zip", root_dir=STAGE.parent, base_dir=STAGE.name)
    portable = Path(archive)
    print(f"[win] staged Tauri source bundle for a Windows build host: {portable}")
    print("[win] final installer command on Windows:")
    suffix = f" --build-number {build_number}" if build_number is not None else ""
    print(f"      uv run python tools/build_windows_installer.py --version {version}{suffix}")
    return portable


def main(argv: list[str] | None = None) -> int:
    from tools.build_tauri_app import release_contract

    contract = release_contract()
    parser = argparse.ArgumentParser(description="Build the Windows LES installer.")
    parser.add_argument("--version", default=str(contract["product_version"]))
    parser.add_argument("--build-number", type=int, default=int(contract["build_number"]))
    args = parser.parse_args(argv)

    artifact = build(args.version, args.build_number)
    print(artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
