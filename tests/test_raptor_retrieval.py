from types import SimpleNamespace

import pytest

from backend.qdrant_adapter import QdrantLlamaIndexAdapter


@pytest.mark.asyncio
async def test_raptor_navigation_can_only_return_evidence_leaves(monkeypatch):
    monkeypatch.setenv("RAG_QDRANT_SCHEMA", "named")
    leaf_id = "1" * 32

    class AsyncClient:
        async def get_aliases(self):
            return SimpleNamespace(
                aliases=[
                    SimpleNamespace(alias_name="les_rag", collection_name="main-v1")
                ]
            )

        async def query_points(self, **kwargs):
            assert kwargs["collection_name"] == "main-v1__raptor_v1"
            return SimpleNamespace(
                points=[
                    SimpleNamespace(
                        id="a" * 32,
                        payload={
                            "node_id": "route-1",
                            "node_role": "navigation",
                            "descendant_leaf_ids": [leaf_id],
                        },
                    )
                ]
            )

        async def retrieve(self, **kwargs):
            assert kwargs["collection_name"] == "les_rag"
            return [
                SimpleNamespace(
                    id=leaf_id,
                    payload={
                        "text": "Exact source requirement 42 mm",
                        "doc_id": "doc-1",
                        "file_name": "source.pdf",
                        "node_role": "evidence",
                    },
                )
            ]

    adapter = QdrantLlamaIndexAdapter.__new__(QdrantLlamaIndexAdapter)
    adapter.collection_name = "les_rag"
    adapter.aclient = AsyncClient()
    adapter.embed = SimpleNamespace(
        encode_async=lambda *_args, **_kwargs: _async_value([[0.1, 0.2]])
    )

    chunks = await adapter.retrieve_raptor_evidence(
        "technical requirement",
        target_collection="main-v1__raptor_v1",
        source_collection="main-v1",
        dataset_ids=["ds"],
        route_k=4,
        top_k=8,
    )

    assert len(chunks) == 1
    assert chunks[0].content == "Exact source requirement 42 mm"
    assert chunks[0].meta["raptor_route_id"] == "route-1"
    assert chunks[0].meta["node_role"] == "evidence"


async def _async_value(value):
    return value
