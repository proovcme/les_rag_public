import json
import hashlib

import pytest

from backend.rag_config import index_contract_payload, index_contract_status
from tools.activate_qdrant_generation import (
    _read_ready_report,
    _restore_lexical_alias,
    alias_contract,
    alias_manifest,
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
