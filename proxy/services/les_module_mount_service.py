"""Single fail-closed mount boundary for optional LES feature modules."""

from __future__ import annotations

import importlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from fastapi import APIRouter

from proxy.services.les_module_contracts import (
    ChatContext,
    ChatRequestContext,
    ChatResponse,
    ModuleManifest,
)
from proxy.services.les_module_service import load_enabled_modules


_ALLOWED_CONTEXT_KEYS = ("system_instructions", "tool_instructions")
_MAX_CONTEXT_VALUE_CHARS = 4000
logger = logging.getLogger(__name__)


class ModuleMountError(ValueError):
    """Bounded mount error safe for startup diagnostics."""

    def __init__(self, code: str):
        self.code = str(code)
        super().__init__(self.code)


@dataclass(frozen=True)
class MountedRouter:
    module_id: str
    router: APIRouter


@dataclass(frozen=True)
class MountedPanel:
    module_id: str
    title: str
    builder: Callable[[], Any]


@dataclass(frozen=True)
class MountedChatHandler:
    module_id: str
    handler: Any


def _resolve_entry_point(entry_point: str) -> Callable[..., Any]:
    """Resolve only code below the explicit ``modules`` package boundary."""
    module_name, separator, attribute = str(entry_point or "").partition(":")
    if separator != ":" or not module_name.startswith("modules.") or not attribute:
        raise ModuleMountError("MODULE_ENTRY_POINT_INVALID")
    try:
        factory = getattr(importlib.import_module(module_name), attribute)
    except (ImportError, AttributeError) as error:
        raise ModuleMountError("MODULE_ENTRY_POINT_UNAVAILABLE") from error
    if not callable(factory):
        raise ModuleMountError("MODULE_ENTRY_POINT_INVALID")
    return factory


def _manifests(manifests: Sequence[ModuleManifest] | None) -> tuple[ModuleManifest, ...]:
    return tuple(load_enabled_modules() if manifests is None else manifests)


def module_routers(
    manifests: Sequence[ModuleManifest] | None = None,
    *,
    resolve_entry_point: Callable[[str], Callable[..., Any]] = _resolve_entry_point,
) -> tuple[MountedRouter, ...]:
    mounted: list[MountedRouter] = []
    for manifest in _manifests(manifests):
        for entry_point in manifest.router_factories:
            try:
                router = resolve_entry_point(entry_point)()
            except Exception:
                logger.warning("[MODULE/MOUNT] MODULE_ROUTER_UNAVAILABLE:%s", manifest.module_id)
                continue
            if isinstance(router, APIRouter):
                mounted.append(MountedRouter(manifest.module_id, router))
    return tuple(mounted)


def module_panels(
    manifests: Sequence[ModuleManifest] | None = None,
    *,
    resolve_entry_point: Callable[[str], Callable[..., Any]] = _resolve_entry_point,
) -> tuple[MountedPanel, ...]:
    mounted: list[MountedPanel] = []
    for manifest in _manifests(manifests):
        if not manifest.panel_builder:
            continue
        try:
            builder = resolve_entry_point(manifest.panel_builder)
        except Exception:
            logger.warning("[MODULE/MOUNT] MODULE_PANEL_UNAVAILABLE:%s", manifest.module_id)
            continue
        mounted.append(MountedPanel(manifest.module_id, manifest.title, builder))
    return tuple(mounted)


def render_module_panels(
    panels: Sequence[MountedPanel] | None = None,
    *,
    on_error: Callable[[str, str], Any] | None = None,
) -> None:
    """Render every healthy panel even when another optional builder fails."""
    for mounted in tuple(module_panels() if panels is None else panels):
        try:
            mounted.builder()
        except Exception:
            if on_error is not None:
                on_error(mounted.module_id, "MODULE_PANEL_UNAVAILABLE")


def module_chat_handlers(
    manifests: Sequence[ModuleManifest] | None = None,
    *,
    resolve_entry_point: Callable[[str], Callable[..., Any]] = _resolve_entry_point,
) -> tuple[MountedChatHandler, ...]:
    mounted: list[MountedChatHandler] = []
    for manifest in _manifests(manifests):
        for entry_point in manifest.chat_handler_factories:
            try:
                handler = resolve_entry_point(entry_point)()
            except Exception:
                logger.warning("[MODULE/MOUNT] MODULE_HANDLER_UNAVAILABLE:%s", manifest.module_id)
                continue
            if callable(getattr(handler, "handle", None)):
                mounted.append(MountedChatHandler(manifest.module_id, handler))
    return tuple(mounted)


def _route_keys(routes: Iterable[Any]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for route in routes:
        path = str(getattr(route, "path", "") or "")
        for method in getattr(route, "methods", ()) or ():
            normalized = str(method).upper()
            if path and normalized not in {"HEAD", "OPTIONS"}:
                keys.add((normalized, path))
    return keys


def validate_route_collisions(
    core_routes: Iterable[Any],
    routers: Sequence[MountedRouter],
) -> None:
    """Reject method/path collisions with core and between optional modules."""
    occupied = _route_keys(core_routes)
    for mounted in routers:
        for route in mounted.router.routes:
            current = _route_keys((route,))
            if occupied.intersection(current):
                raise ModuleMountError("MODULE_ROUTE_COLLISION")
            occupied.update(current)


async def run_module_chat_handlers(
    request: ChatRequestContext,
    context: ChatContext,
    handlers: Sequence[MountedChatHandler] | None = None,
) -> ChatResponse:
    """Collect bounded model context; never accept a code-owned final answer."""
    deltas: dict[str, list[str]] = {key: [] for key in _ALLOWED_CONTEXT_KEYS}
    diagnostics: list[str] = []
    for mounted in tuple(module_chat_handlers() if handlers is None else handlers):
        try:
            response = await mounted.handler.handle(request, context)
        except Exception:
            diagnostics.append(f"MODULE_HANDLER_FAILED:{mounted.module_id}")
            continue
        try:
            if response is None:
                continue
            if not isinstance(response, ChatResponse):
                raise TypeError("response")
            if not isinstance(response.terminal, bool):
                raise TypeError("terminal")
            if response.message is not None and not isinstance(response.message, str):
                raise TypeError("message")
            if not isinstance(response.context_delta, Mapping):
                raise TypeError("context_delta")
            if (
                not isinstance(response.diagnostics, tuple)
                or any(not isinstance(diagnostic, str) for diagnostic in response.diagnostics)
            ):
                raise TypeError("diagnostics")
            if response.terminal or response.message is not None:
                diagnostics.append(f"MODULE_CODE_OWNED_ANSWER_REJECTED:{mounted.module_id}")
                continue
            for diagnostic in response.diagnostics:
                code = diagnostic.strip()
                if code and len(code) <= 120:
                    diagnostics.append(code)
            for key in _ALLOWED_CONTEXT_KEYS:
                value = response.context_delta.get(key)
                if isinstance(value, str) and value.strip():
                    deltas[key].append(value.strip()[:_MAX_CONTEXT_VALUE_CHARS])
        except Exception:
            diagnostics.append(f"MODULE_HANDLER_INVALID:{mounted.module_id}")

    context_delta = {
        key: "\n".join(values)[:_MAX_CONTEXT_VALUE_CHARS]
        for key, values in deltas.items()
        if values
    }
    return ChatResponse(
        terminal=False,
        message=None,
        context_delta=context_delta,
        diagnostics=tuple(diagnostics),
    )
