#!/usr/bin/env python3
"""Build a contract-clean sibling collection for selected RAG datasets.

The source collection is read-only.  Source text is sanitized, split to the
current embedding budget and embedded again with the active embedding service;
legacy vectors are never copied.  Point ids are deterministic, so rerunning a
dataset is idempotent.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Iterable


MIGRATION_NAMESPACE = uuid.UUID("e40ed045-32cd-48b2-a15d-e523c64921bc")
DEFAULT_DATASETS = (
    "BAI",
    "ПД_Инновационный центр",
    "NTD_FIRE_Index",
)


def resolve_datasets(db_path: Path, names: Iterable[str]) -> list[dict[str, str]]:
    requested = [str(name).strip() for name in names if str(name).strip()]
    if not requested:
        raise ValueError("at least one dataset name is required")
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in requested)
        rows = conn.execute(
            f"SELECT id, name FROM datasets WHERE name IN ({placeholders}) ORDER BY name",
            requested,
        ).fetchall()
    found = {str(row["name"]): str(row["id"]) for row in rows}
    missing = [name for name in requested if name not in found]
    if missing:
        raise ValueError(f"datasets not found: {', '.join(missing)}")
    return [{"id": found[name], "name": name} for name in requested]


def deterministic_point_id(
    *, source_collection: str, source_point_id: object, child_ord: int, text: str
) -> str:
    identity = f"{source_collection}\n{source_point_id}\n{child_ord}\n{text}"
    return str(uuid.uuid5(MIGRATION_NAMESPACE, identity))


def _configure_contract(args: argparse.Namespace) -> None:
    os.environ["RAG_COLLECTION_NAME"] = args.dst
    os.environ["RAG_INDEX_CONTRACT_PATH"] = str(args.contract_path)
    os.environ["RAG_QDRANT_SCHEMA"] = "named"
    os.environ.setdefault("RAG_DENSE_VECTOR_NAME", "dense")
    os.environ.setdefault("RAG_SPARSE_VECTOR_NAME", "bm25_sparse")


def _ensure_destination(client: Any, args: argparse.Namespace) -> bool:
    from backend.rag_config import rag_vector_size
    from qdrant_client import models

    exists = client.collection_exists(args.dst)
    if exists and not args.resume:
        raise RuntimeError(
            f"destination already exists: {args.dst}; use --resume or choose another name"
        )
    if not exists:
        if not args.create:
            raise RuntimeError("destination is missing; pass --create after reviewing --dry-run")
        client.create_collection(
            collection_name=args.dst,
            vectors_config={
                args.dense_name: models.VectorParams(
                    size=rag_vector_size(), distance=models.Distance.COSINE
                )
            },
            sparse_vectors_config={
                args.sparse_name: models.SparseVectorParams(modifier=models.Modifier.IDF)
            },
        )
    for field in ("dataset_id", "file_name", "migration_source_point_id"):
        client.create_payload_index(
            args.dst,
            field_name=field,
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
    return not exists


def _iter_source_points(
    client: Any,
    *,
    collection: str,
    dataset_id: str,
    page_size: int,
    limit: int,
):
    from qdrant_client import models

    offset = None
    read = 0
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="dataset_id", match=models.MatchValue(value=dataset_id)
                    )
                ]
            ),
            limit=min(page_size, limit - read) if limit else page_size,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            return
        for point in points:
            yield point
            read += 1
            if limit and read >= limit:
                return
        if offset is None:
            return


def _migrate_dataset(client: Any, embed: Any, args: argparse.Namespace, dataset: dict[str, str]) -> dict[str, Any]:
    from backend.inference.bm25_sparse import encode_bm25
    from backend.qdrant_adapter import (
        QdrantLlamaIndexAdapter,
        _content_hash,
        _embedding_cache_descriptor,
        _embedding_cache_fingerprint,
    )
    from backend.rag_config import chunking_config
    from qdrant_client import models

    descriptor = _embedding_cache_descriptor()
    fingerprint = _embedding_cache_fingerprint(descriptor)
    chunking = chunking_config()
    pending: list[dict[str, Any]] = []
    read = written = dropped = 0

    def flush() -> None:
        nonlocal written
        if not pending:
            return
        vectors = embed.encode_sync([item["text"] for item in pending])
        if len(vectors) != len(pending):
            raise RuntimeError(
                f"embedding count mismatch: got {len(vectors)}, expected {len(pending)}"
            )
        points = []
        for item, dense in zip(pending, vectors):
            payload = dict(item["payload"])
            payload.update(
                {
                    "text": item["text"],
                    "content_hash": _content_hash(item["text"]),
                    "embedding_fingerprint": fingerprint,
                    "embedding_backend": descriptor.get("backend", ""),
                    "embedding_model_id": descriptor.get("model_id", ""),
                    "embedding_profile": descriptor.get("profile", ""),
                    "embedding_coreml_model": descriptor.get("coreml_model", ""),
                    "embedding_coreml_seq_len": descriptor.get("coreml_seq_len", ""),
                    "embedding_coreml_compute_units": descriptor.get("coreml_compute_units", ""),
                    "embedding_coreml_fallback": descriptor.get("coreml_fallback", ""),
                    "migration_kind": "contract_reembed_v1",
                    "migration_source_collection": args.src,
                    "migration_source_point_id": str(item["source_point_id"]),
                }
            )
            sparse = encode_bm25(item["text"])
            point_vector: dict[str, Any] = {args.dense_name: dense}
            if sparse:
                point_vector[args.sparse_name] = models.SparseVector(
                    indices=list(sparse.keys()), values=list(sparse.values())
                )
            points.append(
                models.PointStruct(
                    id=deterministic_point_id(
                        source_collection=args.src,
                        source_point_id=item["source_point_id"],
                        child_ord=int(payload.get("migration_child_ord") or 0),
                        text=item["text"],
                    ),
                    vector=point_vector,
                    payload=payload,
                )
            )
        client.upsert(args.dst, points=points, wait=True)
        written += len(points)
        pending.clear()

    for point in _iter_source_points(
        client,
        collection=args.src,
        dataset_id=dataset["id"],
        page_size=args.page_size,
        limit=args.limit,
    ):
        read += 1
        source_payload = dict(getattr(point, "payload", None) or {})
        source_text = str(source_payload.get("text") or "")
        nodes = QdrantLlamaIndexAdapter._finalize_embedding_nodes(
            [
                {
                    "text": source_text,
                    "doc_id": str(source_payload.get("doc_id") or point.id),
                    "payload": source_payload,
                }
            ],
            chunking=chunking,
        )
        if not nodes:
            dropped += 1
            continue
        for child_ord, node in enumerate(nodes):
            payload = dict(node.get("payload") or {})
            payload["migration_child_ord"] = child_ord
            pending.append(
                {
                    "text": str(node["text"]),
                    "payload": payload,
                    "source_point_id": point.id,
                }
            )
            if len(pending) >= args.embed_batch:
                flush()
        if read % max(args.page_size, 1) == 0:
            print(
                json.dumps(
                    {
                        "dataset": dataset["name"],
                        "source_points_read": read,
                        "points_written": written,
                        "dropped": dropped,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    flush()
    return {
        "dataset_id": dataset["id"],
        "dataset": dataset["name"],
        "source_points_read": read,
        "points_written": written,
        "dropped": dropped,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", required=True)
    parser.add_argument("--dst", required=True)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--contract-path", type=Path, required=True)
    parser.add_argument("--dataset", action="append", dest="datasets")
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--embed-url", default="http://127.0.0.1:8080")
    parser.add_argument("--dense-name", default="dense")
    parser.add_argument("--sparse-name", default="bm25_sparse")
    parser.add_argument("--page-size", type=int, default=128)
    parser.add_argument("--embed-batch", type=int, default=16)
    parser.add_argument("--limit", type=int, default=0, help="source points per dataset; 0 = all")
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    args.datasets = args.datasets or list(DEFAULT_DATASETS)
    if args.create and args.dry_run:
        parser.error("--create and --dry-run are mutually exclusive")
    if not args.source_db.is_file():
        parser.error(f"source db not found: {args.source_db}")

    datasets = resolve_datasets(args.source_db, args.datasets)
    plan = {
        "schema": "les.rag.contract-sibling-plan.v1",
        "source_collection": args.src,
        "destination_collection": args.dst,
        "contract_path": str(args.contract_path),
        "datasets": datasets,
        "limit_per_dataset": args.limit,
        "mutates_source": False,
    }
    print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
    if args.dry_run or not args.create and not args.resume:
        return 0

    _configure_contract(args)
    from backend.qdrant_adapter import EmbedClient
    from backend.rag_config import embedding_api_model, index_contract_status, write_index_contract
    from qdrant_client import QdrantClient

    client = QdrantClient(url=args.qdrant_url, timeout=180.0, check_compatibility=False)
    created = _ensure_destination(client, args)
    if created:
        write_index_contract(replace=False)
    contract = index_contract_status()
    if not contract.get("compatible"):
        raise RuntimeError(f"destination contract is not compatible: {contract}")

    embed = EmbedClient(args.embed_url, model=embedding_api_model())
    results = [_migrate_dataset(client, embed, args, dataset) for dataset in datasets]
    report = {
        "schema": "les.rag.contract-sibling-result.v1",
        "status": "completed",
        "source_collection": args.src,
        "destination_collection": args.dst,
        "contract": contract,
        "datasets": results,
        "destination_points": int(client.count(args.dst, exact=True).count),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
