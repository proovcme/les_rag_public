"""W2.2: cross-encoder реранкер — клиент, переключатель, эндпоинт-логика."""

import pytest

from backend.reranker import (
    CrossEncoderReranker,
    RankedChunk,
    Reranker,
    SentenceTransformerReranker,
    select_reranker_cls,
)


def _chunks(n):
    return [{"text": f"чанк номер {i} с содержимым", "metadata": {"doc_name": f"d{i}"}, "score": 0.5} for i in range(n)]


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload
        self.sent = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None, **kw):
        self.sent = {"url": url, "json": json}
        return _FakeResp(self._payload)


@pytest.mark.asyncio
async def test_rerank_orders_by_endpoint_results(monkeypatch):
    import httpx

    payload = {"results": [{"index": 2, "score": 3.2}, {"index": 0, "score": 1.1}, {"index": 1, "score": -2.0}]}
    fake = _FakeClient(payload)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: fake)

    rr = CrossEncoderReranker(mlx_url="http://test:8080")
    ranked = await rr.rerank("вопрос", _chunks(3), top_k=2)

    assert [r.metadata["doc_name"] for r in ranked] == ["d2", "d0"]
    assert ranked[0].rank == 1 and ranked[0].score == pytest.approx(3.2)
    assert fake.sent["url"].endswith("/v1/rerank")
    assert len(fake.sent["json"]["documents"]) == 3


@pytest.mark.asyncio
async def test_rerank_passthrough_only_for_single_candidate():
    rr = CrossEncoderReranker()
    ranked = await rr.rerank("вопрос", _chunks(1), top_k=5)
    assert len(ranked) == 1
    assert all(isinstance(r, RankedChunk) for r in ranked)


@pytest.mark.asyncio
async def test_rerank_raises_on_empty_results(monkeypatch):
    import httpx

    fake = _FakeClient({"results": []})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: fake)
    rr = CrossEncoderReranker()
    with pytest.raises(RuntimeError):
        await rr.rerank("вопрос", _chunks(5), top_k=2)


@pytest.mark.asyncio
async def test_cross_encoder_waits_for_a_valid_slow_host_response(monkeypatch):
    """A local host permits 60 s; the outer client must not abandon it at 30 s."""
    import httpx

    received = []

    class SlowHost(_FakeClient):
        def __init__(self, *, timeout, **kwargs):
            super().__init__({"results": [{"index": i, "score": 1.0}
                                        for i in reversed(range(24))]})
            self.deadline = httpx.Timeout(timeout).read

        async def post(self, url, json=None, **kwargs):
            received.append(json)
            # Virtual elapsed time: exercise the timeout boundary without a
            # 35-second sleep in the offline suite. Live replay is separate.
            if self.deadline < 35:
                raise httpx.ReadTimeout("host result arrives after 35 seconds")
            return await super().post(url, json=json, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", SlowHost)
    ranked = await CrossEncoderReranker().rerank("original query", _chunks(24), top_k=24)
    assert [r.metadata["doc_name"] for r in ranked] == [f"d{i}" for i in reversed(range(24))]
    assert len(received) == 1
    assert received[0]["query"] == "original query"
    assert received[0]["documents"] == [c["text"] for c in _chunks(24)]
    with pytest.raises(httpx.ReadTimeout):
        await CrossEncoderReranker(timeout=10).rerank("original query", _chunks(24), top_k=24)


@pytest.mark.asyncio
async def test_cross_encoder_batches_without_losing_global_indices_or_scores(monkeypatch):
    import httpx
    calls = []
    chunks = [{"text": str(i), "metadata": {"index": i}, "score": 0.25} for i in range(49)]

    class BoundedHost(_FakeClient):
        async def post(self, url, json=None, **kwargs):
            calls.append(json)
            if len(json["documents"]) > 24:
                raise httpx.ReadTimeout("host cannot finish an oversized pool")
            results = [{"index": i, "score": float(text)} for i, text in enumerate(json["documents"])]
            return _FakeResp({"results": sorted(results, key=lambda r: -r["score"])[:json["top_k"]]})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: BoundedHost({}))
    result = await CrossEncoderReranker().rerank("unchanged query", chunks, top_k=3)
    assert [len(c["documents"]) for c in calls] == [24, 24, 1]
    assert [text for c in calls for text in c["documents"]] == [c["text"] for c in chunks]
    assert all(c["query"] == "unchanged query" for c in calls)
    assert [r.metadata["index"] for r in result] == [48, 47, 46]
    assert [r.score for r in result] == [48.0, 47.0, 46.0]
    assert [r.rank for r in result] == [1, 2, 3]
    assert all(r.original_score == 0.25 for r in result)


@pytest.mark.asyncio
async def test_cross_encoder_batch_failure_never_returns_successful_prefix(monkeypatch):
    import httpx
    calls = []

    class FailingTail(_FakeClient):
        async def post(self, url, json=None, **kwargs):
            calls.append(json)
            if len(calls) == 2:
                raise httpx.ReadTimeout("second batch failed")
            return _FakeResp({"results": [{"index": i, "score": 1.0} for i in range(len(json["documents"]))]})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: FailingTail({}))
    with pytest.raises(httpx.ReadTimeout, match="second batch failed"):
        await CrossEncoderReranker().rerank("unchanged", _chunks(25), top_k=25)
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("tail", [[], [{"index": 99, "score": 2.0}]])
async def test_cross_encoder_rejects_empty_or_invalid_tail_batch(monkeypatch, tail):
    import httpx
    calls = []

    class EmptyTail(_FakeClient):
        async def post(self, url, json=None, **kwargs):
            calls.append(json)
            results = ([{"index": i, "score": 1.0} for i in range(24)] if len(calls) == 1 else tail)
            return _FakeResp({"results": results})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: EmptyTail({}))
    with pytest.raises(RuntimeError, match="пустой результат"):
        await CrossEncoderReranker().rerank("unchanged", _chunks(25), top_k=25)
    assert len(calls) == 2


def test_select_reranker_cls_default_is_platform_aware(monkeypatch):
    import sys

    monkeypatch.delenv("RERANKER_BACKEND", raising=False)
    if sys.platform.startswith("win"):
        assert select_reranker_cls() is SentenceTransformerReranker
    else:
        assert select_reranker_cls() is CrossEncoderReranker


def test_select_reranker_cls_llm_escape_hatch(monkeypatch):
    monkeypatch.setenv("RERANKER_BACKEND", "llm")
    assert select_reranker_cls() is Reranker
