from types import SimpleNamespace

from qdrant_client import models

import tools.rag_rrf_readiness as readiness
from tools.rag_rrf_readiness import audit_rrf_readiness, select_compatible_embed_url


class FakeClient:
    def __init__(self, *, sparse_points: int = 2, colbert_points: int = 2):
        self.sparse_points = sparse_points
        self.colbert_points = colbert_points

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
        if any(
            isinstance(item, models.FieldCondition)
            and item.key == "domain"
            and item.match.value == "TABLE_SMETA"
            for item in conditions
        ):
            return SimpleNamespace(count=0)
        base = 1 if dataset else 2
        if any(
            isinstance(item, models.HasVectorCondition)
            and item.has_vector == "bm25_sparse"
            for item in conditions
        ):
            base = min(base, self.sparse_points if not dataset else int(self.sparse_points > 0))
        if any(
            isinstance(item, models.HasVectorCondition)
            and item.has_vector == "colbert"
            for item in conditions
        ):
            base = min(base, self.colbert_points if not dataset else int(self.colbert_points > 0))
        return SimpleNamespace(count=base)


def _contract():
    return {
        "schema": "les.rag.index-contract.v3",
        "collection": "clean-v2",
        "qdrant_schema": "named",
        "dense_vector_name": "dense",
        "sparse_vector_name": "bm25_sparse",
        "point_embedding_fingerprint": "fp",
        "hierarchy_schema": "les.rag.hierarchy.v1",
        "navigation_evidence_policy": "navigation_not_evidence",
    }


def _migration_report():
    return {
        "status": "completed",
        "destination_collection": "clean-v2",
        "source_coverage": 1.0,
        "source_points": 2,
        "source_points_read": 2,
        "destination_points": 2,
        "destination_points_accounted": 2,
        "datasets": [
            {
                "dataset_id": "a",
                "source_identity_sha256": "a" * 64,
                "source_points_read": 1,
                "source_points_with_searchable_children": 1,
                "source_points_excluded": 0,
                "child_points_total": 1,
                "destination_points": 1,
                "excluded_child_points": 0,
                "exclusions": [],
            },
            {
                "dataset_id": "b",
                "source_identity_sha256": "b" * 64,
                "source_points_read": 1,
                "source_points_with_searchable_children": 1,
                "source_points_excluded": 0,
                "child_points_total": 1,
                "destination_points": 1,
                "excluded_child_points": 0,
                "exclusions": [],
            },
        ],
    }


def _lexical_status():
    return {
        "collection": "clean-v2",
        "ready": True,
        "stale": False,
        "chunks": 2,
        "point_count": 2,
        "indexed_count": 2,
    }


def test_rrf_readiness_requires_every_dataset_and_both_vector_channels():
    report = audit_rrf_readiness(
        client=FakeClient(),
        collection="clean-v2",
        contract=_contract(),
        datasets=[{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
        migration_report=_migration_report(),
        lexical_status=_lexical_status(),
    )

    assert report["ready"] is True
    assert report["datasets_ready"] == 2
    assert report["covered_dataset_points"] == 2


def test_rrf_readiness_rejects_migration_from_different_scope_manifest():
    migration = _migration_report()
    migration["scope_manifest_sha256"] = "old"
    report = audit_rrf_readiness(
        client=FakeClient(),
        collection="clean-v2",
        contract=_contract(),
        datasets=[{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
        migration_report=migration,
        lexical_status=_lexical_status(),
        scope_manifest_sha256="current",
    )
    assert report["ready"] is False
    assert report["scope_manifest_match"] is False


def test_rrf_readiness_blocks_collection_with_missing_sparse_vectors():
    report = audit_rrf_readiness(
        client=FakeClient(sparse_points=1),
        collection="clean-v2",
        contract=_contract(),
        datasets=[{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
        migration_report=_migration_report(),
        lexical_status=_lexical_status(),
    )

    assert report["ready"] is False
    assert report["sparse_points"] == 1


def test_rrf_readiness_blocks_incomplete_required_colbert_vectors():
    contract = _contract()
    contract.update(
        {
            "colbert_vector_name": "colbert",
            "colbert_schema": "les.rag.colbert.v1",
        }
    )
    report = audit_rrf_readiness(
        client=FakeClient(colbert_points=1),
        collection="clean-v2",
        contract=contract,
        datasets=[{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
        migration_report=_migration_report(),
        lexical_status=_lexical_status(),
    )

    assert report["ready"] is False
    assert report["colbert_required"] is True
    assert report["colbert_points"] == 1


def test_rrf_readiness_accepts_complete_required_colbert_vectors():
    contract = _contract()
    contract.update(
        {
            "colbert_vector_name": "colbert",
            "colbert_schema": "les.rag.colbert.v1",
        }
    )
    report = audit_rrf_readiness(
        client=FakeClient(),
        collection="clean-v2",
        contract=contract,
        datasets=[{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
        migration_report=_migration_report(),
        lexical_status=_lexical_status(),
    )

    assert report["ready"] is True
    assert report["colbert_points"] == report["points"]


def test_rrf_readiness_blocks_missing_alias_fts_projection():
    lexical = _lexical_status()
    lexical["chunks"] = 1
    report = audit_rrf_readiness(
        client=FakeClient(),
        collection="clean-v2",
        contract=_contract(),
        datasets=[{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
        migration_report=_migration_report(),
        lexical_status=lexical,
    )
    assert report["ready"] is False
    assert report["lexical"]["ready"] is False


def test_rrf_readiness_accepts_only_audited_noise_exclusion():
    migration = _migration_report()
    migration["source_points"] = migration["source_points_read"] = 3
    migration["source_points_excluded"] = 1
    migration["datasets"][0].update(
        {
            "source_points_read": 2,
            "source_points_with_searchable_children": 1,
            "source_points_excluded": 1,
            "exclusions": [
                {
                    "source_point_id": "noise",
                    "child_ord": None,
                    "reason": "sanitation_removed_all_text",
                    "text_sha256": "c" * 64,
                }
            ],
        }
    )
    report = audit_rrf_readiness(
        client=FakeClient(),
        collection="clean-v2",
        contract=_contract(),
        datasets=[{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
        migration_report=migration,
        lexical_status=_lexical_status(),
    )
    assert report["ready"] is True
    assert report["exclusion_accounting_ok"] is True

    migration["datasets"][0]["exclusions"][0]["reason"] = "silent_drop"
    blocked = audit_rrf_readiness(
        client=FakeClient(),
        collection="clean-v2",
        contract=_contract(),
        datasets=[{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
        migration_report=migration,
        lexical_status=_lexical_status(),
    )
    assert blocked["ready"] is False
    assert blocked["exclusion_accounting_ok"] is False


def test_live_probe_selects_one_identity_checked_url_from_parallel_build_list():
    checked = []

    def verifier(url, *, contract):
        checked.append(url)
        if url.endswith("8080"):
            raise RuntimeError("wrong model")

    selected, failures = select_compatible_embed_url(
        "http://127.0.0.1:8080,http://127.0.0.1:8081",
        contract=_contract(),
        verifier=verifier,
    )
    assert selected == "http://127.0.0.1:8081"
    assert checked == ["http://127.0.0.1:8080", "http://127.0.0.1:8081"]
    assert failures[0]["url"].endswith("8080")


def test_live_probe_uses_collection_contract_model_not_runtime_default(monkeypatch):
    captured = {}

    class FakeEmbedClient:
        def __init__(self, url, *, model, backend):
            captured.update(url=url, model=model, backend=backend)

        def encode_sync(self, texts):
            assert texts == []
            return []

    monkeypatch.setattr(readiness, "EmbedClient", FakeEmbedClient)

    report = readiness.live_rrf_probe(
        client=object(),
        collection="clean-v2",
        datasets=[],
        dense_name="dense",
        sparse_name="bm25_sparse",
        embed_url="http://127.0.0.1:8080",
        embed_model="qwen3-embedding-0.6b",
        embed_backend="coreml",
    )

    assert captured == {
        "url": "http://127.0.0.1:8080",
        "model": "qwen3-embedding-0.6b",
        "backend": "coreml",
    }
    assert report["ready"] is True
