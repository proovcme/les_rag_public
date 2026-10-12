"""Canonical process environment for the Windows Lemonade adapter."""

from __future__ import annotations


def windows_runtime_environment(*, adapter_port: int = 18080) -> dict[str, str]:
    adapter_url = f"http://127.0.0.1:{adapter_port}"
    return {
        "LEMONADE_BASE_URL": "http://127.0.0.1:13305/api/v1",
        "LEMONADE_HOST_PORT": str(adapter_port),
        "MLX_URL": adapter_url,
        "EMBED_URL_PARSE": adapter_url,
        "LEMONADE_EMBED_MODEL": "Qwen3-Embedding-0.6B-GGUF",
        "EMBED_MODEL": "Qwen3-Embedding-0.6B-GGUF",
        # Сметный RAG строит карточки норм через тот же адаптер: несовпадающее имя
        # модели отбивается им как 409 embedding_model_mismatch.
        "LES_SMETA_NORM_EMBED_MODEL": "Qwen3-Embedding-0.6B-GGUF",
        "EMBEDDING_MODEL": "Qwen/Qwen3-Embedding-0.6B",
        "LEMONADE_EMBED_BACKEND": "llama_cpp",
        "EMBED_BACKEND": "llama_cpp",
        "LES_EMBED_PROFILE": "qwen",
        "RAG_VECTOR_SIZE": "1024",
    }
