"""Build a Qdrant native dense+sparse sibling collection for hybrid RAG.

Safe by default: creates/fills a new collection, never mutates the current one
unless explicitly pointed at an already-created destination.
"""

from __future__ import annotations

import argparse
import os
import time
from typing import Any

from qdrant_client import QdrantClient, models

from backend.inference.bm25_sparse import SPARSE_VECTOR_NAME, encode_bm25
from backend.rag_config import rag_collection_name, rag_vector_size


PAYLOAD_INDEXES = ("dataset_id", "file_name")


def _dense_vector(point: Any) -> list[float] | None:
    vector = getattr(point, "vector", None)
    if isinstance(vector, list):
        return vector
    if isinstance(vector, dict):
        value = vector.get("") or vector.get("dense")
        return value if isinstance(value, list) else None
    return None


def ensure_destination(
    client: QdrantClient,
    dst: str,
    *,
    dense_name: str,
    sparse_name: str,
    recreate: bool,
) -> None:
    if recreate and client.collection_exists(dst):
        client.delete_collection(dst)
        print(f"[native] deleted existing {dst}")
    if not client.collection_exists(dst):
        client.create_collection(
            collection_name=dst,
            vectors_config={
                dense_name: models.VectorParams(size=rag_vector_size(), distance=models.Distance.COSINE)
            },
            sparse_vectors_config={
                sparse_name: models.SparseVectorParams(modifier=models.Modifier.IDF)
            },
        )
        print(f"[native] created {dst}")
    for field in PAYLOAD_INDEXES:
        try:
            client.create_payload_index(dst, field_name=field, field_schema=models.PayloadSchemaType.KEYWORD)
        except Exception as error:  # noqa: BLE001
            print(f"[native] payload index {field}: {type(error).__name__}: {error}")


def build(
    src: str,
    dst: str,
    *,
    dense_name: str,
    sparse_name: str,
    batch: int,
    limit: int | None,
    recreate: bool,
    dry_run: bool,
) -> dict[str, int]:
    url = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
    client = QdrantClient(url=url, timeout=180.0, check_compatibility=False)
    src_count = int(client.count(src, exact=False).count)
    print(f"[native] {src} -> {dst}; points≈{src_count}; dry_run={dry_run}; url={url}")
    if not dry_run:
        ensure_destination(client, dst, dense_name=dense_name, sparse_name=sparse_name, recreate=recreate)

    done = written = no_dense = no_sparse = 0
    offset = None
    started = time.time()
    while True:
        points, offset = client.scroll(
            src,
            limit=batch,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        if not points:
            break
        out: list[models.PointStruct] = []
        for point in points:
            done += 1
            dense = _dense_vector(point)
            if dense is None:
                no_dense += 1
                continue
            payload = dict(getattr(point, "payload", None) or {})
            sparse = encode_bm25(str(payload.get("text") or ""))
            vector: dict[str, Any] = {dense_name: dense}
            if sparse:
                vector[sparse_name] = models.SparseVector(
                    indices=list(sparse.keys()),
                    values=list(sparse.values()),
                )
            else:
                no_sparse += 1
            out.append(models.PointStruct(id=point.id, vector=vector, payload=payload))
        if out and not dry_run:
            client.upsert(dst, points=out, wait=True)
            written += len(out)
        elif out:
            written += len(out)
        if done % max(batch * 5, 1) == 0 or offset is None:
            rate = done / max(0.1, time.time() - started)
            print(f"[native] done={done}/{src_count} writable={written} no_dense={no_dense} no_sparse={no_sparse} rate={rate:.0f}/s")
        if limit and done >= limit:
            break
        if offset is None:
            break
    result = {"read": done, "writable": written, "no_dense": no_dense, "no_sparse": no_sparse}
    if not dry_run:
        result["dst_count_exact"] = int(client.count(dst, exact=True).count)
    print(f"[native] result={result}")
    return result


def verify(src: str, dst: str) -> dict[str, int | bool]:
    url = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
    client = QdrantClient(url=url, timeout=60.0, check_compatibility=False)
    src_count = int(client.count(src, exact=True).count)
    dst_count = int(client.count(dst, exact=True).count)
    info = client.get_collection(dst)
    payload_schema = getattr(info, "payload_schema", {}) or {}
    result = {
        "src_count": src_count,
        "dst_count": dst_count,
        "counts_match": src_count == dst_count,
        "has_dataset_id_index": "dataset_id" in payload_schema,
        "has_file_name_index": "file_name" in payload_schema,
    }
    print(f"[native] verify={result}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create/fill Qdrant named dense+sparse native hybrid collection.")
    parser.add_argument("--src", default=rag_collection_name())
    parser.add_argument("--dst", default="")
    parser.add_argument("--dense-name", default=os.getenv("RAG_DENSE_VECTOR_NAME", "dense"))
    parser.add_argument("--sparse-name", default=os.getenv("RAG_SPARSE_VECTOR_NAME", SPARSE_VECTOR_NAME))
    parser.add_argument("--batch", type=int, default=512)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--create", action="store_true", help="actually create/fill destination; default is dry-run")
    parser.add_argument("--recreate", action="store_true", help="delete destination before filling")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    dst = args.dst or f"{args.src}_native_v1"
    if args.verify_only:
        verify(args.src, dst)
        return 0
    build(
        args.src,
        dst,
        dense_name=args.dense_name,
        sparse_name=args.sparse_name,
        batch=args.batch,
        limit=args.limit or None,
        recreate=args.recreate,
        dry_run=not args.create,
    )
    if args.create:
        verify(args.src, dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
