"""Immutable model-visible evidence manifests for dialogue continuity."""

from __future__ import annotations

import copy
import re
from typing import Any, Mapping, Sequence

from proxy.services.source_locator_service import source_map_item


SCHEMA = "les.chat-evidence-manifest.v1"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _cited_ids(answer: str, visible: Sequence[Mapping[str, Any]]) -> list[str]:
    index_to_id: dict[int, str] = {}
    valid: set[str] = set()
    for position, raw in enumerate(visible, 1):
        item = _mapping(raw)
        identity = str(item.get("id") or f"S{position}").strip().upper()
        index_to_id[position] = identity
        valid.add(identity)
    cited: set[str] = set()
    for group in re.findall(
        r"\[Источники?\s+([0-9,;|\s]+)\]",
        str(answer or ""),
        flags=re.IGNORECASE,
    ):
        for value in re.findall(r"\d+", group):
            identity = index_to_id.get(int(value))
            if identity:
                cited.add(identity)
    for value in re.findall(r"Q\d+\.H\d+", str(answer or ""), flags=re.IGNORECASE):
        identity = value.upper()
        if identity in valid:
            cited.add(identity)
    return [str(item.get("id") or "") for item in visible if str(item.get("id") or "").upper() in cited]


def build_evidence_manifest(
    *,
    query: str,
    scope: Mapping[str, Any],
    chunks: Sequence[Any],
    answer: str,
) -> dict[str, Any]:
    """Freeze the evidence that actually entered the model context for one turn."""

    visible: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, 1):
        source = source_map_item(chunk, index=index)
        identity = str(source.get("evidence_ref") or f"S{index}")
        visible.append(
            {
                "id": identity,
                "label": str(source.get("label") or f"Источник {index}"),
                "doc_name": str(source.get("doc_name") or ""),
                "doc_id": str(source.get("doc_id") or ""),
                "dataset_id": str(source.get("dataset_id") or ""),
                "locator": copy.deepcopy(source.get("locator") or {}),
            }
        )
    return {
        "schema": SCHEMA,
        "query": str(query or ""),
        "scope": copy.deepcopy(dict(scope or {})),
        "model_visible": copy.deepcopy(visible),
        "cited_ids": _cited_ids(answer, visible),
    }


def compact_prior_evidence_index(
    manifests: Sequence[Mapping[str, Any]],
    *,
    max_items: int = 24,
) -> tuple[dict[str, Any], ...]:
    """Keep addressable prior handles and locators, never prior evidence bodies."""

    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw_manifest in reversed(list(manifests)):
        manifest = _mapping(raw_manifest)
        cited = {str(value) for value in (manifest.get("cited_ids") or [])}
        visible = [
            _mapping(item)
            for item in (manifest.get("model_visible") or [])
            if isinstance(item, Mapping)
        ]
        visible.sort(key=lambda item: str(item.get("id") or "") not in cited)
        for item in visible:
            locator = _mapping(item.get("locator"))
            locator.pop("excerpt", None)
            identity = str(item.get("id") or "")
            key = (identity, repr(sorted(locator.items())))
            if not identity or key in seen:
                continue
            seen.add(key)
            result.append(
                {
                    "id": identity,
                    "doc_name": str(item.get("doc_name") or ""),
                    "locator": copy.deepcopy(locator),
                    "cited": identity in cited,
                    "query": str(manifest.get("query") or "")[:240],
                }
            )
            if len(result) >= max(1, int(max_items)):
                return tuple(result)
    return tuple(result)


def format_prior_evidence_index(items: Sequence[Mapping[str, Any]]) -> str:
    if not items:
        return ""
    lines = [
        "Индекс evidence предыдущих реплик (это адреса для повторного чтения, не самостоятельное основание):"
    ]
    for raw in items:
        item = _mapping(raw)
        locator = _mapping(item.get("locator"))
        coordinate = (
            locator.get("source_ref")
            or locator.get("url")
            or locator.get("card_code")
            or locator.get("relative_path")
            or locator.get("reason")
            or "координата недоступна"
        )
        cited = " · цитировался" if item.get("cited") else ""
        lines.append(
            f"- {item.get('id')}: {item.get('doc_name') or locator.get('title') or 'источник'}"
            f" · {coordinate}{cited}"
        )
    return "\n".join(lines)
