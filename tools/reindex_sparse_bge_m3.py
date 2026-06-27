"""W2.4: BM25/IDF sparse-сайдкар рядом с основной коллекцией.

Строим ОТДЕЛЬНУЮ sparse-only коллекцию `{src}_sparse` с теми же point id
(vectors_config={}, только named sparse `bm25_sparse` с modifier=Idf). Для каждой
точки храним TF термов (токенизация+стемминг как в FTS); IDF Qdrant считает сам.
Ретрив фьюзит dense (основная коллекция) + sparse (сайдкар) по id. Основную
коллекцию не трогаем (нулевой риск, свап не нужен). Без нейромодели — индексация
за минуты на CPU (ноль нагрузки на Metal).

Идемпотентно (upsert по id). Запуск:
    uv run python tools/reindex_sparse_bge_m3.py [--batch 1000] [--limit N] [--recreate]
"""

from __future__ import annotations

import argparse
import os
import time

from qdrant_client import QdrantClient, models

from backend.inference.bm25_sparse import SPARSE_VECTOR_NAME as SPARSE_NAME, encode_bm25

_PAYLOAD_FIELDS = ["text", "dataset_id", "doc_id", "file_name"]


def ensure_sidecar(client: QdrantClient, dst: str, recreate: bool) -> None:
    if recreate and client.collection_exists(dst):
        client.delete_collection(dst)
        print(f"[sparse] пересоздаю {dst}")
    if client.collection_exists(dst):
        print(f"[sparse] сайдкар {dst} существует — дополняем")
        return
    client.create_collection(
        dst,
        vectors_config={},  # sparse-only
        sparse_vectors_config={SPARSE_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )
    try:
        client.create_payload_index(dst, field_name="dataset_id", field_schema=models.PayloadSchemaType.KEYWORD)
    except Exception:
        pass
    print(f"[sparse] создан BM25-сайдкар {dst} (modifier=Idf)")


def build(src: str, dst: str, *, batch: int, limit: int | None, recreate: bool) -> None:
    url = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
    client = QdrantClient(url=url, timeout=180.0)
    ensure_sidecar(client, dst, recreate)
    total = client.count(src, exact=False).count
    print(f"[sparse] {src} → {dst}, точек≈{total}, url={url}")

    done = empty = 0
    offset = None
    t0 = time.time()
    while True:
        points, offset = client.scroll(
            src, limit=batch, offset=offset, with_payload=_PAYLOAD_FIELDS, with_vectors=False,
        )
        if not points:
            break
        out = []
        for p in points:
            vec = encode_bm25((p.payload or {}).get("text", "") or "")
            if not vec:
                empty += 1
                continue
            out.append(models.PointStruct(
                id=p.id,
                vector={SPARSE_NAME: models.SparseVector(indices=list(vec.keys()), values=list(vec.values()))},
                payload={k: (p.payload or {}).get(k) for k in _PAYLOAD_FIELDS},
            ))
        if out:
            client.upsert(dst, points=out, wait=False)
        done += len(points)
        if done % (batch * 5) == 0 or offset is None:
            rate = done / max(0.1, time.time() - t0)
            eta = (total - done) / max(1.0, rate)
            print(f"[sparse] {done}/{total} ({rate:.0f}/с, ~{eta/60:.1f} мин, пустых {empty})", flush=True)
        if limit and done >= limit:
            print(f"[sparse] --limit {limit} достигнут")
            break
        if offset is None:
            break
    final = client.count(dst, exact=True).count
    print(f"[sparse] ГОТОВО: {done} обработано, в {dst} точек {final}, за {(time.time()-t0)/60:.1f} мин")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="BM25/IDF sparse-сайдкар для гибрида (W2.4).")
    ap.add_argument("--src", default=os.getenv("RAG_COLLECTION_NAME", "les_rag_qwen3_06b"))
    ap.add_argument("--dst", default="")
    ap.add_argument("--batch", type=int, default=1000)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--recreate", action="store_true", help="пересоздать сайдкар с нуля")
    args = ap.parse_args(argv)
    dst = args.dst or f"{args.src}_sparse"
    build(args.src, dst, batch=args.batch, limit=args.limit or None, recreate=args.recreate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
