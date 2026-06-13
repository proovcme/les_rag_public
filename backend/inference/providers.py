"""Протоколы провайдеров инференса (W3.1).

Формализуют контракт того, что УЖЕ работает в коде, без смены поведения:
- chat: `proxy/routers/chat.py:_llm_runtime` (mlx/openrouter/openai/ollama/lemonade,
  единый OpenAI-совместимый `/v1/chat/completions`);
- embed: `backend/qdrant_adapter.EmbedClient` (MLX `/v1/embeddings`);
- validator: rules (`backend.inference.validator`) → MLX `/api/validate` / облачный LLM;
- rerank: `mlx_host.CrossEncoderReranker` (`/v1/rerank`, W2.2);
- ocr: `backend/ocr_parser.MLXVisualOCRParser`.

Используются как `typing.Protocol` (structural) — существующие классы им
соответствуют без наследования. Цель — единая точка типизации/документации
и опора для дальнейшей пошаговой миграции вызовов на провайдеро-агностичный путь.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ChatProvider(Protocol):
    """LLM чата. Реализация — OpenAI-совместимый POST на `chat_url`."""

    provider: str
    base_url: str
    chat_url: str
    model: str
    api_key: str
    supports_validation: bool


@runtime_checkable
class EmbedProvider(Protocol):
    """Эмбеддер. Текущая реализация — `EmbedClient` к MLX `/v1/embeddings`."""

    def encode_sync(self, texts: list[str]) -> list[list[float]]: ...

    async def encode_async(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class ValidatorProvider(Protocol):
    """Валидатор фактов (Т.О.С.К.А.). Возвращает VERIFIED/HALLUCINATION/NO_DATA."""

    def validate(self, question: str, answer: str, context: str) -> dict[str, Any]: ...


@runtime_checkable
class RerankProvider(Protocol):
    """Кросс-энкодер реранкер (W2.2). Возвращает скоры по парам (query, doc)."""

    def score(self, query: str, documents: list[str]) -> list[float]: ...


@runtime_checkable
class OCRProvider(Protocol):
    """Визуальный OCR. Текущая реализация — MLX GLM-OCR / Tesseract-фолбэк."""

    def ocr_page(self, image: Any, prompt: str = ...) -> str: ...
