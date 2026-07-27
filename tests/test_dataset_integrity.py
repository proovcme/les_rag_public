from __future__ import annotations

from types import SimpleNamespace

from backend import qdrant_adapter


class _DB:
    def __init__(self, source, *, lexical_ids=None):
        self.source = source
        self.lexical_ids = lexical_ids or {"project.txt": {"p1", "p2"}}
        self.pending = set()
        self.missing = set()

    def dataset_integrity_rows(self, dataset_id):
        assert dataset_id == "ds-1"
        stat = self.source.stat()
        return [{
            "id": "doc-1",
            "file_name": "project.txt",
            "status": "INDEXED",
            "file_hash": qdrant_adapter._sha256_file(self.source),
            "file_mtime": stat.st_mtime,
            "file_size": stat.st_size,
            "chunk_count": 2,
            "source_path": str(self.source),
        }]

    def lexical_integrity_projection(self, dataset_id):
        return {
            "available": True,
            "fts_available": True,
            "files": self.lexical_ids,
            "lexical_ids": {1, 2},
            "fts_ids": {1, 2},
        }

    def set_documents_pending(self, dataset_id, names):
        self.pending.update(names)
        return len(names)

    def set_documents_missing(self, dataset_id, names):
        self.missing.update(names)
        return len(names)

    def rebuild_lexical_fts(self):
        raise AssertionError("healthy FTS must not be rebuilt")

    def update_dataset_chunk_count(self, dataset_id):
        assert dataset_id == "ds-1"


class _Qdrant:
    def __init__(self, **_kwargs):
        pass

    def scroll(self, **kwargs):
        if kwargs.get("offset") is not None:
            return [], None
        return [
            SimpleNamespace(id="p1", payload={"dataset_id": "ds-1", "file_name": "project.txt"}),
            SimpleNamespace(id="p2", payload={"dataset_id": "ds-1", "file_name": "project.txt"}),
        ], None

    def count(self, **_kwargs):
        return SimpleNamespace(count=2)

    def delete(self, **_kwargs):
        return None


def _adapter(db):
    value = object.__new__(qdrant_adapter.QdrantLlamaIndexAdapter)
    value.db = db
    value.content_dir = db.source.parent
    value.qdrant_url = "http://qdrant.invalid"
    value.collection_name = "les_rag"
    return value


def test_dataset_integrity_audits_all_search_channels(tmp_path, monkeypatch):
    source = tmp_path / "project.txt"
    source.write_text("project source", encoding="utf-8")
    db = _DB(source)
    monkeypatch.setattr(qdrant_adapter.qdrant_client, "QdrantClient", _Qdrant)
    monkeypatch.setattr(qdrant_adapter, "index_contract_status", lambda: {"compatible": True})

    result = _adapter(db).audit_dataset_integrity("ds-1")

    assert result["state"] == "healthy"
    assert result["clean_files"] == 1
    assert result["damaged_files"] == 0
    assert result["fts_ok"] is True


def test_dataset_integrity_requeues_only_the_damaged_document(tmp_path, monkeypatch):
    source = tmp_path / "project.txt"
    source.write_text("project source", encoding="utf-8")
    db = _DB(source, lexical_ids={"project.txt": {"p1"}})
    monkeypatch.setattr(qdrant_adapter.qdrant_client, "QdrantClient", _Qdrant)
    monkeypatch.setattr(qdrant_adapter, "index_contract_status", lambda: {"compatible": True})

    result = _adapter(db).audit_dataset_integrity("ds-1", repair=True)

    assert result["state"] == "repairable"
    assert result["requeued"] == 1
    assert db.pending == {"project.txt"}
    assert db.missing == set()
