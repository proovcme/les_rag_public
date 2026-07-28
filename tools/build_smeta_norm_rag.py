"""Build a dedicated hybrid Qdrant index over trusted typed GESN norm cards.

SQLite remains the source of truth. Qdrant stores only searchable projections and
norm identity; every retrieval result is rehydrated from SQLite before the model
sees it. The command targets one small sibling collection and never mutates the
general LES RAG collection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient, models

from backend.inference.bm25_sparse import SPARSE_VECTOR_NAME, encode_bm25
from backend.qdrant_adapter import EmbedClient
from backend.rag_config import point_embedding_fingerprint, rag_vector_size
from proxy.smeta_core.base_registry import active_base
from proxy.smeta_core.integrity import normative_base_integrity


def _json_list(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except Exception:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _rows(base_path: Path) -> list[dict[str, str]]:
    conn = sqlite3.connect(base_path)
    conn.row_factory = sqlite3.Row
    try:
        norms = conn.execute("SELECT * FROM norms ORDER BY norm_key").fetchall()
        output = []
        for norm in norms:
            resources = conn.execute(
                "SELECT resource_name FROM resources WHERE parent_norm_id=? "
                "ORDER BY kind, resource_code LIMIT 80",
                (norm["norm_id"],),
            ).fetchall()
            steps = _json_list(norm["work_steps"])
            resource_names = [
                str(row["resource_name"] or "")
                for row in resources
                if str(row["resource_name"] or "").strip()
            ]
            # Retrieval represents the operation described by the norm. Resource names
            # remain payload diagnostics; putting dozens of incidental machines and
            # materials into the embedding made unrelated heavy norms look relevant.
            text = "\n".join(filter(None, [
                f"Шифр: {norm['display_code']}",
                f"Наименование работы: {norm['norm_name']}",
                f"Измеритель: {norm['norm_unit']}",
                f"Состав работ: {'; '.join(steps)}" if steps else "",
            ]))
            output.append({
                "norm_key": str(norm["norm_key"]),
                "norm_code": str(norm["display_code"]),
                "base_type": str(norm["base_type"]),
                "measure_unit": str(norm["norm_unit"]),
                "text": text,
                "resource_text": "; ".join(resource_names),
            })
        return output
    finally:
        conn.close()


def _dense_count(client: QdrantClient, collection: str) -> int:
    return int(client.count(
        collection,
        count_filter=models.Filter(must=[models.HasVectorCondition(has_vector="dense")]),
        exact=True,
    ).count)


def _sparse_count(client: QdrantClient, collection: str) -> int:
    return int(client.count(
        collection,
        count_filter=models.Filter(
            must=[models.HasVectorCondition(has_vector=SPARSE_VECTOR_NAME)]
        ),
        exact=True,
    ).count)


def _missing_dense_keys(client: QdrantClient, collection: str) -> set[str]:
    keys: set[str] = set()
    offset = None
    missing_filter = models.Filter(must_not=[models.HasVectorCondition(has_vector="dense")])
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            scroll_filter=missing_filter,
            limit=1000,
            offset=offset,
            with_payload=["norm_key"],
            with_vectors=False,
        )
        keys.update(
            str((point.payload or {}).get("norm_key") or "")
            for point in points
            if str((point.payload or {}).get("norm_key") or "")
        )
        if offset is None:
            break
    return keys


def _complete_keys(
    client: QdrantClient,
    collection: str,
    *,
    base_sha256: str,
    embedding_fingerprint: str,
) -> set[str]:
    """Return resumable points that already match this exact projection."""
    keys: set[str] = set()
    offset = None
    complete_filter = models.Filter(
        must=[
            models.HasVectorCondition(has_vector="dense"),
            models.HasVectorCondition(has_vector=SPARSE_VECTOR_NAME),
            models.FieldCondition(
                key="base_sha256",
                match=models.MatchValue(value=base_sha256),
            ),
            models.FieldCondition(
                key="embedding_fingerprint",
                match=models.MatchValue(value=embedding_fingerprint),
            ),
        ]
    )
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            scroll_filter=complete_filter,
            limit=1000,
            offset=offset,
            with_payload=["norm_key"],
            with_vectors=False,
        )
        keys.update(
            str((point.payload or {}).get("norm_key") or "")
            for point in points
            if str((point.payload or {}).get("norm_key") or "")
        )
        if offset is None:
            return keys


def _write_manifest(target: Path, result: dict[str, object]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(target)


def _write_build_status(target: Path, result: dict[str, object]) -> None:
    """Publish sibling-build progress without replacing the active manifest."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)


def build(
    *,
    collection: str,
    batch_size: int,
    recreate: bool,
    sparse_only: bool = False,
    dense_only: bool = False,
    local_mps: bool = False,
    local_batch_size: int = 32,
    replace_dense: bool = False,
    manifest_path: Path | None = None,
    build_status_path: Path | None = None,
) -> dict[str, object]:
    config = active_base()
    base_path = Path(config["base_path"])
    integrity = normative_base_integrity(base_path=base_path)
    # Qdrant is a navigation projection, never a pricing source. Missing original
    # provenance keeps the resulting estimate draft/partial, but must not hide a
    # structurally valid norm catalog from the model. Every hit is rehydrated from
    # SQLite before it is exposed or calculated.
    if not integrity.get("trusted_for_navigation"):
        raise RuntimeError(
            f"normative base is not trusted for navigation: {integrity.get('navigation_reasons')}"
        )
    all_rows = _rows(base_path)
    rows = all_rows
    manifest_path = manifest_path or base_path.with_name("les_smeta_norm_rag_manifest.json")
    build_status_path = build_status_path or base_path.with_name("les_smeta_norm_rag_build.json")
    base_sha = hashlib.sha256(base_path.read_bytes()).hexdigest()
    client = QdrantClient(
        url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"), timeout=180.0, check_compatibility=False
    )
    if sparse_only and dense_only:
        raise ValueError("sparse_only and dense_only are mutually exclusive")
    if replace_dense and not dense_only:
        raise ValueError("replace_dense requires dense_only")
    if recreate and client.collection_exists(collection):
        client.delete_collection(collection)
    if not client.collection_exists(collection):
        client.create_collection(
            collection_name=collection,
            vectors_config={"dense": models.VectorParams(size=rag_vector_size(), distance=models.Distance.COSINE)},
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)
            },
        )
    for field in (
        "norm_key",
        "norm_code",
        "base_type",
        "measure_unit",
        "base_sha256",
        "embedding_fingerprint",
    ):
        client.create_payload_index(collection, field, models.PayloadSchemaType.KEYWORD)
    embed_model = (
        os.getenv("LES_SMETA_NORM_EMBED_MODEL", "").strip()
        or str(config.get("rag_embedding_model") or "qwen3-embedding-0.6b")
    )
    embedding_backend = (
        "sentence_transformers_mps"
        if local_mps
        else os.getenv("EMBED_BACKEND", "sentence_transformers").strip().lower()
    )
    if dense_only:
        if replace_dense:
            dense_start = 0
            print(f"[smeta-norm-rag] dense full replacement: points={len(rows)}")
        else:
            missing_keys = _missing_dense_keys(client, collection)
            rows = [row for row in rows if row["norm_key"] in missing_keys]
            dense_start = len(all_rows) - len(rows)
            print(f"[smeta-norm-rag] dense resume: missing={len(rows)}")
    else:
        dense_start = 0
    if local_mps and not sparse_only:
        from sentence_transformers import SentenceTransformer
        from backend.rag_config import embed_seq_len

        local_embed = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")
        # Match the runtime Core ML query encoder. Without this cap the HF model
        # pads/attends far beyond the static 512-token contract and dense rebuild
        # becomes needlessly slow while producing a subtly different projection.
        local_embed.max_seq_length = embed_seq_len()
        embed = None
    else:
        local_embed = None
        embed = None if sparse_only else EmbedClient(
            os.getenv("MLX_URL", "http://127.0.0.1:8080"), model=embed_model
        )
    total_expected = len(all_rows)
    completed_start = 0
    if not recreate and not sparse_only and not dense_only:
        complete_keys = _complete_keys(
            client,
            collection,
            base_sha256=base_sha,
            embedding_fingerprint=point_embedding_fingerprint(),
        )
        rows = [row for row in rows if row["norm_key"] not in complete_keys]
        completed_start = total_expected - len(rows)
        print(f"[smeta-norm-rag] hybrid resume: complete={completed_start}, missing={len(rows)}")
    build_status = {
        "schema": "smeta_norm_rag_build_v1",
        "status": "building",
        "collection": collection,
        "expected_points": total_expected,
        "points": int(client.count(collection, exact=True).count),
        "dense_points": _dense_count(client, collection),
        "sparse_points": _sparse_count(client, collection),
        "embedding_model": embed_model,
        "embedding_backend": embedding_backend,
        "started_at": time.time(),
        "updated_at": time.time(),
    }
    _write_build_status(build_status_path, build_status)
    for offset in range(0, len(rows), max(1, batch_size)):
        batch = rows[offset : offset + max(1, batch_size)]
        if sparse_only:
            vectors = [None] * len(batch)
        elif local_embed is not None:
            vectors = local_embed.encode(
                [row["text"] for row in batch],
                normalize_embeddings=True,
                show_progress_bar=False,
                batch_size=max(1, local_batch_size),
            ).tolist()
        else:
            assert embed is not None
            vectors = embed.encode_sync([row["text"] for row in batch])
        if dense_only:
            client.update_vectors(
                collection_name=collection,
                points=[
                    models.PointVectors(
                        id=str(uuid5(NAMESPACE_URL, f"les:smeta:norm:{row['norm_key']}")),
                        vector={"dense": dense},
                    )
                    for row, dense in zip(batch, vectors, strict=True)
                ],
                wait=True,
            )
            dense_points = dense_start + offset + len(batch)
            progress = {
                "schema": "smeta_norm_rag_manifest_v1",
                "collection": collection,
                "points": int(client.count(collection, exact=True).count),
                "dense_points": dense_points,
                "expected_points": total_expected,
                "base_path": str(base_path),
                "base_sha256": base_sha,
                "embedding_model": embed_model,
                "embedding_backend": embedding_backend,
                "embedding_space_id": "",
                "embedding_space_verified": False,
                "index_mode": "hybrid" if dense_points == total_expected else "building_dense",
                # Sparse coverage stays complete and queryable while dense is resumed.
                "status": "passed",
                "updated_at": time.time(),
            }
            _write_manifest(manifest_path, progress)
            _write_build_status(
                build_status_path,
                {
                    **build_status,
                    "points": int(client.count(collection, exact=True).count),
                    "dense_points": dense_points,
                    "sparse_points": _sparse_count(client, collection),
                    "updated_at": time.time(),
                },
            )
            print(f"[smeta-norm-rag] dense {dense_points}/{total_expected}")
            continue
        points = []
        for row, dense in zip(batch, vectors, strict=True):
            sparse = encode_bm25(row["text"])
            vector = {
                SPARSE_VECTOR_NAME: models.SparseVector(
                    indices=list(sparse), values=list(sparse.values())
                ),
            }
            if dense is not None:
                vector["dense"] = dense
            points.append(models.PointStruct(
                id=str(uuid5(NAMESPACE_URL, f"les:smeta:norm:{row['norm_key']}")),
                vector=vector,
                payload={
                    **row,
                    "schema": "smeta_norm_card_v2",
                    "base_sha256": base_sha,
                    "embedding_model": embed_model,
                    "embedding_backend": embedding_backend,
                    "embedding_fingerprint": point_embedding_fingerprint(),
                },
            ))
        client.upsert(collection, points=points, wait=True)
        completed = completed_start + offset + len(batch)
        if completed == total_expected or completed % max(256, batch_size) == 0:
            _write_build_status(
                build_status_path,
                {
                    **build_status,
                    "points": int(client.count(collection, exact=True).count),
                    "dense_points": _dense_count(client, collection),
                    "sparse_points": _sparse_count(client, collection),
                    "updated_at": time.time(),
                },
            )
        print(f"[smeta-norm-rag] {completed}/{total_expected}")
    count = int(client.count(collection, exact=True).count)
    dense_points = _dense_count(client, collection)
    sparse_points = _sparse_count(client, collection)
    result = {
        "schema": "smeta_norm_rag_manifest_v2",
        "collection": collection,
        "points": count,
        "dense_points": dense_points,
        "sparse_points": sparse_points,
        "expected_points": total_expected,
        "base_path": str(base_path),
        "base_sha256": base_sha,
        "embedding_model": embed_model,
        "embedding_backend": embedding_backend,
        "point_embedding_fingerprint": point_embedding_fingerprint(),
        "embedding_space_id": "",
        "embedding_space_verified": False,
        "index_mode": "hybrid" if dense_points == total_expected else "sparse_only",
        "status": "passed" if (
            count == total_expected
            and sparse_points == total_expected
            and (sparse_only or dense_points == total_expected)
        ) else "failed",
    }
    _write_manifest(manifest_path, result)
    _write_build_status(
        build_status_path,
        {
            **build_status,
            "status": "completed" if result["status"] == "passed" else "failed",
            "points": count,
            "dense_points": dense_points,
            "sparse_points": sparse_points,
            "updated_at": time.time(),
        },
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    client.close()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", default=str(active_base().get("rag_collection") or "les_smeta_norm_cards_v1"))
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument("--sparse-only", action="store_true")
    parser.add_argument("--dense-only", action="store_true")
    parser.add_argument("--local-mps", action="store_true")
    parser.add_argument("--local-batch-size", type=int, default=32)
    parser.add_argument("--replace-dense", action="store_true")
    parser.add_argument(
        "--manifest-path",
        type=Path,
        help="generation-scoped manifest; defaults to the active sibling manifest",
    )
    parser.add_argument(
        "--build-status-path",
        type=Path,
        help="generation-scoped progress file; defaults to the active sibling status",
    )
    args = parser.parse_args()
    result = build(
        collection=args.collection,
        batch_size=args.batch_size,
        recreate=args.recreate,
        sparse_only=args.sparse_only,
        dense_only=args.dense_only,
        local_mps=args.local_mps,
        local_batch_size=args.local_batch_size,
        replace_dense=args.replace_dense,
        manifest_path=args.manifest_path,
        build_status_path=args.build_status_path,
    )
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
