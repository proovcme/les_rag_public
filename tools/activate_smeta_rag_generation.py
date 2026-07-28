#!/usr/bin/env python3
"""Atomically activate a readiness-approved typed smeta RAG generation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient, models

from tools.activate_qdrant_generation import (
    _restore_file,
    _write_json_atomic,
    alias_manifest,
    has_physical_alias_blocker,
)


def read_smeta_ready_report(path: Path, target: str) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError("readiness report must be an object")
    if report.get("schema") != "les.smeta.rag-readiness.v1":
        raise ValueError("unsupported smeta readiness report")
    if report.get("ready") is not True or report.get("status") != "ready":
        raise ValueError("smeta readiness report is not ready")
    if report.get("collection") != target:
        raise ValueError("smeta readiness report belongs to another collection")
    if report.get("live_rrf_ready") is not True:
        raise ValueError("smeta readiness report has no successful live RRF probe")
    return report


def _count(client: QdrantClient, target: str, conditions: list[Any]) -> int:
    return int(
        client.count(
            target,
            count_filter=models.Filter(must=conditions) if conditions else None,
            exact=True,
        ).count
    )


def verify_smeta_target(
    client: QdrantClient,
    *,
    target: str,
    report: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    if not client.collection_exists(target):
        raise ValueError(f"target collection does not exist: {target}")
    if manifest.get("collection") != target or manifest.get("status") != "passed":
        raise ValueError("generation manifest does not approve the target")
    expected = int(report.get("expected_points") or 0)
    if expected <= 0 or int(manifest.get("expected_points") or 0) != expected:
        raise ValueError("readiness and manifest expected point counts differ")
    checks = {
        "points": [],
        "dense": [models.HasVectorCondition(has_vector="dense")],
        "sparse": [models.HasVectorCondition(has_vector="bm25_sparse")],
        "fingerprint": [
            models.FieldCondition(
                key="embedding_fingerprint",
                match=models.MatchValue(
                    value=str(manifest.get("point_embedding_fingerprint") or "")
                ),
            )
        ],
        "base": [
            models.FieldCondition(
                key="base_sha256",
                match=models.MatchValue(
                    value=str(manifest.get("base_sha256") or "")
                ),
            )
        ],
    }
    if str(report.get("base_sha256") or "") != str(manifest.get("base_sha256") or ""):
        raise ValueError("readiness and manifest base fingerprints differ")
    for label, conditions in checks.items():
        if _count(client, target, conditions) != expected:
            raise ValueError(
                f"target {label} coverage changed after readiness approval"
            )


def activate(
    *,
    client: QdrantClient,
    alias: str,
    target: str,
    report: dict[str, Any],
    manifest_source: Path,
    manifest_destinations: list[Path],
) -> None:
    if not manifest_destinations:
        raise ValueError("at least one active manifest destination is required")
    source = json.loads(manifest_source.read_text(encoding="utf-8"))
    verify_smeta_target(
        client,
        target=target,
        report=report,
        manifest=source,
    )
    active_manifest = alias_manifest(source, target=target, alias=alias)
    existing = {
        item.alias_name: item.collection_name
        for item in client.get_aliases().aliases
    }
    if has_physical_alias_blocker(
        client,
        alias=alias,
        target=target,
        existing_aliases=existing,
    ):
        raise ValueError(f"stable alias is blocked by a physical collection: {alias}")
    operations: list[models.AliasOperations] = []
    if alias in existing:
        operations.append(
            models.DeleteAliasOperation(
                delete_alias=models.DeleteAlias(alias_name=alias)
            )
        )
    operations.append(
        models.CreateAliasOperation(
            create_alias=models.CreateAlias(
                collection_name=target,
                alias_name=alias,
            )
        )
    )
    previous_target = existing.get(alias)
    previous_manifests = {
        path: path.read_bytes() if path.exists() else None
        for path in manifest_destinations
    }
    try:
        if not client.update_collection_aliases(operations):
            raise RuntimeError("Qdrant rejected smeta alias update")
        for destination in manifest_destinations:
            _write_json_atomic(destination, active_manifest)
        activated = {
            item.alias_name: item.collection_name
            for item in client.get_aliases().aliases
        }
        if activated.get(alias) != target:
            raise RuntimeError("smeta alias postcondition failed")
    except Exception:
        try:
            current = {
                item.alias_name: item.collection_name
                for item in client.get_aliases().aliases
            }
            rollback: list[models.AliasOperations] = []
            if alias in current:
                rollback.append(
                    models.DeleteAliasOperation(
                        delete_alias=models.DeleteAlias(alias_name=alias)
                    )
                )
            if previous_target:
                rollback.append(
                    models.CreateAliasOperation(
                        create_alias=models.CreateAlias(
                            collection_name=previous_target,
                            alias_name=alias,
                        )
                    )
                )
            if rollback:
                client.update_collection_aliases(rollback)
        finally:
            for destination, previous in previous_manifests.items():
                _restore_file(destination, previous)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alias", default="les_smeta_norm_cards")
    parser.add_argument("--target", required=True)
    parser.add_argument("--readiness-report", type=Path, required=True)
    parser.add_argument("--manifest-source", type=Path, required=True)
    parser.add_argument(
        "--manifest-destination",
        action="append",
        type=Path,
        required=True,
        help="active manifest destination; repeat for each runtime sharing the alias",
    )
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    args = parser.parse_args()
    report = read_smeta_ready_report(args.readiness_report, args.target)
    client = QdrantClient(
        url=args.qdrant_url,
        timeout=60.0,
        check_compatibility=False,
    )
    try:
        activate(
            client=client,
            alias=args.alias,
            target=args.target,
            report=report,
            manifest_source=args.manifest_source,
            manifest_destinations=args.manifest_destination,
        )
    finally:
        client.close()
    print(json.dumps({"status": "activated", "alias": args.alias, "target": args.target}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
