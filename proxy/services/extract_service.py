"""Wire schema-constrained extraction to LES's active LLM provider.

Bridges proxy/services/structured_extract (the backend-agnostic engine) to the
runtime provider config, mirroring proxy/services/doc_router's provider
selection (cloud OpenAI/OpenRouter when model+key are set, else local MLX) and
the GPT-5 max_completion_tokens compatibility fix.

Async by design — the per-attempt model call is awaited so the validate-and-
repair loop never blocks the proxy event loop.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from proxy.services import structured_extract as se

CLOUD_PROVIDERS = {"openai", "openai-compatible", "openai_compatible", "openrouter"}


def _provider() -> str:
    return (os.getenv("LES_LLM_PROVIDER", "mlx").strip().lower() or "mlx")


def _endpoint() -> tuple[str, str, dict[str, str], bool]:
    """Return (url, model, headers, is_cloud) for the active provider.

    Cloud requires both a model and an API key; otherwise falls back to local MLX
    (same rule as doc_router, so behaviour stays consistent across the codebase).
    """
    base = (os.getenv("OPENAI_BASE_URL", "").strip() or "https://api.openai.com/v1")
    model = os.getenv("OPENAI_MODEL", "").strip()
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if _provider() in CLOUD_PROVIDERS and model and key:
        url = base.rstrip("/") + "/chat/completions"
        return url, model, {"content-type": "application/json", "Authorization": f"Bearer {key}"}, True
    url = os.getenv("MLX_URL", "http://127.0.0.1:8080").rstrip("/") + "/v1/chat/completions"
    return url, os.getenv("MLX_MODEL", ""), {"content-type": "application/json"}, False


def _needs_completion_tokens(model: str) -> bool:
    m = (model or "").lower()
    return m.startswith("gpt-5") or (len(m) >= 2 and m[0] == "o" and m[1].isdigit())


def _is_gpt5_family(model: str) -> bool:
    return (model or "").strip().lower().startswith("gpt-5")


def _max_tokens(override: int | None = None) -> int:
    if override is not None:
        return max(256, int(override))
    try:
        return max(256, int(os.getenv("LES_EXTRACT_MAX_TOKENS", "8192")))
    except ValueError:
        return 8192


def _extract_reasoning_effort(model: str) -> str:
    if not _needs_completion_tokens(model):
        return ""
    return os.getenv("LES_EXTRACT_REASONING_EFFORT", "minimal").strip().lower()


def _extract_verbosity(model: str) -> str:
    if not _is_gpt5_family(model):
        return ""
    return os.getenv("LES_EXTRACT_VERBOSITY", "low").strip().lower()


def _local_prompt(prompt: str) -> str:
    text = str(prompt or "")
    return text if text.lstrip().startswith("/no_think") else "/no_think\n" + text


def _format_exception(exc: Exception) -> str:
    text = str(exc).strip()
    if text:
        return text
    return repr(exc)


def _request_body(
    prompt: str,
    model: str,
    response_format: Optional[dict],
    *,
    include_tuning: bool = True,
    local_no_think: bool = False,
    max_tokens_override: int | None = None,
) -> dict:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": _local_prompt(prompt) if local_no_think else prompt}],
        "temperature": 0,
    }
    if _needs_completion_tokens(model):
        body["max_completion_tokens"] = _max_tokens(max_tokens_override)
    else:
        body["max_tokens"] = _max_tokens(max_tokens_override)
    if response_format is not None:
        body["response_format"] = response_format
    if include_tuning:
        effort = _extract_reasoning_effort(model)
        if effort:
            body["reasoning_effort"] = effort
        verbosity = _extract_verbosity(model)
        if verbosity:
            body["verbosity"] = verbosity
    return body


def _message_content(payload: dict) -> str:
    message = (payload.get("choices") or [{}])[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                elif isinstance(item.get("content"), str):
                    parts.append(str(item["content"]))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(part for part in parts if part)
    return ""


async def _provider_call(prompt: str, response_format: Optional[dict], *, max_tokens: int | None = None) -> str:
    """One model turn against the active provider. Raises on transport error."""
    import httpx

    url, model, headers, is_cloud = _endpoint()
    body = _request_body(prompt, model, response_format, local_no_think=not is_cloud, max_tokens_override=max_tokens)
    timeout_default = "120" if is_cloud else "300"
    timeout = float(os.getenv("LES_EXTRACT_TIMEOUT_SEC", timeout_default))
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=body, headers=headers)
        if resp.status_code == 400 and any(k in body for k in ("reasoning_effort", "verbosity")):
            fallback_body = _request_body(
                prompt,
                model,
                response_format,
                include_tuning=False,
                local_no_think=not is_cloud,
                max_tokens_override=max_tokens,
            )
            resp = await client.post(url, json=fallback_body, headers=headers)
        resp.raise_for_status()
        return _message_content(resp.json())


async def run_structured_extraction(
    schema: dict,
    instruction: str,
    context: str,
    *,
    max_attempts: int = 3,
    max_tokens: int | None = None,
) -> se.ExtractResult:
    """Extract a schema-valid object from ``context`` using the active provider.

    Cloud providers get native ``response_format`` json-schema enforcement; local
    MLX leans on validate-and-repair. Transport failures degrade to an error
    result rather than raising into the caller.
    """
    _url, _model, _headers, is_cloud = _endpoint()

    async def call_provider(prompt: str, response_format: Optional[dict]) -> str:
        if max_tokens is None:
            return await _provider_call(prompt, response_format)
        return await _provider_call(prompt, response_format, max_tokens=max_tokens)

    try:
        result = await se.aextract(
            schema,
            instruction,
            context,
            call_provider,
            max_attempts=max_attempts,
            use_cloud_response_format=is_cloud,
        )
    except Exception as exc:  # native cloud schema/transport can fail before validation
        if not is_cloud:
            return se.ExtractResult(ok=False, data=None, attempts=0, errors=[f"provider error: {_format_exception(exc)}"])
        first_error = f"provider error: {_format_exception(exc)}"
        try:
            fallback = await se.aextract(
                schema,
                instruction,
                context,
                call_provider,
                max_attempts=max_attempts,
                use_cloud_response_format=False,
            )
        except Exception as fallback_exc:  # transport / provider error
            return se.ExtractResult(
                ok=False,
                data=None,
                attempts=0,
                errors=[first_error, f"provider fallback error: {_format_exception(fallback_exc)}"],
            )
        fallback.errors = [first_error, *fallback.errors]
        return fallback if fallback.ok else fallback

    if (
        is_cloud
        and not result.ok
        and any("валидного JSON" in str(error) for error in (result.errors or []))
    ):
        fallback = await se.aextract(
            schema,
            instruction,
            context,
            call_provider,
            max_attempts=max_attempts,
            use_cloud_response_format=False,
        )
        if fallback.ok:
            return fallback
        fallback.errors = [*result.errors, *fallback.errors]
        return fallback
    return result
