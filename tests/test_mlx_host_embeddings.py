from types import SimpleNamespace

import pytest

import mlx_host


@pytest.mark.asyncio
async def test_openai_embeddings_reports_the_model_that_produced_vectors(monkeypatch):
    fake_embedder = SimpleNamespace(
        model_id="Qwen/Qwen3-Embedding-0.6B",
        backend="coreml",
        encode=lambda texts: [[0.1, 0.2] for _ in texts],
    )
    monkeypatch.setattr(mlx_host, "embedder", fake_embedder)

    response = await mlx_host.embeddings_openai(
        mlx_host.OAIEmbeddingRequest(input=["test"], model="qwen3-embedding-0.6b")
    )

    assert response["model"] == "Qwen/Qwen3-Embedding-0.6B"
    assert response["embedding_model"] == "Qwen/Qwen3-Embedding-0.6B"
    assert response["requested_model"] == "qwen3-embedding-0.6b"
    assert response["embedding_backend"] == "coreml"
