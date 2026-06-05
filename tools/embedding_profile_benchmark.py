"""Benchmark embedding models on existing RAG chunks without writing to Qdrant."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

from backend.rag_config import EMBEDDING_PROFILES, rag_collection_name


def _sample_texts(qdrant_url: str, collection: str, limit: int) -> list[str]:
    client = QdrantClient(url=qdrant_url)
    points, _ = client.scroll(
        collection_name=collection,
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )
    texts = []
    for point in points:
        payload = point.payload or {}
        text = str(payload.get("text") or "").strip()
        if text:
            texts.append(text)
    return texts


def _bench_model(model_id: str, texts: list[str], batch_size: int) -> dict[str, Any]:
    started = time.perf_counter()
    model = SentenceTransformer(model_id)
    load_sec = time.perf_counter() - started

    started = time.perf_counter()
    vectors = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
        batch_size=batch_size,
    )
    encode_sec = time.perf_counter() - started

    dim = int(vectors.shape[1]) if len(vectors.shape) > 1 else len(vectors[0])
    return {
        "model": model_id,
        "texts": len(texts),
        "dim": dim,
        "batch_size": batch_size,
        "load_sec": round(load_sec, 3),
        "encode_sec": round(encode_sec, 3),
        "sec_per_chunk": round(encode_sec / max(1, len(texts)), 4),
        "chunks_per_sec": round(len(texts) / encode_sec, 3) if encode_sec else 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--collection", default=rag_collection_name())
    parser.add_argument("--limit", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument(
        "--models",
        nargs="+",
        default=[EMBEDDING_PROFILES["legacy"].model, EMBEDDING_PROFILES["qwen"].model],
    )
    args = parser.parse_args()

    texts = _sample_texts(args.qdrant_url, args.collection, args.limit)
    if not texts:
        raise SystemExit(f"No texts found in collection {args.collection}")

    results = [_bench_model(model, texts, args.batch_size) for model in args.models]
    print(json.dumps({"collection": args.collection, "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
