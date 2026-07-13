"""Live semantic and latency probe for the configured LES cross-encoder."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

from backend.reranker import SentenceTransformerReranker


async def run(model: str) -> dict:
    os.environ["RERANK_MODEL"] = model
    chunks = [
        {
            "text": "В совещании КЖС участвовали Иванов, Петров и Сидоров.",
            "score": 0.2,
            "metadata": {"id": "relevant"},
        },
        {
            "text": "Поставка бетона запланирована на вторник.",
            "score": 0.9,
            "metadata": {"id": "noise"},
        },
        {
            "text": "Температура наружного воздуха минус 20 градусов.",
            "score": 0.8,
            "metadata": {"id": "noise2"},
        },
    ]
    reranker = SentenceTransformerReranker(model=model)
    timings: list[float] = []
    ranked = []
    for _ in range(2):
        started = time.perf_counter()
        ranked = await reranker.rerank("Кто участвовал в совещании КЖС?", chunks, top_k=3)
        timings.append(round(time.perf_counter() - started, 3))
    ids = [item.metadata["id"] for item in ranked]
    return {
        "model": model,
        "cold_seconds": timings[0],
        "warm_seconds": timings[1],
        "ranked": [
            {"id": item.metadata["id"], "score": round(item.score, 6)}
            for item in ranked
        ],
        "semantic_order_ok": ids[0] == "relevant",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3"))
    args = parser.parse_args()
    result = asyncio.run(run(args.model))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["semantic_order_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
