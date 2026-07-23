"""Append-only JSON revisions for deterministic estimate recalculation."""

from __future__ import annotations

import json
from pathlib import Path

from proxy.smeta_core.contracts import LSRRevision


DEFAULT_ROOT = Path("storage/smeta_revisions")


def save_revision(revision: LSRRevision, *, root: str | Path = DEFAULT_ROOT) -> Path:
    target_root = Path(root)
    target_root.mkdir(parents=True, exist_ok=True)
    target = target_root / f"{revision.revision_id}.json"
    if target.exists():
        raise FileExistsError(f"revision already exists: {revision.revision_id}")
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(revision.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)
    return target


def load_revision(revision_id: str, *, root: str | Path = DEFAULT_ROOT) -> dict:
    safe_id = "".join(ch for ch in str(revision_id) if ch.isalnum() or ch in {"-", "_"})
    if safe_id != revision_id or not safe_id:
        raise ValueError("invalid revision id")
    return json.loads((Path(root) / f"{safe_id}.json").read_text(encoding="utf-8"))
