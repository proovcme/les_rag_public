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

PROFILE_STOPPED = "STOPPED"
PROFILE_CORE_IDLE = "CORE_IDLE"
PROFILE_OBSERVE_UI = "OBSERVE_UI"
PROFILE_RETRIEVAL = "RETRIEVAL"
PROFILE_CHAT = "CHAT"
PROFILE_CHAT_VALIDATED = "CHAT_VALIDATED"
PROFILE_INDEX_LIGHT = "INDEX_LIGHT"
PROFILE_INDEX_HEAVY_PDF = "INDEX_HEAVY_PDF"
PROFILE_MAINTENANCE = "MAINTENANCE"

RUNTIME_PROFILES = {
    PROFILE_STOPPED,
    PROFILE_CORE_IDLE,
    PROFILE_OBSERVE_UI,
    PROFILE_RETRIEVAL,
    PROFILE_CHAT,
    PROFILE_CHAT_VALIDATED,
    PROFILE_INDEX_LIGHT,
    PROFILE_INDEX_HEAVY_PDF,
    PROFILE_MAINTENANCE,
}

PROFILE_ALIASES = {
    "RAG": PROFILE_CHAT,
    "CHAT": PROFILE_CHAT,
    "VALIDATED": PROFILE_CHAT_VALIDATED,
    "INDEXING": PROFILE_INDEX_LIGHT,
    "INDEX": PROFILE_INDEX_LIGHT,
    "HEAVY_PDF": PROFILE_INDEX_HEAVY_PDF,
    "HEAVY": PROFILE_INDEX_HEAVY_PDF,
    "MAINT": PROFILE_MAINTENANCE,
}

MODE_PROFILE_MAP = {
    CHAT_MODE: PROFILE_CHAT,
    INDEXING_MODE: PROFILE_INDEX_LIGHT,
    MAINTENANCE_MODE: PROFILE_MAINTENANCE,
}

DEFAULT_PARSE_PRIORITY_ORDER = (
    "NTD_FIRE_Index",
    "GKRF_Index",
    "NTD_ELECTRICAL_Index",
    "NTD_STRUCTURAL_Index",
    "NTD_GEOTECH_Index",
    "NTD_SPDS_Index",
    "NTD_HVAC_Index",
    "NTD_WATER_Index",
    "NTD_PIPELINES_Index",
    "NTD_TRANSPORT_Index",
    "NTD_ARCH_URBAN_Index",
    "NTD_CONSTRUCTION_Index",
    "NTD_BIM_OPERATION_Index",
    "NTD_SAFETY_Index",
    "NTD_MATERIALS_Index",
    "NTD_GENERAL_Index",
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


def normalize_runtime_profile(profile: str | None) -> str:
    value = (profile or "").strip().upper()
    if not value:
        return PROFILE_CHAT
    return PROFILE_ALIASES.get(value, value if value in RUNTIME_PROFILES else PROFILE_CHAT)


def current_runtime_profile(current_mode: dict[str, Any] | None) -> str:
    if current_mode:
        explicit = current_mode.get("runtime_profile") or current_mode.get("profile")
        if explicit:
            return normalize_runtime_profile(str(explicit))
    return MODE_PROFILE_MAP.get(current_resource_mode(current_mode), PROFILE_CHAT)


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
    profile = current_runtime_profile(current_mode)
    if profile not in {PROFILE_CHAT, PROFILE_CHAT_VALIDATED}:
        return False, f"Runtime profile {profile} does not allow chat generation."
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
            "runtime_profile": PROFILE_INDEX_LIGHT,
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
            "runtime_profile": PROFILE_CHAT,
            "model": os.getenv("LLM_MODEL", "mlx-community/Qwen3-14B-4bit"),
            "reason": reason,
            "chat_generation": "allowed",
            "switched_at": datetime.now().isoformat(),
        }
    )
    return current_mode
