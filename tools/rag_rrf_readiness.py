#!/usr/bin/env python3
"""Fail-closed readiness gate for activating a dense+sparse RRF collection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient, models

from backend.inference.bm25_sparse import encode_bm25
from backend.qdrant_adapter import EmbedClient
from backend.rag_config import embedding_api_model, prepare_query_for_embedding
from tools.build_rag_contract_sibling import resolve_indexed_datasets


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

    migration_complete = bool(
        migration_report
        and migration_report.get("status") == "completed"
        and float(migration_report.get("source_coverage") or 0.0) == 1.0
        and int(migration_report.get("source_points_read") or 0)
        == int(migration_report.get("source_points") or -1)
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
    ready = bool(
        schema_ok
        and total > 0
        and total == dense == sparse == matching_fingerprint
        and all_datasets_ready
        and covered_dataset_points == total
        and migration_complete
    )
    return {
        "schema": "les.rag.rrf-readiness.v1",
        "status": "ready" if ready else "blocked",
        "collection": collection,
        "contract_schema_ok": schema_ok,
        "points": total,
        "dense_points": dense,
        "sparse_points": sparse,
        "compatible_fingerprint_points": matching_fingerprint,
        "migration_complete": migration_complete,
        "datasets_total": len(dataset_reports),
        "datasets_ready": sum(item["ready"] for item in dataset_reports),
        "covered_dataset_points": covered_dataset_points,
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
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--embed-url", default="http://127.0.0.1:8080")
    parser.add_argument("--live-rrf", action="store_true")
    parser.add_argument("--report-path", type=Path)
    args = parser.parse_args()
    contract = json.loads(args.contract_path.read_text(encoding="utf-8"))
    migration_report = json.loads(args.migration_report.read_text(encoding="utf-8"))
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
    )
    if args.live_rrf and report["ready"]:
        live = live_rrf_probe(
            client=client,
            collection=args.collection,
            datasets=datasets,
            dense_name=str(contract.get("dense_vector_name") or "dense"),
            sparse_name=str(contract.get("sparse_vector_name") or "bm25_sparse"),
            embed_url=args.embed_url,
        )
        report["live_rrf"] = live
        report["ready"] = bool(report["ready"] and live["ready"])
        report["status"] = "ready" if report["ready"] else "blocked"
    elif args.live_rrf:
        report["live_rrf"] = {"ready": False, "skipped": "structural_gate_blocked"}
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
