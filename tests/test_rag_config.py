from backend.rag_config import (
    embedding_api_model,
    embedding_model_id,
    rag_collection_name,
    rag_meta_db_path,
    rag_runtime_config,
    rag_vector_size,
)


def test_legacy_profile_keeps_bge_backward_compatibility(monkeypatch):
    monkeypatch.setenv("LES_EMBED_PROFILE", "legacy")
    monkeypatch.setenv("BGE_MODEL", "BAAI/bge-m3")
    monkeypatch.setenv("EMBED_MODEL", "bge-m3")
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("RAG_COLLECTION_NAME", raising=False)
    monkeypatch.delenv("RAG_META_DB_PATH", raising=False)

    assert embedding_model_id() == "BAAI/bge-m3"
    assert embedding_api_model() == "bge-m3"
    assert rag_collection_name() == "les_rag"
    assert rag_meta_db_path() == "./data/les_meta.db"


def test_qwen_profile_uses_qwen_defaults_without_mixing_bge_env(monkeypatch):
    monkeypatch.setenv("LES_EMBED_PROFILE", "qwen")
    monkeypatch.setenv("BGE_MODEL", "BAAI/bge-m3")
    monkeypatch.setenv("EMBED_MODEL", "bge-m3")
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("RAG_COLLECTION_NAME", raising=False)
    monkeypatch.delenv("RAG_META_DB_PATH", raising=False)
    monkeypatch.delenv("RAG_VECTOR_SIZE", raising=False)

    assert embedding_model_id() == "Qwen/Qwen3-Embedding-0.6B"
    assert embedding_api_model() == "qwen3-embedding-0.6b"
    assert rag_collection_name() == "les_rag_qwen3_06b"
    assert rag_meta_db_path() == "./data/les_meta_qwen.db"
    assert rag_vector_size() == 1024


def test_runtime_config_exposes_single_active_profile_trace(monkeypatch):
    monkeypatch.setenv("LES_EMBED_PROFILE", "qwen")
    monkeypatch.delenv("RAG_COLLECTION_NAME", raising=False)
    monkeypatch.delenv("RAG_META_DB_PATH", raising=False)

    config = rag_runtime_config()

    assert config["profile"] == "qwen"
    assert config["collection"] == "les_rag_qwen3_06b"
    assert config["meta_db"] == "./data/les_meta_qwen.db"
    assert config["embedding_api_model"] == "qwen3-embedding-0.6b"
