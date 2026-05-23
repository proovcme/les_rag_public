"""Shared resource-mode helpers for LES runtime.

This is intentionally small: it gives routers one vocabulary for chat/indexing
mode decisions without coupling them to UI state.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

CHAT_MODE = "chat"
INDEXING_MODE = "indexing"
MAINTENANCE_MODE = "maintenance"

DEFAULT_PARSE_PRIORITY_ORDER = (
    "NTD_FIRE_Index",
    "GKRF_Index",
    "NTD_ELECTRICAL_Index",
    "NTD_STRUCTURAL_Index",
    "TABLE_SMETA_Index",
    "NTD_OTHER_Index",
)


def default_parse_priority_order() -> list[str]:
    raw = os.getenv("RAG_PARSE_PRIORITY_ORDER", "")
    if raw.strip():
        return [item.strip() for item in raw.split(",") if item.strip()]
    return list(DEFAULT_PARSE_PRIORITY_ORDER)


def normalize_mode(mode: str | None) -> str:
    value = (mode or CHAT_MODE).strip().lower()
    if value == "rag":
        return CHAT_MODE
    return value


def current_resource_mode(current_mode: dict[str, Any] | None) -> str:
    if not current_mode:
        return CHAT_MODE
    return normalize_mode(str(current_mode.get("mode") or CHAT_MODE))


def is_indexing_mode(current_mode: dict[str, Any] | None) -> bool:
    return current_resource_mode(current_mode) == INDEXING_MODE


def chat_generation_allowed(current_mode: dict[str, Any] | None) -> tuple[bool, str]:
    mode = current_resource_mode(current_mode)
    if mode == INDEXING_MODE:
        return False, "Indexing mode is active: chat generation is paused to protect MLX memory."
    if mode == MAINTENANCE_MODE:
        return False, "Maintenance mode is active: chat generation is paused."
    return True, "chat generation allowed"


def active_parse_priority_order(
    current_mode: dict[str, Any] | None,
    requested: list[str] | None = None,
) -> list[str]:
    if requested:
        return [item.strip() for item in requested if item.strip()]
    if current_mode and isinstance(current_mode.get("parse_priority_order"), list):
        return [str(item) for item in current_mode["parse_priority_order"] if str(item).strip()]
    return default_parse_priority_order()


def enter_indexing_mode(
    current_mode: dict[str, Any],
    *,
    reason: str = "manual",
    priority_order: list[str] | None = None,
) -> dict[str, Any]:
    current_mode.clear()
    current_mode.update(
        {
            "mode": INDEXING_MODE,
            "model": "embedder",
            "reason": reason,
            "chat_generation": "paused",
            "parse_concurrency": 1,
            "parse_priority_order": active_parse_priority_order(None, priority_order),
            "switched_at": datetime.now().isoformat(),
        }
    )
    return current_mode


def enter_chat_mode(current_mode: dict[str, Any], *, reason: str = "manual") -> dict[str, Any]:
    current_mode.clear()
    current_mode.update(
        {
            "mode": CHAT_MODE,
            "model": os.getenv("LLM_MODEL", "mlx-community/Qwen3-14B-4bit"),
            "reason": reason,
            "chat_generation": "allowed",
            "switched_at": datetime.now().isoformat(),
        }
    )
    return current_mode
