from proxy.services.rag_advanced_preflight_service import (
    advanced_preflight,
    estimate_colbert_storage,
    estimate_raptor_nodes,
)


def test_colbert_storage_estimate_is_deterministic_and_fp16():
    result = estimate_colbert_storage(
        evidence_points=100,
        max_passage_tokens=128,
    )
    assert result["raw_bytes"] == 100 * 128 * 1024 * 2
    assert result["estimated_bytes"] > result["raw_bytes"]


def test_raptor_estimate_is_bounded_by_fanout_and_depth():
    assert estimate_raptor_nodes(evidence_points=64, fanout=8, max_depth=3) == 8 + 1


def test_preflight_never_claims_model_loaded(monkeypatch, tmp_path):
    monkeypatch.setenv("LES_RAG_ADVANCED_POLICY_PATH", str(tmp_path / "policy.json"))
    monkeypatch.setattr(
        "proxy.services.rag_advanced_preflight_service._bge_m3_cache",
        lambda: {
            "status": "missing",
            "bytes": 0,
            "path": "",
            "error_code": "COLBERT_MODEL_CACHE_MISSING",
        },
    )
    result = advanced_preflight(
        {"qdrant": {"points": 1000, "collection": "les_rag"}}
    )
    assert result["read_only"] is True
    assert result["model_loaded"] is False
    assert result["colbert"]["status"] == "blocked"
    assert result["colbert"]["storage_target"]["free_bytes"] is None
    assert result["raptor"]["estimated_navigation_nodes"] > 0


def test_large_cpu_only_colbert_build_is_blocked_until_operator_override(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("LES_RAG_ADVANCED_POLICY_PATH", str(tmp_path / "policy.json"))
    monkeypatch.setattr(
        "proxy.services.rag_advanced_preflight_service._bge_m3_cache",
        lambda: {"status": "ready", "bytes": 4_000_000_000, "error_code": ""},
    )
    monkeypatch.setattr(
        "proxy.services.rag_advanced_preflight_service._colbert_acceleration",
        lambda: {"status": "cpu_only", "backend": "cpu"},
    )

    blocked = advanced_preflight(
        {"qdrant": {"points": 10_001, "collection": "les_rag"}}
    )

    assert "COLBERT_ACCELERATOR_REQUIRED_FOR_FULL_BUILD" in blocked["colbert"]["blockers"]
    assert blocked["colbert"]["acceleration"] == {
        "status": "cpu_only",
        "backend": "cpu",
    }

    current = __import__(
        "proxy.services.rag_advanced_policy_service", fromlist=["load_policy"]
    ).load_policy()
    current["colbert"]["allow_cpu_full_build"] = True
    __import__(
        "proxy.services.rag_advanced_policy_service", fromlist=["save_policy"]
    ).save_policy(current)

    allowed = advanced_preflight(
        {"qdrant": {"points": 10_001, "collection": "les_rag"}}
    )
    assert "COLBERT_ACCELERATOR_REQUIRED_FOR_FULL_BUILD" not in allowed["colbert"]["blockers"]
