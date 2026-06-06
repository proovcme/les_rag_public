"""Build a boxed ATLAS standalone release archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "standalone" / "cad_bim_viewer"
DEFAULT_DIST = ROOT / "dist"
DEFAULT_INSTALL_DOC = ROOT / "products" / "atlas" / "INSTALL.md"

EXCLUDED_DIRS = {"JSON", "ifc-sample", "__pycache__"}
EXCLUDED_NAMES = {".DS_Store"}
REQUIRED_FILES = (
    "index.html",
    "assets/index.js",
    "assets/index.css",
    "fragments/worker.mjs",
    "web-ifc/web-ifc.wasm",
    "web-ifc/web-ifc-mt.wasm",
    "web-ifc/web-ifc-node.wasm",
    "models/demo.cad_bim_graph.json",
    "serve.sh",
    "serve.ps1",
    "README.md",
)


def _rel(path: Path, source: Path) -> str:
    return path.relative_to(source).as_posix()


def is_excluded(path: Path, source: Path) -> bool:
    rel_parts = path.relative_to(source).parts
    return any(part in EXCLUDED_DIRS for part in rel_parts) or path.name in EXCLUDED_NAMES


def collect_files(source: Path) -> list[Path]:
    files: list[Path] = []
    for path in source.rglob("*"):
        if is_excluded(path, source):
            continue
        if path.is_file():
            files.append(path)
    return sorted(files, key=lambda item: _rel(item, source))


def validate_source(source: Path) -> None:
    missing = [rel for rel in REQUIRED_FILES if not (source / rel).is_file()]
    if missing:
        joined = ", ".join(missing)
        raise FileNotFoundError(f"ATLAS standalone source is incomplete: {joined}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_archive(source: Path, dist: Path, name: str, install_doc: Path = DEFAULT_INSTALL_DOC) -> Path:
    validate_source(source)
    files = collect_files(source)
    dist.mkdir(parents=True, exist_ok=True)
    target = dist / f"{name}.zip"

    manifest = {
        "product": "ATLAS",
        "artifact": f"{name}.zip",
        "built_at": datetime.now(timezone.utc).isoformat(),
        "source": "standalone/cad_bim_viewer",
        "files": [_rel(path, source) for path in files],
        "excluded": sorted(EXCLUDED_DIRS | EXCLUDED_NAMES),
    }

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=f"{name}/{_rel(path, source)}")
        if install_doc.is_file():
            archive.write(install_doc, arcname=f"{name}/INSTALL.md")
            manifest["files"].append("INSTALL.md")
        archive.writestr(
            f"{name}/ATLAS_MANIFEST.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )

    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build ATLAS standalone release zip.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--name", default="atlas-standalone")
    parser.add_argument("--install-doc", type=Path, default=DEFAULT_INSTALL_DOC)
    args = parser.parse_args(argv)

    target = build_archive(args.source, args.dist, args.name, args.install_doc)
    print(os.fspath(target))
    print(f"sha256={sha256(target)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
