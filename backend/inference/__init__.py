"""Слой инференса Л.Е.С. (W3.1): протоколы провайдеров + общий rules-валидатор.

Провайдеры (chat/embed/validator/rerank/ocr) уже работают через
OpenAI-совместимый путь (`proxy/routers/chat.py:_llm_runtime`) и MLX-host;
здесь — формальные протоколы (контракт) и переиспользуемая детерминированная
логика, которую раньше держал только `mlx_host` (ADR-11: rules до LLM).
"""

from backend.inference.providers import (
    ChatProvider,
    EmbedProvider,
    OCRProvider,
    RerankProvider,
    ValidatorProvider,
)
from backend.inference.validator import rules_pre_verdict, rules_validate

__all__ = [
    "ChatProvider",
    "EmbedProvider",
    "OCRProvider",
    "RerankProvider",
    "ValidatorProvider",
    "rules_pre_verdict",
    "rules_validate",
]
