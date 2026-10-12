"""Public's immutable contract is not the private mutable attestation token."""
import asyncio
from types import SimpleNamespace

import pytest

import backend.qdrant_adapter as qa
from backend.rag_config import index_contract_status, write_index_contract


@pytest.fixture
def boundary(tmp_path, monkeypatch):
    contract = tmp_path / "contract.json"
    monkeypatch.setenv("RAG_INDEX_CONTRACT_PATH", str(contract))
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "meta.db"))
    monkeypatch.setenv("RAG_LEXICAL_DB_PATH", str(tmp_path / "meta.db"))
    monkeypatch.setenv("RAG_COLLECTION_NAME", "disposable-contract")
    monkeypatch.setenv("RAG_CHUNK_UNIT", "chars")
    monkeypatch.setenv("RAG_VECTOR_SIZE", "1024")
    adapter = object.__new__(qa.QdrantLlamaIndexAdapter)
    adapter._collection_ready = True  # existing initialized collection, not startup/adoption
    adapter.content_dir = tmp_path / "content"
    adapter.qdrant_url = "http://disposable.invalid"
    adapter.db = qa.MetaDB(str(tmp_path / "meta.db"))
    dataset = adapter.db.create_dataset("contract boundary")
    calls = []

    class NoMutationClient:
        def __getattr__(self, name):
            calls.append(name)
            raise AssertionError(f"no-op must not access Qdrant operation {name}")

    monkeypatch.setattr(qa.qdrant_client, "QdrantClient", lambda **kwargs: NoMutationClient())
    return SimpleNamespace(adapter=adapter, dataset=dataset, contract=contract, calls=calls)


@pytest.mark.parametrize("case", ["missing-directory", "empty-pending", "missing-file"])
def test_noop_parse_preserves_compatible_contract(boundary, case):
    b = boundary
    write_index_contract()
    before = (b.contract.read_bytes(), b.contract.stat().st_mtime_ns)
    if case != "missing-directory":
        (b.adapter.content_dir / b.dataset).mkdir(parents=True)
    if case == "missing-file":
        b.adapter.db.add_document(b.dataset, "absent.md")
    result = asyncio.run(b.adapter.parse_dataset(b.dataset, limit=1))
    if case == "missing-directory":
        assert result == {"status": "error", "msg": "dir missing"}
    else:
        assert result["status"] == "completed"
        assert result["chunks"] == 0
    assert (b.contract.read_bytes(), b.contract.stat().st_mtime_ns) == before
    assert index_contract_status()["compatible"] is True
    assert not b.calls
    assert not (b.contract.parent / "ingestion-locks").exists()


@pytest.mark.parametrize("case", ["missing", "mismatch"])
def test_contract_rejection_precedes_dataset_and_point_writes(boundary, monkeypatch, case):
    b = boundary
    if case == "mismatch":
        write_index_contract()
        monkeypatch.setenv("RAG_VECTOR_SIZE", "384")
    before = b.contract.read_bytes() if b.contract.exists() else None
    downstream = []
    monkeypatch.setattr(b.adapter.db, "update_dataset_status", lambda *args: downstream.append(args))
    monkeypatch.setattr(b.adapter, "_sync_parse", lambda *args: downstream.append(args))
    with pytest.raises(qa.EmbeddingContractError, match=f"index contract {case}"):
        asyncio.run(b.adapter.parse_dataset(b.dataset, limit=1))
    assert not downstream
    assert not b.calls
    assert (b.contract.read_bytes() if b.contract.exists() else None) == before
