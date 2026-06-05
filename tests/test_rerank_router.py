from types import SimpleNamespace

import pytest

from proxy.routers import rerank


class FakeRequest:
    async def json(self):
        return {
            "query": "q",
            "chunks": [{"text": "chunk", "score": 0.5, "metadata": {"doc_name": "doc"}}],
            "top_k": 1,
        }


class TrackingSemaphore:
    def __init__(self):
        self.active = False
        self.seen_inside = False

    async def __aenter__(self):
        self.active = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.active = False


@pytest.fixture()
def rerank_state():
    previous = rerank._state
    yield
    rerank._state = previous


@pytest.mark.asyncio
async def test_rerank_direct_uses_llm_budget(monkeypatch, rerank_state):
    budget = TrackingSemaphore()

    class FakeReranker:
        def __init__(self, mlx_url):
            pass

        async def rerank(self, query, chunks, top_k=5):
            budget.seen_inside = budget.active
            return [
                SimpleNamespace(
                    text="chunk",
                    score=9.0,
                    original_score=0.5,
                    rank=1,
                    metadata={"doc_name": "doc"},
                )
            ]

    monkeypatch.setattr(rerank, "RERANKER_AVAILABLE", True)
    monkeypatch.setattr(rerank, "Reranker", FakeReranker)
    rerank.set_rerank_state(rerank.RerankRouterState(llm_semaphore=budget, current_mode={"mode": "chat"}))

    response = await rerank.rerank_direct(FakeRequest(), _admin=object())

    assert budget.seen_inside is True
    assert budget.active is False
    assert response["ranked"][0]["score"] == 9.0


@pytest.mark.asyncio
async def test_rerank_direct_pauses_in_indexing_mode(monkeypatch, rerank_state):
    monkeypatch.setattr(rerank, "RERANKER_AVAILABLE", True)
    rerank.set_rerank_state(
        rerank.RerankRouterState(llm_semaphore=TrackingSemaphore(), current_mode={"mode": "indexing"})
    )

    with pytest.raises(rerank.HTTPException) as exc:
        await rerank.rerank_direct(FakeRequest(), _admin=object())

    assert exc.value.status_code == 409
