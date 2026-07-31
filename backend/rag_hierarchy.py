"""Shared deterministic hierarchy contract for LES retrieval.

Navigation nodes route retrieval but are never admissible answer evidence.
Evidence nodes remain globally searchable, so a hierarchy miss cannot hide a
relevant leaf.  The module is domain-neutral and contains no professional
selection rules.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

HIERARCHY_SCHEMA = "les.rag.hierarchy.v1"
HIERARCHY_BUILDER = "deterministic-heading-stack-v1"
NAVIGATION_ROLE = "navigation"
EVIDENCE_ROLE = "evidence"


def deterministic_node_id(
    *,
    dataset_id: str,
    document_id: str,
    node_kind: str,
    identity: str,
) -> str:
    raw = json.dumps(
        [HIERARCHY_SCHEMA, dataset_id, document_id, node_kind, identity],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def evidence_payload(
    *,
    dataset_id: str,
    document_id: str,
    identity: str,
    ancestor_ids: Iterable[str] = (),
    depth: int = 0,
    node_kind: str = "chunk",
) -> dict[str, Any]:
    ancestors = [str(value) for value in ancestor_ids if str(value)]
    return {
        "hierarchy_schema": HIERARCHY_SCHEMA,
        "hierarchy_builder": HIERARCHY_BUILDER,
        "node_id": deterministic_node_id(
            dataset_id=dataset_id,
            document_id=document_id,
            node_kind=node_kind,
            identity=identity,
        ),
        "node_role": EVIDENCE_ROLE,
        "node_kind": node_kind,
        "hierarchy_depth": max(0, int(depth)),
        "ancestor_ids": ancestors,
        "hierarchy_parent_id": ancestors[-1] if ancestors else "",
        "evidence_admissible": True,
    }


def navigation_payload(
    *,
    dataset_id: str,
    document_id: str,
    identity: str,
    title: str,
    ancestor_ids: Iterable[str] = (),
    depth: int,
    node_kind: str = "section",
) -> dict[str, Any]:
    ancestors = [str(value) for value in ancestor_ids if str(value)]
    return {
        "hierarchy_schema": HIERARCHY_SCHEMA,
        "hierarchy_builder": HIERARCHY_BUILDER,
        "node_id": deterministic_node_id(
            dataset_id=dataset_id,
            document_id=document_id,
            node_kind=node_kind,
            identity=identity,
        ),
        "node_role": NAVIGATION_ROLE,
        "node_kind": node_kind,
        "hierarchy_depth": max(0, int(depth)),
        "ancestor_ids": ancestors,
        "hierarchy_parent_id": ancestors[-1] if ancestors else "",
        "navigation_title": str(title or ""),
        "evidence_admissible": False,
    }


def evidence_only(items: Iterable[Any]) -> list[Any]:
    """Drop navigation hits before rerank/citation, accepting legacy evidence."""
    result: list[Any] = []
    for item in items:
        meta = getattr(item, "meta", None) or getattr(item, "metadata", None) or {}
        if str(meta.get("node_role") or EVIDENCE_ROLE) == EVIDENCE_ROLE:
            result.append(item)
    return result


def reciprocal_rank_fuse(
    rankings: Iterable[Iterable[Any]],
    *,
    limit: int,
    rank_constant: int = 60,
) -> list[Any]:
    """Fuse hierarchy/global evidence legs without inventing score semantics."""
    scores: dict[str, float] = {}
    values: dict[str, Any] = {}
    first_seen: dict[str, int] = {}
    serial = 0
    for ranking in rankings:
        for rank, item in enumerate(evidence_only(ranking), 1):
            meta = getattr(item, "meta", None) or getattr(item, "metadata", None) or {}
            key = str(
                meta.get("node_id")
                or getattr(item, "doc_id", "")
                or f"{getattr(item, 'doc_name', '')}:{getattr(item, 'content', '')}"
            )
            if key not in first_seen:
                first_seen[key] = serial
                serial += 1
            values[key] = item
            scores[key] = scores.get(key, 0.0) + 1.0 / (rank_constant + rank)
    ordered = sorted(scores, key=lambda key: (-scores[key], first_seen[key]))
    result = [values[key] for key in ordered[: max(0, limit)]]
    for item in result:
        try:
            item.score = scores[str(
                (getattr(item, "meta", None) or getattr(item, "metadata", None) or {}).get("node_id")
                or getattr(item, "doc_id", "")
                or f"{getattr(item, 'doc_name', '')}:{getattr(item, 'content', '')}"
            )]
        except Exception:
            pass
    return result
