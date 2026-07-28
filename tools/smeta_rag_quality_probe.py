#!/usr/bin/env python3
"""Measure smeta dense/sparse/RRF behavior without declaring a norm correct."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient, models

from backend.inference.bm25_sparse import SPARSE_VECTOR_NAME, encode_bm25
from backend.qdrant_adapter import EmbedClient
from backend.rag_config import prepare_query_for_embedding
from proxy.smeta_core.norm_browser import _cards_by_norm_keys
from proxy.smeta_core.norm_browser import browse_norms_many


DEFAULT_QUERIES = [
    "монтаж блока аварийного питания светильника",
    "прокладка кабеля низковольтного внутри здания в гофрированной трубе",
    "крепление кабеля однолапковыми скобами",
    "монтаж огнестойкой ответвительной коробки открытой проводки",
    "демонтаж реечного подвесного потолка с сохранением реек",
    "повторный монтаж сохраненного реечного потолка",
    "устройство отверстий в потолке из гипсокартона",
    "грунтование потолка перед отделкой",
    "оклейка потолка стеклохолстом",
    "монтаж кабеля СКС категории 6 в лотке",
    "монтаж патч панели 24 порта",
    "установка информационной розетки RJ45",
]


def _keys(points: list[Any]) -> list[str]:
    return [
        str((point.payload or {}).get("norm_key") or "")
        for point in points
        if str((point.payload or {}).get("norm_key") or "")
    ]


def _compact(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "norm_key": card.get("norm_key"),
            "norm_code": card.get("norm_code"),
            "base_type": card.get("base_type"),
            "title": card.get("title"),
            "measure_unit": card.get("measure_unit"),
            "work_steps": list(card.get("work_steps") or [])[:5],
            "resource_preview": list(card.get("resource_preview") or [])[:8],
        }
        for card in cards
    ]


def _channel_query(
    client: QdrantClient,
    collection: str,
    *,
    dense: list[float],
    sparse: dict[int, float],
    limit: int,
) -> tuple[list[Any], list[Any], list[Any]]:
    dense_points = client.query_points(
        collection,
        query=dense,
        using="dense",
        limit=limit,
        with_payload=True,
    ).points
    sparse_vector = models.SparseVector(indices=list(sparse), values=list(sparse.values()))
    sparse_points = client.query_points(
        collection,
        query=sparse_vector,
        using=SPARSE_VECTOR_NAME,
        limit=limit,
        with_payload=True,
    ).points
    fused_points = client.query_points(
        collection,
        prefetch=[
            models.Prefetch(query=dense, using="dense", limit=max(24, limit * 3)),
            models.Prefetch(query=sparse_vector, using=SPARSE_VECTOR_NAME, limit=max(24, limit * 3)),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=limit,
        with_payload=True,
    ).points
    return dense_points, sparse_points, fused_points


def run_probe(
    *,
    collection: str,
    base_path: Path,
    queries: list[str],
    limit: int,
    qdrant_url: str,
    embed_url: str,
    embed_model: str,
) -> dict[str, Any]:
    client = QdrantClient(url=qdrant_url, timeout=60.0, check_compatibility=False)
    embed = EmbedClient(embed_url, model=embed_model)
    embed_started = time.perf_counter()
    vectors = embed.encode_sync([prepare_query_for_embedding(query) for query in queries])
    embedding_ms = round((time.perf_counter() - embed_started) * 1000, 2)
    probes: list[dict[str, Any]] = []
    retrieval_started = time.perf_counter()
    try:
        for query, dense in zip(queries, vectors, strict=True):
            sparse = encode_bm25(query)
            dense_points, sparse_points, fused_points = _channel_query(
                client,
                collection,
                dense=dense,
                sparse=sparse,
                limit=limit,
            )
            dense_keys = _keys(dense_points)
            sparse_keys = _keys(sparse_points)
            fused_keys = _keys(fused_points)
            cards = _cards_by_norm_keys(fused_keys, base_path=base_path)
            families = {str(card.get("base_type") or "") for card in cards if card.get("base_type")}
            fused_top = set(fused_keys[:5])
            probes.append(
                {
                    "query": query,
                    "dense_keys": dense_keys,
                    "sparse_keys": sparse_keys,
                    "rrf_keys": fused_keys,
                    "dense_sparse_overlap": len(set(dense_keys) & set(sparse_keys)),
                    "rrf_top5_from_dense": len(fused_top & set(dense_keys)),
                    "rrf_top5_from_sparse": len(fused_top & set(sparse_keys)),
                    "rrf_unique_families": len(families),
                    "rehydrated": len(cards),
                    "missing_cards": max(0, len(fused_keys) - len(cards)),
                    "rrf_cards": _compact(cards),
                }
            )
    finally:
        client.close()
    raw_retrieval_ms = round((time.perf_counter() - retrieval_started) * 1000, 2)
    visible_started = time.perf_counter()
    visible = browse_norms_many(queries, limit=limit, base_path=base_path, rerank=False)
    model_visible = [
        {
            "query": query,
            "backend": visible[query].get("backend"),
            "query_variants": (visible[query].get("retrieval_trace") or {}).get("query_variants") or [query],
            "cards": _compact(list(visible[query].get("cards") or [])),
        }
        for query in queries
    ]
    return {
        "schema": "les.smeta.rag-quality-probe.v1",
        "status": "measured",
        "note": "Diagnostic retrieval measurement; it does not declare any candidate professionally applicable.",
        "collection": collection,
        "generated_at": time.time(),
        "queries": len(queries),
        "limit": limit,
        "embedding_ms": embedding_ms,
        "retrieval_ms": raw_retrieval_ms,
        "model_visible_ms": round((time.perf_counter() - visible_started) * 1000, 2),
        "both_channels_in_rrf_top5": sum(
            bool(item["rrf_top5_from_dense"] and item["rrf_top5_from_sparse"])
            for item in probes
        ),
        "all_cards_rehydrated": all(item["missing_cards"] == 0 for item in probes),
        "probes": probes,
        "model_visible": model_visible,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--base-path", type=Path, required=True)
    parser.add_argument("--manifest-path", type=Path)
    parser.add_argument("--report-path", type=Path, required=True)
    parser.add_argument("--query", action="append", default=[])
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"))
    parser.add_argument("--embed-url", default=os.getenv("MLX_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--embed-model", default=os.getenv("LES_SMETA_NORM_EMBED_MODEL", "qwen3-embedding-0.6b"))
    args = parser.parse_args()
    os.environ["LES_SMETA_NORM_RAG_COLLECTION"] = args.collection
    if args.manifest_path:
        os.environ["LES_SMETA_NORM_RAG_MANIFEST"] = str(args.manifest_path)
    report = run_probe(
        collection=args.collection,
        base_path=args.base_path,
        queries=args.query or DEFAULT_QUERIES,
        limit=max(1, min(args.limit, 50)),
        qdrant_url=args.qdrant_url,
        embed_url=args.embed_url,
        embed_model=args.embed_model,
    )
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.report_path.with_suffix(args.report_path.suffix + ".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(args.report_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
