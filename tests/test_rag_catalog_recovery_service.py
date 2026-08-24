from __future__ import annotations

import sqlite3

import pytest

from proxy.services.rag_catalog_recovery_service import (
    link_recovered_datasets,
    recover_metadb_catalog,
)


def _schema(path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE datasets (
                id TEXT PRIMARY KEY, name TEXT, status TEXT, chunk_count INTEGER,
                sensitivity TEXT, group_name TEXT, dataset_scope TEXT, module_id TEXT
            );
            CREATE TABLE documents (
                id TEXT PRIMARY KEY, dataset_id TEXT, file_name TEXT, status TEXT,
                file_mtime REAL, file_size INTEGER, chunk_count INTEGER,
                domain TEXT, route_dataset TEXT, doc_type TEXT, content_type TEXT,
                complexity TEXT, pipeline TEXT, last_error TEXT, stage TEXT, source_path TEXT
            );
            """
        )


def test_link_recovered_datasets_keeps_project_visibility(tmp_path):
    db_path = tmp_path / "meta.db"
    _schema(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO datasets VALUES ('ds-1', 'Recovered', 'IDLE', 0, 'P0', '', 'user', '')"
        )

    project_id = link_recovered_datasets(meta_db_path=db_path, dataset_ids=["ds-1"])

    assert project_id > 0
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT ref FROM les_project_links WHERE project_id=? AND kind='dataset'",
            (project_id,),
        ).fetchone() == ("ds-1",)


def test_recovery_requires_explicit_dataset_identity(tmp_path):
    db_path = tmp_path / "meta.db"
    _schema(db_path)
    inventory = {"orphans": [{"dataset_id": "orphan", "points": 1, "files": []}]}

    with pytest.raises(ValueError, match="explicit dataset names"):
        recover_metadb_catalog(inventory=inventory, dataset_names={}, meta_db_path=db_path)


def test_recovery_rebuilds_dataset_and_document_rows_idempotently(tmp_path):
    db_path = tmp_path / "meta.db"
    _schema(db_path)
    inventory = {
        "orphans": [
            {
                "dataset_id": "orphan",
                "points": 3,
                "files": [
                    {
                        "file_name": "Project/a.pdf",
                        "chunk_count": 3,
                        "domain": "GENERAL",
                        "route_dataset": "PROJECT_Index",
                        "doc_type": "DOCUMENT",
                        "content_type": "text",
                        "complexity": "simple",
                        "pipeline": "markdown",
                    }
                ],
            }
        ]
    }

    first = recover_metadb_catalog(
        inventory=inventory,
        dataset_names={"orphan": "Project documents"},
        meta_db_path=db_path,
    )
    second = recover_metadb_catalog(
        inventory=inventory,
        dataset_names={"orphan": "Project documents"},
        meta_db_path=db_path,
    )

    assert first == {"recovered_datasets": 1, "recovered_documents": 1}
    assert second == {"recovered_datasets": 0, "recovered_documents": 0}
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT name, chunk_count FROM datasets").fetchone() == (
            "Project documents",
            3,
        )
        assert conn.execute("SELECT status, chunk_count, source_path FROM documents").fetchone() == (
            "INDEXED",
            3,
            "",
        )
