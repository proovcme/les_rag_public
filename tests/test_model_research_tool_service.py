from types import SimpleNamespace

import pytest

from proxy.services.model_research_tool_service import ModelResearchToolService


class _Retrieval:
    def __init__(self):
        self.chunks = [
            SimpleNamespace(
                content="Точный фрагмент",
                doc_name="Письмо.pdf",
                score=0.73,
                meta={
                    "dataset_id": "selected-a",
                    "chunk_id": "chunk-7",
                    "page": 4,
                    "rrf_score": 0.031,
                    "retrieval_channels": ["dense", "bm25_sparse"],
                },
            )
        ]

    def payload(self):
        return {
            "schema": "retrieval_trace_v1",
            "fusion": "native_rrf",
            "retrieval_channels": ["dense", "bm25_sparse"],
        }


@pytest.mark.asyncio
async def test_search_sources_uses_canonical_retriever_and_frozen_scope():
    calls = []

    async def retrieve(**kwargs):
        calls.append(kwargs)
        return _Retrieval()

    service = ModelResearchToolService(
        retrieve=retrieve,
        frozen_dataset_ids=("selected-a", "selected-b"),
        retrieval_kwargs={"rag_backend": "backend", "return_trace": True},
        fallback=lambda *_args: pytest.fail("fallback must not run"),
    )

    result = await service.execute(
        {
            "tool": "search_sources",
            "args": {"q": "котёл", "dataset_ids": ["foreign-dataset"]},
        }
    )

    assert calls == [
        {
            "question": "котёл",
            "dataset_ids": ["selected-a", "selected-b"],
            "rag_backend": "backend",
            "return_trace": True,
        }
    ]
    assert result.chunks == tuple(_Retrieval().chunks)
    assert result.payload["trace"]["fusion"] == "native_rrf"
    assert result.payload["result"]["hits"][0]["content"] == "Точный фрагмент"


@pytest.mark.asyncio
async def test_search_sources_preserves_rrf_provenance_in_tool_payload():
    async def retrieve(**_kwargs):
        return _Retrieval()

    service = ModelResearchToolService(
        retrieve=retrieve,
        frozen_dataset_ids=("selected-a",),
        retrieval_kwargs={},
        fallback=lambda *_args: pytest.fail("fallback must not run"),
    )

    result = await service.execute({"tool": "search_sources", "args": {"q": "письмо"}})
    hit = result.payload["result"]["hits"][0]

    assert hit["meta"]["chunk_id"] == "chunk-7"
    assert hit["meta"]["rrf_score"] == 0.031
    assert hit["meta"]["retrieval_channels"] == ["dense", "bm25_sparse"]
    assert result.payload["trace"]["retrieval_channels"] == ["dense", "bm25_sparse"]


@pytest.mark.asyncio
async def test_non_search_tool_delegates_unchanged():
    delegated = []
    payload = {"schema": "les_tool_result_v1", "tool": "read_source", "result": {"x": 1}}

    async def fallback(tool, args):
        delegated.append((tool, args))
        return payload

    service = ModelResearchToolService(
        retrieve=lambda **_kwargs: pytest.fail("retriever must not run"),
        frozen_dataset_ids=("selected-a",),
        retrieval_kwargs={},
        fallback=fallback,
    )

    result = await service.execute({"tool": "read_source", "args": {"doc_id": "d1"}})

    assert delegated == [("read_source", {"doc_id": "d1"})]
    assert result.payload is payload
    assert result.chunks == ()
