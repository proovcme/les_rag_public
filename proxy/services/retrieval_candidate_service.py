"""Deterministic candidate deduplication and document diversity for RAG."""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any, Mapping, Sequence


def _meta(chunk: Any) -> Mapping[str, Any]:
    value = getattr(chunk, "meta", {}) or {}
    return value if isinstance(value, Mapping) else {}


def _clean(value: Any) -> str:
    return str(value or "").strip().replace("\\", "/")


def _source_path(chunk: Any) -> str:
    meta = _meta(chunk)
    source_ref = _clean(meta.get("source_ref") or getattr(chunk, "source_ref", ""))
    if source_ref:
        return source_ref.split("#", 1)[0].casefold()
    for key in ("file_path", "source_path", "relative_path", "path"):
        value = _clean(meta.get(key))
        if value:
            return value.casefold()
    return _clean(getattr(chunk, "doc_name", "") or meta.get("doc_name")).casefold()


def physical_document_identity(chunk: Any) -> str:
    """Identify a physical document without collapsing equal basenames across paths."""

    meta = _meta(chunk)
    dataset_id = _clean(meta.get("dataset_id") or getattr(chunk, "dataset_id", "")).casefold()
    norm_code = _clean(meta.get("norm_code")).casefold()
    if norm_code:
        return f"norm:{dataset_id}:{norm_code}"
    doc_id = _clean(getattr(chunk, "doc_id", "") or meta.get("doc_id")).casefold()
    if doc_id:
        return f"doc:{dataset_id}:{doc_id}"
    path = _source_path(chunk)
    if path:
        return f"path:{dataset_id}:{path}"
    content = _clean(getattr(chunk, "content", ""))
    digest = hashlib.sha1(content.encode("utf-8", errors="ignore")).hexdigest()
    return f"anonymous:{dataset_id}:{digest}"


def candidate_identity(chunk: Any) -> tuple[str, str]:
    """Return document and exact-fragment identities for stable duplicate collapse."""

    meta = _meta(chunk)
    document = physical_document_identity(chunk)
    fragment = _clean(
        meta.get("chunk_id")
        or getattr(chunk, "chunk_id", "")
        or meta.get("point_id")
        or meta.get("_point_id")
        or meta.get("content_hash")
    ).casefold()
    if not fragment:
        page = _clean(meta.get("page") or getattr(chunk, "page", ""))
        content = _clean(getattr(chunk, "content", ""))
        digest = hashlib.sha1(content.encode("utf-8", errors="ignore")).hexdigest()
        fragment = f"page:{page}:sha1:{digest}"
    return document, fragment


def collapse_exact_duplicates(chunks: Sequence[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for chunk in chunks:
        identity = candidate_identity(chunk)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(chunk)
    return result


def select_diverse_candidates(
    chunks: Sequence[Any],
    *,
    per_document_k: int,
    limit: int,
) -> list[Any]:
    """Preserve rank order while limiting repeated excerpts from one document."""

    selected: list[Any] = []
    counts: Counter[str] = Counter()
    document_limit = max(1, int(per_document_k))
    result_limit = max(1, int(limit))
    for chunk in collapse_exact_duplicates(chunks):
        document = physical_document_identity(chunk)
        if counts[document] >= document_limit:
            continue
        counts[document] += 1
        selected.append(chunk)
        if len(selected) >= result_limit:
            break
    return selected
