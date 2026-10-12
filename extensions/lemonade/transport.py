"""Pure request normalization for Lemonade's OpenAI-compatible transport."""

from __future__ import annotations

import re
from typing import Any, Mapping


_QWEN_36_MODEL = re.compile(
    r"(?:^|[^a-z0-9])qwen[-_ ]?3[.]6(?:$|[^0-9])",
    re.IGNORECASE,
)


def lemonade_transport_options(
    body: Mapping[str, Any],
    *,
    provider: str | None,
    model_id: str | None,
    backend: str | None,
) -> dict[str, Any]:
    """Apply the bounded Qwen 3.6 non-FLM no-thinking transport option.

    Missing or unknown provider/model/backend facts fail closed by returning a
    copy unchanged. An explicit caller value always wins.
    """
    normalized = dict(body)
    if (provider or "").strip().lower() != "lemonade":
        return normalized
    if (backend or "").strip().lower() != "llama_cpp":
        return normalized
    if not _QWEN_36_MODEL.search((model_id or "").strip()):
        return normalized

    template_options = dict(normalized.get("chat_template_kwargs") or {})
    if "enable_thinking" in template_options:
        return normalized
    template_options["enable_thinking"] = False
    normalized["chat_template_kwargs"] = template_options
    return normalized
