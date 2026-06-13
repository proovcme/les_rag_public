"""W2.4: гибридная коллекция (dense Qwen + BGE-M3 sparse) миграцией.

Qdrant 1.18 НЕ умеет добавлять sparse-вектор к существующей коллекции, поэтому
создаём новую `{src}_hybrid` с безымянным dense (как у источника) + named sparse
`bge_m3_sparse` и копируем точки: dense ПЕРЕИСПОЛЬЗУЕМ из источника (не
перембеддим — он даёт 16/16), sparse считаем из payload['text'] через BGE-M3.
Старая коллекция остаётся нетронутой (бэкап до свапа RAG_COLLECTION_NAME).

Идемпотентно по точкам (upsert по id). При падении — перезапуск с --resume-offset
или просто заново (перезапишет).

Запуск:  uv run python tools/reindex_sparse_bge_m3.py [--batch 24] [--limit N]
"""

from __future__ import annotations

import argparse
import os
import time

from qdrant_client import QdrantClient, models

from backend.inference.sparse_embed import SPARSE_VECTOR_NAME as SPARSE_NAME, encode_sparse


def ensure_target(client: QdrantClient, src: str, dst: str) -> None:
    src_info = client.get_collection(src)
    dense = src_info.config.params.vectors  # безымянный VectorParams
    if client.collection_exists(dst):
        print(f"[mig] целевая {dst} уже существует — дополняем")
        return
    client.create_collection(
        dst,
        vectors_config=models.VectorParams(size=dense.size, distance=dense.distance),
        sparse_vectors_config={SPARSE_NAME: models.SparseVectorParams()},
    )
    print(f"[mig] создана {dst}: dense {dense.size}/{dense.distance} + sparse '{SPARSE_NAME}'")


def migrate(src: str, dst: str, *, batch: int, limit: int | None) -> None:
    url = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
    client = QdrantClient(url=url, timeout=180.0)
    ensure_target(client, src, dst)

    total = client.count(src, exact=False).count
    print(f"[mig] {src} → {dst}, точек≈{total}, url={url}")

    done = 0
    empty = 0
    offset = None
    t0 = time.time()
    while True:
        points, offset = client.scroll(
            src, limit=batch, offset=offset, with_payload=True, with_vectors=True,
        )
        if not points:
            break
        texts = [(p.payload or {}).get("text", "") or "" for p in points]
        sparse_vecs = encode_sparse(texts, batch_size=batch)
        out = []
        for p, sv in zip(points, sparse_vecs):
            dense = p.vector if isinstance(p.vector, list) else (p.vector or {}).get("")
            if dense is None:
                continue
            vec: dict = {"": dense}
            if sv:
                vec[SPARSE_NAME] = models.SparseVector(indices=list(sv.keys()), values=list(sv.values()))
            else:
                empty += 1
            out.append(models.PointStruct(id=p.id, vector=vec, payload=p.payload))
        if out:
            client.upsert(dst, points=out, wait=False)
        done += len(points)
        if done % (batch * 20) == 0 or offset is None:
            rate = done / max(0.1, time.time() - t0)
            eta = (total - done) / max(1.0, rate)
            print(f"[mig] {done}/{total} ({rate:.0f}/с, ~{eta/60:.1f} мин, sparse-пустых {empty})", flush=True)
        if limit and done >= limit:
            print(f"[mig] --limit {limit} достигнут")
            break
        if offset is None:
            break
    final = client.count(dst, exact=True).count
    print(f"[mig] ГОТОВО: {done} обработано, в {dst} точек {final}, за {(time.time()-t0)/60:.1f} мин")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Миграция в гибридную dense+sparse коллекцию (W2.4).")
    ap.add_argument("--src", default=os.getenv("RAG_COLLECTION_NAME", "les_rag_qwen3_06b"))
    ap.add_argument("--dst", default="")
    ap.add_argument("--batch", type=int, default=24)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)
    dst = args.dst or f"{args.src}_hybrid"
    migrate(args.src, dst, batch=args.batch, limit=args.limit or None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
