"""Checkpointed RAPTOR publication orchestration independent of storage backend."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable

from backend.raptor_tree import RAPTOR_SCHEMA, RaptorLeaf, RaptorNode, build_tree


PUBLICATION_SCHEMA = "les.rag.raptor-publication.v1"


def leaf_set_fingerprint(leaves: Iterable[RaptorLeaf]) -> str:
    digest = hashlib.sha256()
    for leaf in sorted(leaves, key=lambda item: (item.document_id, item.point_id)):
        digest.update(leaf.document_id.encode("utf-8", errors="replace"))
        digest.update(b"\0")
        digest.update(leaf.point_id.encode("utf-8", errors="replace"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(leaf.text.encode("utf-8", errors="replace")).digest())
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(5):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


def load_publication_checkpoint(path: Path, *, leaf_fingerprint: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != PUBLICATION_SCHEMA
        or payload.get("raptor_schema") != RAPTOR_SCHEMA
        or payload.get("leaf_fingerprint") != leaf_fingerprint
    ):
        return {}
    return payload


def publish_with_resume(
    leaves: list[RaptorLeaf],
    summarizer: Callable[[list[str], int], tuple[str, str]],
    publisher: Callable[[str, list[RaptorNode]], None],
    *,
    checkpoint_path: Path,
    fanout: int = 8,
    max_depth: int = 3,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Publish one document atomically, checkpoint, then continue after restart."""
    fingerprint = leaf_set_fingerprint(leaves)
    grouped: dict[str, list[RaptorLeaf]] = defaultdict(list)
    for leaf in leaves:
        grouped[leaf.document_id].append(leaf)
    documents = sorted(grouped)
    checkpoint = load_publication_checkpoint(
        checkpoint_path,
        leaf_fingerprint=fingerprint,
    )
    completed = set(str(value) for value in checkpoint.get("completed_documents") or [])
    published_nodes = int(checkpoint.get("published_nodes") or 0)

    for document_id in documents:
        if document_id in completed:
            continue
        nodes = build_tree(
            grouped[document_id],
            summarizer,
            fanout=fanout,
            max_depth=max_depth,
        )
        publisher(document_id, nodes)
        completed.add(document_id)
        published_nodes += len(nodes)
        payload = {
            "schema": PUBLICATION_SCHEMA,
            "raptor_schema": RAPTOR_SCHEMA,
            "status": "running",
            "leaf_fingerprint": fingerprint,
            "documents_total": len(documents),
            "documents_completed": len(completed),
            "completed_documents": sorted(completed),
            "published_nodes": published_nodes,
        }
        _atomic_json(checkpoint_path, payload)
        if progress:
            progress(dict(payload))

    result = {
        "schema": PUBLICATION_SCHEMA,
        "raptor_schema": RAPTOR_SCHEMA,
        "status": "completed",
        "leaf_fingerprint": fingerprint,
        "documents_total": len(documents),
        "documents_completed": len(completed),
        "completed_documents": sorted(completed),
        "published_nodes": published_nodes,
    }
    _atomic_json(checkpoint_path, result)
    if progress:
        progress(dict(result))
    return result


def publish_document_batches_with_resume(
    document_ids: Iterable[str],
    load_document: Callable[[str], list[RaptorLeaf]],
    summarizer: Callable[[list[str], int], tuple[str, str]],
    publisher: Callable[[str, list[RaptorNode]], None],
    *,
    source_fingerprint: str,
    documents_total: int,
    checkpoint_path: Path,
    fanout: int = 8,
    max_depth: int = 3,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Publish a corpus while retaining only the current document's text.

    A document enters the checkpoint only after its idempotent publisher has
    confirmed the write. Restart therefore resumes at the first unconfirmed
    document without treating a partial write as ready.
    """
    fingerprint = str(source_fingerprint or "").strip()
    if not fingerprint:
        raise ValueError("RAPTOR_SOURCE_FINGERPRINT_MISSING")
    checkpoint = load_publication_checkpoint(
        checkpoint_path,
        leaf_fingerprint=fingerprint,
    )
    completed = set(str(value) for value in checkpoint.get("completed_documents") or [])
    published_nodes = int(checkpoint.get("published_nodes") or 0)
    total = max(0, int(documents_total))

    for document_id in document_ids:
        stable_id = str(document_id)
        if stable_id in completed:
            continue
        leaves = load_document(stable_id)
        nodes = build_tree(leaves, summarizer, fanout=fanout, max_depth=max_depth)
        publisher(stable_id, nodes)
        completed.add(stable_id)
        published_nodes += len(nodes)
        payload = {
            "schema": PUBLICATION_SCHEMA,
            "raptor_schema": RAPTOR_SCHEMA,
            "status": "running",
            "leaf_fingerprint": fingerprint,
            "documents_total": total,
            "documents_completed": len(completed),
            "completed_documents": sorted(completed),
            "published_nodes": published_nodes,
            "progress": (len(completed) / total) if total else 1.0,
        }
        _atomic_json(checkpoint_path, payload)
        if progress:
            progress(dict(payload))

    if len(completed) != total:
        raise RuntimeError(
            "RAPTOR_DOCUMENT_STREAM_INCOMPLETE: "
            f"expected={total}, completed={len(completed)}"
        )
    result = {
        "schema": PUBLICATION_SCHEMA,
        "raptor_schema": RAPTOR_SCHEMA,
        "status": "completed",
        "leaf_fingerprint": fingerprint,
        "documents_total": total,
        "documents_completed": len(completed),
        "completed_documents": sorted(completed),
        "published_nodes": published_nodes,
        "progress": 1.0,
    }
    _atomic_json(checkpoint_path, result)
    if progress:
        progress(dict(result))
    return result
