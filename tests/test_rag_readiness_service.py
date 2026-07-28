import json
from types import SimpleNamespace

from proxy.services import rag_readiness_service as service


class FakeClient:
    def __init__(self, points=10):
        self.points = points

    def collection_exists(self, collection):
        return bool(collection)

    def count(self, collection, count_filter=None, exact=True):
        return SimpleNamespace(count=self.points)


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


def test_general_rrf_is_not_ready_without_alias_lexical_projection(monkeypatch):
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
    assert result["rrf_ready"] is False
    assert result["lexical"]["ready"] is False


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

    assert result["state"] == "building"
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

    assert result["state"] == "awaiting_activation"
    assert result["ready"] is True
    assert result["activated"] is False


def test_smeta_verified_mechanical_base_is_ready_without_optional_card_index(monkeypatch, tmp_path):
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

    assert result["state"] == "ready"
    assert result["ready"] is True
    assert result["mechanical_base"]["ready"] is True
    assert result["search_index"] == {
        "state": "missing",
        "ready": False,
        "optional": True,
        "reason": "collection_missing",
    }
