from __future__ import annotations

from backend.qdrant_adapter import _named_collection_layout


def test_named_collection_layout_accepts_dense_and_sparse_contract():
    info = {
        "points_count": 0,
        "config": {
            "params": {
                "vectors": {"dense": {"size": 1024, "distance": "Cosine"}},
                "sparse_vectors": {"bm25_sparse": {"modifier": "idf"}},
            }
        },
    }

    assert _named_collection_layout(info, vector_size=1024) == (True, 0)


def test_named_collection_layout_rejects_legacy_unnamed_vector_and_preserves_count():
    info = {
        "points_count": 17,
        "config": {"params": {"vectors": {"size": 1024, "distance": "Cosine"}}},
    }

    assert _named_collection_layout(info, vector_size=1024) == (False, 17)


def test_named_collection_layout_rejects_wrong_dense_size_or_missing_sparse():
    wrong_size = {
        "points_count": 0,
        "config": {
            "params": {
                "vectors": {"dense": {"size": 768}},
                "sparse_vectors": {"bm25_sparse": {}},
            }
        },
    }
    missing_sparse = {
        "points_count": 0,
        "config": {"params": {"vectors": {"dense": {"size": 1024}}}},
    }

    assert _named_collection_layout(wrong_size, vector_size=1024) == (False, 0)
    assert _named_collection_layout(missing_sparse, vector_size=1024) == (False, 0)
