"""Build a boxed ARTEL MVP hand-test release archive."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "products" / "artel"
DIST = ROOT / "dist"

INCLUDE_PATTERNS = (
    "README.md",
    "RUNBOOK_HAND_TEST.md",
    "LES_PRODUCT_NOTE.md",
    "app/**",
    "backend/**",
    "docs/**",
    "openapi/**",
    "skills/**",
)

EXCLUDE_PATTERNS = (
    ".git/**",
    ".github/**",
    ".DS_Store",
    "**/.DS_Store",
    "**/bin/**",
    "**/obj/**",
    "Dist/**",
    "node_modules/**",
    "BUILD.md",
    "MyVeras*/**",
    "MyVeras.*",
    "**/*.dll",
    "**/*.pdb",
    "**/*.user",
    "**/*.suo",
)

REQUIRED_FILES = (
    "README.md",
    "RUNBOOK_HAND_TEST.md",
    "app/index.html",
    "app/app.js",
    "app/styles.css",
    "backend/Agnostis.Api/Agnostis.Api.csproj",
    "backend/Agnostis.Api/Program.cs",
    "openapi/agnostis-mvp.yaml",
)


def rel(path: Path, source: Path = SOURCE) -> str:
    return path.relative_to(source).as_posix()


def _matches(patterns: tuple[str, ...], relative_path: str) -> bool:
    return any(fnmatch.fnmatch(relative_path, pattern) for pattern in patterns)


def is_included(path: Path, source: Path = SOURCE) -> bool:
    relative_path = rel(path, source)
    return _matches(INCLUDE_PATTERNS, relative_path) and not is_excluded(path, source)


def is_excluded(path: Path, source: Path = SOURCE) -> bool:
    relative_path = rel(path, source)
    return _matches(EXCLUDE_PATTERNS, relative_path)


def validate_source(source: Path = SOURCE) -> None:
    missing = [item for item in REQUIRED_FILES if not (source / item).is_file()]
    if missing:
        raise FileNotFoundError(f"ARTEL source is incomplete: {', '.join(missing)}")


def collect_files(source: Path = SOURCE) -> list[Path]:
    validate_source(source)
    files = [path for path in source.rglob("*") if path.is_file() and is_included(path, source)]
    return sorted(files, key=lambda item: rel(item, source))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_archive(source: Path, dist: Path, name: str) -> Path:
    files = collect_files(source)
    dist.mkdir(parents=True, exist_ok=True)
    target = dist / f"{name}.zip"
    manifest = {
        "product": "ARTEL",
        "artifact": f"{name}.zip",
        "built_at": datetime.now(timezone.utc).isoformat(),
        "source": "products/artel",
        "mode": "mvp-hand-test",
        "files": [rel(path, source) for path in files],
        "excluded": list(EXCLUDE_PATTERNS),
    }

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=f"{name}/{rel(path, source)}")
        archive.writestr(
            f"{name}/ARTEL_MANIFEST.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build ARTEL MVP hand-test release zip.")
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--dist", type=Path, default=DIST)
    parser.add_argument("--name", default="artel-mvp")
    args = parser.parse_args(argv)

    target = build_archive(args.source, args.dist, args.name)
    print(os.fspath(target))
    print(f"sha256={sha256(target)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
