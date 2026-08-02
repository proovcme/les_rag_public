"""Parent-card hydration after retrieval/rerank.

Search hits short chunks; analysis needs the parent window (siblings sharing
``parent_id``). This service never chooses a professional answer — it only
attaches a typed ``les.parent_card.v1`` object to chunk metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

PARENT_CARD_SCHEMA = "les.parent_card.v1"

SiblingProvider = Callable[[str, str], list[Any]]


@dataclass
class ParentHydrationResult:
    chunks: list[Any]
    hydrated_count: int = 0
    pool_sibling_count: int = 0
    provider_sibling_count: int = 0
    skipped_without_parent: int = 0

    def payload(self) -> dict[str, Any]:
        return {
            "schema": PARENT_CARD_SCHEMA,
            "hydrated_count": self.hydrated_count,
            "pool_sibling_count": self.pool_sibling_count,
            "provider_sibling_count": self.provider_sibling_count,
            "skipped_without_parent": self.skipped_without_parent,
            "output_count": len(self.chunks),
        }


@dataclass
class _Sibling:
    text: str
    doc_name: str
    doc_id: str
    chunk_ord: int | None
    content_hash: str
    source: str


def hydrate_parent_cards(
    chunks: Iterable[Any],
    *,
    sibling_provider: SiblingProvider | None = None,
    max_chunks: int = 8,
    max_siblings: int = 12,
) -> ParentHydrationResult:
    """Attach ``meta.parent_card`` for top hits that carry ``parent_id``.

    Siblings are gathered first from the current candidate pool (same parent),
    then optionally from ``sibling_provider(parent_id, dataset_id)``.
    """
    selected = list(chunks)
    result = ParentHydrationResult(chunks=selected)
    if not selected:
        return result

    by_parent: dict[str, list[Any]] = {}
    for chunk in selected:
        parent_id = _parent_id(chunk)
        if parent_id:
            by_parent.setdefault(parent_id, []).append(chunk)

    for index, chunk in enumerate(selected[: max(0, max_chunks)]):
        meta = _meta(chunk)
        parent_id = str(meta.get("parent_id") or "").strip()
        if not parent_id:
            result.skipped_without_parent += 1
            continue
        if isinstance(meta.get("parent_card"), dict) and meta["parent_card"].get("schema") == PARENT_CARD_SCHEMA:
            continue

        siblings: list[_Sibling] = []
        seen: set[str] = set()
        for peer in by_parent.get(parent_id, []):
            item = _as_sibling(peer, source="candidate_pool")
            key = item.content_hash or item.text[:240].casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            siblings.append(item)
            result.pool_sibling_count += 1

        dataset_id = str(meta.get("dataset_id") or "")
        if sibling_provider is not None and len(siblings) < max_siblings:
            try:
                fetched = sibling_provider(parent_id, dataset_id) or []
            except Exception:
                fetched = []
            for peer in fetched:
                item = _as_sibling(peer, source="provider")
                key = item.content_hash or item.text[:240].casefold()
                if not key or key in seen:
                    continue
                seen.add(key)
                siblings.append(item)
                result.provider_sibling_count += 1
                if len(siblings) >= max_siblings:
                    break

        siblings.sort(key=lambda item: (item.chunk_ord is None, item.chunk_ord or 0))
        siblings = siblings[:max_siblings]
        card = {
            "schema": PARENT_CARD_SCHEMA,
            "parent_id": parent_id,
            "parent_heading": str(
                meta.get("parent_heading") or meta.get("section_heading") or ""
            ).strip(),
            "hit_role": "search_chunk",
            "sibling_count": len(siblings),
            "texts": [item.text for item in siblings if item.text],
            "source_refs": [
                {
                    "doc_id": item.doc_id,
                    "doc_name": item.doc_name,
                    "chunk_ord": item.chunk_ord,
                    "source": item.source,
                }
                for item in siblings
            ],
        }
        meta = dict(meta)
        meta["parent_card"] = card
        meta["parent_card_hydrated"] = True
        _set_meta(chunk, meta)
        selected[index] = chunk
        result.hydrated_count += 1

    result.chunks = selected
    return result


def _parent_id(chunk: Any) -> str:
    return str(_meta(chunk).get("parent_id") or "").strip()


def _meta(chunk: Any) -> dict[str, Any]:
    meta = getattr(chunk, "meta", None)
    if isinstance(meta, dict) and meta:
        return meta
    meta = getattr(chunk, "metadata", None)
    return meta if isinstance(meta, dict) else {}


def _set_meta(chunk: Any, meta: dict[str, Any]) -> None:
    if hasattr(chunk, "meta"):
        chunk.meta = meta
    elif hasattr(chunk, "metadata"):
        chunk.metadata = meta


def _as_sibling(chunk: Any, *, source: str) -> _Sibling:
    meta = _meta(chunk)
    text = str(getattr(chunk, "content", "") or meta.get("text") or "").strip()
    try:
        ord_value = int(meta["chunk_ord"]) if meta.get("chunk_ord") is not None else None
    except (TypeError, ValueError):
        ord_value = None
    return _Sibling(
        text=text,
        doc_name=str(getattr(chunk, "doc_name", "") or meta.get("file_name") or ""),
        doc_id=str(getattr(chunk, "doc_id", "") or meta.get("doc_id") or ""),
        chunk_ord=ord_value,
        content_hash=str(meta.get("content_hash") or ""),
        source=source,
    )
