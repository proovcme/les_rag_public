from tools.rag_index_contract_audit import summarize_points


def test_contract_audit_rejects_mixed_legacy_points():
    points = [
        {"payload": {"embedding_fingerprint": "current", "embedding_model_id": "qwen"}},
        {"payload": {"embedding_fingerprint": "old", "embedding_model_id": "qwen"}},
    ]

    report = summarize_points(points, current_fingerprint="current")

    assert report["status"] == "mixed_fingerprints"
    assert report["adoptable"] is False
    assert report["embedding_budget_coverage"] == 0


def test_contract_audit_accepts_only_fully_reported_current_points():
    points = [
        {
            "payload": {
                "embedding_fingerprint": "current",
                "embedding_model_id": "qwen",
                "embedding_backend": "coreml",
                "embedding_budget_enforced": True,
                "content_sanitized": False,
            }
        }
    ]

    report = summarize_points(points, current_fingerprint="current")

    assert report["status"] == "compatible_sample"
    assert report["adoptable"] is True
