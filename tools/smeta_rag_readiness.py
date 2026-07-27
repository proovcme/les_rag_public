#!/usr/bin/env python3
"""Fail-closed structural and live RRF gate for the dedicated smeta norm index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from qdrant_client import QdrantClient, models

from proxy.smeta_core.norm_browser import _rag_cards_many


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--base-path", type=Path, required=True)
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--report-path", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = args.base_path.with_name("les_smeta_norm_rag_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    client = QdrantClient(
        url=args.qdrant_url, timeout=60.0, check_compatibility=False
    )
    fingerprint = str(manifest.get("point_embedding_fingerprint") or "")
    total = int(client.count(args.collection, exact=True).count)
    dense = int(client.count(
        args.collection,
        count_filter=models.Filter(
            must=[models.HasVectorCondition(has_vector="dense")]
        ),
        exact=True,
    ).count)
    sparse = int(client.count(
        args.collection,
        count_filter=models.Filter(
            must=[models.HasVectorCondition(has_vector="bm25_sparse")]
        ),
        exact=True,
    ).count)
    compatible = int(client.count(
        args.collection,
        count_filter=models.Filter(must=[models.FieldCondition(
            key="embedding_fingerprint", match=models.MatchValue(value=fingerprint)
        )]),
        exact=True,
    ).count) if fingerprint else 0
    queries = [
        "прокладка кабеля в помещениях",
        "монтаж коробок электрических",
        "шпатлевка потолка",
    ]
    trace: dict = {}
    cards = _rag_cards_many(queries, limit=5, base_path=args.base_path, trace=trace)
    live_ready = bool(
        trace.get("status") == "ok"
        and trace.get("index_mode") == "hybrid"
        and all(cards.get(query) for query in queries)
    )
    expected = int(manifest.get("expected_points") or 0)
    ready = bool(
        manifest.get("schema") == "smeta_norm_rag_manifest_v2"
        and manifest.get("status") == "passed"
        and manifest.get("collection") == args.collection
        and expected > 0
        and total == dense == sparse == compatible == expected
        and live_ready
    )
    report = {
        "schema": "les.smeta.rag-readiness.v1",
        "status": "ready" if ready else "blocked",
        "collection": args.collection,
        "expected_points": expected,
        "points": total,
        "dense_points": dense,
        "sparse_points": sparse,
        "compatible_fingerprint_points": compatible,
        "live_rrf_ready": live_ready,
        "live_trace": trace,
        "query_card_counts": {query: len(cards.get(query) or []) for query in queries},
        "ready": ready,
    }
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.report_path.with_suffix(args.report_path.suffix + ".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(args.report_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
