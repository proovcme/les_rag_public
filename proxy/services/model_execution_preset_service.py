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
    reasoning_supported: bool = False


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
    reasoning_requested: bool = False
    reasoning_source: str = "factory_default"
    reasoning_supported: bool = False
    default_generation_reserve_tokens: int | None = None
    output_capacity_observed: bool = False
    query_output_tokens_requested: int | None = None
    query_generation_reserve_tokens: int | None = None
    query_output_tokens_source: str = "factory_default"
    answer_output_tokens_requested: int | None = None
    answer_output_tokens_effective: int | None = None
    answer_output_tokens_source: str = "factory_default"
    output_purpose: str = "query"

    def diagnostics(self, *, requested_input_tokens: int | None = None) -> dict[str, Any]:
        """Return operator-safe requested/effective/source values."""
        source = " > ".join(self.source_chain)
        query_budget = query_generation_budget(
            self,
            reserved_tokens=self.query_generation_reserve_tokens or self.generation_reserve_tokens,
        )
        answer_budget = {
            "requested": self.answer_output_tokens_requested,
            "effective": self.answer_output_tokens_effective or self.generation_reserve_tokens,
            "source": self.answer_output_tokens_source,
            "restart_required": False,
        }
        reserve_requested = (self.answer_output_tokens_requested if self.output_purpose == "answer"
                             else self.query_output_tokens_requested)
        reserve_source = (self.answer_output_tokens_source if self.output_purpose == "answer"
                          else self.query_output_tokens_source)
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
                "requested": reserve_requested,
                "effective": self.generation_reserve_tokens,
                "source": reserve_source if reserve_requested is not None else source,
                "restart_required": False,
            },
            "query_output_tokens": query_budget,
            "answer_output_tokens": answer_budget,
            "safety_reserve": {
                "requested": None,
                "effective": self.safety_reserve_tokens,
                "source": "workflow_invariants",
                "restart_required": False,
            },
            "reasoning": {
                "requested": self.reasoning_requested,
                "effective": self.reasoning_enabled,
                "source": self.reasoning_source,
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
MIN_EXTENDED_35B_CONTEXT_TOKENS = 16384
_MIN_EXTENDED_GENERATION_CONTEXT_TOKENS = MIN_EXTENDED_35B_CONTEXT_TOKENS
_EXTENDED_GENERATION_RESERVE_TOKENS = 4096
_PROVEN_RESTRICTIVE_CONTEXT_TOKENS = 32768
MIN_OUTPUT_BUDGET_INPUT_HEADROOM_TOKENS = 1024


def is_qwen_35b(model_id: str) -> bool:
    normalized = "".join(str(model_id or "").lower().split())
    return "qwen" in normalized and "35b" in normalized


def _is_qwen_35b(model_id: str) -> bool:
    return is_qwen_35b(model_id)


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
        and is_qwen_35b(capacity.model_id)
        and int(capacity.context_tokens or 0) >= MIN_EXTENDED_35B_CONTEXT_TOKENS
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
        usable_context = (
            observed_context
            if extended_35b_available
            else min(observed_context, _PROVEN_RESTRICTIVE_CONTEXT_TOKENS)
        )
        resolved = replace(
            resolved,
            input_token_limit=(
                min(usable_context, requested_context)
                if requested_context is not None
                else usable_context
            ),
            generation_reserve_tokens=(
                max(
                    resolved.generation_reserve_tokens,
                    _EXTENDED_GENERATION_RESERVE_TOKENS,
                )
                if observed_context >= _MIN_EXTENDED_GENERATION_CONTEXT_TOKENS
                else resolved.generation_reserve_tokens
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

    resolved = apply_reasoning_policy(
        replace(resolved, source_chain=tuple(source_chain),
                default_generation_reserve_tokens=resolved.generation_reserve_tokens,
                output_capacity_observed=has_observed_capacity, reasoning_supported=(
            capacity.provider.strip().casefold() == "freetoken" or capacity.reasoning_supported
        )), operator, restrictions=restrictions
    )
    return apply_output_budget_policy(resolved, operator)


def validate_output_budget_policy(policy: Mapping[str, Any] | None) -> None:
    """Reject profile output limits before any persistent profile write."""
    for field in ("query_output_tokens", "answer_output_tokens"):
        if field not in (policy or {}):
            continue
        value = policy[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{field}: значение должно быть положительным целым числом")


def _bounded_output_budget(
    preset: ModelExecutionPreset, *, requested: int | None, default: int, source: str,
) -> tuple[int, str]:
    if requested is None:
        return default, source
    effective = requested
    if not preset.output_capacity_observed and effective > default:
        effective = default
        source += " > unobserved_capacity_default"
    maximum = (preset.input_token_limit - preset.safety_reserve_tokens
               - MIN_OUTPUT_BUDGET_INPUT_HEADROOM_TOKENS)
    if maximum < 1:
        raise ValueError(
            "Недостаточно контекста для лимита вывода: после резерва безопасности "
            "нужно сохранить не менее 1024 токенов для входных данных"
        )
    if effective > maximum:
        effective = maximum
        source += " > effective_context_window"
    return effective, source


def apply_output_budget_policy(
    preset: ModelExecutionPreset, policy: Mapping[str, Any] | None,
) -> ModelExecutionPreset:
    """Reserve explicit purpose output inside the existing effective total window.

    A requested context window is not observed capacity. Without observation,
    an explicit budget may narrow its purpose default but cannot widen it.
    """
    validate_output_budget_policy(policy)
    values = policy or {}
    default = preset.default_generation_reserve_tokens or preset.generation_reserve_tokens
    query_requested = values.get("query_output_tokens")
    answer_requested = values.get("answer_output_tokens")
    query_reserve, query_source = _bounded_output_budget(
        preset, requested=query_requested, default=default,
        source="profile_model_policy.query_output_tokens" if query_requested is not None else "factory_default",
    )
    answer_reserve, answer_source = _bounded_output_budget(
        preset, requested=answer_requested, default=default,
        source="profile_model_policy.answer_output_tokens" if answer_requested is not None else "factory_default",
    )
    return replace(
        preset, generation_reserve_tokens=query_reserve,
        default_generation_reserve_tokens=default,
        query_output_tokens_requested=query_requested,
        query_generation_reserve_tokens=query_reserve,
        query_output_tokens_source=query_source,
        answer_output_tokens_requested=answer_requested,
        answer_output_tokens_effective=answer_reserve,
        answer_output_tokens_source=answer_source,
        output_purpose="query",
    )


def model_rag_answer_execution_preset(
    preset: ModelExecutionPreset, *, model_rag: bool,
) -> ModelExecutionPreset:
    """Select the answer reserve before context and native-tool packing."""
    default = preset.default_generation_reserve_tokens or preset.generation_reserve_tokens
    source_chain = preset.source_chain
    source = "factory_default"
    if model_rag and preset.input_token_limit >= 32768:
        default = max(default, 8192)
        source = "model_rag_complete_answer"
        source_chain = (*source_chain, source)
    requested = preset.answer_output_tokens_requested
    reserve, source = _bounded_output_budget(
        preset, requested=requested, default=default,
        source="profile_model_policy.answer_output_tokens" if requested is not None else source,
    )
    return replace(
        preset, generation_reserve_tokens=reserve,
        answer_output_tokens_effective=reserve, answer_output_tokens_source=source,
        output_purpose="answer", source_chain=source_chain,
    )


def apply_reasoning_policy(
    preset: ModelExecutionPreset,
    policy: Mapping[str, Any] | None,
    *,
    restrictions: Mapping[str, Any] | None = None,
) -> ModelExecutionPreset:
    """Apply an explicit profile boolean without changing capacity or routing."""
    requested = (policy or {}).get("reasoning_enabled", False)
    if not isinstance(requested, bool):
        raise ValueError("reasoning_enabled must be a boolean")
    enabled = requested
    source = "profile_model_policy" if "reasoning_enabled" in (policy or {}) else "factory_default"
    if (restrictions or {}).get("reasoning_enabled") is False:
        enabled = False
        source = "workflow_profile_restrictions"
    elif requested and not preset.reasoning_supported:
        enabled = False
        source = "unsupported_by_transport"
    return replace(preset, reasoning_enabled=enabled, reasoning_requested=requested, reasoning_source=source)


def query_generation_budget(
    preset: ModelExecutionPreset, *, reserved_tokens: int, configured_limit: str = "",
) -> dict[str, Any]:
    """Use only output space actually reserved by the query's ContextGovernor.

    Thinking and the final query list share the provider's output limit. Auto
    preserves the ordinary 1600-token limit unless the profile explicitly chooses
    its query output budget. Thinking may use its existing reserve. Both cases
    remain bounded by the actual packed reserve without enlarging context.
    """
    reserve = int(reserved_tokens)
    if reserve < 1:
        raise ValueError("query output reserve must be positive")
    literal = str(configured_limit).strip()
    if literal:
        try:
            requested = int(literal)
        except ValueError as error:
            raise ValueError("query output limit must be a positive integer") from error
        if requested < 1:
            raise ValueError("query output limit must be a positive integer")
        limit, source = requested, "operator_query_limit"
    elif preset.query_output_tokens_requested is not None:
        requested = preset.query_output_tokens_requested
        limit = min(requested, preset.query_generation_reserve_tokens or reserve)
        source = preset.query_output_tokens_source
    else:
        requested = None
        limit = reserve if preset.reasoning_enabled else 1600
        source = "profile_reasoning_reserved_output" if preset.reasoning_enabled else "ordinary_query_default"
    return {"requested": requested, "effective": min(limit, reserve),
            "reserved_tokens": reserve, "source": source, "restart_required": False}
