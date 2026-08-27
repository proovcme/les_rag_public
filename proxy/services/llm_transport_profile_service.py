"""Provider-specific OpenAI-compatible transport normalization."""

from __future__ import annotations

import os
from typing import Any, Mapping

from proxy.services.model_execution_preset_service import (
    BackendCapacity,
    ModelExecutionPreset,
    resolve_execution_preset,
)
from proxy.services.context_governor_service import (
    ContextCandidate,
    ContextGovernor,
    ContextKind,
    ContextObject,
)


LOCAL_OPENAI_PROVIDER_NAMES = frozenset({"freetoken"})


def _configured_model(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized == "freetoken":
        return os.getenv("FREETOKEN_MODEL", "").strip() or os.getenv("LLM_MODEL", "").strip()
    if normalized == "ollama":
        return os.getenv("OLLAMA_MODEL", "").strip() or os.getenv("LLM_MODEL", "").strip()
    if normalized in {"mlx", "local"}:
        return os.getenv("MLX_MODEL", "").strip() or os.getenv("LLM_MODEL", "").strip()
    return os.getenv("OPENAI_MODEL", "").strip() or os.getenv("LLM_MODEL", "").strip()


def _configured_context_request(provider: str) -> int | None:
    env_name = "FREETOKEN_CONTEXT_TOKENS" if provider.strip().lower() == "freetoken" else ""
    if not env_name:
        return None
    try:
        value = int(os.getenv(env_name, "").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def resolve_transport_execution_profile(
    *,
    provider: str,
    model_id: str,
    observed_context_tokens: int | None = None,
    observed: bool = False,
    observed_source: str = "unavailable",
    operator: Mapping[str, Any] | None = None,
    restrictions: Mapping[str, Any] | None = None,
) -> ModelExecutionPreset:
    """Resolve a preset from transport facts without changing provider state."""
    return resolve_execution_preset(
        BackendCapacity(
            provider=str(provider or "unknown"),
            model_id=str(model_id or "unknown"),
            context_tokens=observed_context_tokens,
            observed=bool(observed),
            source=str(observed_source or "unavailable"),
        ),
        operator=operator,
        restrictions=restrictions,
    )


def effective_model_execution_diagnostics() -> dict[str, Any]:
    """Describe configured request versus safe unprobed effective preset.

    Version/config diagnostics have no live backend probe. Consequently configured
    context is reported as requested capacity, never promoted to an observed fact.
    """
    provider = os.getenv("LES_LLM_PROVIDER", "mlx").strip().lower() or "mlx"
    model_id = _configured_model(provider) or "unknown"
    requested_context = _configured_context_request(provider)
    operator = {"input_tokens": requested_context} if requested_context else None
    preset = resolve_transport_execution_profile(
        provider=provider,
        model_id=model_id,
        observed_context_tokens=None,
        observed=False,
        operator=operator,
    )
    diagnostics = preset.diagnostics(requested_input_tokens=requested_context)
    diagnostics["model_preset"] = {
        **diagnostics["model_preset"],
        "requested": model_id,
    }
    return diagnostics


def assistant_delta_text(delta: Mapping[str, Any] | None) -> str:
    """Normalize text fields used by OpenAI-compatible streaming providers."""
    if not isinstance(delta, Mapping):
        return ""
    return str(
        delta.get("content")
        or delta.get("reasoning")
        or delta.get("reasoning_content")
        or ""
    )


def provider_is_local(provider: str | None) -> bool:
    return (provider or "").strip().lower() in LOCAL_OPENAI_PROVIDER_NAMES


def apply_transport_options(
    body: Mapping[str, Any],
    provider: str | None,
) -> dict[str, Any]:
    normalized = dict(body)
    if not provider_is_local(provider):
        return normalized
    template_options = dict(normalized.get("chat_template_kwargs") or {})
    template_options["enable_thinking"] = False
    normalized["chat_template_kwargs"] = template_options
    return normalized


def freetoken_prompt_chars_for_context(
    context_tokens: int,
    *,
    reserve_tokens: int = 1200,
    chars_per_token: float = 2.0,
) -> int:
    """Derive a conservative prompt ceiling from the operator-owned KV window."""
    usable_tokens = max(512, max(2048, int(context_tokens)) - max(256, int(reserve_tokens)))
    return max(2000, int(usable_tokens * max(0.5, float(chars_per_token))))


def provider_prompt_max_chars(provider: str | None) -> int:
    if not provider_is_local(provider):
        return 120000
    explicit = os.getenv("FREETOKEN_PROMPT_MAX_CHARS", "").strip()
    if explicit:
        try:
            return max(2000, int(explicit))
        except ValueError:
            pass
    try:
        context_tokens = max(2048, int(os.getenv("FREETOKEN_CONTEXT_TOKENS", "8253")))
    except ValueError:
        context_tokens = 8253
    try:
        reserve_tokens = max(
            256,
            int(os.getenv("FREETOKEN_GENERATION_RESERVE_TOKENS", "1200")),
        )
    except ValueError:
        reserve_tokens = 1200
    try:
        chars_per_token = max(
            0.5,
            float(os.getenv("FREETOKEN_PROMPT_CHARS_PER_TOKEN", "2.0")),
        )
    except ValueError:
        chars_per_token = 1.25
    return freetoken_prompt_chars_for_context(
        context_tokens,
        reserve_tokens=reserve_tokens,
        chars_per_token=chars_per_token,
    )


def fit_prompt_sections(
    sections: list[tuple[str, str]],
    *,
    required_tail: str,
    max_chars: int,
) -> tuple[str, dict[str, Any]]:
    limit = max(1, int(max_chars))
    tail = str(required_tail or "").strip()
    kind_by_name = {
        "profile_prefix": ContextKind.PROFILE_PREFIX,
        "tools": ContextKind.TOOL_EXCHANGE,
        "tool_shortlist": ContextKind.TOOL_SHORTLIST,
        "checkpoint": ContextKind.CHECKPOINT,
        "session_memory": ContextKind.WORKING_MEMORY,
        "working_memory": ContextKind.WORKING_MEMORY,
        "evidence": ContextKind.EVIDENCE,
        "navigation": ContextKind.SOURCE_MAP,
        "dataset_navigation": ContextKind.SOURCE_MAP,
        "inventory_navigation": ContextKind.SOURCE_MAP,
        "notebook_navigation": ContextKind.SOURCE_MAP,
        "selected_documents": ContextKind.SOURCE_MAP,
        "project_memory_advisory": ContextKind.WORKING_MEMORY,
        "tool_exchange": ContextKind.TOOL_EXCHANGE,
        "dialogue": ContextKind.DIALOGUE,
    }
    candidates: list[ContextCandidate] = []
    values_by_id: dict[str, tuple[int, str, str]] = {}
    for section_index, (name, raw_value) in enumerate(sections):
        value = str(raw_value or "").strip()
        if not value:
            continue
        # Existing producers commonly delimit addressable evidence/pages with a
        # blank line. Those units may be omitted, but are never sliced.
        parts = tuple(part.strip() for part in value.split("\n\n") if part.strip())
        objects: list[ContextObject] = []
        for part_index, part in enumerate(parts):
            object_id = f"compat:{section_index}:{part_index}"
            objects.append(ContextObject(object_id=object_id, payload=part))
            values_by_id[object_id] = (section_index, str(name), part)
        candidates.append(
            ContextCandidate(
                kind=kind_by_name.get(str(name), ContextKind.DIALOGUE),
                objects=tuple(objects),
            )
        )
    request_id = "compat:required-request"
    candidates.append(
        ContextCandidate(
            kind=ContextKind.REQUEST,
            objects=(ContextObject(object_id=request_id, payload=tail),),
            required=True,
        )
    )
    compatibility_preset = ModelExecutionPreset(
        preset_id="legacy-prompt-compatibility",
        model_family="provider-compatible",
        input_token_limit=limit + 1,
        generation_reserve_tokens=0,
        safety_reserve_tokens=0,
        normal_tool_count=1,
        max_tools=1,
        max_batch_items=1,
        parallel_read_limit=1,
        reasoning_enabled=False,
        source_chain=("workflow_invariants", "compatibility_wrapper"),
    )
    packet = ContextGovernor(
        compatibility_preset,
        estimate_tokens=lambda text: len(text) + 1,
    ).pack(candidates)
    selected_ids = {
        item.object_id
        for section in packet.sections
        for item in section.objects
        if item.object_id != request_id
    }
    fitted_sections: list[str] = []
    section_chars: dict[str, int] = {}
    for section_index, (name, _) in enumerate(sections):
        parts = [
            value
            for object_id, (object_section_index, _object_name, value) in values_by_id.items()
            if object_section_index == section_index and object_id in selected_ids
        ]
        if parts:
            fitted_value = "\n".join(parts)
            fitted_sections.append(fitted_value)
            section_chars[str(name)] = section_chars.get(str(name), 0) + len(fitted_value)
        elif section_index in {
            object_section_index
            for object_section_index, _object_name, _value in values_by_id.values()
        }:
            section_chars.setdefault(str(name), 0)
    fitted = "\n".join([*fitted_sections, tail]) if fitted_sections else tail
    return fitted, {
        "truncated": bool(packet.omissions),
        "output_chars": len(fitted),
        "sections": section_chars,
        "omissions": [
            {
                "kind": omission.kind.value,
                "omitted": omission.omitted,
                "object_ids": list(omission.object_ids),
                "cursor": omission.cursor,
                "reason": omission.reason,
            }
            for omission in packet.omissions
        ],
    }
