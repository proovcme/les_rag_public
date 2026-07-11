from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tools.build_rag_contract_sibling import (
    deterministic_point_id,
    resolve_datasets,
    resolve_indexed_datasets,
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
