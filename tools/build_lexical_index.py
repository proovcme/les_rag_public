"""Build the SQLite FTS side index from Qdrant payload text."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import qdrant_client

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.rag_config import rag_collection_name, rag_meta_db_path
from proxy.services.lexical_index_service import LexicalIndex


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build LES lexical FTS index from Qdrant payloads.")
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"))
    parser.add_argument("--collection", default=rag_collection_name())
    parser.add_argument("--db", default=os.getenv("RAG_LEXICAL_DB_PATH") or rag_meta_db_path())
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--limit", type=int, default=0, help="Optional max points for a guarded partial build.")
    parser.add_argument("--rebuild", action="store_true", help="Clear this collection from FTS before indexing.")
    parser.add_argument("--resume", action="store_true", help="Resume from the last stored Qdrant scroll cursor.")
    return parser.parse_args(argv)


def _cursor(index: LexicalIndex, collection: str) -> str | None:
    with index.connect() as conn:
        row = conn.execute(
            "SELECT cursor_json FROM lexical_index_meta WHERE collection=?",
            (collection,),
        ).fetchone()
    if not row or not row["cursor_json"]:
        return None
    try:
        return json.loads(row["cursor_json"])
    except Exception:
        return row["cursor_json"]


def _row_from_point(point: Any) -> dict[str, Any] | None:
    payload = point.payload or {}
    text = str(payload.get("text") or "")
    if not text.strip():
        return None
    return {
        "point_id": str(point.id),
        "dataset_id": payload.get("dataset_id"),
        "doc_id": payload.get("doc_id"),
        "doc_name": payload.get("file_name") or payload.get("doc_name"),
        "text": text,
        "content_hash": payload.get("content_hash"),
        "chunk_ord": payload.get("chunk_ord"),
        "section_heading": payload.get("section_heading"),
        "parent_id": payload.get("parent_id"),
        "parent_ord": payload.get("parent_ord"),
        "child_ord": payload.get("child_ord"),
        "parent_heading": payload.get("parent_heading"),
        "context_before": payload.get("context_before"),
        "context_after": payload.get("context_after"),
        "context_kind": payload.get("context_kind"),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    index = LexicalIndex(args.db)
    if args.rebuild:
        index.clear_collection(args.collection)

    client = qdrant_client.QdrantClient(url=args.qdrant_url)
    point_count = int(client.count(args.collection, exact=True).count)
    offset = _cursor(index, args.collection) if args.resume else None
    indexed = 0

    while True:
        points, next_offset = client.scroll(
            collection_name=args.collection,
            limit=args.batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        rows = [row for point in points if (row := _row_from_point(point))]
        indexed += index.upsert_chunks(args.collection, rows)
        cursor_json = json.dumps(str(next_offset), ensure_ascii=False) if next_offset is not None else ""
        index.mark_collection(
            args.collection,
            point_count=point_count,
            indexed_count=indexed,
            cursor_json=cursor_json,
        )
        print(f"indexed={indexed} batch={len(rows)} total_points={point_count} next={next_offset}")
        if next_offset is None:
            break
        if args.limit and indexed >= args.limit:
            break
        offset = next_offset

    status = index.status(args.collection)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
