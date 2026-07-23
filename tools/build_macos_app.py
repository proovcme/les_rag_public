"""Build the canonical Tauri 2 ``dist/LES.app`` desktop bundle.

The helper functions for the historical handwritten bundle remain for narrow
plist tests, but ``build_app`` delegates to ``tools.build_tauri_app``. The
native window/tray is Rust/Tauri; NiceGUI remains the single product UI and the
bundled Python tree remains the local runtime sidecar.

Build:
    uv run python tools/build_macos_app.py                 # -> dist/LES.app
    uv run python tools/build_macos_app.py --version 0.3.0 --sign

The result is a self-contained .app you can drag to /Applications. Wrap it in a
.dmg with tools/build_macos_dmg.py.
"""

from __future__ import annotations

import argparse
import plistlib
import shutil
from pathlib import Path

from tools.build_release_artifacts import iter_files

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
APP_SRC = ROOT / "installers" / "macos" / "app"


def _write_info_plist(contents: Path, version: str) -> None:
    template = (APP_SRC / "Info.plist.template").read_text(encoding="utf-8")
    text = template.replace("__VERSION__", version)
    # Validate by round-tripping through plistlib so we never ship a broken plist.
    parsed = plistlib.loads(text.encode("utf-8"))
    (contents / "Info.plist").write_bytes(plistlib.dumps(parsed))


def _copy_runtime(resources: Path) -> int:
    """Copy the clean code export into Resources/runtime. Returns file count."""
    runtime = resources / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in iter_files():
        rel = path.relative_to(ROOT)
        dest = runtime / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        count += 1
    return count


def build_app(version: str, sign: bool) -> Path:
    from tools.build_tauri_app import build

    build(version, "app")
    return DIST / "LES.app"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build dist/LES.app")
    parser.add_argument("--version", default="0.1.0", help="bundle version string")
    parser.add_argument("--sign", action="store_true", help="ad-hoc codesign the bundle")
    args = parser.parse_args(argv)

    DIST.mkdir(exist_ok=True)
    app = build_app(args.version, args.sign)
    print(app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
