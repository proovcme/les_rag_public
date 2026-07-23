#!/usr/bin/env python3
"""Atomically bind a stable Qdrant alias to a readiness-approved generation."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient, models


def _read_ready_report(path: Path, target: str) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError("readiness report must be an object")
    if report.get("ready") is not True or report.get("status") != "ready":
        raise ValueError("readiness report is not ready")
    if report.get("collection") != target:
        raise ValueError("readiness report belongs to another collection")
    if not isinstance(report.get("live_rrf"), dict) or report["live_rrf"].get("ready") is not True:
        raise ValueError("readiness report has no successful live RRF probe")
    if not isinstance(report.get("lexical"), dict) or report["lexical"].get("ready") is not True:
        raise ValueError("readiness report has no complete lexical projection")
    return report


def _count(client: QdrantClient, target: str, conditions: list[Any]) -> int:
    return int(
        client.count(
            target,
            count_filter=models.Filter(must=conditions) if conditions else None,
            exact=True,
        ).count
    )


def _verify_target_matches_report(
    client: QdrantClient,
    *,
    target: str,
    report: dict[str, Any],
    contract: dict[str, Any] | None,
) -> None:
    if not client.collection_exists(target):
        raise ValueError(f"target collection does not exist: {target}")
    expected = int(report.get("points") or 0)
    if expected <= 0 or _count(client, target, []) != expected:
        raise ValueError("target point count changed after readiness approval")
    if contract is None:
        return
    if report.get("contract_fingerprint") != contract.get("fingerprint"):
        raise ValueError("readiness report and source contract fingerprints differ")
    dense_name = str(contract.get("dense_vector_name") or "dense")
    sparse_name = str(contract.get("sparse_vector_name") or "bm25_sparse")
    point_fingerprint = str(contract.get("point_embedding_fingerprint") or "")
    checks = {
        "dense": [models.HasVectorCondition(has_vector=dense_name)],
        "sparse": [models.HasVectorCondition(has_vector=sparse_name)],
        "fingerprint": [
            models.FieldCondition(
                key="embedding_fingerprint",
                match=models.MatchValue(value=point_fingerprint),
            )
        ],
    }
    for label, conditions in checks.items():
        if _count(client, target, conditions) != expected:
            raise ValueError(f"target {label} coverage changed after readiness approval")


def alias_contract(source: dict[str, Any], *, target: str, alias: str) -> dict[str, Any]:
    """Create the runtime contract for an alias without changing point identity."""
    if source.get("collection") != target:
        raise ValueError("source contract belongs to another collection")
    result = dict(source)
    result["collection"] = alias
    result.pop("fingerprint", None)
    stable = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    result["fingerprint"] = hashlib.sha256(stable.encode("utf-8")).hexdigest()
    # Audit-only metadata is deliberately outside the compatibility fingerprint.
    result["physical_generation"] = target
    return result


def alias_manifest(source: dict[str, Any], *, target: str, alias: str) -> dict[str, Any]:
    """Move an approved navigation manifest from generation identity to alias identity."""
    if source.get("collection") != target:
        raise ValueError("source manifest belongs to another collection")
    if source.get("status") != "passed":
        raise ValueError("source manifest is not passed")
    result = dict(source)
    result["collection"] = alias
    result["physical_generation"] = target
    return result


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def mark_generation_job_activated(
    path: Path,
    *,
    alias: str,
    target: str,
) -> None:
    """Reconcile supervisor state after a successful direct activation."""
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    state.update(
        {
            "schema": "les.rag.generation-job.v1",
            "status": "activated",
            "stage": "complete",
            "alias": alias,
            "destination_collection": target,
            "failures": 0,
            "error": "",
            "updated_at": time.time(),
        }
    )
    _write_json_atomic(path, state)


def _restore_file(path: Path, previous: bytes | None) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".rollback")
    tmp.write_bytes(previous)
    tmp.replace(path)


def _restore_lexical_alias(index: Any, *, alias: str, previous_target: str | None) -> None:
    try:
        previous = index.status(previous_target) if previous_target else {}
        if previous_target and previous.get("ready") and int(previous.get("chunks") or 0) > 0:
            index.promote_collection(
                previous_target,
                alias,
                expected_count=int(previous["chunks"]),
            )
        else:
            index.clear_collection(alias)
    except Exception:
        index.clear_collection(alias)


def has_physical_alias_blocker(
    client: Any,
    *,
    alias: str,
    target: str,
    existing_aliases: dict[str, str],
) -> bool:
    """Distinguish a real collection from Qdrant's alias-resolved existence check."""
    return bool(
        alias != target
        and alias not in existing_aliases
        and client.collection_exists(alias)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alias", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--readiness-report", type=Path, required=True)
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--contract-source", type=Path)
    parser.add_argument("--contract-destination", type=Path)
    parser.add_argument("--manifest-source", type=Path)
    parser.add_argument("--manifest-destination", type=Path)
    parser.add_argument("--lexical-db", type=Path, required=True)
    parser.add_argument("--lexical-source-collection", required=True)
    parser.add_argument("--job-state-path", type=Path)
    parser.add_argument(
        "--drop-empty-alias-placeholder",
        action="store_true",
        help="delete a zero-point collection that blocks creation of the stable alias",
    )
    args = parser.parse_args()

    ready_report = _read_ready_report(args.readiness_report, args.target)
    if bool(args.contract_source) != bool(args.contract_destination):
        raise ValueError("contract source and destination must be supplied together")
    if bool(args.manifest_source) != bool(args.manifest_destination):
        raise ValueError("manifest source and destination must be supplied together")
    contract_payload = None
    contract_source_payload = None
    if args.contract_source:
        contract_source_payload = json.loads(args.contract_source.read_text(encoding="utf-8"))
        contract_payload = alias_contract(
            contract_source_payload,
            target=args.target,
            alias=args.alias,
        )
        contract_payload["generation_points"] = int(ready_report.get("points") or 0)
        contract_payload["generation_source_points"] = int(
            ready_report.get("source_points") or 0
        )
        contract_payload["generation_datasets"] = {
            str(item.get("dataset_id")): int(item.get("points") or 0)
            for item in ready_report.get("datasets", [])
            if isinstance(item, dict) and item.get("dataset_id")
        }
        contract_payload["readiness_report_sha256"] = hashlib.sha256(
            args.readiness_report.read_bytes()
        ).hexdigest()
    manifest_payload = None
    if args.manifest_source:
        source = json.loads(args.manifest_source.read_text(encoding="utf-8"))
        manifest_payload = alias_manifest(source, target=args.target, alias=args.alias)

    client = QdrantClient(url=args.qdrant_url, timeout=60.0, check_compatibility=False)
    _verify_target_matches_report(
        client,
        target=args.target,
        report=ready_report,
        contract=contract_source_payload,
    )
    existing = {item.alias_name: item.collection_name for item in client.get_aliases().aliases}
    if has_physical_alias_blocker(
        client,
        alias=args.alias,
        target=args.target,
        existing_aliases=existing,
    ):
        placeholder_points = int(client.count(args.alias, exact=True).count)
        if placeholder_points or not args.drop_empty_alias_placeholder:
            raise ValueError(
                "stable alias is blocked by a physical collection: "
                f"{args.alias} ({placeholder_points} points)"
            )
        client.delete_collection(args.alias)
    operations: list[models.AliasOperations] = []
    if args.alias in existing:
        operations.append(
            models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=args.alias))
        )
    operations.append(
        models.CreateAliasOperation(
            create_alias=models.CreateAlias(collection_name=args.target, alias_name=args.alias)
        )
    )
    file_snapshots = {
        path: path.read_bytes() if path.exists() else None
        for path in (args.contract_destination, args.manifest_destination)
        if path is not None
    }
    previous_target = existing.get(args.alias)
    lexical_index = None
    lexical_promoted = False
    try:
        if not client.update_collection_aliases(operations):
            raise RuntimeError("Qdrant rejected alias update")
        if contract_payload is not None and args.contract_destination:
            _write_json_atomic(args.contract_destination, contract_payload)
        if manifest_payload is not None and args.manifest_destination:
            _write_json_atomic(args.manifest_destination, manifest_payload)
        activated = {
            item.alias_name: item.collection_name for item in client.get_aliases().aliases
        }
        if activated.get(args.alias) != args.target:
            raise RuntimeError("alias postcondition failed")
        from proxy.services.lexical_index_service import LexicalIndex

        lexical_index = LexicalIndex(str(args.lexical_db))
        lexical = lexical_index.promote_collection(
            args.lexical_source_collection,
            args.alias,
            expected_count=int(ready_report.get("points") or 0),
        )
        lexical_promoted = True
        if not lexical.get("ready") or int(lexical.get("chunks") or 0) != int(
            ready_report.get("points") or 0
        ):
            raise RuntimeError("lexical alias postcondition failed")
    except Exception:
        try:
            current_aliases = {
                item.alias_name: item.collection_name for item in client.get_aliases().aliases
            }
            rollback: list[models.AliasOperations] = []
            if args.alias in current_aliases:
                rollback.append(
                    models.DeleteAliasOperation(
                        delete_alias=models.DeleteAlias(alias_name=args.alias)
                    )
                )
            if previous_target:
                rollback.append(
                    models.CreateAliasOperation(
                        create_alias=models.CreateAlias(
                            collection_name=previous_target,
                            alias_name=args.alias,
                        )
                    )
                )
            if rollback:
                client.update_collection_aliases(rollback)
        except Exception:
            pass
        if lexical_promoted and lexical_index is not None:
            _restore_lexical_alias(
                lexical_index,
                alias=args.alias,
                previous_target=previous_target,
            )
        for path, previous in file_snapshots.items():
            _restore_file(path, previous)
        raise

    print(json.dumps({"status": "activated", "alias": args.alias, "target": args.target}))
    if args.job_state_path:
        mark_generation_job_activated(
            args.job_state_path,
            alias=args.alias,
            target=args.target,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
