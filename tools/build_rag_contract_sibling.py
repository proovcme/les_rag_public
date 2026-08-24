#!/usr/bin/env python3
"""Build a contract-clean sibling collection for selected RAG datasets.

The source collection is read-only.  Source text is sanitized, split to the
current embedding budget and embedded again with the active embedding service;
legacy vectors are never copied.  Point ids are deterministic, so rerunning a
dataset is idempotent.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Iterable


MIGRATION_NAMESPACE = uuid.UUID("e40ed045-32cd-48b2-a15d-e523c64921bc")
SCOPE_MANIFEST_SCHEMA = "les.rag.collection-scope.v1"
GENERAL_RAG_ROLE = "general_project_rag"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _retry_call(
    operation: Any,
    *,
    label: str,
    attempts: int,
    base_delay_sec: float,
) -> Any:
    """Retry transient network/runtime work without hiding the final exception."""
    last_error: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001 - the final error is re-raised verbatim
            last_error = exc
            if attempt >= max(1, attempts):
                raise
            delay = min(30.0, max(0.0, base_delay_sec) * (2 ** (attempt - 1)))
            print(
                json.dumps(
                    {
                        "event": "retry",
                        "operation": label,
                        "attempt": attempt,
                        "next_delay_sec": delay,
                        "error": type(exc).__name__,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            time.sleep(delay)
    raise RuntimeError(f"unreachable retry state: {label}") from last_error


def verify_embedding_runtime(embed: Any, *, expected_vector_size: int) -> dict[str, Any]:
    """Fail before creating a collection when the live embedder differs from the build contract."""
    vectors = embed.encode_sync(["LES embedding contract preflight"])
    if len(vectors) != 1:
        raise RuntimeError(
            f"embedding preflight returned {len(vectors)} vectors instead of 1"
        )
    actual_size = len(vectors[0])
    if actual_size != expected_vector_size:
        raise RuntimeError(
            "embedding vector size mismatch: "
            f"expected={expected_vector_size}, actual={actual_size}"
        )
    return {"status": "passed", "vector_size": actual_size}


def validate_embedding_health(
    health: dict[str, Any], *, contract: dict[str, Any]
) -> dict[str, Any]:
    """Prove remote embedder identity, not merely a coincidental vector size."""
    observed = health.get("embed_model") if isinstance(health.get("embed_model"), dict) else {}
    expected_fallback = str(contract.get("embedding_fallback") or "").strip().lower()
    expected = {
        "model": str(contract.get("embedding_model") or ""),
        "backend": str(contract.get("embedding_backend") or ""),
        "package": str(contract.get("embedding_package") or ""),
        "seq_len": int(contract.get("embedding_seq_len") or 0),
        "compute_units": str(contract.get("embedding_compute_units") or ""),
        "fallback_enabled": expected_fallback in {"1", "true", "yes", "on"},
    }
    actual = {
        "model": str(observed.get("path") or observed.get("coreml_model_id") or ""),
        "backend": str(observed.get("backend") or ""),
        "package": str(observed.get("coreml_model") or ""),
        "seq_len": int(observed.get("coreml_seq_len") or 0),
        "compute_units": str(observed.get("coreml_compute_units") or ""),
        "fallback_enabled": bool(observed.get("fallback_enabled")),
    }
    mismatches: dict[str, Any] = {}
    for key, value in expected.items():
        required = (
            bool(str(contract.get("embedding_fallback") or ""))
            if key == "fallback_enabled"
            else value not in {"", 0}
        )
        if required and actual[key] != value:
            mismatches[key] = {"expected": value, "actual": actual[key]}
    if health.get("status") != "ok":
        mismatches["health_status"] = {"expected": "ok", "actual": health.get("status")}
    if mismatches:
        raise RuntimeError(f"embedding runtime identity mismatch: {mismatches}")
    return {"status": "passed", **actual}


def verify_embedding_runtime_identity(
    url: str, *, contract: dict[str, Any]
) -> dict[str, Any]:
    import httpx

    if str(contract.get("embedding_backend") or "").strip().lower() == "ollama":
        response = httpx.get(url.rstrip("/") + "/api/tags", timeout=20.0)
        response.raise_for_status()
        payload = response.json()
        models = payload.get("models") if isinstance(payload, dict) else None
        expected = str(
            contract.get("embedding_api_model")
            or contract.get("embedding_model")
            or ""
        ).strip()

        def _tag(value: Any) -> str:
            return str(value or "").strip().casefold().removesuffix(":latest")

        matching = next(
            (
                item
                for item in models or []
                if isinstance(item, dict)
                and _tag(item.get("name") or item.get("model")) == _tag(expected)
            ),
            None,
        )
        if not expected or matching is None:
            available = sorted(
                str(item.get("name") or item.get("model") or "")
                for item in models or []
                if isinstance(item, dict)
            )
            raise RuntimeError(
                f"embedding runtime identity mismatch: expected Ollama model "
                f"{expected!r}, available={available}"
            )
        return {
            "status": "passed",
            "backend": "ollama",
            "model": str(matching.get("name") or matching.get("model") or expected),
            "digest": str(matching.get("digest") or ""),
        }

    response = httpx.get(url.rstrip("/") + "/api/health", timeout=20.0)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("embedding health response is not an object")
    return validate_embedding_health(payload, contract=contract)


class ParallelEmbedClient:
    """Use independent compatible embedding hosts without changing vector order."""

    def __init__(self, clients: list[Any]):
        if not clients:
            raise ValueError("at least one embedding client is required")
        self.clients = clients

    def encode_sync(self, texts: list[str]) -> list[list[float]]:
        if len(self.clients) == 1 or len(texts) <= 1:
            return self.clients[0].encode_sync(texts)
        worker_count = min(len(self.clients), len(texts))
        chunk_size = (len(texts) + worker_count - 1) // worker_count
        spans = [
            (index, texts[index * chunk_size : (index + 1) * chunk_size])
            for index in range(worker_count)
        ]
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = {
                pool.submit(self.clients[index].encode_sync, chunk): index
                for index, chunk in spans
                if chunk
            }
            parts = {futures[future]: future.result() for future in futures}
        return [vector for index in sorted(parts) for vector in parts[index]]


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


def resolve_indexed_dataset_identities(db_path: Path) -> list[dict[str, str]]:
    """Return canonical identities for every dataset with indexed chunks."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(datasets)")}
        scope_expr = "COALESCE(d.dataset_scope, 'user')" if "dataset_scope" in columns else "'user'"
        module_expr = "COALESCE(d.module_id, '')" if "module_id" in columns else "''"
        rows = conn.execute(
            f"""
            SELECT DISTINCT d.id, d.name,
                   {scope_expr} AS dataset_scope,
                   {module_expr} AS module_id
            FROM datasets d
            LEFT JOIN documents doc ON doc.dataset_id = d.id
            WHERE COALESCE(d.chunk_count, 0) > 0
               OR (doc.status = 'INDEXED' AND COALESCE(doc.chunk_count, 0) > 0)
            ORDER BY d.name
            """
        ).fetchall()
    from proxy.services.system_dataset_service import dataset_identity

    result: list[dict[str, str]] = []
    for row in rows:
        name = str(row["name"])
        registered_scope, registered_module = dataset_identity(name)
        dataset_scope = str(row["dataset_scope"] or "user")
        module_id = str(row["module_id"] or "")
        if registered_scope == "system":
            dataset_scope, module_id = registered_scope, registered_module
        result.append(
            {
                "id": str(row["id"]),
                "name": name,
                "dataset_scope": dataset_scope,
                "module_id": module_id,
            }
        )
    return result


def resolve_indexed_datasets(db_path: Path) -> list[dict[str, str]]:
    """Return all indexed user datasets eligible for the general LES RAG."""
    return [
        {"id": item["id"], "name": item["name"]}
        for item in resolve_indexed_dataset_identities(db_path)
        if item["dataset_scope"] == "user"
    ]


def scope_manifest_payload(db_path: Path) -> dict[str, Any]:
    datasets = [
        item
        for item in resolve_indexed_dataset_identities(db_path)
        if item["dataset_scope"] == "user"
    ]
    if not datasets:
        raise ValueError("no indexed user datasets found for general LES RAG")
    return {
        "schema": SCOPE_MANIFEST_SCHEMA,
        "collection_role": GENERAL_RAG_ROLE,
        "selection_policy": "exact-indexed-user-datasets",
        "datasets": datasets,
    }


def scope_manifest_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def load_scope_manifest(path: Path, db_path: Path) -> tuple[dict[str, Any], str]:
    payload = _read_json(path)
    if payload.get("schema") != SCOPE_MANIFEST_SCHEMA:
        raise ValueError(f"invalid RAG scope manifest schema: {payload.get('schema')!r}")
    if payload.get("collection_role") != GENERAL_RAG_ROLE:
        raise ValueError(
            f"scope manifest is not for {GENERAL_RAG_ROLE}: {payload.get('collection_role')!r}"
        )
    expected = scope_manifest_payload(db_path)
    if payload.get("selection_policy") != expected["selection_policy"]:
        raise ValueError("scope manifest selection policy is not exact user scope")
    if payload.get("datasets") != expected["datasets"]:
        raise ValueError("scope manifest is stale or does not match indexed user datasets")
    return payload, scope_manifest_sha256(payload)


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
    # A resumed supervised build must not inherit an unrelated interactive
    # shell/default profile.  Rehydrate the immutable generation contract
    # before importing the adapter or running the embedding preflight.
    existing = _read_json(args.contract_path)
    if existing:
        model = str(existing.get("embedding_model") or "")
        if model == "Qwen/Qwen3-Embedding-0.6B":
            os.environ["LES_EMBED_PROFILE"] = "qwen"
        if model:
            os.environ["EMBEDDING_MODEL"] = model
        mappings = {
            "EMBED_MODEL": "embedding_api_model",
            "EMBED_BACKEND": "embedding_backend",
            "RAG_VECTOR_SIZE": "vector_size",
            "RAG_CHUNK_UNIT": "chunk_unit",
            "RAG_DENSE_VECTOR_NAME": "dense_vector_name",
            "RAG_SPARSE_VECTOR_NAME": "sparse_vector_name",
            "COREML_EMBED_MODEL": "embedding_package",
            "COREML_EMBED_SEQ_LEN": "embedding_seq_len",
            "COREML_EMBED_COMPUTE_UNITS": "embedding_compute_units",
            "COREML_EMBED_FALLBACK": "embedding_fallback",
        }
        for env_name, contract_name in mappings.items():
            value = existing.get(contract_name)
            if value is not None and str(value) != "":
                os.environ[env_name] = str(value)


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
        vector_config = {
            args.dense_name: models.VectorParams(
                size=rag_vector_size(), distance=models.Distance.COSINE
            )
        }
        if getattr(args, "with_colbert", False):
            vector_config[args.colbert_name] = models.VectorParams(
                size=args.colbert_dimension,
                distance=models.Distance.COSINE,
                hnsw_config=models.HnswConfigDiff(m=0),
                on_disk=True,
                datatype=models.Datatype.FLOAT16,
                multivector_config=models.MultiVectorConfig(
                    comparator=models.MultiVectorComparator.MAX_SIM
                ),
            )
        client.create_collection(
            collection_name=args.dst,
            vectors_config=vector_config,
            sparse_vectors_config={
                args.sparse_name: models.SparseVectorParams(modifier=models.Modifier.IDF)
            },
        )
    for field in (
        "dataset_id",
        "file_name",
        "embedding_fingerprint",
        "migration_source_point_id",
        "node_role",
        "node_id",
        "ancestor_ids",
        "hierarchy_parent_id",
    ):
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


def _source_dataset_snapshot(
    client: Any,
    *,
    collection: str,
    dataset_id: str,
    page_size: int,
    limit: int,
) -> dict[str, Any]:
    digest = hashlib.sha256()
    count = 0
    for point in _iter_source_points(
        client,
        collection=collection,
        dataset_id=dataset_id,
        page_size=page_size,
        limit=limit,
    ):
        payload = dict(getattr(point, "payload", None) or {})
        content_identity = str(payload.get("content_hash") or payload.get("text") or "")
        digest.update(f"{point.id}\n{content_identity}\n".encode("utf-8", errors="ignore"))
        count += 1
    return {"points": count, "identity_sha256": digest.hexdigest()}


def sparse_vector_or_exclusion(text: str) -> tuple[dict[int, float] | None, str]:
    """Return real BM25 terms or an explicit audited exclusion reason."""
    from backend.inference.bm25_sparse import encode_bm25

    sparse = encode_bm25(text)
    if not sparse:
        return None, "empty_sparse_after_tokenization"
    return sparse, ""


def canonicalize_dataset_payload(
    payload: dict[str, Any], dataset: dict[str, str]
) -> tuple[dict[str, Any], bool]:
    """Project point ownership from MetaDB instead of copying stale route labels."""
    result = dict(payload)
    result["dataset_id"] = dataset["id"]
    result["dataset_name"] = dataset["name"]
    removed_legacy_domain = str(result.get("domain") or "").upper() == "TABLE_SMETA"
    if removed_legacy_domain:
        result.pop("domain", None)
    return result, removed_legacy_domain


def _migrate_dataset(
    client: Any,
    embed: Any,
    args: argparse.Namespace,
    dataset: dict[str, str],
    *,
    progress: Any | None = None,
) -> dict[str, Any]:
    from backend.qdrant_adapter import (
        QdrantLlamaIndexAdapter,
        _apply_context_metadata_to_nodes,
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
    read = written = dropped = skipped_existing = 0
    source_points_with_searchable_children = 0
    source_points_excluded = 0
    child_points_total = 0
    excluded_children: list[dict[str, Any]] = []
    canonicalized_legacy_domain_points = 0
    source_digest = hashlib.sha256()

    def flush() -> None:
        nonlocal written, skipped_existing, canonicalized_legacy_domain_points
        if not pending:
            return
        for item in pending:
            item["point_id"] = deterministic_point_id(
                source_collection=args.source_identity or args.src,
                source_point_id=item["source_point_id"],
                child_ord=int((item.get("payload") or {}).get("migration_child_ord") or 0),
                text=item["text"],
            )
        existing_points = client.retrieve(
            collection_name=args.dst,
            ids=[item["point_id"] for item in pending],
            with_payload=True,
            with_vectors=False,
        )
        existing = {str(point.id): point for point in existing_points}
        canonical_updates: list[str] = []
        remove_legacy_domain: list[str] = []
        for item in pending:
            point = existing.get(item["point_id"])
            if point is None:
                continue
            old_payload = dict(getattr(point, "payload", None) or {})
            if (
                old_payload.get("dataset_id") != dataset["id"]
                or old_payload.get("dataset_name") != dataset["name"]
            ):
                canonical_updates.append(item["point_id"])
            if str(old_payload.get("domain") or "").upper() == "TABLE_SMETA":
                remove_legacy_domain.append(item["point_id"])
        if canonical_updates:
            client.set_payload(
                args.dst,
                payload={"dataset_id": dataset["id"], "dataset_name": dataset["name"]},
                points=canonical_updates,
                wait=True,
            )
        if remove_legacy_domain:
            client.delete_payload(
                args.dst,
                keys=["domain"],
                points=remove_legacy_domain,
                wait=True,
            )
            canonicalized_legacy_domain_points += len(remove_legacy_domain)
        missing = [item for item in pending if item["point_id"] not in existing]
        skipped_existing += len(pending) - len(missing)
        if not missing:
            pending.clear()
            return
        vectors = _retry_call(
            lambda: embed.encode_sync([item["text"] for item in missing]),
            label="embedding_batch",
            attempts=args.retry_attempts,
            base_delay_sec=args.retry_delay,
        )
        if len(vectors) != len(missing):
            raise RuntimeError(
                f"embedding count mismatch: got {len(vectors)}, expected {len(missing)}"
            )
        colbert_vectors = (
            _retry_call(
                lambda: args.colbert_encoder.encode(
                    [item["text"] for item in missing],
                    max_length=args.colbert_passage_tokens,
                ),
                label="colbert_embedding_batch",
                attempts=args.retry_attempts,
                base_delay_sec=args.retry_delay,
            )
            if getattr(args, "with_colbert", False) else [None] * len(missing)
        )
        if len(colbert_vectors) != len(missing):
            raise RuntimeError("colbert embedding count mismatch")
        points = []
        for item, dense, colbert in zip(missing, vectors, colbert_vectors, strict=True):
            sparse = item["sparse"]
            payload, removed_legacy_domain = canonicalize_dataset_payload(
                dict(item["payload"]), dataset
            )
            canonicalized_legacy_domain_points += int(removed_legacy_domain)
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
                    "migration_source_collection": args.source_identity or args.src,
                    "migration_source_point_id": str(item["source_point_id"]),
                }
            )
            point_vector: dict[str, Any] = {
                args.dense_name: dense,
                args.sparse_name: models.SparseVector(
                    indices=list(sparse.keys()), values=list(sparse.values())
                ),
            }
            if colbert is not None:
                if not colbert or len(colbert[0]) != args.colbert_dimension:
                    raise RuntimeError("COLBERT_VECTOR_DIMENSION_MISMATCH")
                point_vector[args.colbert_name] = colbert
                payload.update({
                    "colbert_schema": "les.rag.colbert.bge-m3.v1",
                    "colbert_model": "BAAI/bge-m3",
                    "colbert_passage_tokens": args.colbert_passage_tokens,
                })
            points.append(
                models.PointStruct(
                    id=item["point_id"],
                    vector=point_vector,
                    payload=payload,
                )
            )
        _retry_call(
            lambda: client.upsert(args.dst, points=points, wait=True),
            label="qdrant_upsert",
            attempts=args.retry_attempts,
            base_delay_sec=args.retry_delay,
        )
        written += len(points)
        pending.clear()

    def excluded_child_count() -> int:
        return sum(item.get("child_ord") is not None for item in excluded_children)

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
        source_digest.update(
            f"{point.id}\n{source_payload.get('content_hash') or source_text}\n".encode(
                "utf-8", errors="ignore"
            )
        )
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
        _apply_context_metadata_to_nodes(
            nodes,
            dataset["id"],
            str(source_payload.get("file_name") or source_payload.get("doc_name") or point.id),
        )
        if not nodes:
            dropped += 1
            source_points_excluded += 1
            excluded_children.append(
                {
                    "source_point_id": str(point.id),
                    "child_ord": None,
                    "reason": "sanitation_removed_all_text",
                    "text_sha256": hashlib.sha256(
                        source_text.encode("utf-8", errors="ignore")
                    ).hexdigest(),
                }
            )
            continue
        child_points_total += len(nodes)
        searchable_for_source = 0
        for child_ord, node in enumerate(nodes):
            text = str(node["text"])
            sparse, exclusion_reason = sparse_vector_or_exclusion(text)
            if not sparse:
                excluded_children.append(
                    {
                        "source_point_id": str(point.id),
                        "child_ord": child_ord,
                        "reason": exclusion_reason,
                        "text_sha256": hashlib.sha256(
                            text.encode("utf-8", errors="ignore")
                        ).hexdigest(),
                    }
                )
                continue
            payload = dict(node.get("payload") or {})
            payload["migration_child_ord"] = child_ord
            pending.append(
                {
                    "text": text,
                    "sparse": sparse,
                    "payload": payload,
                    "source_point_id": point.id,
                }
            )
            searchable_for_source += 1
            if len(pending) >= args.embed_batch:
                flush()
        if searchable_for_source:
            source_points_with_searchable_children += 1
        else:
            source_points_excluded += 1
        if read % max(args.page_size, 1) == 0:
            current = {
                "dataset_id": dataset["id"],
                "dataset": dataset["name"],
                "source_points_read": read,
                "points_written": written,
                "points_already_present": skipped_existing,
                "dropped": dropped,
                "excluded_child_points": excluded_child_count(),
                "source_points_excluded": source_points_excluded,
                "canonicalized_legacy_domain_points": canonicalized_legacy_domain_points,
            }
            print(json.dumps(current, ensure_ascii=False), flush=True)
            if progress is not None:
                progress(current)
    flush()
    destination_points = int(
        client.count(
            args.dst,
            count_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="dataset_id",
                        match=models.MatchValue(value=dataset["id"]),
                    )
                ]
            ),
            exact=True,
        ).count
    )
    result = {
        "dataset_id": dataset["id"],
        "dataset": dataset["name"],
        "source_points_read": read,
        "source_identity_sha256": source_digest.hexdigest(),
        "source_points_with_searchable_children": source_points_with_searchable_children,
        "source_points_excluded": source_points_excluded,
        "child_points_total": child_points_total,
        "excluded_child_points": excluded_child_count(),
        "exclusions": excluded_children,
        "canonicalized_legacy_domain_points": canonicalized_legacy_domain_points,
        "points_written": written,
        "points_already_present": skipped_existing,
        "destination_points": destination_points,
        "dropped": dropped,
    }
    if destination_points != written + skipped_existing:
        raise RuntimeError(
            "destination dataset contains unexpected points: "
            f"dataset={dataset['name']}, observed={destination_points}, "
            f"accounted={written + skipped_existing}"
        )
    if child_points_total != destination_points + excluded_child_count():
        raise RuntimeError(
            "child accounting mismatch: "
            f"dataset={dataset['name']}, children={child_points_total}, "
            f"destination={destination_points}, excluded={excluded_child_count()}"
        )
    if read != source_points_with_searchable_children + source_points_excluded:
        raise RuntimeError(
            "source accounting mismatch: "
            f"dataset={dataset['name']}, read={read}, "
            f"searchable={source_points_with_searchable_children}, "
            f"excluded={source_points_excluded}"
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", required=True)
    parser.add_argument(
        "--source-identity",
        default="",
        help="stable logical source name when --src is a pinned physical alias target",
    )
    parser.add_argument("--dst", required=True)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--contract-path", type=Path, required=True)
    parser.add_argument("--scope-manifest", type=Path)
    parser.add_argument("--dataset", action="append", dest="datasets")
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument(
        "--embed-url",
        default="http://127.0.0.1:8080",
        help="one URL or comma-separated compatible embedding hosts",
    )
    parser.add_argument("--dense-name", default="dense")
    parser.add_argument("--sparse-name", default="bm25_sparse")
    parser.add_argument("--with-colbert", action="store_true")
    parser.add_argument("--colbert-name", default="colbert")
    parser.add_argument("--colbert-dimension", type=int, default=1024)
    parser.add_argument("--colbert-passage-tokens", type=int, default=128)
    parser.add_argument("--page-size", type=int, default=128)
    parser.add_argument("--embed-batch", type=int, default=16)
    parser.add_argument("--limit", type=int, default=0, help="source points per dataset; 0 = all")
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report-path", type=Path)
    parser.add_argument("--progress-path", type=Path)
    parser.add_argument("--retry-attempts", type=int, default=6)
    parser.add_argument("--retry-delay", type=float, default=2.0)
    args = parser.parse_args(argv)
    args.datasets = args.datasets or []
    if args.create and args.dry_run:
        parser.error("--create and --dry-run are mutually exclusive")
    if not args.source_db.is_file():
        parser.error(f"source db not found: {args.source_db}")
    if args.scope_manifest and args.datasets:
        parser.error("--scope-manifest and --dataset are mutually exclusive")

    scope_manifest: dict[str, Any] = {}
    scope_manifest_digest = ""
    if args.scope_manifest:
        try:
            scope_manifest, scope_manifest_digest = load_scope_manifest(
                args.scope_manifest, args.source_db
            )
        except ValueError as exc:
            parser.error(str(exc))
        datasets = [
            {"id": str(item["id"]), "name": str(item["name"])}
            for item in scope_manifest["datasets"]
        ]
    elif args.datasets:
        datasets = resolve_datasets(args.source_db, args.datasets)
    else:
        parser.error("--scope-manifest is required unless explicit --dataset is provided")
    if not datasets:
        parser.error("no indexed datasets found")
    plan = {
        "schema": "les.rag.contract-sibling-plan.v1",
        "source_collection": args.source_identity or args.src,
        "source_physical_collection": args.src,
        "destination_collection": args.dst,
        "contract_path": str(args.contract_path),
        "datasets": datasets,
        "scope": "manifest" if args.scope_manifest else "selected",
        "scope_manifest": str(args.scope_manifest or ""),
        "scope_manifest_sha256": scope_manifest_digest,
        "limit_per_dataset": args.limit,
        "mutates_source": False,
    }
    print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
    if args.dry_run or not args.create and not args.resume:
        return 0

    _configure_contract(args)
    if args.with_colbert:
        from backend.colbert_late_interaction import BgeM3ColbertEncoder

        args.colbert_encoder = BgeM3ColbertEncoder("BAAI/bge-m3")
    else:
        args.colbert_encoder = None
    from backend.qdrant_adapter import EmbedClient
    from backend.rag_config import (
        embedding_api_model,
        index_contract_payload,
        index_contract_status,
        rag_vector_size,
        write_index_contract,
    )
    from qdrant_client import QdrantClient, models

    embed_urls = [item.strip() for item in args.embed_url.split(",") if item.strip()]
    embed_clients = [EmbedClient(url, model=embedding_api_model()) for url in embed_urls]
    expected_contract = _read_json(args.contract_path) or index_contract_payload()
    preflight = [
        {
            "url": url,
            "identity": verify_embedding_runtime_identity(url, contract=expected_contract),
            "vector": verify_embedding_runtime(client, expected_vector_size=rag_vector_size()),
        }
        for url, client in zip(embed_urls, embed_clients, strict=True)
    ]
    print(json.dumps({"embedding_preflight": preflight}, ensure_ascii=False), flush=True)
    embed = ParallelEmbedClient(embed_clients)

    client = QdrantClient(url=args.qdrant_url, timeout=180.0, check_compatibility=False)
    created = _ensure_destination(client, args)
    if created:
        write_index_contract(replace=False)
        if args.with_colbert:
            contract_payload = _read_json(args.contract_path)
            contract_payload.update({
                "colbert_schema": "les.rag.colbert.bge-m3.v1",
                "colbert_model": "BAAI/bge-m3",
                "colbert_vector_name": args.colbert_name,
                "colbert_dimension": args.colbert_dimension,
                "colbert_datatype": "float16",
                "colbert_passage_tokens": args.colbert_passage_tokens,
            })
            _write_json_atomic(args.contract_path, contract_payload)
    contract = index_contract_status()
    if not contract.get("compatible"):
        raise RuntimeError(f"destination contract is not compatible: {contract}")

    source_points = int(client.count(args.src, exact=True).count)
    progress_path = args.progress_path or (
        args.report_path.with_suffix(args.report_path.suffix + ".progress")
        if args.report_path
        else None
    )
    previous_progress = _read_json(progress_path)
    if previous_progress and str(previous_progress.get("scope_manifest_sha256") or "") != scope_manifest_digest:
        raise RuntimeError("resume checkpoint belongs to a different RAG scope manifest")
    completed_by_id = {
        str(item.get("dataset_id")): item
        for item in previous_progress.get("completed_datasets", [])
        if isinstance(item, dict) and item.get("dataset_id")
    }
    progress_payload: dict[str, Any] = {
        "schema": "les.rag.contract-sibling-progress.v1",
        "status": "building",
        "source_collection": args.source_identity or args.src,
        "source_physical_collection": args.src,
        "destination_collection": args.dst,
        "source_points_snapshot": source_points,
        "scope_manifest_sha256": scope_manifest_digest,
        "datasets_total": len(datasets),
        "completed_datasets": [],
        "current_dataset": {},
        "updated_at": time.time(),
    }

    def persist_progress(current: dict[str, Any] | None = None) -> None:
        if current is not None:
            progress_payload["current_dataset"] = current
        progress_payload["updated_at"] = time.time()
        if progress_path:
            _write_json_atomic(progress_path, progress_payload)

    results: list[dict[str, Any]] = []
    for dataset in datasets:
        prior = completed_by_id.get(dataset["id"])
        if prior:
            source_now = _source_dataset_snapshot(
                client,
                collection=args.src,
                dataset_id=dataset["id"],
                page_size=args.page_size,
                limit=args.limit,
            )
            destination_now = int(
                client.count(
                    args.dst,
                    count_filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="dataset_id",
                                match=models.MatchValue(value=dataset["id"]),
                            )
                        ]
                    ),
                    exact=True,
                ).count
            )
            if (
                source_now["points"] == int(prior.get("source_points_read") or -1)
                and source_now["identity_sha256"]
                == str(prior.get("source_identity_sha256") or "")
                and destination_now == int(prior.get("destination_points") or -1)
                and int(prior.get("dropped") or 0) == 0
            ):
                results.append(dict(prior))
                progress_payload["completed_datasets"] = results
                persist_progress()
                continue
        result = _migrate_dataset(
            client,
            embed,
            args,
            dataset,
            progress=persist_progress,
        )
        results.append(result)
        progress_payload["completed_datasets"] = results
        progress_payload["current_dataset"] = {}
        persist_progress()

    source_points_after = int(client.count(args.src, exact=True).count)
    if source_points_after != source_points:
        raise RuntimeError(
            "source collection changed during migration: "
            f"before={source_points}, after={source_points_after}"
        )
    for dataset, result in zip(datasets, results, strict=True):
        final_source = _source_dataset_snapshot(
            client,
            collection=args.src,
            dataset_id=dataset["id"],
            page_size=args.page_size,
            limit=args.limit,
        )
        if (
            final_source["points"] != int(result["source_points_read"])
            or final_source["identity_sha256"] != result["source_identity_sha256"]
        ):
            raise RuntimeError(f"source dataset changed during migration: {dataset['name']}")
    source_points_read = sum(int(item["source_points_read"]) for item in results)
    dropped = sum(int(item["dropped"]) for item in results)
    excluded_source_points = sum(
        int(item["source_points_excluded"]) for item in results
    )
    excluded_child_points = sum(
        int(item["excluded_child_points"]) for item in results
    )
    child_points_total = sum(int(item["child_points_total"]) for item in results)
    if source_points_read > source_points:
        raise RuntimeError(
            f"selected source coverage exceeds collection: read={source_points_read}, source={source_points}"
        )
    report = {
        "schema": "les.rag.contract-sibling-result.v1",
        "status": "completed",
        "source_collection": args.source_identity or args.src,
        "source_physical_collection": args.src,
        "destination_collection": args.dst,
        "contract": contract,
        "datasets": results,
        "scope_manifest": str(args.scope_manifest or ""),
        "scope_manifest_sha256": scope_manifest_digest,
        "source_collection_points": source_points,
        "source_unselected_points": source_points - source_points_read,
        "source_points": source_points_read,
        "source_points_read": source_points_read,
        "source_coverage": 1.0,
        "source_points_excluded": excluded_source_points,
        "child_points_total": child_points_total,
        "excluded_child_points": excluded_child_points,
        "sanitation_removed_source_points": dropped,
        "destination_points": int(client.count(args.dst, exact=True).count),
        "destination_points_accounted": sum(
            int(item["destination_points"]) for item in results
        ),
    }
    if report["destination_points"] != report["destination_points_accounted"]:
        raise RuntimeError(
            "destination collection contains orphan or foreign points: "
            f"observed={report['destination_points']}, "
            f"accounted={report['destination_points_accounted']}"
        )
    if child_points_total != report["destination_points"] + excluded_child_points:
        raise RuntimeError(
            "global child accounting mismatch: "
            f"children={child_points_total}, destination={report['destination_points']}, "
            f"excluded={excluded_child_points}"
        )
    if args.report_path:
        _write_json_atomic(args.report_path, report)
    progress_payload.update(
        {
            "status": "completed",
            "completed_datasets": results,
            "current_dataset": {},
            "source_points_read": source_points_read,
            "destination_points": report["destination_points"],
        }
    )
    persist_progress()
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
