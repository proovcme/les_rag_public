from proxy.services.version_service import version_info


def test_version_info_exposes_redacted_model_execution_factors(monkeypatch):
    monkeypatch.setenv("LES_LLM_PROVIDER", "freetoken")
    monkeypatch.setenv("FREETOKEN_MODEL", "qwen3.5:9b")
    monkeypatch.setenv("FREETOKEN_CONTEXT_TOKENS", "8253")
    monkeypatch.setenv("FREETOKEN_API_KEY", "secret-value")

    payload = version_info()
    factors = payload["model_execution"]

    assert {
        "model_preset",
        "context_input_tokens",
        "generation_reserve",
        "safety_reserve",
        "reasoning",
    } <= factors.keys()
    assert all(
        {"requested", "effective", "source", "restart_required"} <= row.keys()
        for row in factors.values()
    )
    assert "secret-value" not in repr(payload)
