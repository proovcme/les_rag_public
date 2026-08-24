import pytest

from proxy.services import rag_pipeline_status_service as pipeline_status
from proxy.services.rag_pipeline_status_service import build_retrieval_pipeline_status


@pytest.fixture(autouse=True)
def stable_advanced_status(monkeypatch):
    monkeypatch.setattr(
        pipeline_status,
        "load_status",
        lambda: {
            "raptor": {"readiness": "not_built", "published_nodes": 0},
            "colbert": {"readiness": "not_built", "circuit_state": "closed"},
        },
    )


def _healthy_snapshot():
    return {
        "qdrant": {
            "ok": True,
            "collection": "les_rag",
            "points": 100,
            "compatible_fingerprint_points": 100,
            "points_match_sqlite_chunks": True,
            "point_fingerprint_match": True,
        },
        "index_contract": {
            "compatible": True,
            "actual": {
                "qdrant_schema": "named",
                "dense_vector_name": "dense",
                "sparse_vector_name": "bm25_sparse",
                "hierarchy_schema": "les.rag.hierarchy.v1",
                "navigation_evidence_policy": "navigation_not_evidence",
            },
        },
    }


def test_pipeline_reports_proven_base_and_honest_optional_stages(monkeypatch):
    monkeypatch.delenv("LES_COLBERT_ENABLED", raising=False)
    result = build_retrieval_pipeline_status(_healthy_snapshot())

    assert result["status"] == "ready"
    assert result["stages"]["native_rrf"]["status"] == "ready"
    assert result["stages"]["hierarchy"]["status"] == "ready"
    assert result["stages"]["raptor"]["status"] == "configured"
    assert result["stages"]["colbert"]["status"] == "configured"
    assert result["stages"]["reranker"]["status"] == "configured"


def test_pipeline_blocks_rrf_when_sparse_contract_is_missing():
    snapshot = _healthy_snapshot()
    snapshot["index_contract"]["actual"]["sparse_vector_name"] = ""

    result = build_retrieval_pipeline_status(snapshot)

    assert result["status"] == "degraded"
    assert result["stages"]["native_rrf"]["status"] == "blocked"
    assert result["stages"]["hierarchy"]["status"] == "blocked"


def test_pipeline_marks_published_raptor_generation_ready(monkeypatch):
    snapshot = _healthy_snapshot()
    monkeypatch.setattr(
        pipeline_status,
        "load_status",
        lambda: {
            "raptor": {
                "readiness": "ready",
                "published_nodes": 42,
                "schema": "les.rag.raptor-collection.v1",
                "source_collection": "les_rag",
                "progress": 1.0,
            },
            "colbert": {"readiness": "not_built", "circuit_state": "closed"},
        },
    )

    result = build_retrieval_pipeline_status(snapshot)

    assert result["stages"]["raptor"]["status"] == "ready"
    assert result["stages"]["raptor"]["points"] == 42


def test_pipeline_accepts_exact_generation_counts_with_navigation_nodes():
    snapshot = _healthy_snapshot()
    snapshot["qdrant"].update(
        {
            "points": 76_918,
            "compatible_fingerprint_points": 76_918,
            "points_match_sqlite_chunks": False,
        }
    )
    snapshot["index_contract"]["actual"]["generation_points"] = 76_918

    result = build_retrieval_pipeline_status(snapshot)

    assert result["status"] == "ready"
    assert result["stages"]["index"]["status"] == "ready"
    assert result["stages"]["native_rrf"]["status"] == "ready"


def test_pipeline_keeps_rrf_available_during_compatible_incremental_indexing():
    snapshot = _healthy_snapshot()
    snapshot["qdrant"].update(
        {
            "points": 77_048,
            "compatible_fingerprint_points": 77_048,
            "points_match_sqlite_chunks": False,
        }
    )
    snapshot["index_contract"]["actual"]["generation_points"] = 76_918
    snapshot["totals"] = {"pending_files": 1_651}

    result = build_retrieval_pipeline_status(snapshot)

    assert result["status"] == "indexing"
    assert result["stages"]["index"]["status"] == "indexing"
    assert result["stages"]["native_rrf"]["status"] == "ready"
    assert result["stages"]["hierarchy"]["status"] == "ready"
