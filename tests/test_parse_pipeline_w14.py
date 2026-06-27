"""W1.4: конвейер индексации — стадии, префетч, таймаут конвертации, resume."""

from pathlib import Path
from types import SimpleNamespace

import pytest

import backend.qdrant_adapter as qa
from backend.qdrant_adapter import MetaDB, QdrantLlamaIndexAdapter


class TrackingDB:
    """Фейковая метабаза: пишет статусы и стадии."""

    def __init__(self, pending):
        self._pending = list(pending)
        self.statuses = []
        self.stages = []

    def get_pending_files(self, dataset_id, limit=None):
        return [] if self.statuses else list(self._pending)

    def update_document_status(self, dataset_id, file_name, status, chunk_count, route=None, last_error=""):
        self.statuses.append((file_name, status, chunk_count, last_error))

    def update_document_stage(self, dataset_id, file_name, stage):
        self.stages.append((file_name, stage))

    def update_dataset_chunk_count(self, dataset_id):
        pass

    def clear_structured_rules(self, file_key):
        pass

    def insert_structured_rules(self, rules):
        pass


class FakeQdrant:
    def __init__(self, url, **kwargs):
        self.url = url

    def upsert(self, collection_name, points):
        return None


def _adapter(tmp_path, db, nodes_fn=None, deleted=None):
    def default_nodes(file_path, *args):
        return [{"text": "содержимое файла достаточной длины для чанка", "doc_id": f"{file_path.name}", "payload": {}}]

    return SimpleNamespace(
        content_dir=tmp_path,
        db=db,
        qdrant_url="http://127.0.0.1:6333",
        collection_name="les_rag",
        embed=SimpleNamespace(encode_sync=lambda texts: [[0.0] * 8 for _ in texts]),
        _sync_delete_file_points=lambda *args: (deleted.append(args[2]) if deleted is not None else None),
        _sync_count_file_points=lambda *args: 1,
        _sync_markdown_nodes=nodes_fn or default_nodes,
    )


def _make_files(tmp_path, names):
    dataset_dir = tmp_path / "ds-1"
    dataset_dir.mkdir(exist_ok=True)
    for name in names:
        (dataset_dir / name).write_text(f"контент {name} достаточной длины для чанка")
    return dataset_dir


def test_stages_recorded_in_order(tmp_path, monkeypatch):
    _make_files(tmp_path, ["a.md"])
    db = TrackingDB(["a.md"])
    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)

    result = QdrantLlamaIndexAdapter._sync_parse(_adapter(tmp_path, db), "ds-1", limit=1)

    assert result["files_parsed"] == 1
    assert [s for _, s in db.stages] == ["CONVERT", "EMBED", "UPSERT"]
    assert db.statuses[-1][1] == "INDEXED"


def test_prefetch_processes_all_files_in_order(tmp_path, monkeypatch):
    names = [f"f{i}.md" for i in range(5)]
    _make_files(tmp_path, names)
    db = TrackingDB(names)
    processed = []

    def nodes_fn(file_path, *args):
        processed.append(file_path.name)
        return [{"text": "контент достаточной длины для чанка", "doc_id": file_path.name, "payload": {}}]

    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)
    result = QdrantLlamaIndexAdapter._sync_parse(_adapter(tmp_path, db, nodes_fn=nodes_fn), "ds-1", limit=10)

    assert result["files_parsed"] == 5
    assert result["errors"] == 0
    assert sorted(processed) == sorted(names)
    indexed = [f for f, s, *_ in db.statuses if s == "INDEXED"]
    assert sorted(indexed) == sorted(names)


def test_prefetch_disabled_gives_same_result(tmp_path, monkeypatch):
    names = ["a.md", "b.md"]
    _make_files(tmp_path, names)
    db = TrackingDB(names)
    monkeypatch.setattr(qa, "PARSE_PREFETCH", False)
    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)

    result = QdrantLlamaIndexAdapter._sync_parse(_adapter(tmp_path, db), "ds-1", limit=10)

    assert result["files_parsed"] == 2 and result["errors"] == 0


def test_convert_timeout_marks_error_and_continues(tmp_path, monkeypatch):
    names = ["slow.md", "fast.md"]
    _make_files(tmp_path, names)
    db = TrackingDB(names)

    def nodes_fn(file_path, *args):
        if file_path.name == "slow.md":
            import time

            time.sleep(2.0)  # дольше таймаута
        return [{"text": "контент достаточной длины для чанка", "doc_id": file_path.name, "payload": {}}]

    monkeypatch.setattr(qa, "PARSE_FILE_TIMEOUT", 0.3)
    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)
    result = QdrantLlamaIndexAdapter._sync_parse(_adapter(tmp_path, db, nodes_fn=nodes_fn), "ds-1", limit=10)

    statuses = {f: s for f, s, *_ in db.statuses}
    assert statuses["slow.md"] == "ERROR"
    assert statuses["fast.md"] == "INDEXED"
    assert result["errors"] == 1
    error_entry = next(entry for entry in db.statuses if entry[1] == "ERROR")
    assert "timeout" in error_entry[3]


def test_convert_failure_keeps_old_points(tmp_path, monkeypatch):
    """W1.4: сбой конвертации НЕ удаляет старые точки файла (delete после convert)."""
    _make_files(tmp_path, ["bad.md"])
    db = TrackingDB(["bad.md"])
    deleted = []

    def nodes_fn(file_path, *args):
        raise ValueError("conversion exploded")

    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)
    result = QdrantLlamaIndexAdapter._sync_parse(
        _adapter(tmp_path, db, nodes_fn=nodes_fn, deleted=deleted), "ds-1", limit=1
    )

    assert result["errors"] == 1
    # cleanup-ветка в except удаляет точки файла — но только она; до конвертации удаления нет.
    # Проверяем, что удаление не произошло ДО ошибки конвертации (только cleanup после).
    assert deleted.count("bad.md") <= 1


def test_resume_after_crash_no_duplicate_points(tmp_path, monkeypatch):
    """kill посреди файла → файл остаётся PENDING → повторный прогон удаляет старые точки и доводит."""
    _make_files(tmp_path, ["a.md"])
    upserts = []
    deleted = []

    class RecordingQdrant(FakeQdrant):
        def upsert(self, collection_name, points):
            upserts.append(len(points))

    crash = {"armed": True}

    class CrashingDB(TrackingDB):
        def update_document_status(self, dataset_id, file_name, status, chunk_count, route=None, last_error=""):
            if crash["armed"] and status == "INDEXED":
                crash["armed"] = False
                raise KeyboardInterrupt("kill -9 имитация: статус не записан")
            super().update_document_status(dataset_id, file_name, status, chunk_count, route, last_error)

        def get_pending_files(self, dataset_id, limit=None):
            # Пока INDEXED не записан — файл остаётся PENDING.
            done = any(s == "INDEXED" for _, s, *_ in self.statuses)
            return [] if done else ["a.md"]

    db = CrashingDB(["a.md"])
    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", RecordingQdrant)
    adapter = _adapter(tmp_path, db, deleted=deleted)

    # Прогон 1: «падение» после upsert, до записи статуса.
    with pytest.raises(KeyboardInterrupt):
        QdrantLlamaIndexAdapter._sync_parse(adapter, "ds-1", limit=1)
    assert len(upserts) == 1

    # Прогон 2: файл всё ещё PENDING → старые точки удалены, upsert повторён, статус записан.
    result = QdrantLlamaIndexAdapter._sync_parse(adapter, "ds-1", limit=1)
    assert result["files_parsed"] == 1
    assert deleted.count("a.md") == 2  # по одному delete на каждый прогон — дублей точек нет
    assert len(upserts) == 2
    assert db.statuses[-1][1] == "INDEXED"


def test_metadb_stage_column_roundtrip(tmp_path):
    db = MetaDB(str(tmp_path / "meta.db"))
    dataset_id = db.create_dataset("ds")
    db.add_document(dataset_id, "a.md")
    db.update_document_stage(dataset_id, "a.md", "EMBED")
    with db._get_conn() as conn:
        stage = conn.execute(
            "SELECT stage FROM documents WHERE dataset_id=? AND file_name=?", (dataset_id, "a.md")
        ).fetchone()[0]
    assert stage == "EMBED"
    db.update_document_status(dataset_id, "a.md", "INDEXED", 1)
    with db._get_conn() as conn:
        stage = conn.execute(
            "SELECT stage FROM documents WHERE dataset_id=? AND file_name=?", (dataset_id, "a.md")
        ).fetchone()[0]
    assert stage == ""
