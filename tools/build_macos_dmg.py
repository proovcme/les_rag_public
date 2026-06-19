"""Wrap dist/LES.app into a distributable dist/LES.dmg.

Produces a compressed read-only .dmg whose window shows LES.app next to an
/Applications symlink — the familiar drag-to-install layout. Builds the .app
first if it is missing.

    uv run python tools/build_macos_dmg.py
    uv run python tools/build_macos_dmg.py --version 0.3.0 --sign

macOS only (uses hdiutil).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tools import build_macos_app

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def build_dmg(version: str, sign: bool) -> Path:
    if sys.platform != "darwin":
        raise SystemExit("build_macos_dmg requires macOS (hdiutil)")
    if shutil.which("hdiutil") is None:
        raise SystemExit("hdiutil not found")

    app = DIST / "LES.app"
    if not app.exists():
        print("[dmg] LES.app missing — building it first")
        build_macos_app.build_app(version, sign)

    dmg = DIST / "LES.dmg"
    if dmg.exists():
        dmg.unlink()

    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "LES"
        stage.mkdir()
        # Copy the app into the staging tree and add the /Applications shortcut.
        shutil.copytree(app, stage / "LES.app", symlinks=True)
        (stage / "Applications").symlink_to("/Applications")
        rc = subprocess.run(
            [
                "hdiutil", "create",
                "-volname", "ЛЕС · Совушка",
                "-srcfolder", str(stage),
                "-ov", "-format", "UDZO",
                str(dmg),
            ],
            check=False,
        ).returncode
        if rc != 0:
            raise SystemExit("hdiutil create failed")
    return dmg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build dist/LES.dmg")
    parser.add_argument("--version", default="0.1.0")
    parser.add_argument("--sign", action="store_true", help="ad-hoc codesign the .app before packaging")
    args = parser.parse_args(argv)

    DIST.mkdir(exist_ok=True)
    dmg = build_dmg(args.version, args.sign)
    print(dmg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
