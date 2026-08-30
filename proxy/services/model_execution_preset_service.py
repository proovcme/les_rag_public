"""Capacity-bounded, provider-neutral model execution presets.

The service interprets observed backend facts but never rewrites provider
configuration and never changes the canonical route mode.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping


@dataclass(frozen=True)
class BackendCapacity:
    provider: str
    model_id: str
    context_tokens: int | None
    observed: bool
    source: str


@dataclass(frozen=True)
class ModelExecutionPreset:
    preset_id: str
    model_family: str
    input_token_limit: int
    generation_reserve_tokens: int
    safety_reserve_tokens: int
    normal_tool_count: int
    max_tools: int
    max_batch_items: int
    parallel_read_limit: int
    reasoning_enabled: bool
    source_chain: tuple[str, ...]

    def diagnostics(self, *, requested_input_tokens: int | None = None) -> dict[str, Any]:
        """Return operator-safe requested/effective/source values."""
        source = " > ".join(self.source_chain)
        return {
            "model_preset": {
                "requested": self.model_family,
                "effective": self.preset_id,
                "source": source,
                "restart_required": False,
            },
            "context_input_tokens": {
                "requested": requested_input_tokens,
                "effective": self.input_token_limit,
                "source": source,
                "restart_required": False,
            },
            "generation_reserve": {
                "requested": None,
                "effective": self.generation_reserve_tokens,
                "source": source,
                "restart_required": False,
            },
            "safety_reserve": {
                "requested": None,
                "effective": self.safety_reserve_tokens,
                "source": "workflow_invariants",
                "restart_required": False,
            },
            "reasoning": {
                "requested": False,
                "effective": self.reasoning_enabled,
                "source": "workflow_invariants",
                "restart_required": False,
            },
        }


_FACTORY_9B = ModelExecutionPreset(
    preset_id="qwen-9b-restrictive",
    model_family="qwen-9b",
    input_token_limit=6000,
    generation_reserve_tokens=1200,
    safety_reserve_tokens=512,
    normal_tool_count=3,
    max_tools=5,
    max_batch_items=5,
    parallel_read_limit=1,
    reasoning_enabled=False,
    source_chain=("workflow_invariants", "factory_preset"),
)

_FACTORY_35B = ModelExecutionPreset(
    preset_id="qwen-35b-extended",
    model_family="qwen-35b",
    input_token_limit=35000,
    generation_reserve_tokens=4096,
    safety_reserve_tokens=2048,
    normal_tool_count=5,
    max_tools=8,
    max_batch_items=12,
    parallel_read_limit=4,
    reasoning_enabled=False,
    source_chain=("workflow_invariants", "factory_preset"),
)

# Below this observed window the larger shortlist/batch/parallel-read envelope
# is not coherent after fixed generation and safety reserves. A 35B identity
# therefore keeps the 9B-compatible execution contract on small KV windows.
_MIN_EXTENDED_35B_CONTEXT_TOKENS = 16384


def _is_qwen_35b(model_id: str) -> bool:
    normalized = "".join(str(model_id or "").lower().split())
    return "qwen" in normalized and "35b" in normalized


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _narrow(preset: ModelExecutionPreset, values: Mapping[str, Any]) -> ModelExecutionPreset:
    aliases = {
        "input_tokens": "input_token_limit",
        "input_token_limit": "input_token_limit",
        "normal_tool_count": "normal_tool_count",
        "max_tools": "max_tools",
        "max_batch_items": "max_batch_items",
        "parallel_read_limit": "parallel_read_limit",
    }
    updates: dict[str, int] = {}
    for requested_name, field_name in aliases.items():
        if requested_name not in values:
            continue
        requested = _positive_int(values.get(requested_name))
        if requested is not None:
            updates[field_name] = min(int(getattr(preset, field_name)), requested)
    effective_max_tools = updates.get("max_tools", preset.max_tools)
    updates["normal_tool_count"] = min(
        updates.get("normal_tool_count", preset.normal_tool_count),
        effective_max_tools,
    )
    return replace(preset, **updates)


def resolve_execution_preset(
    capacity: BackendCapacity,
    *,
    operator: Mapping[str, Any] | None = None,
    restrictions: Mapping[str, Any] | None = None,
) -> ModelExecutionPreset:
    """Resolve invariants -> observed capacity -> factory -> narrowing layers.

    A 35B identity is insufficient without observed capacity. Unknown identity or
    capacity deliberately falls back to the restrictive 9B-compatible preset.
    """
    has_observed_capacity = bool(
        capacity.observed and _positive_int(capacity.context_tokens) is not None
    )
    extended_35b_available = bool(
        has_observed_capacity
        and _is_qwen_35b(capacity.model_id)
        and int(capacity.context_tokens or 0) >= _MIN_EXTENDED_35B_CONTEXT_TOKENS
    )
    factory = _FACTORY_35B if extended_35b_available else _FACTORY_9B
    source_chain: list[str] = ["workflow_invariants"]

    requested_context = None
    if operator:
        requested_context = _positive_int(
            operator.get("input_tokens", operator.get("input_token_limit"))
        )

    resolved = factory
    if has_observed_capacity:
        source_chain.append("observed_backend_capacity")
        observed_context = int(capacity.context_tokens or 0)
        resolved = replace(
            resolved,
            input_token_limit=(
                min(observed_context, requested_context)
                if requested_context is not None
                else observed_context
            ),
        )
    elif requested_context is not None:
        resolved = replace(resolved, input_token_limit=requested_context)

    source_chain.append("factory_preset")
    if operator:
        resolved = _narrow(resolved, operator)
        source_chain.append("operator_clone")
    if restrictions:
        resolved = _narrow(resolved, restrictions)
        source_chain.append("workflow_profile_restrictions")

    return replace(resolved, source_chain=tuple(source_chain), reasoning_enabled=False)
