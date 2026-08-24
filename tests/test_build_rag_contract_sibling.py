from __future__ import annotations

import sqlite3
import json
from argparse import Namespace
from pathlib import Path

import pytest

from tools.build_rag_contract_sibling import (
    ParallelEmbedClient,
    _configure_contract,
    _read_json,
    _retry_call,
    _write_json_atomic,
    canonicalize_dataset_payload,
    deterministic_point_id,
    resolve_datasets,
    load_scope_manifest,
    resolve_indexed_datasets,
    scope_manifest_payload,
    scope_manifest_sha256,
    sparse_vector_or_exclusion,
    validate_embedding_health,
    verify_embedding_runtime_identity,
    verify_embedding_runtime,
)


def _db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE datasets (id TEXT PRIMARY KEY, name TEXT, chunk_count INTEGER DEFAULT 0)")
        conn.execute(
            "CREATE TABLE documents (id TEXT PRIMARY KEY, dataset_id TEXT, status TEXT, chunk_count INTEGER DEFAULT 0)"
        )
        conn.executemany(
            "INSERT INTO datasets (id, name, chunk_count) VALUES (?, ?, ?)",
            [("b", "BAI", 10), ("f", "NTD_FIRE_Index", 0), ("z", "EMPTY", 0)],
        )
        conn.execute(
            "INSERT INTO documents (id, dataset_id, status, chunk_count) VALUES ('doc-f', 'f', 'INDEXED', 3)"
        )


def test_resolve_datasets_preserves_requested_order(tmp_path: Path):
    path = tmp_path / "meta.db"
    _db(path)
    assert resolve_datasets(path, ["NTD_FIRE_Index", "BAI"]) == [
        {"id": "f", "name": "NTD_FIRE_Index"},
        {"id": "b", "name": "BAI"},
    ]


def test_resolve_datasets_rejects_unknown_name(tmp_path: Path):
    path = tmp_path / "meta.db"
    _db(path)
    with pytest.raises(ValueError, match="datasets not found: missing"):
        resolve_datasets(path, ["missing"])


def test_default_migration_scope_contains_every_indexed_dataset(tmp_path: Path):
    path = tmp_path / "meta.db"
    _db(path)

    assert resolve_indexed_datasets(path) == [
        {"id": "b", "name": "BAI"},
        {"id": "f", "name": "NTD_FIRE_Index"},
    ]


def test_general_rag_scope_excludes_module_owned_artel_and_is_exact(tmp_path: Path):
    path = tmp_path / "meta.db"
    _db(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO datasets (id, name, chunk_count) VALUES ('artel', 'ARTEL_Index', 7)"
        )
    manifest = scope_manifest_payload(path)
    assert [item["name"] for item in manifest["datasets"]] == [
        "BAI",
        "NTD_FIRE_Index",
    ]
    manifest_path = tmp_path / "scope.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded, digest = load_scope_manifest(manifest_path, path)
    assert loaded == manifest
    assert digest == scope_manifest_sha256(manifest)

    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO datasets (id, name, chunk_count) VALUES ('new', 'New project', 1)"
        )
    with pytest.raises(ValueError, match="stale"):
        load_scope_manifest(manifest_path, path)


def test_deterministic_point_id_is_idempotent_and_child_specific():
    first = deterministic_point_id(
        source_collection="src", source_point_id=7, child_ord=0, text="evidence"
    )
    assert first == deterministic_point_id(
        source_collection="src", source_point_id=7, child_ord=0, text="evidence"
    )
    assert first != deterministic_point_id(
        source_collection="src", source_point_id=7, child_ord=1, text="evidence"
    )


def test_builder_pins_physical_source_but_keeps_stable_logical_identity():
    source = Path("tools/build_rag_contract_sibling.py").read_text(encoding="utf-8")

    assert '"--source-identity"' in source
    assert "source_collection=args.source_identity or args.src" in source
    assert '"source_physical_collection": args.src' in source


def test_embedding_preflight_checks_count_and_vector_size():
    class Embed:
        def encode_sync(self, texts):
            assert texts == ["LES embedding contract preflight"]
            return [[0.0, 1.0, 0.0]]

    assert verify_embedding_runtime(Embed(), expected_vector_size=3) == {
        "status": "passed",
        "vector_size": 3,
    }

    with pytest.raises(RuntimeError, match="vector size mismatch"):
        verify_embedding_runtime(Embed(), expected_vector_size=4)


def test_parallel_embed_client_preserves_input_order():
    class Embed:
        def __init__(self, marker):
            self.marker = marker

        def encode_sync(self, texts):
            return [[float(text), self.marker] for text in texts]

    result = ParallelEmbedClient([Embed(1.0), Embed(2.0)]).encode_sync(
        ["0", "1", "2", "3", "4"]
    )
    assert result == [
        [0.0, 1.0],
        [1.0, 1.0],
        [2.0, 1.0],
        [3.0, 2.0],
        [4.0, 2.0],
    ]


def test_progress_json_is_atomic_and_invalid_state_fails_empty(tmp_path: Path):
    path = tmp_path / "progress.json"
    _write_json_atomic(path, {"status": "building", "completed_datasets": []})
    assert _read_json(path)["status"] == "building"
    path.write_text("{broken", encoding="utf-8")
    assert _read_json(path) == {}


def test_retry_call_recovers_transient_failure(monkeypatch):
    attempts = []
    monkeypatch.setattr("tools.build_rag_contract_sibling.time.sleep", lambda _delay: None)

    def operation():
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError("cold worker")
        return "ready"

    assert _retry_call(
        operation,
        label="embed",
        attempts=4,
        base_delay_sec=0.01,
    ) == "ready"
    assert len(attempts) == 3


def test_resume_rehydrates_embedding_environment_from_generation_contract(
    monkeypatch, tmp_path: Path
):
    # _configure_contract intentionally writes the process environment for the
    # resumed worker. Register every written key with monkeypatch first so this
    # test cannot leak the Qwen build profile into later runtime tests.
    for env_name in (
        "RAG_COLLECTION_NAME",
        "RAG_INDEX_CONTRACT_PATH",
        "RAG_QDRANT_SCHEMA",
        "RAG_DENSE_VECTOR_NAME",
        "RAG_SPARSE_VECTOR_NAME",
        "EMBEDDING_MODEL",
        "EMBED_MODEL",
        "EMBED_BACKEND",
        "RAG_VECTOR_SIZE",
        "RAG_CHUNK_UNIT",
        "COREML_EMBED_MODEL",
        "COREML_EMBED_SEQ_LEN",
        "COREML_EMBED_COMPUTE_UNITS",
        "COREML_EMBED_FALLBACK",
    ):
        monkeypatch.setenv(env_name, __import__("os").environ.get(env_name, ""))
    contract = tmp_path / "contract.json"
    contract.write_text(
        json.dumps(
            {
                "embedding_model": "Qwen/Qwen3-Embedding-0.6B",
                "embedding_api_model": "qwen3-embedding-0.6b",
                "embedding_backend": "coreml",
                "vector_size": 1024,
                "dense_vector_name": "dense",
                "sparse_vector_name": "bm25_sparse",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LES_EMBED_PROFILE", "legacy")
    _configure_contract(Namespace(dst="clean-v2", contract_path=contract))

    assert __import__("os").environ["LES_EMBED_PROFILE"] == "qwen"
    assert __import__("os").environ["EMBED_MODEL"] == "qwen3-embedding-0.6b"
    assert __import__("os").environ["RAG_COLLECTION_NAME"] == "clean-v2"


def test_punctuation_only_child_is_explicitly_excluded_without_synthetic_token():
    sparse, reason = sparse_vector_or_exclusion("‹ ; ;; ‹ ›")
    assert sparse is None
    assert reason == "empty_sparse_after_tokenization"

    meaningful, reason = sparse_vector_or_exclusion("пожарный насос Grundfos")
    assert meaningful
    assert reason == ""


def test_migration_overwrites_stale_dataset_identity_and_removes_table_smeta_domain():
    payload, removed = canonicalize_dataset_payload(
        {
            "dataset_id": "stale",
            "dataset_name": "TABLE_SMETA_Index",
            "domain": "TABLE_SMETA",
            "file_name": "Grundfos.pdf",
        },
        {"id": "books-id", "name": "BOOKS_Index"},
    )
    assert payload["dataset_id"] == "books-id"
    assert payload["dataset_name"] == "BOOKS_Index"
    assert "domain" not in payload
    assert payload["file_name"] == "Grundfos.pdf"
    assert removed is True


def test_embedding_health_preflight_rejects_same_size_wrong_model():
    contract = {
        "embedding_model": "Qwen/Qwen3-Embedding-0.6B",
        "embedding_backend": "coreml",
        "embedding_package": "artifacts/coreml/qwen.mlpackage",
        "embedding_seq_len": 512,
        "embedding_compute_units": "all",
        "embedding_fallback": "false",
    }
    health = {
        "status": "ok",
        "embed_model": {
            "path": "Qwen/Qwen3-Embedding-0.6B",
            "backend": "coreml",
            "coreml_model": "artifacts/coreml/qwen.mlpackage",
            "coreml_seq_len": 512,
            "coreml_compute_units": "all",
            "fallback_enabled": False,
        },
    }
    assert validate_embedding_health(health, contract=contract)["status"] == "passed"

    health["embed_model"]["path"] = "BAAI/bge-m3"
    with pytest.raises(RuntimeError, match="identity mismatch"):
        validate_embedding_health(health, contract=contract)

    health["embed_model"]["path"] = contract["embedding_model"]
    health["embed_model"]["fallback_enabled"] = True
    with pytest.raises(RuntimeError, match="fallback_enabled"):
        validate_embedding_health(health, contract=contract)


def test_ollama_embedding_identity_uses_installed_model_tags(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "models": [
                    {"name": "bge-m3:latest", "digest": "sha256:verified"}
                ]
            }

    monkeypatch.setattr("httpx.get", lambda url, timeout: Response())

    assert verify_embedding_runtime_identity(
        "http://127.0.0.1:11434",
        contract={
            "embedding_backend": "ollama",
            "embedding_api_model": "bge-m3:latest",
        },
    ) == {
        "status": "passed",
        "backend": "ollama",
        "model": "bge-m3:latest",
        "digest": "sha256:verified",
    }


def test_ollama_embedding_identity_rejects_wrong_installed_model(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"name": "other:latest"}]}

    monkeypatch.setattr("httpx.get", lambda url, timeout: Response())
    with pytest.raises(RuntimeError, match="expected Ollama model"):
        verify_embedding_runtime_identity(
            "http://127.0.0.1:11434",
            contract={
                "embedding_backend": "ollama",
                "embedding_api_model": "bge-m3:latest",
            },
        )
