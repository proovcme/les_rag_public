import sys
from types import SimpleNamespace

import backend.rag_config as rag_config_module
from backend.rag_config import (
    embedding_api_model,
    embedding_model_id,
    prepare_query_for_embedding,
    query_embedding_instruction_id,
    query_embedding_mode,
    rag_collection_name,
    rag_meta_db_path,
    rag_runtime_config,
    rag_vector_size,
    index_contract_payload,
    index_contract_status,
    write_index_contract,
    token_length_fn,
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
    assert config["query_embedding_mode"] == "raw-v1"


def test_qwen_instruction_mode_is_opt_in_and_query_only(monkeypatch):
    monkeypatch.setenv("LES_EMBED_PROFILE", "qwen")
    monkeypatch.setenv("RAG_QUERY_EMBEDDING_MODE", "qwen-retrieval-v1")

    assert query_embedding_mode() == "qwen-retrieval-v1"
    assert query_embedding_instruction_id() == "qwen-retrieval-v1"
    assert prepare_query_for_embedding("Какие системы есть?") == (
        "Instruct: Given a search query, retrieve relevant passages from the selected corpus\n"
        "Query: Какие системы есть?"
    )


def test_qwen_instruction_mode_fails_safe_for_other_embedding_profile(monkeypatch):
    monkeypatch.setenv("LES_EMBED_PROFILE", "legacy")
    monkeypatch.setenv("RAG_QUERY_EMBEDDING_MODE", "qwen-retrieval-v1")

    assert query_embedding_mode() == "raw-v1"
    assert prepare_query_for_embedding("Where is the source?") == "Where is the source?"


def test_index_contract_is_versioned_and_detects_runtime_drift(monkeypatch, tmp_path):
    contract_path = tmp_path / "index-contract.json"
    monkeypatch.setenv("RAG_INDEX_CONTRACT_PATH", str(contract_path))
    monkeypatch.setenv("LES_EMBED_PROFILE", "qwen")
    monkeypatch.setenv("RAG_COLLECTION_NAME", "contract-test")
    monkeypatch.setenv("RAG_CHUNK_UNIT", "chars")
    monkeypatch.setenv("RAG_CHUNK_SIZE", "900")

    payload = index_contract_payload()
    assert payload["schema"] == "les.rag.index-contract.v1"
    assert payload["document_embedding_mode"] == "raw-v1"
    write_index_contract()
    assert index_contract_status()["compatible"] is True

    monkeypatch.setenv("RAG_VECTOR_SIZE", "384")
    status = index_contract_status()
    assert status["status"] == "mismatch"
    assert status["compatible"] is False


def test_tokenizer_loading_is_local_only_by_default(monkeypatch):
    calls = []

    class FakeTokenizer:
        @staticmethod
        def encode(text, add_special_tokens=False):
            return text.split()

    class FakeAutoTokenizer:
        @staticmethod
        def from_pretrained(model, **kwargs):
            calls.append((model, kwargs))
            return FakeTokenizer()

    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(AutoTokenizer=FakeAutoTokenizer))
    monkeypatch.delenv("RAG_TOKENIZER_LOCAL_FILES_ONLY", raising=False)
    rag_config_module._token_len_fn_cache = None

    assert token_length_fn()("один два") == 2
    assert calls[0][1]["local_files_only"] is True
    rag_config_module._token_len_fn_cache = None
