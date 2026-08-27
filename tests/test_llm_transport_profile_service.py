from proxy.services.llm_transport_profile_service import (
    effective_model_execution_diagnostics,
    resolve_transport_execution_profile,
)


def test_transport_uses_observed_capacity_for_35b():
    preset = resolve_transport_execution_profile(
        provider="freetoken",
        model_id="Qwen3.5-35B-A3B",
        observed_context_tokens=65536,
        observed=True,
        observed_source="freetoken_runtime_probe",
    )

    assert preset.preset_id == "qwen-35b-extended"
    assert "observed_backend_capacity" in preset.source_chain


def test_configured_capacity_is_requested_not_falsely_observed(monkeypatch):
    monkeypatch.setenv("LES_LLM_PROVIDER", "freetoken")
    monkeypatch.setenv("FREETOKEN_MODEL", "Qwen3.5-35B-A3B")
    monkeypatch.setenv("FREETOKEN_CONTEXT_TOKENS", "65536")
    monkeypatch.setenv("FREETOKEN_API_KEY", "must-not-appear")

    diagnostics = effective_model_execution_diagnostics()

    assert diagnostics["model_preset"]["effective"] == "qwen-9b-restrictive"
    assert diagnostics["context_input_tokens"]["requested"] == 65536
    assert "must-not-appear" not in repr(diagnostics)

