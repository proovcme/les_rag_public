"""In-place индексация внешних папок (LES_EXTERNAL_SOURCE_ROOTS).

Покрывает: безопасность валидатора (allowlist + traversal/симлинк наружу),
round-trip source_path в метабазе и чтение внешнего источника в _sync_parse
БЕЗ копии в storage.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.qdrant_adapter import MetaDB, QdrantLlamaIndexAdapter
from proxy.storage.file_storage import validate_external_source


# ── Валидатор: безопасность ──────────────────────────────────────────────────

def test_validate_external_source_disabled_when_allowlist_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("LES_EXTERNAL_SOURCE_ROOTS", raising=False)
    with pytest.raises(HTTPException) as exc:
        validate_external_source(str(tmp_path))
    assert exc.value.status_code == 403


def test_validate_external_source_accepts_path_inside_root(tmp_path, monkeypatch):
    root = tmp_path / "approved"
    sub = root / "АМК ВОР 1901"
    sub.mkdir(parents=True)
    monkeypatch.setenv("LES_EXTERNAL_SOURCE_ROOTS", str(root))
    result = validate_external_source(str(sub))
    assert result == sub.resolve()


def test_validate_external_source_rejects_outside_root(tmp_path, monkeypatch):
    root = tmp_path / "approved"
    root.mkdir()
    outside = tmp_path / "secret"
    outside.mkdir()
    monkeypatch.setenv("LES_EXTERNAL_SOURCE_ROOTS", str(root))
    with pytest.raises(HTTPException) as exc:
        validate_external_source(str(outside))
    assert exc.value.status_code == 403


def test_validate_external_source_rejects_traversal(tmp_path, monkeypatch):
    root = tmp_path / "approved"
    root.mkdir()
    (tmp_path / "secret").mkdir()
    monkeypatch.setenv("LES_EXTERNAL_SOURCE_ROOTS", str(root))
    with pytest.raises(HTTPException):
        validate_external_source(str(root / ".." / "secret"))


def test_validate_external_source_rejects_symlink_escaping_root(tmp_path, monkeypatch):
    root = tmp_path / "approved"
    root.mkdir()
    outside = tmp_path / "outside_target"
    outside.mkdir()
    link = root / "escape"
    link.symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("LES_EXTERNAL_SOURCE_ROOTS", str(root))
    # Симлинк внутри корня указывает наружу → resolve() снимает его, путь вне корня.
    with pytest.raises(HTTPException) as exc:
        validate_external_source(str(link))
    assert exc.value.status_code == 403


def test_validate_external_source_rejects_file(tmp_path, monkeypatch):
    root = tmp_path / "approved"
    root.mkdir()
    file = root / "doc.pdf"
    file.write_text("x")
    monkeypatch.setenv("LES_EXTERNAL_SOURCE_ROOTS", str(root))
    with pytest.raises(HTTPException) as exc:
        validate_external_source(str(file))
    assert exc.value.status_code == 400


# ── Метабаза: source_path round-trip ─────────────────────────────────────────

def test_metadb_stores_and_returns_source_path(tmp_path):
    db = MetaDB(db_path=str(tmp_path / "meta.db"))
    ds_id = db.create_dataset("ext")
    db.add_document(ds_id, "АМК ВОР 1901/x.xlsx", file_mtime=1.0, file_size=10,
                    source_path="/abs/АМК ВОР 1901/x.xlsx")
    db.add_document(ds_id, "internal.md", file_mtime=1.0, file_size=5)  # без source_path

    pairs = dict(db.get_pending_files_with_paths(ds_id))
    assert pairs["АМК ВОР 1901/x.xlsx"] == "/abs/АМК ВОР 1901/x.xlsx"
    assert pairs["internal.md"] == ""
    # get_pending_files остаётся совместимым
    assert set(db.get_pending_files(ds_id)) == {"АМК ВОР 1901/x.xlsx", "internal.md"}


# ── _sync_parse: чтение внешнего источника без копии в storage ───────────────

class ExternalPendingDB:
    def __init__(self, file_name, source_path):
        self._pair = (file_name, source_path)
        self.updated = []

    def get_pending_files_with_paths(self, dataset_id, limit=None):
        return [] if self.updated else [self._pair]

    def get_pending_files(self, dataset_id, limit=None):
        return [] if self.updated else [self._pair[0]]

    def update_document_status(self, dataset_id, file_name, status, chunk_count, route=None, last_error=""):
        self.updated.append((dataset_id, file_name, status, chunk_count))

    def update_dataset_chunk_count(self, dataset_id):
        pass

    def clear_structured_rules(self, file_key):
        pass

    def insert_structured_rules(self, rules):
        pass


def test_sync_parse_reads_external_source_in_place(tmp_path, monkeypatch):
    # storage/datasets/ds-1 существует (для дериватов), но внешний файл лежит ВНЕ него.
    storage = tmp_path / "storage"
    data_dir = storage / "ds-1"
    data_dir.mkdir(parents=True)
    external = tmp_path / "RAG" / "АМК ВОР 1901"
    external.mkdir(parents=True)
    ext_file = external / "vor.md"
    ext_file.write_text("Ведомость объёмов работ с достаточным количеством текста для чанка")

    file_name = "АМК ВОР 1901/vor.md"
    db = ExternalPendingDB(file_name, str(ext_file))
    seen_paths = []
    adapter = SimpleNamespace(
        content_dir=storage,
        db=db,
        qdrant_url="http://127.0.0.1:6333",
        collection_name="les_rag",
        embed=SimpleNamespace(encode_sync=lambda texts: [[0.0] * 1024 for _ in texts]),
        _sync_delete_file_points=lambda *args: None,
        _sync_count_file_points=lambda *args: 1,
        _sync_markdown_nodes=lambda file_path, *args: seen_paths.append(file_path)
        or [{"text": "Ведомость объёмов работ с достаточным количеством текста для чанка",
             "doc_id": "n-1", "payload": {}}],
    )

    class FakeQdrant:
        def __init__(self, url, **kwargs):
            self.url = url

        def upsert(self, collection_name, points):
            return None

    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)

    result = QdrantLlamaIndexAdapter._sync_parse(adapter, "ds-1", limit=5)

    assert result["files_parsed"] == 1
    assert result["errors"] == 0
    # читали именно внешний абсолютный путь, без копии в storage
    assert seen_paths == [ext_file]
    assert not (data_dir / "vor.md").exists()
    assert not (data_dir / file_name).exists()
    # статус апдейтнут по db_file_key == file_name (rel под корнем)
    assert db.updated == [("ds-1", file_name, "INDEXED", 1)]
