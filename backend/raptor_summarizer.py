"""Explicit RAPTOR summarizers selected by the persisted GUI policy."""

from __future__ import annotations

import re
from typing import Any, Callable


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _title(summary: str, depth: int) -> str:
    first = re.split(r"(?<=[.!?])\s+|\n", summary, maxsplit=1)[0].strip(" #:-")
    return (first or f"RAPTOR level {depth}")[:240]


class ExtractiveRaptorSummarizer:
    """Fast, deterministic fallback; never invents text absent from leaves."""

    def __init__(self, *, input_max_chars: int = 12000, summary_max_chars: int = 1800):
        self.input_max_chars = max(256, int(input_max_chars))
        self.summary_max_chars = max(128, int(summary_max_chars))

    def __call__(self, texts: list[str], depth: int) -> tuple[str, str]:
        joined = " ".join(_compact(text) for text in texts if _compact(text))
        summary = joined[: min(self.input_max_chars, self.summary_max_chars)].rstrip()
        if not summary:
            raise RuntimeError("RAPTOR_SUMMARY_EMPTY")
        return _title(summary, depth), summary


class OllamaRaptorSummarizer:
    """Local abstractive summarizer with bounded input and deterministic settings."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        input_max_chars: int = 12000,
        summary_max_chars: int = 1800,
        post: Callable[..., Any] | None = None,
    ) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.model = str(model).strip()
        self.input_max_chars = max(256, int(input_max_chars))
        self.summary_max_chars = max(128, int(summary_max_chars))
        self._post = post

    def __call__(self, texts: list[str], depth: int) -> tuple[str, str]:
        source = "\n\n---\n\n".join(str(text) for text in texts)[: self.input_max_chars]
        if not source.strip():
            raise RuntimeError("RAPTOR_SUMMARY_SOURCE_EMPTY")
        prompt = (
            "Суммируй фрагменты документа для навигационного поиска. "
            "Не добавляй факты, числа или выводы, которых нет в источнике. "
            "Сохрани обозначения, требования, исключения и числовые значения. "
            f"Уровень дерева: {int(depth)}. Ответ только кратким связным резюме.\n\n"
            f"ИСТОЧНИК:\n{source}"
        )
        if self._post is None:
            import httpx

            post = httpx.post
        else:
            post = self._post
        response = post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "stream": False,
                "messages": [{"role": "user", "content": prompt}],
                "options": {"temperature": 0},
            },
            timeout=180.0,
        )
        response.raise_for_status()
        payload = response.json()
        message = payload.get("message") if isinstance(payload, dict) else None
        summary = _compact(message.get("content") if isinstance(message, dict) else "")
        if not summary:
            raise RuntimeError("RAPTOR_SUMMARY_EMPTY")
        summary = summary[: self.summary_max_chars].rstrip()
        return _title(summary, depth), summary


def summarizer_from_policy(policy: dict[str, Any]) -> Any:
    backend = str(policy.get("summary_backend") or "").strip().lower()
    kwargs = {
        "input_max_chars": int(policy.get("summary_input_chars") or 12000),
        "summary_max_chars": int(policy.get("summary_max_chars") or 1800),
    }
    if backend == "extractive":
        return ExtractiveRaptorSummarizer(**kwargs)
    if backend == "ollama":
        return OllamaRaptorSummarizer(
            base_url=str(policy.get("summary_api_url") or ""),
            model=str(policy.get("summary_model") or ""),
            **kwargs,
        )
    raise RuntimeError("RAPTOR_SUMMARY_BACKEND_UNSUPPORTED")
