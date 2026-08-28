from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

import backend.qdrant_adapter as qdrant_adapter
from backend.interface import EmbeddingContractError
from backend.qdrant_adapter import EmbedClient
from proxy.services.model_connection_contracts import CapabilityName, ConnectionRole
from proxy.services.model_connection_resolver_service import ModelConnectionResolutionError
from proxy.services.openai_compatible_transport_service import EmbeddingResponse


class Resolver:
    def __init__(self, resolved=None, error=None):
        self.resolved = resolved
        self.error = error
        self.calls = []

    def resolve(self, role, *, required_capabilities=frozenset()):
        self.calls.append((role, required_capabilities))
        if self.error is not None:
            raise self.error
        return self.resolved


class Transport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def embed(self, connection, inputs):
        self.calls.append((connection.revision_id, tuple(inputs)))
        return self.response


def _response(vectors, model="embed-model"):
    return EmbeddingResponse(
        vectors=tuple(tuple(row) for row in vectors),
        model_id=model,
        usage={},
    )


def test_active_embed_client_uses_exact_embeddings_binding() -> None:
    resolved = SimpleNamespace(revision_id="conn:embed:r3")
    resolver = Resolver(resolved)
    transport = Transport(_response([[0.1, 0.2]]))
    client = EmbedClient(
        "http://legacy",
        model="embed-model",
        connection_mode="active",
        connection_resolver=resolver,
        connection_transport=transport,
    )

    assert client.encode_sync(["duct"]) == [[0.1, 0.2]]
    assert resolver.calls == [
        (ConnectionRole.EMBEDDINGS, frozenset({CapabilityName.EMBEDDINGS}))
    ]
    assert transport.calls == [("conn:embed:r3", ("duct",))]


def test_shadow_embedding_uses_legacy_once_and_never_calls_candidate(monkeypatch) -> None:
    legacy_calls = []

    def post(_url, *, json, timeout):
        legacy_calls.append(tuple(json["input"]))
        return httpx.Response(
            200,
            json={
                "model": "embed-model",
                "data": [{"index": 0, "embedding": [1.0]}],
            },
        )

    monkeypatch.setattr(qdrant_adapter.httpx, "post", post)
    resolver = Resolver(SimpleNamespace(revision_id="conn:candidate:r1"))
    transport = Transport(_response([[9.0]]))
    client = EmbedClient(
        "http://legacy",
        model="embed-model",
        backend="ollama",
        connection_mode="shadow",
        connection_resolver=resolver,
        connection_transport=transport,
    )

    assert client.encode_sync(["valve"]) == [[1.0]]
    assert len(legacy_calls) == 1
    assert len(resolver.calls) == 1
    assert transport.calls == []


def test_active_embedding_never_substitutes_answer_or_fallback() -> None:
    resolver = Resolver(error=ModelConnectionResolutionError("ROLE_BINDING_MISSING: embeddings"))
    transport = Transport(_response([[9.0]]))
    client = EmbedClient(
        "http://legacy",
        model="embed-model",
        connection_mode="active",
        connection_resolver=resolver,
        connection_transport=transport,
    )

    with pytest.raises(ModelConnectionResolutionError, match="ROLE_BINDING_MISSING: embeddings"):
        client.encode_sync(["valve"])

    assert resolver.calls == [
        (ConnectionRole.EMBEDDINGS, frozenset({CapabilityName.EMBEDDINGS}))
    ]
    assert transport.calls == []


@pytest.mark.asyncio
async def test_active_query_preserves_instruction_and_batch_order(monkeypatch) -> None:
    monkeypatch.setenv("LES_EMBED_PROFILE", "qwen")
    monkeypatch.setenv("RAG_QUERY_EMBEDDING_MODE", "qwen-retrieval-v1")
    resolver = Resolver(SimpleNamespace(revision_id="conn:embed:r1"))
    transport = Transport(_response([[1.0, 1.1], [2.0, 2.1]]))
    client = EmbedClient(
        "http://legacy",
        model="embed-model",
        connection_mode="active",
        connection_resolver=resolver,
        connection_transport=transport,
    )

    vectors = await client.encode_async(["first", "second"], query=True)

    assert vectors == [[1.0, 1.1], [2.0, 2.1]]
    sent = transport.calls[0][1]
    assert sent[0].startswith("Instruct: Given a search query")
    assert sent[0].endswith("Query: first")
    assert sent[1].endswith("Query: second")


def test_active_embedding_rejects_observed_model_and_dimension_drift() -> None:
    resolved = SimpleNamespace(revision_id="conn:embed:r1")
    wrong_model = EmbedClient(
        "http://legacy",
        model="embed-model",
        connection_mode="active",
        connection_resolver=Resolver(resolved),
        connection_transport=Transport(_response([[1.0]], model="other-model")),
    )
    with pytest.raises(EmbeddingContractError, match="embedding contract mismatch"):
        wrong_model.encode_sync(["one"])

    mixed_dimensions = EmbedClient(
        "http://legacy",
        model="embed-model",
        connection_mode="active",
        connection_resolver=Resolver(resolved),
        connection_transport=Transport(_response([[1.0], [2.0, 3.0]])),
    )
    with pytest.raises(EmbeddingContractError, match="embedding dimension mismatch"):
        mixed_dimensions.encode_sync(["one", "two"])
