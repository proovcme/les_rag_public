from __future__ import annotations

import pytest

from backend.reranker import (
    CrossEncoderReranker,
    RankedChunk,
    Reranker,
    SentenceTransformerReranker,
    resolve_rerank_device,
)


def test_resolve_rerank_device_falls_back_to_cpu_when_cuda_unavailable(monkeypatch):
    class _FakeCuda:
        @staticmethod
        def is_available():
            return False

    class _FakeTorch:
        cuda = _FakeCuda
        version = type("V", (), {"cuda": None})()

    monkeypatch.setitem(__import__("sys").modules, "torch", _FakeTorch)
    assert resolve_rerank_device("cuda") == "cpu"
    assert resolve_rerank_device("cuda:0") == "cpu"


def test_resolve_rerank_device_keeps_cuda_when_available(monkeypatch):
    class _FakeCuda:
        @staticmethod
        def is_available():
            return True

    class _FakeTorch:
        cuda = _FakeCuda
        version = type("V", (), {"cuda": "12.4"})()

    monkeypatch.setitem(__import__("sys").modules, "torch", _FakeTorch)
    assert resolve_rerank_device("cuda") == "cuda"


def test_sentence_transformer_uses_resolved_device(monkeypatch):
    monkeypatch.setenv("RERANK_DEVICE", "cuda")
    monkeypatch.setattr(
        "backend.reranker.resolve_rerank_device",
        lambda requested=None: "cpu",
    )
    reranker = SentenceTransformerReranker(model="test/reranker")
    assert reranker.device == "cpu"


@pytest.mark.asyncio
async def test_llm_reranker_scores_pool_even_when_top_k_keeps_every_chunk(monkeypatch):
    reranker = Reranker(model="qwen3.5:9b", mode="batch")
    calls: list[int] = []

    async def score_batch(_query, chunks):
        calls.append(len(chunks))
        return [1.0, 9.0]

    monkeypatch.setattr(reranker, "_score_batch", score_batch)
    ranked = await reranker.rerank(
        "вопрос",
        [{"text": "слабый", "score": 0.8}, {"text": "сильный", "score": 0.2}],
        top_k=2,
    )

    assert calls == [2]
    assert [item.text for item in ranked] == ["сильный", "слабый"]


@pytest.mark.asyncio
async def test_cross_encoder_calls_endpoint_even_when_top_k_keeps_every_chunk(monkeypatch):
    reranker = CrossEncoderReranker(mlx_url="http://reranker")
    called: list[str] = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [{"index": 1, "score": 3.0}, {"index": 0, "score": 1.0}]}

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, json):
            called.append(url)
            assert json["top_k"] == 2
            return Response()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    ranked = await reranker.rerank(
        "вопрос",
        [
            {"text": "первый", "metadata": {"_idx": 0}, "score": 0.9},
            {"text": "второй", "metadata": {"_idx": 1}, "score": 0.1},
        ],
        top_k=2,
    )

    assert called == ["http://reranker/v1/rerank"]
    assert all(isinstance(item, RankedChunk) for item in ranked)
    assert [item.text for item in ranked] == ["второй", "первый"]


@pytest.mark.asyncio
async def test_sentence_transformer_reranker_scores_in_thread_without_answer_llm(monkeypatch):
    reranker = SentenceTransformerReranker(model="test/reranker")
    calls: list[tuple[str, int]] = []

    def score(query, chunks):
        calls.append((query, len(chunks)))
        return [0.1, 0.9]

    monkeypatch.setattr(reranker, "_score", score)
    ranked = await reranker.rerank(
        "нужный вопрос",
        [{"text": "шум", "score": 0.8}, {"text": "ответ", "score": 0.2}],
        top_k=2,
    )

    assert calls == [("нужный вопрос", 2)]
    assert [item.text for item in ranked] == ["ответ", "шум"]
