"""Durable RAPTOR build orchestration for the active general RAG generation."""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any, Callable

from backend.raptor_publication_worker import (
    load_publication_checkpoint,
    publish_document_batches_with_resume,
)
from backend.raptor_qdrant_store import (
    RaptorDocumentRef,
    RaptorQdrantStore,
    source_snapshot_fingerprint,
    target_collection_name,
)
from backend.raptor_summarizer import summarizer_from_policy
from proxy.services.rag_advanced_policy_service import load_policy, save_status


_BUILD_LOCK = threading.Lock()


def _error_code(error: BaseException) -> str:
    match = re.search(r"\b([A-Z][A-Z0-9_]{3,})\b", str(error))
    return match.group(1) if match else f"RAPTOR_{type(error).__name__.upper()}"


def active_physical_collection(client: Any, alias: str) -> str:
    aliases = {
        str(item.alias_name): str(item.collection_name)
        for item in client.get_aliases().aliases
    }
    return aliases.get(alias, alias)


def indexed_document_refs(meta_db: Any) -> list[RaptorDocumentRef]:
    refs: list[RaptorDocumentRef] = []
    for dataset in meta_db.list_datasets():
        module_id = str(getattr(dataset, "module_id", "") or "").casefold()
        if module_id.startswith("smeta"):
            continue
        for row in meta_db.dataset_integrity_rows(str(dataset.id)):
            if str(row.get("status") or "").upper() != "INDEXED":
                continue
            source_hash = str(row.get("file_hash") or "")
            if not source_hash:
                source_hash = f"{row.get('file_mtime') or 0}:{row.get('file_size') or 0}"
            refs.append(
                RaptorDocumentRef(
                    dataset_id=str(dataset.id),
                    file_name=str(row.get("file_name") or ""),
                    chunk_count=int(row.get("chunk_count") or 0),
                    source_hash=source_hash,
                )
            )
    return sorted(refs, key=lambda item: (item.dataset_id, item.file_name))


def checkpoint_path_for(target_collection: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", target_collection)
    return Path("storage/rag/advanced") / f"{safe}.publication.json"


def run_raptor_publication(
    backend: Any,
    *,
    client_factory: Callable[..., Any] | None = None,
    policy: dict[str, Any] | None = None,
    checkpoint_path: Path | None = None,
) -> dict[str, Any]:
    """Build or resume a separate RAPTOR collection; never mutate evidence."""
    if not _BUILD_LOCK.acquire(blocking=False):
        raise RuntimeError("RAPTOR_BUILD_ALREADY_RUNNING")
    try:
        if client_factory is None:
            from qdrant_client import QdrantClient

            client_factory = QdrantClient
        client = client_factory(
            url=backend.qdrant_url,
            timeout=180.0,
            check_compatibility=False,
        )
        source = active_physical_collection(client, backend.collection_name)
        target = target_collection_name(source)
        selected_policy = (policy or load_policy())["raptor"] if "raptor" in (policy or {}) else (policy or load_policy())
        documents = indexed_document_refs(backend.db)
        fingerprint = source_snapshot_fingerprint(source, documents)
        checkpoint = checkpoint_path or checkpoint_path_for(target)
        store = RaptorQdrantStore(
            client,
            source_collection=source,
            target_collection=target,
            embed=backend.embed.encode_sync,
            vector_size=backend.vector_size,
        )
        store.ensure_collection()
        previous = load_publication_checkpoint(checkpoint, leaf_fingerprint=fingerprint)
        if not previous:
            store.reset_source()
        summarizer = summarizer_from_policy(selected_policy)
        by_id = {document.document_id: document for document in documents}

        save_status(
            {
                "raptor": {
                    "readiness": "building",
                    "progress": float(previous.get("progress") or 0.0),
                    "last_error_code": "",
                    "source_collection": source,
                    "target_collection": target,
                    "checkpoint_path": str(checkpoint),
                    "documents_total": len(documents),
                    "documents_completed": int(previous.get("documents_completed") or 0),
                }
            }
        )

        def progress(payload: dict[str, Any]) -> None:
            save_status(
                {
                    "raptor": {
                        "readiness": "building" if payload["status"] == "running" else "verifying",
                        "progress": float(payload.get("progress") or 0.0),
                        "documents_total": int(payload.get("documents_total") or 0),
                        "documents_completed": int(payload.get("documents_completed") or 0),
                        "published_nodes": int(payload.get("published_nodes") or 0),
                    }
                }
            )

        result = publish_document_batches_with_resume(
            (document.document_id for document in documents),
            lambda document_id: store.load_document(by_id[document_id]),
            summarizer,
            lambda document_id, nodes: store.publish_document(by_id[document_id], nodes),
            source_fingerprint=fingerprint,
            documents_total=len(documents),
            checkpoint_path=checkpoint,
            fanout=int(selected_policy["fanout"]),
            max_depth=int(selected_policy["max_depth"]),
            progress=progress,
        )
        readiness = store.readiness(
            expected_nodes=int(result["published_nodes"]),
            source_fingerprint=fingerprint,
        )
        if not readiness["ready"]:
            raise RuntimeError("RAPTOR_PUBLICATION_READINESS_FAILED")
        save_status(
            {
                "raptor": {
                    "readiness": "ready",
                    "progress": 1.0,
                    "last_error_code": "",
                    "documents_total": len(documents),
                    "documents_completed": len(documents),
                    "published_nodes": int(result["published_nodes"]),
                    **readiness,
                }
            }
        )
        return {**result, "readiness": readiness}
    except Exception as error:
        save_status(
            {
                "raptor": {
                    "readiness": "blocked",
                    "last_error_code": _error_code(error),
                    "last_error_detail": str(error)[:500],
                }
            }
        )
        raise
    finally:
        _BUILD_LOCK.release()


def resumable_raptor_checkpoint() -> bool:
    status = load_policy()
    if status["raptor"]["mode"] == "off":
        return False
    from proxy.services.rag_advanced_policy_service import load_status

    raptor = load_status()["raptor"]
    checkpoint = Path(str(raptor.get("checkpoint_path") or ""))
    return raptor.get("readiness") in {"building", "verifying"} and checkpoint.is_file()


def raptor_auto_action_needed(
    backend: Any,
    *,
    client_factory: Callable[..., Any] | None = None,
) -> bool:
    """Resume interrupted work or refresh an established tree after indexing."""
    policy = load_policy()
    if policy["raptor"]["mode"] == "off":
        return False
    datasets = backend.db.list_datasets()
    if any(int(getattr(dataset, "pending_files", 0) or 0) > 0 for dataset in datasets):
        return False
    from proxy.services.rag_advanced_policy_service import load_status

    status = load_status()["raptor"]
    readiness = str(status.get("readiness") or "")
    if readiness in {"building", "verifying"}:
        return bool(str(status.get("checkpoint_path") or ""))
    if readiness != "ready":
        return False
    if client_factory is None:
        from qdrant_client import QdrantClient

        client_factory = QdrantClient
    client = client_factory(
        url=backend.qdrant_url,
        timeout=30.0,
        check_compatibility=False,
    )
    source = active_physical_collection(client, backend.collection_name)
    current = source_snapshot_fingerprint(source, indexed_document_refs(backend.db))
    return current != str(status.get("source_fingerprint") or "")
