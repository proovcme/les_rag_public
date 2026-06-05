"""Context-window expansion for retrieved RAG evidence."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from proxy.services.lexical_index_service import LexicalIndex, lexical_enabled


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def context_window_enabled() -> bool:
    return os.getenv("RAG_CONTEXT_WINDOW_ENABLED", "true").lower() in {"1", "true", "yes", "on"}


@dataclass
class ExpandedContextChunk:
    content: str
    doc_id: str
    doc_name: str
    score: float
    meta: dict[str, Any]


@dataclass
class ContextExpansionResult:
    chunks: list[Any]
    enabled: bool
    input_count: int
    expanded_count: int = 0
    inline_count: int = 0
    lexical_count: int = 0
    fallback_count: int = 0
    max_chars_per_chunk: int = 0
    radius: int = 0

    def payload(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "input_count": self.input_count,
            "output_count": len(self.chunks),
            "expanded_count": self.expanded_count,
            "inline_count": self.inline_count,
            "lexical_count": self.lexical_count,
            "fallback_count": self.fallback_count,
            "max_chars_per_chunk": self.max_chars_per_chunk,
            "radius": self.radius,
        }


def expand_context_windows(
    chunks: list[Any],
    *,
    collection: str = "",
    logger: logging.Logger | None = None,
    max_chunks: int | None = None,
    max_chars_per_chunk: int | None = None,
    radius: int | None = None,
) -> ContextExpansionResult:
    """Add adjacent/parent context where metadata exists; old chunks stay untouched."""
    enabled = context_window_enabled()
    selected = list(chunks[: max_chunks or len(chunks)])
    max_chars = max_chars_per_chunk or _env_int("RAG_CONTEXT_WINDOW_CHARS", 2200)
    neighbor_radius = radius if radius is not None else _env_int("RAG_CONTEXT_NEIGHBOR_RADIUS", 1)
    result = ContextExpansionResult(
        chunks=selected,
        enabled=enabled,
        input_count=len(selected),
        max_chars_per_chunk=max_chars,
        radius=neighbor_radius,
    )
    if not enabled or not selected:
        return result

    index = None
    if collection and lexical_enabled():
        try:
            index = LexicalIndex()
        except Exception as error:
            if logger:
                logger.warning("[CTX] lexical context unavailable: %s", error)

    expanded: list[Any] = []
    for chunk in selected:
        source = ""
        neighbors: list[Any] = []
        if index is not None and _has_window_key(chunk):
            try:
                neighbors = index.context_window(
                    collection,
                    chunk,
                    radius=neighbor_radius,
                    limit=max(5, neighbor_radius * 2 + 1),
                )
            except Exception as error:
                if logger:
                    logger.warning("[CTX] context lookup skipped: %s", error)
                neighbors = []
        if len(neighbors) > 1:
            source = "lexical_parent" if _meta(chunk).get("parent_id") else "lexical_neighbors"
        elif _has_inline_window(chunk):
            source = "inline_neighbors"

        if source:
            expanded_chunk = _expanded_chunk(chunk, neighbors, source=source, max_chars=max_chars)
            expanded.append(expanded_chunk)
            result.expanded_count += 1
            if source.startswith("lexical"):
                result.lexical_count += 1
            else:
                result.inline_count += 1
        else:
            expanded.append(chunk)
            result.fallback_count += 1

    result.chunks = expanded
    return result


def _has_window_key(chunk: Any) -> bool:
    meta = _meta(chunk)
    if meta.get("parent_id"):
        return True
    return meta.get("chunk_ord") is not None and bool(meta.get("dataset_id")) and bool(
        meta.get("file_name") or getattr(chunk, "doc_name", "")
    )


def _has_inline_window(chunk: Any) -> bool:
    meta = _meta(chunk)
    return bool(meta.get("context_before") or meta.get("context_after") or meta.get("parent_heading"))


def _expanded_chunk(chunk: Any, neighbors: list[Any], *, source: str, max_chars: int) -> ExpandedContextChunk:
    original_meta = _meta(chunk)
    meta = dict(original_meta)
    base_text = str(getattr(chunk, "content", "") or "")
    base_hash = str(original_meta.get("content_hash") or _fingerprint(base_text))
    base_ord = _chunk_ord(original_meta)
    parts: list[tuple[str, str]] = []
    heading = str(original_meta.get("parent_heading") or original_meta.get("section_heading") or "").strip()
    if heading:
        parts.append(("Раздел", heading))

    if neighbors:
        for neighbor in neighbors:
            n_text = str(getattr(neighbor, "content", "") or "")
            if not n_text.strip():
                continue
            n_meta = _meta(neighbor)
            n_hash = str(n_meta.get("content_hash") or _fingerprint(n_text))
            n_ord = _chunk_ord(n_meta)
            if n_hash == base_hash or (base_ord is not None and n_ord == base_ord):
                label = "Основной фрагмент"
            elif base_ord is not None and n_ord is not None and n_ord < base_ord:
                label = "Контекст до"
            elif base_ord is not None and n_ord is not None and n_ord > base_ord:
                label = "Контекст после"
            else:
                label = "Соседний фрагмент"
            parts.append((label, n_text))
    else:
        before = str(original_meta.get("context_before") or "").strip()
        after = str(original_meta.get("context_after") or "").strip()
        if before:
            parts.append(("Контекст до", before))
        parts.append(("Основной фрагмент", base_text))
        if after:
            parts.append(("Контекст после", after))

    if not any(label == "Основной фрагмент" for label, _ in parts):
        parts.insert(1 if heading else 0, ("Основной фрагмент", base_text))

    content = _dedup_and_format(parts)
    if max_chars and len(content) > max_chars:
        content = content[: max_chars - 1].rstrip() + "…"
    meta.update(
        {
            "context_expanded": True,
            "context_window_source": source,
            "context_window_chars": len(content),
        }
    )
    return ExpandedContextChunk(
        content=content,
        doc_id=str(getattr(chunk, "doc_id", original_meta.get("doc_id", "")) or ""),
        doc_name=str(getattr(chunk, "doc_name", original_meta.get("file_name", "")) or ""),
        score=float(getattr(chunk, "score", 0.0) or 0.0),
        meta=meta,
    )


def _dedup_and_format(parts: list[tuple[str, str]]) -> str:
    seen: set[str] = set()
    rendered: list[str] = []
    for label, text in parts:
        compact = re.sub(r"\s+", " ", text).strip()
        if not compact:
            continue
        key = compact[:500].casefold()
        if key in seen:
            continue
        seen.add(key)
        rendered.append(f"{label}: {compact}")
    return "\n".join(rendered)


def _meta(chunk: Any) -> dict[str, Any]:
    meta = getattr(chunk, "meta", {}) or {}
    return meta if isinstance(meta, dict) else {}


def _chunk_ord(meta: dict[str, Any]) -> int | None:
    try:
        return int(meta.get("chunk_ord"))
    except (TypeError, ValueError):
        return None


def _fingerprint(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()[:500]
