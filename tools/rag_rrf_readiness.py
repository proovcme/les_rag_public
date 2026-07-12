#!/usr/bin/env python3
"""Fail-closed readiness gate for activating a dense+sparse RRF collection."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient, models

from backend.inference.bm25_sparse import encode_bm25
from backend.qdrant_adapter import EmbedClient
from backend.rag_config import embedding_api_model, prepare_query_for_embedding
from tools.build_rag_contract_sibling import (
    resolve_indexed_datasets,
    verify_embedding_runtime_identity,
)


def select_compatible_embed_url(
    value: str,
    *,
    contract: dict[str, Any],
    verifier: Any = verify_embedding_runtime_identity,
) -> tuple[str, list[dict[str, str]]]:
    failures: list[dict[str, str]] = []
    for candidate in [item.strip() for item in value.split(",") if item.strip()]:
        try:
            verifier(candidate, contract=contract)
            return candidate, failures
        except Exception as exc:  # noqa: BLE001 - all candidates are reported
            failures.append({"url": candidate, "error": f"{type(exc).__name__}: {exc}"})
    return "", failures


def _count(client: QdrantClient, collection: str, conditions: list[Any]) -> int:
    return int(
        client.count(
            collection,
            count_filter=models.Filter(must=conditions) if conditions else None,
            exact=True,
        ).count
    )


def _dataset_condition(dataset_id: str) -> models.FieldCondition:
    return models.FieldCondition(
        key="dataset_id", match=models.MatchValue(value=dataset_id)
    )


def audit_rrf_readiness(
    *,
    client: QdrantClient,
    collection: str,
    contract: dict[str, Any],
    datasets: list[dict[str, str]],
    migration_report: dict[str, Any] | None = None,
    lexical_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dense_name = str(contract.get("dense_vector_name") or "dense")
    sparse_name = str(contract.get("sparse_vector_name") or "bm25_sparse")
    fingerprint = str(contract.get("point_embedding_fingerprint") or "")
    total = _count(client, collection, [])
    dense = _count(client, collection, [models.HasVectorCondition(has_vector=dense_name)])
    sparse = _count(client, collection, [models.HasVectorCondition(has_vector=sparse_name)])
    matching_fingerprint = _count(
        client,
        collection,
        [
            models.FieldCondition(
                key="embedding_fingerprint",
                match=models.MatchValue(value=fingerprint),
            )
        ],
    ) if fingerprint else 0
    legacy_table_smeta_points = _count(
        client,
        collection,
        [
            models.FieldCondition(
                key="domain",
                match=models.MatchValue(value="TABLE_SMETA"),
            )
        ],
    )

    dataset_reports: list[dict[str, Any]] = []
    for dataset in datasets:
        scoped = [_dataset_condition(dataset["id"])]
        scoped_total = _count(client, collection, scoped)
        scoped_dense = _count(
            client,
            collection,
            [*scoped, models.HasVectorCondition(has_vector=dense_name)],
        )
        scoped_sparse = _count(
            client,
            collection,
            [*scoped, models.HasVectorCondition(has_vector=sparse_name)],
        )
        scoped_fingerprint = _count(
            client,
            collection,
            [
                *scoped,
                models.FieldCondition(
                    key="embedding_fingerprint",
                    match=models.MatchValue(value=fingerprint),
                ),
            ],
        ) if fingerprint else 0
        dataset_reports.append(
            {
                "dataset_id": dataset["id"],
                "dataset": dataset["name"],
                "points": scoped_total,
                "dense_points": scoped_dense,
                "sparse_points": scoped_sparse,
                "compatible_fingerprint_points": scoped_fingerprint,
                "ready": bool(
                    scoped_total
                    and scoped_total == scoped_dense == scoped_sparse == scoped_fingerprint
                ),
            }
        )

    migrated_datasets = (
        migration_report.get("datasets", []) if isinstance(migration_report, dict) else []
    )
    allowed_exclusion_reasons = {
        "empty_sparse_after_tokenization",
        "sanitation_removed_all_text",
    }
    exclusion_accounting_ok = bool(migrated_datasets) and all(
        isinstance(item, dict)
        and int(item.get("source_points_read") or 0)
        == int(item.get("source_points_with_searchable_children") or 0)
        + int(item.get("source_points_excluded") or 0)
        and int(item.get("child_points_total") or 0)
        == int(item.get("destination_points") or 0)
        + int(item.get("excluded_child_points") or 0)
        and all(
            isinstance(exclusion, dict)
            and exclusion.get("reason") in allowed_exclusion_reasons
            and bool(exclusion.get("source_point_id"))
            and bool(exclusion.get("text_sha256"))
            for exclusion in item.get("exclusions", [])
        )
        for item in migrated_datasets
    )
    migration_complete = bool(
        migration_report
        and migration_report.get("status") == "completed"
        and float(migration_report.get("source_coverage") or 0.0) == 1.0
        and int(migration_report.get("source_points_read") or 0)
        == int(migration_report.get("source_points") or -1)
        and int(migration_report.get("destination_points") or 0) == total
        and int(migration_report.get("destination_points_accounted") or 0) == total
        and migration_report.get("destination_collection") == collection
        and len(migrated_datasets) == len(datasets)
        and all(
            isinstance(item, dict) and bool(item.get("source_identity_sha256"))
            for item in migrated_datasets
        )
        and exclusion_accounting_ok
    )
    schema_ok = bool(
        contract.get("schema") == "les.rag.index-contract.v2"
        and contract.get("collection") == collection
        and contract.get("qdrant_schema") == "named"
        and fingerprint
    )
    all_datasets_ready = bool(dataset_reports) and all(
        item["ready"] for item in dataset_reports
    )
    covered_dataset_points = sum(int(item["points"]) for item in dataset_reports)
    lexical_ready = bool(
        lexical_status
        and lexical_status.get("collection") == collection
        and lexical_status.get("ready") is True
        and lexical_status.get("stale") is False
        and int(lexical_status.get("chunks") or 0) == total
        and int(lexical_status.get("point_count") or 0) == total
        and int(lexical_status.get("indexed_count") or 0) == total
    )
    ready = bool(
        schema_ok
        and total > 0
        and total == dense == sparse == matching_fingerprint
        and all_datasets_ready
        and covered_dataset_points == total
        and migration_complete
        and legacy_table_smeta_points == 0
        and lexical_ready
    )
    return {
        "schema": "les.rag.rrf-readiness.v1",
        "generated_at": time.time(),
        "status": "ready" if ready else "blocked",
        "collection": collection,
        "contract_fingerprint": str(contract.get("fingerprint") or ""),
        "migration_report_sha256": hashlib.sha256(
            json.dumps(
                migration_report or {},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "contract_schema_ok": schema_ok,
        "points": total,
        "dense_points": dense,
        "sparse_points": sparse,
        "compatible_fingerprint_points": matching_fingerprint,
        "legacy_table_smeta_points": legacy_table_smeta_points,
        "lexical": {**(lexical_status or {}), "ready": lexical_ready},
        "migration_complete": migration_complete,
        "exclusion_accounting_ok": exclusion_accounting_ok,
        "source_points_excluded": int(
            (migration_report or {}).get("source_points_excluded") or 0
        ),
        "excluded_child_points": int(
            (migration_report or {}).get("excluded_child_points") or 0
        ),
        "source_points": int((migration_report or {}).get("source_points") or 0),
        "source_points_read": int((migration_report or {}).get("source_points_read") or 0),
        "datasets_total": len(dataset_reports),
        "datasets_ready": sum(item["ready"] for item in dataset_reports),
        "covered_dataset_points": covered_dataset_points,
        "datasets": dataset_reports,
        "dataset_failures": [item for item in dataset_reports if not item["ready"]],
        "ready": ready,
    }


def live_rrf_probe(
    *,
    client: QdrantClient,
    collection: str,
    datasets: list[dict[str, str]],
    dense_name: str,
    sparse_name: str,
    embed_url: str,
) -> dict[str, Any]:
    samples: list[tuple[dict[str, str], str]] = []
    failures: list[dict[str, str]] = []
    for dataset in datasets:
        points, _ = client.scroll(
            collection,
            scroll_filter=models.Filter(must=[_dataset_condition(dataset["id"])]),
            limit=1,
            with_payload=["text"],
            with_vectors=False,
        )
        text = str((points[0].payload or {}).get("text") or "").strip() if points else ""
        query = " ".join(text.split())[:320]
        if not query:
            failures.append({"dataset": dataset["name"], "reason": "empty_probe_text"})
        else:
            samples.append((dataset, query))

    embed = EmbedClient(embed_url, model=embedding_api_model())
    vectors = embed.encode_sync(
        [prepare_query_for_embedding(query) for _dataset, query in samples]
    )
    passed = 0
    details: list[dict[str, Any]] = []
    for (dataset, query), dense in zip(samples, vectors, strict=True):
        sparse = encode_bm25(query)
        if not sparse:
            failures.append({"dataset": dataset["name"], "reason": "empty_probe_sparse"})
            continue
        scope = models.Filter(must=[_dataset_condition(dataset["id"])])
        dense_points = client.query_points(
            collection,
            query=dense,
            using=dense_name,
            query_filter=scope,
            limit=1,
            with_payload=False,
        ).points
        sparse_query = models.SparseVector(
            indices=list(sparse.keys()), values=list(sparse.values())
        )
        sparse_points = client.query_points(
            collection,
            query=sparse_query,
            using=sparse_name,
            query_filter=scope,
            limit=1,
            with_payload=False,
        ).points
        rrf_points = client.query_points(
            collection,
            prefetch=[
                models.Prefetch(query=dense, using=dense_name, filter=scope, limit=8),
                models.Prefetch(query=sparse_query, using=sparse_name, filter=scope, limit=8),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=3,
            with_payload=False,
        ).points
        ready = bool(dense_points and sparse_points and rrf_points)
        details.append(
            {
                "dataset": dataset["name"],
                "dense_hits": len(dense_points),
                "sparse_hits": len(sparse_points),
                "rrf_hits": len(rrf_points),
                "ready": ready,
            }
        )
        if ready:
            passed += 1
        else:
            failures.append({"dataset": dataset["name"], "reason": "missing_live_channel"})
    return {
        "embed_url": embed_url,
        "datasets_total": len(datasets),
        "datasets_passed": passed,
        "failures": failures,
        "details": details,
        "ready": passed == len(datasets) and not failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--contract-path", type=Path, required=True)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--migration-report", type=Path, required=True)
    parser.add_argument("--lexical-db", type=Path, required=True)
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--embed-url", default="http://127.0.0.1:8080")
    parser.add_argument("--live-rrf", action="store_true")
    parser.add_argument("--report-path", type=Path)
    args = parser.parse_args()
    contract = json.loads(args.contract_path.read_text(encoding="utf-8"))
    migration_report = json.loads(args.migration_report.read_text(encoding="utf-8"))
    from proxy.services.lexical_index_service import LexicalIndex

    lexical_status = LexicalIndex(str(args.lexical_db)).status(args.collection)
    datasets = resolve_indexed_datasets(args.source_db)
    client = QdrantClient(
        url=args.qdrant_url, timeout=60.0, check_compatibility=False
    )
    report = audit_rrf_readiness(
        client=client,
        collection=args.collection,
        contract=contract,
        datasets=datasets,
        migration_report=migration_report,
        lexical_status=lexical_status,
    )
    if args.live_rrf and report["ready"]:
        compatible_url, endpoint_failures = select_compatible_embed_url(
            args.embed_url,
            contract=contract,
        )
        if compatible_url:
            live = live_rrf_probe(
                client=client,
                collection=args.collection,
                datasets=datasets,
                dense_name=str(contract.get("dense_vector_name") or "dense"),
                sparse_name=str(contract.get("sparse_vector_name") or "bm25_sparse"),
                embed_url=compatible_url,
            )
            live["endpoint_failures"] = endpoint_failures
        else:
            live = {
                "ready": False,
                "failures": [{"reason": "no_compatible_embedding_endpoint"}],
                "endpoint_failures": endpoint_failures,
            }
        report["live_rrf"] = live
        report["ready"] = bool(report["ready"] and live["ready"])
        report["status"] = "ready" if report["ready"] else "blocked"
    elif args.live_rrf:
        report["live_rrf"] = {"ready": False, "skipped": "structural_gate_blocked"}
    else:
        # Structural coverage alone is not an activation approval.  The
        # activation tool requires a live native-RRF probe for every dataset.
        report["live_rrf"] = {"ready": False, "skipped": "not_requested"}
    if args.report_path:
        args.report_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = args.report_path.with_suffix(args.report_path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(args.report_path)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
