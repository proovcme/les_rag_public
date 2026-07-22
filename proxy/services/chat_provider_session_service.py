"""Validated request contract for public per-session LLM selection."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class ChatProviderConfig(BaseModel):
    """Per-request BYOK provider. Never persisted by the proxy."""

    provider: str
    model: str = ""
    api_key: str = Field(default="", repr=False)

    @field_validator("provider")
    @classmethod
    def provider_values(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in {"mlx", "openrouter", "openai"}:
            raise ValueError("Некорректный провайдер")
        return normalized

    @field_validator("model")
    @classmethod
    def model_limits(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if len(normalized) > 200:
            raise ValueError("Название модели слишком длинное")
        return normalized

    @field_validator("api_key")
    @classmethod
    def api_key_limits(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if len(normalized) > 4096:
            raise ValueError("API-ключ слишком длинный")
        return normalized

    @model_validator(mode="after")
    def cloud_fields_required(self):
        if self.provider != "mlx" and (not self.model or len(self.api_key) < 8):
            raise ValueError("Для облачной модели нужны название модели и API-ключ")
        return self
