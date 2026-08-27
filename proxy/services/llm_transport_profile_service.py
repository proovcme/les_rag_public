"""Provider-specific OpenAI-compatible transport normalization."""

from __future__ import annotations

import os
from typing import Any, Mapping

from proxy.services.model_execution_preset_service import (
    BackendCapacity,
    ModelExecutionPreset,
    resolve_execution_preset,
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
    tail = str(required_tail or "")
    if len(tail) >= limit:
        fitted = tail[-limit:]
        return fitted, {
            "truncated": True,
            "output_chars": len(fitted),
            "sections": {},
        }

    head_budget = max(0, limit - len(tail) - 2)
    fitted_sections: list[str] = []
    section_chars: dict[str, int] = {}
    truncated = False
    for name, raw_value in sections:
        value = str(raw_value or "").strip()
        if not value:
            continue
        separator_chars = 2 if fitted_sections else 0
        available = head_budget - sum(len(item) for item in fitted_sections) - (
            2 * max(0, len(fitted_sections) - 1)
        ) - separator_chars
        if available <= 0:
            truncated = True
            section_chars[str(name)] = 0
            continue
        used = value[:available].rstrip()
        if len(used) < len(value):
            truncated = True
        if used:
            fitted_sections.append(used)
            section_chars[str(name)] = len(used)

    head = "\n\n".join(fitted_sections)
    fitted = f"{head}\n\n{tail}" if head else tail
    return fitted, {
        "truncated": truncated,
        "output_chars": len(fitted),
        "sections": section_chars,
    }
