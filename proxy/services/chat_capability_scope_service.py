"""Explicit, frozen per-dialogue capability scope for chat tools."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


PUBLIC_WEB_TOOLS = frozenset({"web_search"})


def filter_profile_tools(
    tools: Sequence[str],
    *,
    selected_sources_only: bool,
) -> list[str]:
    result = [str(name) for name in tools if str(name).strip()]
    if not selected_sources_only:
        return result
    return [name for name in result if name not in PUBLIC_WEB_TOOLS]


def resolve_selected_sources_only(
    requested: bool | None,
    prior_traces: Sequence[Mapping[str, Any]],
) -> bool:
    """Use an explicit request value, otherwise preserve the latest frozen scope."""

    if requested is not None:
        return bool(requested)
    for raw_trace in reversed(list(prior_traces)):
        trace = dict(raw_trace) if isinstance(raw_trace, Mapping) else {}
        manifest = trace.get("evidence_manifest")
        if not isinstance(manifest, Mapping):
            continue
        scope = manifest.get("scope")
        if isinstance(scope, Mapping) and scope.get("selected_sources_only") is not None:
            return bool(scope.get("selected_sources_only"))
    return False
