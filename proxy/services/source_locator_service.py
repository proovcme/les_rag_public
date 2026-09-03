"""Typed, honest source locators shared by chat evidence and Sovushka."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _value(*values: Any) -> Any:
    return next((value for value in values if value not in (None, "")), "")


def _text(value: Any) -> str:
    return str(value or "").strip()


def citation_indexes(answer: str) -> list[int]:
    """Read explicit visible source labels, including model-written ranges."""

    indexes: set[int] = set()
    for marker in re.findall(
        r"\[Источники?\s+([^\]]+)\]",
        _text(answer),
        flags=re.IGNORECASE,
    ):
        for position, segment in enumerate(marker.split("|")):
            value = segment.strip()
            if position and not re.fullmatch(r"[0-9,;\s\-–—]+", value):
                continue
            for token in re.finditer(r"(\d+)\s*[\-–—]\s*(\d+)|(\d+)", value):
                if token.group(3):
                    indexes.add(int(token.group(3)))
                    continue
                start, end = int(token.group(1)), int(token.group(2))
                if start <= end and end - start <= 1000:
                    indexes.update(range(start, end + 1))
                else:
                    indexes.update((start, end))
    return sorted(indexes)


def _relative_path(source_ref: str, doc_name: str) -> str:
    path = source_ref.split("#", 1)[0].replace("\\", "/").strip("/")
    return path or doc_name.replace("\\", "/").strip("/")


def source_locator(
    chunk: Any,
    *,
    source: Mapping[str, Any] | None = None,
    excerpt: str | None = None,
) -> dict[str, Any]:
    """Return one typed locator without inventing a file, page, or card."""

    source_data = _mapping(source)
    meta = _mapping(getattr(chunk, "meta", {}))
    content = _text(excerpt if excerpt is not None else getattr(chunk, "content", ""))
    doc_name = _text(_value(source_data.get("doc_name"), getattr(chunk, "doc_name", "")))
    doc_id = _text(_value(source_data.get("doc_id"), getattr(chunk, "doc_id", ""), meta.get("doc_id")))
    dataset_id = _text(_value(source_data.get("dataset_id"), meta.get("dataset_id"), getattr(chunk, "dataset_id", "")))
    source_ref = _text(
        _value(
            source_data.get("source_ref"),
            meta.get("source_ref"),
            getattr(chunk, "source_ref", ""),
        )
    )
    norm_code = _text(_value(source_data.get("norm_code"), meta.get("norm_code")))
    if norm_code or doc_name == "smeta_norm_cards.v1":
        locator: dict[str, Any] = {
            "kind": "norm_card",
            "dataset_id": dataset_id,
            "card_code": norm_code,
            "excerpt": content,
        }
        if source_ref:
            locator["source_ref"] = source_ref
        return {key: value for key, value in locator.items() if value not in (None, "")}

    url = _text(_value(source_data.get("url"), meta.get("url"), meta.get("canonical_url")))
    if not url and source_ref.startswith(("https://", "http://")):
        url = source_ref
    if url:
        locator = {
            "kind": "web_result",
            "url": url,
            "title": _text(_value(source_data.get("title"), meta.get("title"), doc_name)),
            "provider": _text(_value(source_data.get("provider"), meta.get("provider"))),
            "retrieved_at": _text(_value(source_data.get("retrieved_at"), meta.get("retrieved_at"))),
            "excerpt": content,
        }
        return {key: value for key, value in locator.items() if value not in (None, "")}

    relative_path = _relative_path(
        source_ref or _text(_value(meta.get("file_path"), meta.get("source_path"))),
        doc_name,
    )
    if source_ref or doc_id or relative_path:
        locator = {
            "kind": "file_excerpt",
            "dataset_id": dataset_id,
            "doc_id": doc_id,
            "source_ref": source_ref,
            "relative_path": relative_path,
            "page": _value(
                source_data.get("page"),
                source_data.get("source_page"),
                source_data.get("page_number"),
                meta.get("page"),
                meta.get("source_page"),
                meta.get("page_number"),
                getattr(chunk, "page", ""),
            ),
            "chunk_id": _text(
                _value(
                    source_data.get("chunk_id"),
                    meta.get("chunk_id"),
                    meta.get("point_id"),
                    getattr(chunk, "chunk_id", ""),
                )
            ),
            "parent_heading": _text(
                _value(source_data.get("parent_heading"), meta.get("parent_heading"))
            ),
            "section_heading": _text(
                _value(source_data.get("section_heading"), meta.get("section_heading"))
            ),
            "sheet": _text(
                _value(
                    source_data.get("sheet"),
                    source_data.get("sheet_name"),
                    meta.get("sheet"),
                    meta.get("sheet_name"),
                )
            ),
            "row": _value(
                source_data.get("row"),
                source_data.get("row_number"),
                meta.get("row"),
                meta.get("row_number"),
            ),
            "cell": _text(_value(source_data.get("cell"), meta.get("cell"))),
            "excerpt": content,
        }
        return {key: value for key, value in locator.items() if value not in (None, "")}

    return {
        "kind": "unavailable",
        "reason": "source_locator_missing",
        "excerpt": content,
    }


def source_map_item(chunk: Any, *, index: int, excerpt_chars: int = 360) -> dict[str, Any]:
    meta = _mapping(getattr(chunk, "meta", {}))
    excerpt = _text(getattr(chunk, "content", ""))[: max(1, int(excerpt_chars))]
    locator = source_locator(chunk, excerpt=excerpt)
    item: dict[str, Any] = {
        "index": int(index),
        "label": f"Источник {int(index)}",
        "doc_name": _text(getattr(chunk, "doc_name", "")),
        "doc_id": _text(getattr(chunk, "doc_id", "")),
        "dataset_id": _text(meta.get("dataset_id")),
        "snippet": excerpt,
        "locator": locator,
        "score": round(float(getattr(chunk, "score", 0.0) or 0.0), 4),
    }
    for key in ("source_ref", "page", "source_page", "page_number", "chunk_id"):
        value = _value(meta.get(key), locator.get(key))
        if value not in (None, ""):
            item[key] = value
    evidence_ref = _text(meta.get("model_evidence_ref"))
    if evidence_ref:
        item["evidence_ref"] = evidence_ref
    norm_code = _text(meta.get("norm_code"))
    if norm_code:
        item["norm_code"] = norm_code
    return item


def evidence_counts(
    *,
    answer: str,
    source_map: Sequence[Mapping[str, Any]],
    found_count: int,
) -> dict[str, int]:
    """Count internal candidates, model-visible evidence, and valid citations separately."""

    index_to_handle: dict[int, str] = {}
    valid_handles: set[str] = set()
    for position, raw in enumerate(source_map, 1):
        item = _mapping(raw)
        index = int(item.get("index") or position)
        handle = _text(item.get("evidence_ref")).upper() or f"S{index}"
        index_to_handle[index] = handle
        valid_handles.add(handle)

    cited: set[str] = set()
    for raw_index in citation_indexes(answer):
        handle = index_to_handle.get(raw_index)
        if handle:
            cited.add(handle)
    for handle in re.findall(r"Q\d+\.H\d+", _text(answer), flags=re.IGNORECASE):
        normalized = handle.upper()
        if normalized in valid_handles:
            cited.add(normalized)
    return {
        "found": max(0, int(found_count)),
        "model_visible": len(source_map),
        "cited": len(cited),
    }
