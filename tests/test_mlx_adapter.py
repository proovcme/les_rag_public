import pytest

from backend import mlx_adapter


@pytest.mark.asyncio
async def test_mlx_memory_manager_does_not_preload_tokenizer_by_default(monkeypatch):
    calls = []
    monkeypatch.delenv("MLX_PRELOAD_TOKENIZERS", raising=False)
    monkeypatch.setattr(mlx_adapter.AutoTokenizer, "from_pretrained", lambda model: calls.append(model))
    manager = mlx_adapter.MLXMemoryManager("local-model")

    manager.start()
    manager._cleanup_task.cancel()

    assert calls == []
    assert manager.tokenizer is None


@pytest.mark.asyncio
async def test_mlx_memory_manager_can_preload_tokenizer(monkeypatch):
    monkeypatch.setenv("MLX_PRELOAD_TOKENIZERS", "true")
    monkeypatch.setattr(mlx_adapter.AutoTokenizer, "from_pretrained", lambda model: f"tokenizer:{model}")
    manager = mlx_adapter.MLXMemoryManager("local-model")

    manager.start()
    manager._cleanup_task.cancel()

    assert manager.tokenizer == "tokenizer:local-model"
