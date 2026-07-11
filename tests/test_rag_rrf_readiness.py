from types import SimpleNamespace

from qdrant_client import models

from tools.rag_rrf_readiness import audit_rrf_readiness


class FakeClient:
    def __init__(self, *, sparse_points: int = 2):
        self.sparse_points = sparse_points

    def count(self, _collection, *, count_filter=None, exact=True):
        assert exact is True
        conditions = list(getattr(count_filter, "must", None) or [])
        dataset = next(
            (
                item.match.value
                for item in conditions
                if isinstance(item, models.FieldCondition) and item.key == "dataset_id"
            ),
            None,
        )
        base = 1 if dataset else 2
        if any(
            isinstance(item, models.HasVectorCondition)
            and item.has_vector == "bm25_sparse"
            for item in conditions
        ):
            base = min(base, self.sparse_points if not dataset else int(self.sparse_points > 0))
        return SimpleNamespace(count=base)


def _contract():
    return {
        "schema": "les.rag.index-contract.v2",
        "collection": "clean-v2",
        "qdrant_schema": "named",
        "dense_vector_name": "dense",
        "sparse_vector_name": "bm25_sparse",
        "point_embedding_fingerprint": "fp",
    }


def _migration_report():
    return {
        "status": "completed",
        "source_coverage": 1.0,
        "source_points": 2,
        "source_points_read": 2,
    }


def test_rrf_readiness_requires_every_dataset_and_both_vector_channels():
    report = audit_rrf_readiness(
        client=FakeClient(),
        collection="clean-v2",
        contract=_contract(),
        datasets=[{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
        migration_report=_migration_report(),
    )

    assert report["ready"] is True
    assert report["datasets_ready"] == 2
    assert report["covered_dataset_points"] == 2


def test_rrf_readiness_blocks_collection_with_missing_sparse_vectors():
    report = audit_rrf_readiness(
        client=FakeClient(sparse_points=1),
        collection="clean-v2",
        contract=_contract(),
        datasets=[{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
        migration_report=_migration_report(),
    )

    assert report["ready"] is False
    assert report["sparse_points"] == 1
