"""Build the Tauri 2 desktop shell with a clean LES runtime resource tree."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from tools.build_release_artifacts import ROOT, iter_files


TAURI_ROOT = ROOT / "desktop" / "tauri"
SRC_TAURI = TAURI_ROOT / "src-tauri"
RESOURCES = SRC_TAURI / "resources"
DESKTOP_VERSION_MAJOR = 5
DESKTOP_VERSION_MINOR = 1


def desktop_semver(version: str) -> str:
    """Map the four-part LES runtime version to Tauri's three-part SemVer.

    LES uses ``0.milestone.feature.patch``. The desktop shell has its own
    stable product line and advances with the LES patch: ``5.1.patch``.
    Three-part versions remain accepted for standalone shell builds.
    """
    parts = version.split(".")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return version
    if len(parts) == 4 and all(part.isdigit() for part in parts):
        return f"{DESKTOP_VERSION_MAJOR}.{DESKTOP_VERSION_MINOR}.{int(parts[-1])}"
    raise ValueError(f"version must be numeric X.Y.Z or W.X.Y.Z, got {version!r}")


def npm_executable(platform: str | None = None) -> str:
    """Resolve npm without relying on POSIX executable semantics.

    The Windows Node installer exposes ``npm.cmd``.  ``subprocess`` does not
    reliably resolve the bare ``npm`` command through PATHEXT when shell=False,
    so a release build from an ordinary PowerShell otherwise fails after the
    expensive runtime staging step.
    """
    target = platform or os.sys.platform
    candidates = ("npm.cmd", "npm.exe", "npm") if target.startswith("win") else ("npm",)
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise RuntimeError("npm executable not found; install Node.js before building Tauri")


def stage_runtime() -> int:
    runtime = RESOURCES / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir(parents=True)
    count = 0
    for source in iter_files():
        relative = source.relative_to(ROOT)
        if relative.parts[:2] == ("desktop", "tauri"):
            continue
        target = runtime / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        count += 1
    shutil.copy2(ROOT / "installers/macos/app/bootstrap.sh", RESOURCES / "bootstrap.sh")
    (RESOURCES / "bootstrap.sh").chmod(0o755)
    return count


def set_version(version: str) -> None:
    config_path = SRC_TAURI / "tauri.conf.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["version"] = version
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    cargo_path = SRC_TAURI / "Cargo.toml"
    cargo = cargo_path.read_text(encoding="utf-8")
    lines = cargo.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("version = "):
            lines[index] = f'version = "{version}"'
            break
    cargo_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(version: str, bundles: str | None) -> Path:
    desktop_version = desktop_semver(version)
    set_version(desktop_version)
    if desktop_version != version:
        print(f"[tauri] LES {version} -> desktop {desktop_version}")
    count = stage_runtime()
    print(f"[tauri] staged clean runtime: {count} files")
    npm = npm_executable()
    subprocess.run([npm, "install"], cwd=TAURI_ROOT, check=True)
    command = [npm, "run", "tauri", "--", "build"]
    tauri_bundles = bundles
    if os.sys.platform == "darwin" and bundles:
        requested = [item.strip() for item in bundles.split(",") if item.strip()]
        # Sign the .app ourselves before creating the canonical DMG. A DMG made
        # by Tauri before ad-hoc signing contains a bundle Gatekeeper rejects.
        requested = [item for item in requested if item != "dmg"]
        if "app" not in requested:
            requested.append("app")
        tauri_bundles = ",".join(requested)
    if tauri_bundles:
        command.extend(["--bundles", tauri_bundles])
    env = dict(os.environ)
    env["PATH"] = f"{Path.home() / '.cargo/bin'}:{env.get('PATH', '')}"
    subprocess.run(command, cwd=TAURI_ROOT, env=env, check=True)
    bundle_root = SRC_TAURI / "target" / "release" / "bundle"
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    if os.sys.platform == "darwin":
        apps = sorted((bundle_root / "macos").glob("*.app"))
        if apps:
            subprocess.run(
                ["codesign", "--force", "--deep", "--sign", "-", str(apps[-1])],
                check=True,
            )
            target_app = dist / "LES.app"
            if target_app.exists():
                shutil.rmtree(target_app)
            shutil.copytree(apps[-1], target_app, symlinks=True)
            if bundles and "dmg" in bundles.split(","):
                from tools.build_macos_dmg import build_dmg

                build_dmg(version, sign=False)
    elif os.sys.platform.startswith("win"):
        installers = sorted((bundle_root / "nsis").glob("*.exe"))
        if installers:
            shutil.copy2(installers[-1], dist / "LES-Setup.exe")
    return bundle_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="5.1.0")
    parser.add_argument("--bundles", default=None, help="Tauri bundle list, e.g. app,dmg or nsis")
    args = parser.parse_args()
    print(build(args.version, args.bundles))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
