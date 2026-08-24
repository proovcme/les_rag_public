from types import SimpleNamespace

import pytest

from backend.raptor_summarizer import (
    ExtractiveRaptorSummarizer,
    OllamaRaptorSummarizer,
    summarizer_from_policy,
)


def test_extractive_summary_is_bounded_and_source_only():
    summarizer = ExtractiveRaptorSummarizer(input_max_chars=256, summary_max_chars=128)
    title, summary = summarizer(["Exact 42 mm. " * 30], 1)
    assert len(summary) <= 128
    assert "42 mm" in summary
    assert title


def test_ollama_summary_uses_local_deterministic_request():
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "Требование 42 мм. Исключений нет."}}

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    summarizer = OllamaRaptorSummarizer(
        base_url="http://127.0.0.1:11434/",
        model="qwen3.5:9b",
        post=post,
    )
    title, summary = summarizer(["Требование 42 мм."], 2)
    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["json"]["options"]["temperature"] == 0
    assert title == "Требование 42 мм."
    assert summary.endswith("Исключений нет.")


def test_summarizer_factory_rejects_hidden_backend():
    with pytest.raises(RuntimeError, match="UNSUPPORTED"):
        summarizer_from_policy({"summary_backend": "env-secret"})
