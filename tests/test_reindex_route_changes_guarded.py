import sqlite3
from pathlib import Path

import pytest

from tools import reindex_route_changes_guarded as route_guard


def _init_db(path: Path):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE datasets (id TEXT PRIMARY KEY, name TEXT, status TEXT, chunk_count INTEGER DEFAULT 0)")
        conn.execute(
            """
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                dataset_id TEXT,
                file_name TEXT,
                status TEXT,
                file_hash TEXT,
                file_mtime REAL,
                file_size INTEGER,
                chunk_count INTEGER DEFAULT 0,
                domain TEXT DEFAULT '',
                route_dataset TEXT DEFAULT '',
                doc_type TEXT DEFAULT '',
                content_type TEXT DEFAULT '',
                complexity TEXT DEFAULT '',
                pipeline TEXT DEFAULT '',
                last_error TEXT DEFAULT ''
            )
            """
        )
        conn.executemany(
            "INSERT INTO datasets (id, name, status, chunk_count) VALUES (?, ?, ?, ?)",
            [
                ("ds-struct", "NTD_STRUCTURAL_Index", "COMPLETED", 9),
                ("ds-fire", "NTD_FIRE_Index", "COMPLETED", 0),
            ],
        )


def _insert_doc(path: Path, *, file_name: str = "mixed/fire.txt"):
    source = path.parent / "RAG_Content" / file_name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("СП 1.13130 пожарная безопасность эвакуация", encoding="utf-8")
    stat = source.stat()
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO documents
            (id, dataset_id, file_name, status, file_mtime, file_size, chunk_count)
            VALUES ('doc-fire', 'ds-struct', ?, 'INDEXED', ?, ?, 9)
            """,
            (file_name, stat.st_mtime, stat.st_size),
        )
    return source


def test_route_changes_detects_dataset_move(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "rag.db"
    _init_db(db_path)
    _insert_doc(db_path)

    changes = route_guard.route_changes(str(db_path), "RAG_Content")

    assert len(changes) == 1
    assert changes[0].current_dataset_name == "NTD_STRUCTURAL_Index"
    assert changes[0].target_dataset_name == "NTD_FIRE_Index"
    assert changes[0].current_doc_id == "doc-fire"
    assert changes[0].target_file_name == "mixed/fire.txt"


def test_plan_summary_groups_moves(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "rag.db"
    _init_db(db_path)
    _insert_doc(db_path)

    summary = route_guard.plan_summary(route_guard.route_changes(str(db_path), "RAG_Content"))

    assert summary["total"] == 1
    assert summary["groups"][0]["current_dataset_name"] == "NTD_STRUCTURAL_Index"
    assert summary["groups"][0]["target_dataset_name"] == "NTD_FIRE_Index"
    assert summary["groups"][0]["files"] == 1
    assert summary["groups"][0]["chunks"] == 9


def test_move_doc_to_target_updates_sqlite_and_storage(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "rag.db"
    _init_db(db_path)
    source = _insert_doc(db_path)
    old_storage = tmp_path / "storage" / "datasets" / "ds-struct" / "mixed" / "fire.txt"
    old_storage.parent.mkdir(parents=True)
    old_storage.write_text("old copy", encoding="utf-8")
    doc = route_guard.route_changes(str(db_path), "RAG_Content")[0]

    result = route_guard.move_doc_to_target(str(db_path), doc, storage_root="storage/datasets")

    assert result["target_dataset_id"] == "ds-fire"
    assert Path(result["storage_path"]).read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert not old_storage.exists()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM documents WHERE id='doc-fire'").fetchone()
        assert row["dataset_id"] == "ds-fire"
        assert row["file_name"] == "mixed/fire.txt"
        assert row["status"] == "PENDING"
        assert row["chunk_count"] == 0
        assert row["route_dataset"] == "NTD_FIRE_Index"
        old_dataset = conn.execute("SELECT chunk_count FROM datasets WHERE id='ds-struct'").fetchone()
        assert old_dataset["chunk_count"] == 0


def test_move_doc_to_target_rejects_existing_target_doc(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "rag.db"
    _init_db(db_path)
    _insert_doc(db_path)
    doc = route_guard.route_changes(str(db_path), "RAG_Content")[0]
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO documents
            (id, dataset_id, file_name, status, file_mtime, file_size, chunk_count)
            VALUES ('existing', 'ds-fire', 'mixed/fire.txt', 'INDEXED', 1, 1, 1)
            """
        )

    with pytest.raises(RuntimeError, match="target document already exists"):
        route_guard.move_doc_to_target(str(db_path), doc, storage_root="storage/datasets")
