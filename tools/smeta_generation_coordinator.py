#!/usr/bin/env python3
"""Build and atomically activate one matching smeta SQLite/RAG generation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient

from backend.runtime_paths import mutable_path
from tools.activate_smeta_rag_generation import activate_release
from tools.build_smeta_norm_rag import build as build_rag_generation
from tools.build_smeta_structured_base import build_structured_base
from tools.smeta_generation_lease import generation_lease


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


def run_readiness_gate(
    *,
    collection: str,
    base_path: Path,
    manifest_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "tools.smeta_rag_readiness",
        "--collection",
        collection,
        "--base-path",
        str(base_path),
        "--manifest-path",
        str(manifest_path),
        "--report-path",
        str(report_path),
        "--qdrant-url",
        os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
    ]
    completed = subprocess.run(command, check=False)
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("smeta RAG readiness did not produce a valid report") from exc
    if completed.returncode != 0 and report.get("ready") is True:
        raise RuntimeError("smeta RAG readiness process and report disagree")
    return report


def _publish_generation_unlocked(
    *,
    source: Path,
    active_base: Path,
    active_base_manifest: Path,
    active_integrity: Path,
    active_rag_manifest: Path,
    generations_root: Path,
    alias: str,
    minimum_norms: int,
) -> dict[str, Any]:
    """Keep the old pair active until the new SQLite and RAG both pass."""
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(source)
    source_sha = _sha256(source)
    generation_dir = Path(generations_root) / source_sha[:16]
    generation_dir.mkdir(parents=True, exist_ok=True)
    staged_base = generation_dir / "les_smeta_base.sqlite"
    staged_base_manifest = generation_dir / "les_smeta_base_manifest.json"
    staged_integrity = generation_dir / "les_smeta_base_integrity.json"
    staged_rag_manifest = generation_dir / "les_smeta_norm_rag_manifest.json"
    staged_rag_build = generation_dir / "les_smeta_norm_rag_build.json"
    readiness_path = generation_dir / "les_smeta_norm_rag_readiness.json"

    structured = build_structured_base(
        source=source,
        out=staged_base,
        manifest_out=staged_base_manifest,
        integrity_out=staged_integrity,
        minimum_norms=int(minimum_norms),
    )
    base_sha = _sha256(staged_base)
    declared_sha = str((structured.get("output") or {}).get("sha256") or "")
    if declared_sha != base_sha:
        raise RuntimeError("structured base manifest SHA does not match staged SQLite")
    collection = f"{alias}_{base_sha[:20]}"
    rag = build_rag_generation(
        collection=collection,
        batch_size=16,
        recreate=False,
        manifest_path=staged_rag_manifest,
        build_status_path=staged_rag_build,
        base_path=staged_base,
    )
    if rag.get("status") != "passed":
        raise RuntimeError("smeta RAG generation build did not pass")
    report = run_readiness_gate(
        collection=collection,
        base_path=staged_base,
        manifest_path=staged_rag_manifest,
        report_path=readiness_path,
    )
    if (
        report.get("ready") is not True
        or report.get("status") != "ready"
        or report.get("collection") != collection
        or str(report.get("base_sha256") or "") != base_sha
    ):
        raise RuntimeError("smeta RAG generation readiness is blocked")

    client = qdrant_client()
    try:
        activate_release(
            client=client,
            alias=alias,
            target=collection,
            report=report,
            rag_manifest_source=staged_rag_manifest,
            rag_manifest_destinations=[Path(active_rag_manifest)],
            artifact_pairs=[
                (staged_base, Path(active_base)),
                (staged_base_manifest, Path(active_base_manifest)),
                (staged_integrity, Path(active_integrity)),
            ],
        )
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    return {
        "status": "activated",
        "generation_id": source_sha[:16],
        "generation_dir": str(generation_dir),
        "collection": collection,
        "base_sha256": base_sha,
        "structured": structured,
        "rag": rag,
        "readiness": report,
    }


def publish_generation(
    *,
    source: Path,
    active_base: Path,
    active_base_manifest: Path,
    active_integrity: Path,
    active_rag_manifest: Path,
    generations_root: Path,
    alias: str,
    minimum_norms: int,
) -> dict[str, Any]:
    with generation_lease(generations_root, operation="publish-base-and-rag"):
        return _publish_generation_unlocked(
            source=source,
            active_base=active_base,
            active_base_manifest=active_base_manifest,
            active_integrity=active_integrity,
            active_rag_manifest=active_rag_manifest,
            generations_root=generations_root,
            alias=alias,
            minimum_norms=minimum_norms,
        )


def main(argv: list[str] | None = None) -> int:
    from proxy.smeta_core.base_registry import active_base

    parser = argparse.ArgumentParser(
        description="Build and activate one exact-SHA smeta SQLite/RAG generation"
    )
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args(argv)
    config = active_base()
    active = Path(str(config["base_path"]))
    result = publish_generation(
        source=args.source,
        active_base=active,
        active_base_manifest=Path(str(config["manifest_path"])),
        active_integrity=Path(str(config["integrity_path"])),
        active_rag_manifest=active.with_name("les_smeta_norm_rag_manifest.json"),
        generations_root=mutable_path("storage/smeta_generations"),
        alias=str(config.get("rag_collection") or "les_smeta_norm_cards"),
        minimum_norms=int(config.get("minimum_norms") or 1),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "activated" else 1


if __name__ == "__main__":
    raise SystemExit(main())
