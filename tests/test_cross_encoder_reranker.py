"""W2.2: cross-encoder реранкер — клиент, переключатель, эндпоинт-логика."""

import pytest

from backend.reranker import CrossEncoderReranker, RankedChunk, Reranker, select_reranker_cls


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
async def test_rerank_passthrough_when_few_chunks():
    rr = CrossEncoderReranker()
    ranked = await rr.rerank("вопрос", _chunks(2), top_k=5)
    assert len(ranked) == 2
    assert all(isinstance(r, RankedChunk) for r in ranked)


@pytest.mark.asyncio
async def test_rerank_raises_on_empty_results(monkeypatch):
    import httpx

    fake = _FakeClient({"results": []})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: fake)
    rr = CrossEncoderReranker()
    with pytest.raises(RuntimeError):
        await rr.rerank("вопрос", _chunks(5), top_k=2)


def test_select_reranker_cls_default_cross_encoder(monkeypatch):
    monkeypatch.delenv("RERANKER_BACKEND", raising=False)
    assert select_reranker_cls() is CrossEncoderReranker


def test_select_reranker_cls_llm_escape_hatch(monkeypatch):
    monkeypatch.setenv("RERANKER_BACKEND", "llm")
    assert select_reranker_cls() is Reranker
