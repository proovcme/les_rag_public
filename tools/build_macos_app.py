"""Assemble dist/LES.app — the double-click macOS installer/launcher bundle.

Lightweight bootstrap design (per HANDOFF plan): the .app carries a clean code
export of the runtime (no data/secrets — reuses build_release_artifacts.iter_files)
plus a shell bootstrap that, on first launch, installs uv, runs
``uv sync --extra mac-mlx``, downloads model weights, and starts the stack via
``lesctl``. No Python is bundled; the bootstrap provisions a uv environment on
the target machine.

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
import subprocess
import sys
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
    app = DIST / "LES.app"
    if app.exists():
        shutil.rmtree(app)
    contents = app / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    for d in (macos, resources):
        d.mkdir(parents=True, exist_ok=True)

    _write_info_plist(contents, version)

    launcher = macos / "LES"
    shutil.copy2(APP_SRC / "launcher", launcher)
    launcher.chmod(0o755)

    bootstrap = resources / "bootstrap.sh"
    shutil.copy2(APP_SRC / "bootstrap.sh", bootstrap)
    bootstrap.chmod(0o755)

    icon = APP_SRC / "LES.icns"
    if icon.exists():
        shutil.copy2(icon, resources / "LES.icns")
    else:
        print("[build] note: installers/macos/app/LES.icns missing — bundle ships without an icon")

    count = _copy_runtime(resources)
    print(f"[build] runtime files copied: {count}")

    if sign:
        # Ad-hoc signature ("-") so Gatekeeper at least sees a sealed bundle on
        # the build machine. Developer ID signing + notarization is a later step.
        rc = subprocess.run(
            ["codesign", "--force", "--deep", "--sign", "-", str(app)],
            check=False,
        ).returncode
        if rc != 0:
            print("[build] WARN: ad-hoc codesign failed", file=sys.stderr)
        else:
            print("[build] ad-hoc signed")

    return app


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
