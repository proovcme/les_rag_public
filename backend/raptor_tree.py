"""Deterministic, resumable RAPTOR navigation tree contracts.

Summaries route retrieval only. Every node stores descendant leaf ids, and the
evidence boundary must descend to those leaves before citations are produced.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable


RAPTOR_SCHEMA = "les.rag.raptor.v1"


@dataclass(frozen=True)
class RaptorLeaf:
    point_id: str
    document_id: str
    text: str


@dataclass(frozen=True)
class RaptorNode:
    node_id: str
    depth: int
    title: str
    summary: str
    child_ids: tuple[str, ...]
    descendant_leaf_ids: tuple[str, ...]
    node_role: str = "navigation"
    node_kind: str = "raptor_summary"
    schema: str = RAPTOR_SCHEMA

    def payload(self) -> dict:
        return asdict(self)


def _node_id(depth: int, child_ids: Iterable[str]) -> str:
    identity = f"{RAPTOR_SCHEMA}:{depth}:" + "|".join(child_ids)
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def build_tree(
    leaves: list[RaptorLeaf],
    summarizer: Callable[[list[str], int], tuple[str, str]],
    *,
    fanout: int = 8,
    max_depth: int = 3,
) -> list[RaptorNode]:
    """Build stable document-local groups, then recursively group summaries."""
    if fanout < 2:
        raise ValueError("RAPTOR_FANOUT_INVALID")
    ordered = sorted(leaves, key=lambda leaf: (leaf.document_id, leaf.point_id))
    current: list[tuple[str, str, tuple[str, ...]]] = [
        (leaf.point_id, leaf.text, (leaf.point_id,)) for leaf in ordered
    ]
    nodes: list[RaptorNode] = []
    for depth in range(1, max(1, max_depth) + 1):
        if len(current) <= 1:
            break
        next_level: list[tuple[str, str, tuple[str, ...]]] = []
        for start in range(0, len(current), fanout):
            group = current[start:start + fanout]
            child_ids = tuple(item[0] for item in group)
            descendants = tuple(dict.fromkeys(leaf_id for item in group for leaf_id in item[2]))
            title, summary = summarizer([item[1] for item in group], depth)
            node = RaptorNode(
                node_id=_node_id(depth, child_ids), depth=depth,
                title=str(title).strip()[:240], summary=str(summary).strip(),
                child_ids=child_ids, descendant_leaf_ids=descendants,
            )
            nodes.append(node)
            next_level.append((node.node_id, f"{node.title}\n{node.summary}", descendants))
        current = next_level
    return nodes


def save_checkpoint(path: Path, *, completed_leaf_hash: str, nodes: list[RaptorNode]) -> None:
    payload = {
        "schema": RAPTOR_SCHEMA,
        "completed_leaf_hash": completed_leaf_hash,
        "nodes": [node.payload() for node in nodes],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def evidence_leaf_ids(nodes: Iterable[RaptorNode]) -> list[str]:
    """The only ids allowed to cross from RAPTOR navigation into evidence retrieval."""
    return list(dict.fromkeys(leaf for node in nodes for leaf in node.descendant_leaf_ids))
