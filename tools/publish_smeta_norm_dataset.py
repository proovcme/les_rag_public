"""Publish typed estimate norm cards through the ordinary LES RAG contract.

The typed SQLite base is read-only.  This module intentionally keeps card rendering
independent from the protected estimate workflow; the CLI publication step is added
on top of the standard general-collection writer.
"""

from __future__ import annotations

import json
import argparse
import asyncio
import os
import sqlite3
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5


def _json_list(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def norm_cards(base_path: Path) -> list[dict[str, str]]:
    """Return deterministic searchable cards without mutating the typed base."""
    with sqlite3.connect(f"file:{Path(base_path).resolve().as_posix()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM norms ORDER BY norm_key").fetchall()
    cards: list[dict[str, str]] = []
    for norm in rows:
        steps = _json_list(norm["work_steps"])
        text = "\n".join(filter(None, (
            f"Шифр: {norm['display_code']}",
            f"Наименование работы: {norm['norm_name']}",
            f"Измеритель: {norm['norm_unit']}",
            f"Состав работ: {'; '.join(steps)}" if steps else "",
        )))
        cards.append({
            "norm_key": str(norm["norm_key"]),
            "norm_code": str(norm["display_code"]),
            "base_type": str(norm["base_type"]),
            "measure_unit": str(norm["norm_unit"]),
            "text": text,
        })
    return cards


def render_markdown(cards: list[dict[str, str]]) -> str:
    blocks = ["# Сметные нормы\n\nОбычная RAG-проекция типизированной нормативной базы."]
    for card in cards:
        blocks.append(f"## {card['norm_code']}\n\n{card['text']}")
    return "\n\n".join(blocks) + "\n"


def point_payload(
    card: dict[str, str],
    *,
    dataset_id: str,
    doc_id: str,
    chunk_ord: int,
) -> dict[str, object]:
    return {
        **card,
        "schema": "les.smeta-norm-rag-card.v1",
        "dataset_id": dataset_id,
        "doc_id": doc_id,
        "file_name": "smeta_norm_cards.v1",
        "source_role": "normative_reference",
        "chunk_ord": int(chunk_ord),
        "section_heading": card["norm_code"],
        "text": card["text"],
    }


async def publish(base_path: Path) -> dict[str, object]:
    """Upsert one standard named-vector/lexical point per typed norm card."""
    from qdrant_client import QdrantClient, models

    from backend.inference.bm25_sparse import SPARSE_VECTOR_NAME, encode_bm25
    from backend.qdrant_adapter import QdrantLlamaIndexAdapter
    from backend.rag_config import point_embedding_fingerprint
    from proxy.services.lexical_index_service import LexicalIndex

    adapter = QdrantLlamaIndexAdapter(
        qdrant_url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
        mlx_url=os.getenv("EMBED_URL", "http://127.0.0.1:11434"),
        embed_model_name=os.getenv("EMBED_MODEL", "bge-m3:latest"),
        content_dir=os.getenv("RAG_STORAGE_DIR", "storage/datasets"),
    )
    await adapter._ensure_collection()
    dataset_id = await adapter.create_dataset("SMETA_NORMS_Index")
    cards = norm_cards(base_path)
    stat = base_path.stat()
    doc_id, _, _ = adapter.db.add_document(
        dataset_id,
        "smeta_norm_cards.v1",
        file_mtime=stat.st_mtime,
        file_size=stat.st_size,
        source_path=str(base_path.resolve()),
    )
    client = QdrantClient(
        url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
        timeout=180.0,
        check_compatibility=False,
    )
    dataset_filter = models.Filter(must=[
        models.FieldCondition(key="dataset_id", match=models.MatchValue(value=dataset_id))
    ])
    client.delete(
        collection_name=adapter.collection_name,
        points_selector=models.FilterSelector(filter=dataset_filter),
        wait=True,
    )
    lexical = LexicalIndex()
    lexical.delete_dataset(adapter.collection_name, dataset_id=dataset_id)
    embed = getattr(adapter, "embed_parse", None) or adapter.embed
    fingerprint = point_embedding_fingerprint()
    batch_size = max(8, int(os.getenv("SMETA_NORM_GENERAL_RAG_BATCH", "64")))
    indexed = 0
    for start in range(0, len(cards), batch_size):
        batch = cards[start:start + batch_size]
        vectors = embed.encode_sync([card["text"] for card in batch])
        points = []
        lexical_rows = []
        for offset, (card, dense) in enumerate(zip(batch, vectors, strict=True)):
            chunk_ord = start + offset
            payload = point_payload(
                card,
                dataset_id=dataset_id,
                doc_id=doc_id,
                chunk_ord=chunk_ord,
            )
            payload["embedding_fingerprint"] = fingerprint
            sparse = encode_bm25(card["text"])
            point_id = str(uuid5(NAMESPACE_URL, f"les:general-smeta-norm:{card['norm_key']}"))
            points.append(models.PointStruct(
                id=point_id,
                vector={
                    "dense": dense,
                    SPARSE_VECTOR_NAME: models.SparseVector(
                        indices=list(sparse), values=list(sparse.values())
                    ),
                },
                payload=payload,
            ))
            lexical_rows.append({**payload, "point_id": point_id})
        client.upsert(adapter.collection_name, points=points, wait=True)
        lexical.upsert_chunks(adapter.collection_name, lexical_rows)
        indexed += len(points)
        if indexed == len(cards) or indexed % 1024 == 0:
            print(f"[smeta-norm-general-rag] {indexed}/{len(cards)}", flush=True)
    adapter.db.update_document_status(
        dataset_id, "smeta_norm_cards.v1", "INDEXED", indexed
    )
    adapter.db.update_dataset_status(dataset_id, "COMPLETED")
    return {
        "dataset_id": dataset_id,
        "norm_cards": len(cards),
        "parse": {"status": "completed", "indexed_chunks": indexed},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, default=None)
    args = parser.parse_args()
    if args.base is None:
        from proxy.smeta_core.base_registry import active_base

        args.base = Path(active_base()["base_path"])
    result = asyncio.run(publish(args.base))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if (result.get("parse") or {}).get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
