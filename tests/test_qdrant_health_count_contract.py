from __future__ import annotations

from backend.qdrant_adapter import _apply_collection_count_health


def test_collection_health_compares_physical_points_only_with_active_user_catalog():
    snapshot = {
        "status": "ready",
        "totals": {"chunks": 151_184},
        "datasets": [
            {"dataset_scope": "user", "chunks": 101_366},
            {"dataset_scope": "system", "module_id": "smeta", "chunks": 49_818},
        ],
        "qdrant": {},
    }

    _apply_collection_count_health(snapshot, physical_points=101_366)

    assert snapshot["status"] == "ready"
    assert snapshot["qdrant"]["points_match_sqlite_chunks"] is True
    assert snapshot["qdrant"]["count_comparison_scope"] == "active_user_catalog"
    assert snapshot["qdrant"]["catalog_comparable_chunks"] == 101_366
    assert snapshot["qdrant"]["catalog_excluded_system_chunks"] == 49_818


def test_collection_health_degrades_on_real_user_catalog_mismatch():
    snapshot = {
        "status": "ready",
        "totals": {"chunks": 101_366},
        "datasets": [{"dataset_scope": "user", "chunks": 101_366}],
        "qdrant": {},
    }

    _apply_collection_count_health(snapshot, physical_points=101_365)

    assert snapshot["status"] == "degraded"
    assert snapshot["qdrant"]["points_match_sqlite_chunks"] is False
    assert snapshot["qdrant"]["mismatch"] == {
        "catalog_comparable_chunks": 101_366,
        "qdrant_points": 101_365,
    }


def test_collection_health_recognizes_complete_legacy_system_corpus_without_marking_user_rag_red():
    snapshot = {
        "status": "ready",
        "totals": {"chunks": 151_184},
        "datasets": [
            {"dataset_scope": "user", "chunks": 101_366},
            {"dataset_scope": "system", "module_id": "smeta", "chunks": 49_818},
        ],
        "qdrant": {},
    }

    _apply_collection_count_health(snapshot, physical_points=151_184)

    assert snapshot["status"] == "ready"
    assert snapshot["qdrant"]["points_match_sqlite_chunks"] is True
    assert snapshot["qdrant"]["legacy_system_points"] == 49_818
    assert snapshot["qdrant"]["catalog_comparable_chunks"] == 101_366
