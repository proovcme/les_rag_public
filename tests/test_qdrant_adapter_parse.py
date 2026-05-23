from types import SimpleNamespace

import pytest

from backend.qdrant_adapter import MetaDB, QdrantLlamaIndexAdapter


class EmptyPendingDB:
    def get_pending_files(self, dataset_id, limit=None):
        return []


class LegacyNamePendingDB:
    def __init__(self):
        self.updated = []

    def get_pending_files(self, dataset_id, limit=None):
        return ["doc.md"] if not self.updated else []

    def update_document_status(self, dataset_id, file_name, status, chunk_count, route=None, last_error=""):
        self.updated.append((dataset_id, file_name, status, chunk_count))

    def update_dataset_chunk_count(self, dataset_id):
        pass


def test_sync_parse_does_not_parse_all_files_when_no_pending(tmp_path):
    dataset_dir = tmp_path / "ds-1"
    dataset_dir.mkdir()
    (dataset_dir / "doc.md").write_text("content")
    adapter = SimpleNamespace(
        content_dir=tmp_path,
        db=EmptyPendingDB(),
        qdrant_url="http://127.0.0.1:6333",
        collection_name="les_rag",
    )

    result = QdrantLlamaIndexAdapter._sync_parse(adapter, "ds-1", limit=5)

    assert result == {
        "status": "completed",
        "chunks": 0,
        "files_parsed": 0,
        "files_skipped": 1,
        "remaining_pending": 0,
        "errors": 0,
        "elapsed_sec": 0,
    }


def test_sync_parse_updates_legacy_pending_file_name(tmp_path, monkeypatch):
    dataset_dir = tmp_path / "ds-1" / "nested"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "doc.md").write_text("content with enough text for a chunk")
    db = LegacyNamePendingDB()
    adapter = SimpleNamespace(
        content_dir=tmp_path,
        db=db,
        qdrant_url="http://127.0.0.1:6333",
        collection_name="les_rag",
        embed=SimpleNamespace(encode_sync=lambda texts: [[0.0] * 1024 for _ in texts]),
        _sync_delete_file_points=lambda *args: None,
        _sync_count_file_points=lambda *args: 1,
        _sync_markdown_nodes=lambda *args: [
            {"text": "content with enough text for a chunk", "doc_id": "doc-1", "payload": {}}
        ],
    )

    class FakeQdrant:
        def __init__(self, url):
            self.url = url

        def upsert(self, collection_name, points):
            return None

    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)

    result = QdrantLlamaIndexAdapter._sync_parse(adapter, "ds-1", limit=1)

    assert result["files_parsed"] == 1
    assert result["remaining_pending"] == 0
    assert set(result["timings"]) == {
        "delete_sec",
        "route_sec",
        "convert_sec",
        "chunk_sec",
        "embed_sec",
        "upsert_sec",
        "count_sec",
        "db_sec",
    }
    assert db.updated == [("ds-1", "doc.md", "INDEXED", 1)]


def test_pending_files_are_ordered_by_size(tmp_path):
    db = MetaDB(str(tmp_path / "meta.db"))
    dataset_id = db.create_dataset("NTD_Index")
    large = tmp_path / "large.md"
    small = tmp_path / "small.md"
    large.write_text("x" * 100)
    small.write_text("x" * 10)

    db.add_document(dataset_id, "large.md", file_mtime=1, file_size=large.stat().st_size)
    db.add_document(dataset_id, "small.md", file_mtime=1, file_size=small.stat().st_size)

    assert db.get_pending_files(dataset_id, limit=2) == ["small.md", "large.md"]


@pytest.mark.asyncio
async def test_parse_dataset_rejects_unbounded_parse_by_default(monkeypatch):
    monkeypatch.delenv("ALLOW_UNBOUNDED_PARSE", raising=False)

    result = await QdrantLlamaIndexAdapter.parse_dataset(SimpleNamespace(), "ds-1")

    assert result["status"] == "rejected"
    assert "unbounded parse is disabled" in result["error"]


def test_adapter_uses_configured_collection_and_vector_size(monkeypatch, tmp_path):
    monkeypatch.setenv("RAG_COLLECTION_NAME", "les_rag_qwen3_06b")
    monkeypatch.setenv("RAG_VECTOR_SIZE", "1024")

    adapter = QdrantLlamaIndexAdapter(
        qdrant_url="http://127.0.0.1:6333",
        mlx_url="http://127.0.0.1:8080",
        embed_model_name="qwen3-embedding-0.6b",
        content_dir=str(tmp_path),
    )

    assert adapter.collection_name == "les_rag_qwen3_06b"
    assert adapter.vector_size == 1024
    assert adapter.embed.model == "qwen3-embedding-0.6b"
