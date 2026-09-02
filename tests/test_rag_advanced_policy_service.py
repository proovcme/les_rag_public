import json

import pytest

from proxy.services import rag_advanced_policy_service as policy


@pytest.fixture()
def isolated_policy(monkeypatch, tmp_path):
    monkeypatch.setenv("LES_RAG_ADVANCED_POLICY_PATH", str(tmp_path / "policy.json"))
    monkeypatch.setenv("LES_RAG_ADVANCED_STATUS_PATH", str(tmp_path / "status.json"))
    return tmp_path


def test_default_policy_is_gui_visible_and_has_no_hidden_overrides(isolated_policy):
    snapshot = policy.operator_snapshot()

    assert snapshot["policy"]["raptor"]["mode"] == "off"
    assert snapshot["policy"]["colbert"]["mode"] == "adaptive"
    assert snapshot["policy"]["colbert"]["model"] == "BAAI/bge-m3"
    assert snapshot["policy"]["colbert"]["allow_cpu_full_build"] is False
    assert snapshot["hidden_runtime_overrides"] == []
    assert snapshot["status"]["colbert"]["readiness"] == "not_built"


def test_absent_legacy_raptor_mode_migrates_to_safe_effective_off(isolated_policy):
    saved = policy.validate_policy({"schema": policy.POLICY_SCHEMA, "raptor": {}})

    assert saved["raptor"]["mode"] == "off"


def test_colbert_ready_requires_activated_complete_generation_contract(isolated_policy):
    current = policy.load_policy()
    current["colbert"]["mode"] = "always"
    status = {
        "readiness": "ready",
        "target_collection": "les_rag_colbert_abc",
        "circuit_state": "closed",
    }
    contract = {
        "compatible": True,
        "actual": {
            "physical_generation": "les_rag_colbert_abc",
            "colbert_schema": "les.rag.colbert.bge-m3.v1",
            "colbert_vector_name": "colbert",
            "generation_points": 42,
            "readiness_report_sha256": "proof",
        },
    }

    ready = policy.colbert_generation_readiness(current, status, contract)
    incomplete = policy.colbert_generation_readiness(
        current,
        status,
        {**contract, "actual": {**contract["actual"], "readiness_report_sha256": ""}},
    )

    assert ready["ready"] is True
    assert incomplete == {
        "ready": False,
        "reason": "multivector_contract_incomplete",
        "mode": "always",
    }


def test_policy_roundtrip_is_atomic_versioned_and_unicode_safe(isolated_policy):
    updated = policy.load_policy()
    updated["raptor"]["mode"] = "always"
    updated["colbert"]["candidate_k"] = 48
    saved = policy.save_policy(updated)

    assert saved["revision"] == 2
    assert policy.load_policy() == saved
    raw = policy.policy_path().read_text(encoding="utf-8")
    assert "BAAI/bge-m3" in raw
    assert json.loads(raw)["raptor"]["mode"] == "always"
    assert not list(isolated_policy.glob("*.tmp"))


def test_policy_rejects_unknown_mode_and_invalid_shortlist(isolated_policy):
    invalid = policy.load_policy()
    invalid["colbert"]["mode"] = "secret-env-mode"
    with pytest.raises(policy.AdvancedPolicyError, match="off/adaptive/always"):
        policy.save_policy(invalid)

    invalid = policy.load_policy()
    invalid["colbert"]["candidate_k"] = 8
    invalid["colbert"]["output_k"] = 9
    with pytest.raises(policy.AdvancedPolicyError, match="output_k exceeds"):
        policy.save_policy(invalid)


def test_policy_keeps_raptor_summarizer_visible_and_local_only(isolated_policy):
    current = policy.load_policy()
    assert current["raptor"]["summary_backend"] == "ollama"
    assert current["raptor"]["summary_model"]
    assert current["raptor"]["summary_api_url"] == "http://127.0.0.1:11434"

    current["raptor"]["summary_api_url"] = "https://remote.example"
    with pytest.raises(policy.AdvancedPolicyError, match="local Ollama"):
        policy.save_policy(current)


def test_status_keeps_stable_error_codes_and_route_fallbacks(isolated_policy):
    saved = policy.save_status(
        {
            "colbert": {
                "readiness": "blocked",
                "last_error_code": "COLBERT_INDEX_MISSING",
                "last_bypass_reason": "latency_budget",
            },
            "last_route": {
                "stages": ["native_rrf", "hierarchy"],
                "fallbacks": ["COLBERT_INDEX_MISSING"],
            },
        }
    )

    assert saved["colbert"]["last_error_code"] == "COLBERT_INDEX_MISSING"
    assert saved["last_route"]["fallbacks"] == ["COLBERT_INDEX_MISSING"]
