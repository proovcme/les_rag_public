import json
import hashlib

import pytest

from backend.rag_config import index_contract_payload, index_contract_status
from tools.activate_qdrant_generation import (
    _read_ready_report,
    _restore_lexical_alias,
    alias_contract,
    alias_manifest,
    has_physical_alias_blocker,
    mark_generation_job_activated,
)


def test_ready_report_is_fail_closed(tmp_path):
    path = tmp_path / "readiness.json"
    path.write_text(
        json.dumps({"status": "blocked", "ready": False, "collection": "physical_v2"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not ready"):
        _read_ready_report(path, "physical_v2")


def test_ready_report_requires_live_rrf_probe(tmp_path):
    path = tmp_path / "readiness.json"
    path.write_text(
        json.dumps({"status": "ready", "ready": True, "collection": "physical_v2"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="live RRF"):
        _read_ready_report(path, "physical_v2")

    path.write_text(
        json.dumps(
            {
                "status": "ready",
                "ready": True,
                "collection": "physical_v2",
                "live_rrf": {"ready": True},
                "lexical": {"ready": True},
            }
        ),
        encoding="utf-8",
    )
    assert _read_ready_report(path, "physical_v2")["live_rrf"]["ready"] is True


def test_alias_contract_preserves_point_identity_and_records_generation():
    source = {
        "schema": "les.rag.index-contract.v2",
        "collection": "physical_v2",
        "point_embedding_fingerprint": "point-space",
        "fingerprint": "old-contract",
    }

    result = alias_contract(source, target="physical_v2", alias="les_rag")

    assert result["collection"] == "les_rag"
    assert result["physical_generation"] == "physical_v2"
    assert result["point_embedding_fingerprint"] == "point-space"
    assert result["fingerprint"] != "old-contract"
    fingerprint_payload = {key: value for key, value in result.items() if key not in {"fingerprint", "physical_generation"}}
    stable = json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert result["fingerprint"] == hashlib.sha256(stable.encode("utf-8")).hexdigest()


def test_alias_contract_rejects_wrong_generation():
    with pytest.raises(ValueError, match="another collection"):
        alias_contract({"collection": "physical_v1"}, target="physical_v2", alias="les_rag")


def test_alias_contract_is_runtime_compatible(monkeypatch, tmp_path):
    path = tmp_path / "les_rag.index-contract.json"
    monkeypatch.setenv("LES_EMBED_PROFILE", "qwen")
    monkeypatch.setenv("EMBED_BACKEND", "coreml")
    monkeypatch.setenv("RAG_INDEX_CONTRACT_PATH", str(path))
    monkeypatch.setenv("RAG_COLLECTION_NAME", "physical_v2")
    source = index_contract_payload()
    result = alias_contract(source, target="physical_v2", alias="les_rag")
    path.write_text(json.dumps(result), encoding="utf-8")
    monkeypatch.setenv("RAG_COLLECTION_NAME", "les_rag")

    assert index_contract_status()["compatible"] is True


def test_alias_manifest_preserves_projection_identity():
    result = alias_manifest(
        {
            "schema": "smeta_norm_rag_manifest_v2",
            "status": "passed",
            "collection": "smeta_physical_v3",
            "base_sha256": "base",
            "point_embedding_fingerprint": "fp",
        },
        target="smeta_physical_v3",
        alias="les_smeta_norm_cards",
    )

    assert result["collection"] == "les_smeta_norm_cards"
    assert result["physical_generation"] == "smeta_physical_v3"
    assert result["base_sha256"] == "base"
    assert result["point_embedding_fingerprint"] == "fp"


def test_activation_rollback_clears_new_alias_fts_when_no_previous_generation():
    class Index:
        def __init__(self):
            self.cleared = []

        def status(self, _collection):
            return {}

        def clear_collection(self, collection):
            self.cleared.append(collection)

    index = Index()
    _restore_lexical_alias(index, alias="les_rag", previous_target=None)
    assert index.cleared == ["les_rag"]


def test_direct_activation_reconciles_supervisor_state(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps({"status": "blocked", "failures": 12, "error": "old"}),
        encoding="utf-8",
    )

    mark_generation_job_activated(
        path,
        alias="les_rag",
        target="physical_v2",
    )

    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["status"] == "activated"
    assert state["stage"] == "complete"
    assert state["failures"] == 0
    assert state["error"] == ""
    assert state["alias"] == "les_rag"
    assert state["destination_collection"] == "physical_v2"


def test_existing_qdrant_alias_is_not_mistaken_for_physical_blocker():
    class Client:
        def collection_exists(self, _name):
            return True  # Qdrant resolves aliases through this API.

    assert has_physical_alias_blocker(
        Client(),
        alias="les_rag",
        target="physical_v2",
        existing_aliases={"les_rag": "physical_v2"},
    ) is False
    assert has_physical_alias_blocker(
        Client(),
        alias="les_rag",
        target="physical_v2",
        existing_aliases={},
    ) is True
