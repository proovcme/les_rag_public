from proxy.services.llm_transport_profile_service import (
    effective_model_execution_diagnostics,
    fit_prompt_sections,
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


def test_compatibility_wrapper_never_exceeds_character_limit_across_kinds():
    fitted, trace = fit_prompt_sections(
        [("tools", "1234"), ("evidence", "5678"), ("dialogue", "90")],
        required_tail="Q",
        max_chars=10,
    )

    assert len(fitted) <= 10
    assert fitted.endswith("Q")
    assert trace["truncated"] is True


def test_compatibility_wrapper_renders_duplicate_section_names_once():
    fitted, trace = fit_prompt_sections(
        [("evidence", "x" * 100), ("evidence", "y" * 100)],
        required_tail="Q",
        max_chars=210,
    )

    assert len(fitted) <= 210
    assert fitted.count("x" * 100) == 1
    assert fitted.count("y" * 100) == 1
    assert trace["sections"]["evidence"] == 200


def test_compatibility_wrapper_treats_executed_tools_as_exchange():
    _, trace = fit_prompt_sections(
        [("evidence", "e" * 8), ("tools", "t" * 8)],
        required_tail="Q",
        max_chars=12,
    )

    assert trace["sections"]["evidence"] == 8
    assert trace["sections"]["tools"] == 0
    assert trace["omissions"][0]["kind"] == "tool_exchange"
