"""Build boxed LES release archives without local runtime data."""

from __future__ import annotations

import argparse
import fnmatch
import os
import tarfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"

EXCLUDE_PATTERNS = (
    ".git/*",
    ".venv/*",
    ".env",
    "*.env",
    "__pycache__/*",
    "*.pyc",
    ".pytest_cache/*",
    ".mypy_cache/*",
    ".DS_Store",
    "*/.DS_Store",
    ".qdrant-initialized",
    "*/.qdrant-initialized",
    ".claude/*",
    ".aider*",
    "node_modules/*",
    "frontend/cad_bim_viewer/node_modules/*",
    "data/*",
    "storage/*",
    "logs/*",
    "RAG_Content/*",
    "artifacts/*",
    "snapshots/*",
    "local_private_archive/*",
    "outputs/*",
    "legacy/data/*",
    "exporters/artifacts/*",
    "standalone/cad_bim_viewer/ifc-sample/*",
    "dist/*",
)


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def should_exclude(path: Path) -> bool:
    rel = _relative(path)
    if path.is_dir():
        rel = f"{rel}/"
    return any(fnmatch.fnmatch(rel, pattern) for pattern in EXCLUDE_PATTERNS)


def iter_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if should_exclude(path):
            if path.is_dir():
                continue
        if path.is_file() and not should_exclude(path):
            files.append(path)
    return files


def build_tar(name: str, files: list[Path]) -> Path:
    DIST.mkdir(exist_ok=True)
    target = DIST / f"{name}.tar.gz"
    with tarfile.open(target, "w:gz") as archive:
        for path in files:
            archive.add(path, arcname=f"{name}/{_relative(path)}")
    return target


def build_zip(name: str, files: list[Path]) -> Path:
    DIST.mkdir(exist_ok=True)
    target = DIST / f"{name}.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=f"{name}/{_relative(path)}")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build LES boxed release archives.")
    parser.add_argument(
        "--profile",
        choices=("mac-native", "linux-docker", "linux-systemd", "windows-docker", "windows-lite"),
        required=True,
    )
    parser.add_argument("--name", default=None, help="artifact base name")
    args = parser.parse_args(argv)

    files = iter_files()
    name = args.name or f"les-{args.profile}"
    target = build_zip(name, files) if args.profile.startswith("windows") else build_tar(name, files)
    print(os.fspath(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
