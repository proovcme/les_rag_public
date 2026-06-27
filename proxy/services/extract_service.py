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
from typing import Optional

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


async def _provider_call(prompt: str, response_format: Optional[dict]) -> str:
    """One model turn against the active provider. Raises on transport error."""
    import httpx

    url, model, headers, _is_cloud = _endpoint()
    body: dict = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}
    if _needs_completion_tokens(model):
        body["max_completion_tokens"] = 1024
    else:
        body["max_tokens"] = 1024
    if response_format is not None:
        body["response_format"] = response_format
    timeout = float(os.getenv("LES_EXTRACT_TIMEOUT_SEC", "120"))
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def run_structured_extraction(
    schema: dict,
    instruction: str,
    context: str,
    *,
    max_attempts: int = 3,
) -> se.ExtractResult:
    """Extract a schema-valid object from ``context`` using the active provider.

    Cloud providers get native ``response_format`` json-schema enforcement; local
    MLX leans on validate-and-repair. Transport failures degrade to an error
    result rather than raising into the caller.
    """
    _url, _model, _headers, is_cloud = _endpoint()
    try:
        return await se.aextract(
            schema,
            instruction,
            context,
            _provider_call,
            max_attempts=max_attempts,
            use_cloud_response_format=is_cloud,
        )
    except Exception as exc:  # transport / provider error
        return se.ExtractResult(ok=False, data=None, attempts=0, errors=[f"provider error: {exc}"])
