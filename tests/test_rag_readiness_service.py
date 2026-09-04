import json
import hashlib
from types import SimpleNamespace

from proxy.services import rag_readiness_service as service


class FakeClient:
    def __init__(self, points=10):
        self.points = points

    def collection_exists(self, collection):
        return bool(collection)

    def count(self, collection, count_filter=None, exact=True):
        return SimpleNamespace(count=self.points)


def test_user_readiness_separates_backend_contract_optional_and_query_dimensions():
    result = service.user_readiness_dimensions(
        backend_available=True,
        contract_complete=True,
        optional_stages={"colbert": {"status": "bypassed", "reason": "not_ready"}},
        query_quality={"status": "weak", "detail": "one query"},
    )

    assert result["overall"] == "ready"
    assert result["blocking_dimension"] == ""
    assert result["backend_available"]["status"] == "ready"
    assert result["contract_complete"]["status"] == "ready"
    assert result["optional_stages"]["colbert"]["reason"] == "not_ready"
    assert result["query_quality"]["status"] == "weak"


def test_readiness_reports_unproven_colbert_as_bypassed_not_degraded(monkeypatch):
    monkeypatch.setattr(
        service,
        "QdrantClient",
        lambda **kwargs: SimpleNamespace(close=lambda: None),
    )
    monkeypatch.setattr(service, "_aliases", lambda client: {})
    monkeypatch.setattr(
        service,
        "_general_status",
        lambda client, aliases, dataset_id=None: {"rrf_ready": True},
    )
    monkeypatch.setattr(service, "_smeta_status", lambda client, aliases: {"ready": True})
    monkeypatch.setattr(
        service,
        "load_policy",
        lambda: {
            "raptor": {"mode": "off"},
            "colbert": {"mode": "adaptive"},
        },
    )
    monkeypatch.setattr(
        service,
        "load_status",
        lambda: {
            "raptor": {"readiness": "not_built"},
            "colbert": {
                "readiness": "degraded",
                "last_error_code": "COLBERT_RERANK_FAILED",
                "last_bypass_reason": "COLBERT_RERANK_FAILED",
                "circuit_state": "open",
            },
        },
    )
    monkeypatch.setattr(
        service,
        "index_contract_status",
        lambda: {"compatible": True, "actual": {}},
    )

    result = service.rag_readiness(force=True)

    assert result["user_status"]["overall"] == "ready"
    assert result["user_status"]["optional_stages"]["colbert"] == {
        "mode": "adaptive",
        "status": "bypassed",
        "reason": "not_ready",
        "last_error_code": "COLBERT_RERANK_FAILED",
    }


def test_general_rrf_ready_requires_contract_channels_fingerprint_and_alias(monkeypatch):
    monkeypatch.setattr(service, "rag_collection_name", lambda: "les_rag")
    monkeypatch.setattr(service, "_source_chunks", lambda dataset_id: 10)
    monkeypatch.setattr(
        service,
        "_lexical_status",
        lambda collection, dataset_id=None: {
            "collection": collection,
            "ready": True,
            "stale": False,
            "chunks": 10,
            "point_count": 10,
            "indexed_count": 10,
            "scope_chunks": 10,
        },
    )
    monkeypatch.setattr(
        service,
        "index_contract_status",
        lambda: {
            "status": "compatible",
            "compatible": True,
            "actual": {"point_embedding_fingerprint": "fp"},
        },
    )

    result = service._general_status(
        FakeClient(), {"les_rag": "physical_v2"}, dataset_id="dataset-1"
    )

    assert result["state"] == "ready"
    assert result["rrf_ready"] is True
    assert result["dense_points"] == result["sparse_points"] == result["points"] == 10
    assert result["physical_generation"] == "physical_v2"


def test_general_index_with_bad_contract_is_degraded(monkeypatch):
    monkeypatch.setattr(service, "rag_collection_name", lambda: "legacy")
    monkeypatch.setattr(service, "_source_chunks", lambda dataset_id: None)
    monkeypatch.setattr(service, "_lexical_status", lambda collection, dataset_id=None: {})
    monkeypatch.setattr(
        service,
        "index_contract_status",
        lambda: {"status": "mismatch", "compatible": False, "actual": {}},
    )

    result = service._general_status(FakeClient(), {}, dataset_id=None)

    assert result["state"] == "degraded"
    assert result["rrf_ready"] is False
    assert result["reason"] == "contract_incompatible"


def test_general_rag_without_user_documents_is_empty_not_blocked(monkeypatch):
    monkeypatch.setattr(service, "rag_collection_name", lambda: "les_rag")
    monkeypatch.setattr(service, "_source_chunks", lambda dataset_id: 0)
    monkeypatch.setattr(
        service,
        "_lexical_status",
        lambda collection, dataset_id=None: {
            "collection": collection,
            "ready": True,
            "stale": False,
            "chunks": 0,
            "point_count": 0,
            "indexed_count": 0,
        },
    )
    monkeypatch.setattr(
        service,
        "index_contract_status",
        lambda: {
            "status": "compatible",
            "compatible": True,
            "actual": {
                "point_embedding_fingerprint": "fp",
                "generation_points": 0,
            },
        },
    )

    result = service._general_status(FakeClient(points=0), {}, dataset_id=None)

    assert result["state"] == "empty"
    assert result["reason"] == "no_user_documents"
    assert result["ready"] is False
    assert result["rrf_ready"] is False


def test_general_native_rrf_does_not_depend_on_the_legacy_lexical_sidecar(monkeypatch):
    monkeypatch.setattr(service, "rag_collection_name", lambda: "les_rag")
    monkeypatch.setattr(service, "_source_chunks", lambda dataset_id: 10)
    monkeypatch.setattr(
        service, "_lexical_status", lambda collection, dataset_id=None: {"ready": False}
    )
    monkeypatch.setattr(
        service,
        "index_contract_status",
        lambda: {
            "status": "compatible",
            "compatible": True,
            "actual": {"point_embedding_fingerprint": "fp"},
        },
    )
    result = service._general_status(
        FakeClient(), {"les_rag": "physical_v2"}, dataset_id="dataset-1"
    )
    assert result["rrf_ready"] is True
    assert result["state"] == "ready"
    assert result["lexical"]["ready"] is False
    assert result["lexical"]["required"] is False


def test_source_chunk_count_excludes_system_catalogs(monkeypatch, tmp_path):
    db = tmp_path / "meta.sqlite"
    import sqlite3

    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE datasets (id TEXT, chunk_count INTEGER, dataset_scope TEXT)"
        )
        conn.executemany(
            "INSERT INTO datasets VALUES (?, ?, ?)",
            [
                ("user-a", 11, "user"),
                ("user-b", 7, "user"),
                ("smeta", 49818, "system"),
            ],
        )
    monkeypatch.setattr(service, "rag_meta_db_path", lambda: str(db))

    assert service._source_chunks(None) == 18
    assert service._source_chunks("user-b") == 7


def test_general_readiness_uses_current_user_catalog_after_generation_grows(monkeypatch):
    """Incremental user indexing must not leave an otherwise complete RRF red."""

    monkeypatch.setattr(service, "rag_collection_name", lambda: "les_rag")
    monkeypatch.setattr(service, "_source_chunks", lambda dataset_id: 101_366)
    monkeypatch.setattr(
        service,
        "_lexical_status",
        lambda collection, dataset_id=None: {"ready": False},
    )
    monkeypatch.setattr(
        service,
        "index_contract_status",
        lambda: {
            "status": "compatible",
            "compatible": True,
            "actual": {
                "point_embedding_fingerprint": "fp",
                "generation_points": 76_918,
            },
        },
    )

    result = service._general_status(
        FakeClient(points=101_366),
        {"les_rag": "les_rag_v563"},
        dataset_id=None,
    )

    assert result["state"] == "ready"
    assert result["rrf_ready"] is True
    assert result["expected_source_points"] == 101_366
    assert result["expected_generation_points"] == 76_918


def test_general_direct_config_is_active_and_legacy_lexical_marker_is_optional(monkeypatch):
    monkeypatch.setattr(service, "rag_collection_name", lambda: "windows_v2")
    monkeypatch.setattr(service, "_source_chunks", lambda dataset_id: 10)
    monkeypatch.setattr(
        service,
        "_lexical_status",
        lambda collection, dataset_id=None: {
            "ready": True,
            "stale": False,
            "chunks": 10,
            "point_count": 0,
            "indexed_count": 10,
        },
    )
    monkeypatch.setattr(
        service,
        "index_contract_status",
        lambda: {
            "status": "compatible",
            "compatible": True,
            "actual": {"point_embedding_fingerprint": "fp"},
        },
    )

    result = service._general_status(FakeClient(), {}, dataset_id=None)

    assert result["state"] == "ready"
    assert result["activated"] is True
    assert result["rrf_ready"] is True


def test_smeta_build_progress_is_visible(monkeypatch, tmp_path):
    base = tmp_path / "base.sqlite"
    base.write_bytes(b"sqlite")
    base.with_name("les_smeta_norm_rag_manifest.json").write_text(
        json.dumps(
            {
                "status": "building",
                "collection": "smeta_physical_v3",
                "expected_points": 20,
                "index_mode": "building_dense",
                "point_embedding_fingerprint": "fp",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "proxy.smeta_core.base_registry.active_base",
        lambda: {"base_path": str(base), "rag_collection": "les_smeta_norm_cards"},
    )
    monkeypatch.setattr(
        "proxy.smeta_core.integrity.normative_base_integrity",
        lambda: {"status": "quarantined", "trusted_for_pricing": False, "trusted_for_navigation": False},
    )

    result = service._smeta_status(FakeClient(points=10), {})

    assert result["state"] == "blocked"
    assert result["reason"] == "mechanical_base_missing_or_untrusted"
    assert result["progress_pct"] == 50.0
    assert result["rrf_ready"] is False


def test_smeta_complete_generation_waits_for_alias(monkeypatch, tmp_path):
    base = tmp_path / "base.sqlite"
    base.write_bytes(b"sqlite")
    base.with_name("les_smeta_norm_rag_manifest.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "collection": "smeta_physical_v3",
                "expected_points": 10,
                "index_mode": "hybrid",
                "point_embedding_fingerprint": "fp",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "proxy.smeta_core.base_registry.active_base",
        lambda: {"base_path": str(base), "rag_collection": "les_smeta_norm_cards"},
    )
    monkeypatch.setattr(
        "proxy.smeta_core.integrity.normative_base_integrity",
        lambda: {"status": "quarantined", "trusted_for_pricing": False, "trusted_for_navigation": False},
    )

    result = service._smeta_status(FakeClient(points=10), {})

    assert result["state"] == "blocked"
    assert result["ready"] is False
    assert result["activated"] is False


def test_smeta_verified_mechanical_base_is_blocked_without_required_card_index(monkeypatch, tmp_path):
    base = tmp_path / "base.sqlite"
    base.write_bytes(b"sqlite")
    monkeypatch.setattr(
        "proxy.smeta_core.base_registry.active_base",
        lambda: {"base_path": str(base), "rag_collection": "les_smeta_norm_cards"},
    )
    monkeypatch.setattr(
        "proxy.smeta_core.integrity.normative_base_integrity",
        lambda: {"status": "trusted", "trusted_for_pricing": True, "trusted_for_navigation": True},
    )
    client = FakeClient()
    client.collection_exists = lambda _collection: False

    result = service._smeta_status(client, {})

    assert result["state"] == "blocked"
    assert result["ready"] is False
    assert result["reason"] == "smeta_search_index_missing"
    assert result["mechanical_base"]["ready"] is True
    assert result["search_index"] == {
        "state": "missing",
        "ready": False,
        "optional": False,
        "reason": "collection_missing",
    }


def test_smeta_ready_requires_mechanical_base_and_activated_hybrid_index(monkeypatch, tmp_path):
    base = tmp_path / "base.sqlite"
    base.write_bytes(b"sqlite")
    base.with_name("les_smeta_norm_rag_manifest.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "physical_generation": "smeta_physical_v3",
                "expected_points": 10,
                "index_mode": "hybrid",
                "point_embedding_fingerprint": "fp",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "proxy.smeta_core.base_registry.active_base",
        lambda: {"base_path": str(base), "rag_collection": "les_smeta_norm_cards"},
    )
    monkeypatch.setattr(
        "proxy.smeta_core.integrity.normative_base_integrity",
        lambda: {
            "status": "trusted",
            "trusted_for_pricing": True,
            "trusted_for_navigation": True,
        },
    )

    result = service._smeta_status(
        FakeClient(points=10),
        {"les_smeta_norm_cards": "smeta_physical_v3"},
    )

    assert result["state"] == "ready"
    assert result["ready"] is True
    assert result["mechanical_base"]["ready"] is True
    assert result["search_index"]["ready"] is True
    assert result["rrf_ready"] is True


def test_smeta_readiness_blocks_mismatched_sqlite_and_rag_revisions(monkeypatch, tmp_path):
    base = tmp_path / "base.sqlite"
    base.write_bytes(b"new-sqlite-revision")
    active_sha = hashlib.sha256(base.read_bytes()).hexdigest()
    indexed_sha = hashlib.sha256(b"old-sqlite-revision").hexdigest()
    base.with_name("les_smeta_norm_rag_manifest.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "physical_generation": "smeta_physical_v3",
                "expected_points": 10,
                "index_mode": "hybrid",
                "point_embedding_fingerprint": "fp",
                "base_sha256": indexed_sha,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "proxy.smeta_core.base_registry.active_base",
        lambda: {"base_path": str(base), "rag_collection": "les_smeta_norm_cards"},
    )
    monkeypatch.setattr(
        "proxy.smeta_core.integrity.normative_base_integrity",
        lambda: {
            "status": "trusted",
            "trusted_for_pricing": True,
            "trusted_for_navigation": True,
        },
    )

    result = service._smeta_status(
        FakeClient(points=10),
        {"les_smeta_norm_cards": "smeta_physical_v3"},
    )

    assert result["state"] == "blocked"
    assert result["ready"] is False
    assert result["rrf_ready"] is False
    assert result["reason"] == "base_index_revision_mismatch"
    assert result["revision"] == {
        "state": "mismatch",
        "active_base_sha256": active_sha,
        "indexed_base_sha256": indexed_sha,
        "restart_required": False,
    }
    assert result["warnings"][0]["code"] == "SMETA_BASE_INDEX_REVISION_MISMATCH"
    assert result["warnings"][0]["action"] == "rebuild_or_activate_matching_generation"


def test_smeta_readiness_uses_the_configured_catalog_name(monkeypatch, tmp_path):
    base = tmp_path / "customer.sqlite"
    base.write_bytes(b"sqlite")
    base.with_name("les_smeta_norm_rag_manifest.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "collection": "customer_norm_catalog",
                "physical_generation": "customer_norm_catalog_20260901",
                "expected_points": 10,
                "index_mode": "hybrid",
                "point_embedding_fingerprint": "fp",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "proxy.smeta_core.base_registry.active_base",
        lambda: {
            "base_path": str(base),
            "rag_collection": "customer_norm_catalog",
        },
    )
    monkeypatch.setattr(
        "proxy.smeta_core.integrity.normative_base_integrity",
        lambda: {
            "status": "trusted",
            "trusted_for_pricing": True,
            "trusted_for_navigation": True,
        },
    )

    result = service._smeta_status(
        FakeClient(points=10),
        {"customer_norm_catalog": "customer_norm_catalog_20260901"},
    )

    assert result["alias"] == "customer_norm_catalog"
    assert result["physical_generation"] == "customer_norm_catalog_20260901"
    assert result["rrf_ready"] is True
