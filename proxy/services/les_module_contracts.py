"""Versioned contracts shared by optional LES feature modules and core mounts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol


MODULE_API_VERSION = "1.0"

_SAFE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ENTRY_POINT_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$"
)


class ModuleContractError(ValueError):
    """Bounded validation error safe to expose in module diagnostics."""

    def __init__(self, code: str):
        self.code = str(code)
        super().__init__(self.code)


def is_safe_module_id(value: object) -> bool:
    return isinstance(value, str) and _SAFE_ID_RE.fullmatch(value) is not None


@dataclass(frozen=True)
class ChatRequestContext:
    request_id: str
    user_id: str
    message: str
    mode: str
    dataset_id: str | None
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class ChatResponse:
    terminal: bool
    message: str | None
    context_delta: Mapping[str, Any]
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChatContext:
    active_state: Mapping[str, Any]
    allowed_tools: tuple[str, ...]
    module_id: str | None


class ChatHandler(Protocol):
    async def handle(
        self,
        request: ChatRequestContext,
        context: ChatContext,
    ) -> ChatResponse | None:
        raise NotImplementedError


@dataclass(frozen=True)
class ModuleManifest:
    api_version: str
    module_id: str
    title: str
    icon: str
    router_factories: tuple[str, ...]
    panel_builder: str | None
    chat_handler_factories: tuple[str, ...]
    skill_path: str
    capabilities: tuple[str, ...]


def _api_version(value: str) -> tuple[int, int]:
    parts = str(value or "").split(".")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ModuleContractError("MODULE_API_INCOMPATIBLE")
    return int(parts[0]), int(parts[1])


def _validate_entry_points(values: tuple[str, ...]) -> None:
    if len(values) != len(set(values)):
        raise ModuleContractError("MODULE_ENTRY_POINT_DUPLICATE")
    if any(not isinstance(value, str) or not _ENTRY_POINT_RE.fullmatch(value) for value in values):
        raise ModuleContractError("MODULE_ENTRY_POINT_INVALID")


def validate_manifest(manifest: ModuleManifest, expected_module_id: str) -> ModuleManifest:
    """Validate one manifest without importing or executing any declared component."""
    if not isinstance(manifest, ModuleManifest):
        raise ModuleContractError("MODULE_MANIFEST_INVALID")

    expected = str(expected_module_id or "")
    if not is_safe_module_id(manifest.module_id):
        raise ModuleContractError("MODULE_ID_INVALID")
    if manifest.module_id != expected:
        raise ModuleContractError("MODULE_ID_MISMATCH")

    core_major, core_minor = _api_version(MODULE_API_VERSION)
    module_major, module_minor = _api_version(manifest.api_version)
    if module_major != core_major or module_minor > core_minor:
        raise ModuleContractError("MODULE_API_INCOMPATIBLE")

    if not str(manifest.title or "").strip() or not str(manifest.icon or "").strip():
        raise ModuleContractError("MODULE_METADATA_INVALID")

    _validate_entry_points(manifest.router_factories)
    _validate_entry_points(manifest.chat_handler_factories)
    if manifest.panel_builder is not None:
        _validate_entry_points((manifest.panel_builder,))

    capabilities = tuple(manifest.capabilities)
    if len(capabilities) != len(set(capabilities)):
        raise ModuleContractError("MODULE_CAPABILITY_DUPLICATE")
    if any(not _SAFE_ID_RE.fullmatch(value) for value in capabilities):
        raise ModuleContractError("MODULE_CAPABILITY_INVALID")

    skill_path = Path(str(manifest.skill_path or ""))
    if skill_path.name != "SKILL.md" or not skill_path.is_file():
        raise ModuleContractError("MODULE_SKILL_MISSING")
    return manifest
