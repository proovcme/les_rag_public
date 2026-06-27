import sqlite3
from pathlib import Path

from proxy.services.external_radar_service import build_external_radar
from proxy.services.file_map_service import scan_root


def _seed_meta_db(path: Path, source_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE datasets (
                id TEXT PRIMARY KEY,
                name TEXT,
                status TEXT,
                chunk_count INTEGER DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                dataset_id TEXT,
                file_name TEXT,
                status TEXT,
                chunk_count INTEGER DEFAULT 0,
                source_path TEXT DEFAULT ''
            )
            """
        )
        conn.execute("INSERT INTO datasets(id, name, status, chunk_count) VALUES('ds-1', 'External PD', 'IDLE', 3)")
        conn.execute(
            "INSERT INTO documents(id, dataset_id, file_name, status, chunk_count, source_path) "
            "VALUES('doc-1', 'ds-1', 'Проект/ОВ/АТ-РД-ОВ2-С-00-П1.pdf', 'INDEXED', 3, ?)",
            (str(source_path),),
        )
        conn.commit()


def test_external_radar_joins_filemap_and_indexed_sources(tmp_path, monkeypatch):
    root = tmp_path / "archive"
    indexed_dir = root / "Проект" / "ОВ"
    candidate_dir = root / "НТД"
    indexed_dir.mkdir(parents=True)
    candidate_dir.mkdir(parents=True)
    indexed_file = indexed_dir / "АТ-РД-ОВ2-С-00-П1.pdf"
    indexed_file.write_bytes(b"x")
    (candidate_dir / "СП 60.13330.2020 Отопление.pdf").write_bytes(b"y")

    meta_db = tmp_path / "data" / "les_meta.db"
    file_map_db = tmp_path / "data" / "file_map.db"
    _seed_meta_db(meta_db, indexed_file)
    scan_root(root, db_path=file_map_db)

    monkeypatch.setenv("RAG_META_DB_PATH", str(meta_db))
    monkeypatch.setenv("LES_EXTERNAL_SOURCE_ROOTS", str(root))
    monkeypatch.setenv("LES_EXTERNAL_ALLOW_ANY", "0")

    radar = build_external_radar(candidate_limit=10, file_map_db=file_map_db)

    assert radar["status"] == "ok"
    assert radar["allow_any"] is False
    assert radar["external_documents"] == 1
    assert radar["external_datasets"] == 1
    assert radar["filemap"]["files_with_cipher"] == 2

    archive_root = next(row for row in radar["roots"] if row["path"] == str(root.resolve()))
    assert archive_root["mapped_files"] == 2
    assert archive_root["indexed_files"] == 1
    assert archive_root["indexed_datasets"] == [{"id": "ds-1", "name": "External PD"}]

    by_folder = {item["folder"]: item for item in radar["candidates"]}
    assert by_folder["Проект/ОВ"]["radar_status"] == "indexed"
    assert by_folder["НТД"]["radar_status"] == "candidate"
    assert by_folder["НТД"]["indexed_files"] == 0


def test_external_radar_works_without_filemap(tmp_path, monkeypatch):
    root = tmp_path / "external"
    root.mkdir()
    meta_db = tmp_path / "data" / "les_meta.db"
    _seed_meta_db(meta_db, root / "doc.pdf")

    monkeypatch.setenv("RAG_META_DB_PATH", str(meta_db))
    monkeypatch.setenv("LES_EXTERNAL_SOURCE_ROOTS", str(root))
    monkeypatch.setenv("LES_EXTERNAL_ALLOW_ANY", "0")

    radar = build_external_radar(file_map_db=tmp_path / "missing.db")

    assert radar["status"] == "ok"
    assert radar["external_documents"] == 1
    assert radar["roots"][0]["indexed_files"] == 1
    assert radar["candidates"] == []


def test_external_radar_works_without_datasets_table(tmp_path, monkeypatch):
    root = tmp_path / "external"
    root.mkdir()
    indexed_file = root / "doc.pdf"
    indexed_file.write_bytes(b"x")
    meta_db = tmp_path / "data" / "les_meta.db"
    meta_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(meta_db) as conn:
        conn.execute(
            """
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                dataset_id TEXT,
                file_name TEXT,
                status TEXT,
                chunk_count INTEGER DEFAULT 0,
                source_path TEXT DEFAULT ''
            )
            """
        )
        conn.execute(
            "INSERT INTO documents(id, dataset_id, file_name, status, chunk_count, source_path) "
            "VALUES('doc-1', 'legacy-ds', 'doc.pdf', 'INDEXED', 2, ?)",
            (str(indexed_file),),
        )
        conn.commit()

    monkeypatch.setenv("RAG_META_DB_PATH", str(meta_db))
    monkeypatch.setenv("LES_EXTERNAL_SOURCE_ROOTS", str(root))
    monkeypatch.setenv("LES_EXTERNAL_ALLOW_ANY", "0")

    radar = build_external_radar(file_map_db=tmp_path / "missing.db")

    assert radar["status"] == "ok"
    assert radar["external_documents"] == 1
    assert radar["external_datasets"] == 1
    assert radar["roots"][0]["indexed_datasets"] == [{"id": "legacy-ds", "name": "legacy-ds"}]
