"""Versioned active normative-base pointer."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = Path("config/domain/smeta_base_active.json")
CODE_ROOT = Path(__file__).resolve().parents[2]


def runtime_data_path(path: str | Path) -> Path:
    """Resolve shipped data through writable Windows state, never the install junction."""
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    state_root = os.getenv("LES_WINDOWS_STATE_ROOT", "").strip()
    if state_root and candidate.parts and candidate.parts[0].casefold() == "data":
        return Path(state_root).joinpath(*candidate.parts)
    return CODE_ROOT / candidate


def active_base(config_path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    try:
        payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    base_path = os.getenv("LES_SMETA_STRUCTURED_BASE", "").strip() or str(payload.get("base_path") or "")
    base = Path(base_path) if base_path else Path("data/smeta_base/les_smeta_base_v2.sqlite")
    return {
        "schema": "smeta_base_active_v1",
        "edition": str(payload.get("edition") or ""),
        "base_path": str(base),
        "manifest_path": str(payload.get("manifest_path") or base.with_name(f"{base.stem}_manifest.json")),
        "integrity_path": str(payload.get("integrity_path") or base.with_name(f"{base.stem}_integrity.json")),
        "source_path": str(payload.get("source_path") or ""),
        "minimum_norms": max(1, int(payload.get("minimum_norms") or 1)),
        "rag_collection": str(payload.get("rag_collection") or "les_smeta_norm_cards_v1"),
        "rag_embedding_model": str(payload.get("rag_embedding_model") or "qwen3-embedding-0.6b"),
    }
