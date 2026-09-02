#!/usr/bin/env python3
"""Build a sibling RAG for the active smeta SQLite and activate it after readiness."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient

from tools.activate_smeta_rag_generation import activate
from tools.build_smeta_norm_rag import build as build_rag_generation
from tools.smeta_generation_coordinator import run_readiness_gate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def qdrant_client() -> QdrantClient:
    return QdrantClient(
        url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
        timeout=60.0,
        check_compatibility=False,
    )


def rebuild_active_index(
    *,
    base_path: Path,
    alias: str,
    generations_root: Path,
    active_manifest_path: Path,
) -> dict[str, Any]:
    base_path = Path(base_path)
    if not base_path.is_file():
        raise FileNotFoundError(base_path)
    base_sha = _sha256(base_path)
    collection = f"{alias}_{base_sha[:20]}"
    generation_dir = Path(generations_root) / f"{base_sha[:16]}-rag"
    generation_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = generation_dir / "les_smeta_norm_rag_manifest.json"
    readiness_path = generation_dir / "les_smeta_norm_rag_readiness.json"
    build_status_path = base_path.with_name("les_smeta_norm_rag_build.json")
    rag = build_rag_generation(
        collection=collection,
        batch_size=16,
        recreate=False,
        manifest_path=manifest_path,
        build_status_path=build_status_path,
        base_path=base_path,
    )
    if rag.get("status") != "passed":
        raise RuntimeError("smeta RAG rebuild did not pass")
    report = run_readiness_gate(
        collection=collection,
        base_path=base_path,
        manifest_path=manifest_path,
        report_path=readiness_path,
    )
    if (
        report.get("ready") is not True
        or report.get("status") != "ready"
        or report.get("collection") != collection
        or str(report.get("base_sha256") or "") != base_sha
    ):
        raise RuntimeError("smeta RAG rebuild readiness is blocked")
    client = qdrant_client()
    try:
        activate(
            client=client,
            alias=alias,
            target=collection,
            report=report,
            manifest_source=manifest_path,
            manifest_destinations=[Path(active_manifest_path)],
        )
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    return {
        "status": "activated",
        "base_sha256": base_sha,
        "collection": collection,
        "generation_dir": str(generation_dir),
        "readiness": report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-path", type=Path, required=True)
    parser.add_argument("--alias", required=True)
    parser.add_argument("--generations-root", type=Path, required=True)
    parser.add_argument("--active-manifest-path", type=Path, required=True)
    args = parser.parse_args()
    result = rebuild_active_index(
        base_path=args.base_path,
        alias=args.alias,
        generations_root=args.generations_root,
        active_manifest_path=args.active_manifest_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
