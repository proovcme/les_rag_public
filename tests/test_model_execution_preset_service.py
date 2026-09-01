from proxy.services.model_execution_preset_service import (
    BackendCapacity,
    resolve_execution_preset,
)


def _capacity(
    *,
    model_id: str = "qwen3.5:9b",
    tokens: int | None = 8192,
    observed: bool = True,
) -> BackendCapacity:
    return BackendCapacity(
        provider="openai-compatible",
        model_id=model_id,
        context_tokens=tokens,
        observed=observed,
        source="runtime_probe" if observed else "unavailable",
    )


def test_unknown_identity_uses_restrictive_9b_preset():
    resolved = resolve_execution_preset(
        BackendCapacity(
            provider="openai-compatible",
            model_id="unknown",
            context_tokens=None,
            observed=False,
            source="unavailable",
        )
    )

    assert resolved.preset_id == "qwen-9b-restrictive"
    assert resolved.max_tools == 5
    assert resolved.max_batch_items == 5
    assert resolved.parallel_read_limit == 1
    assert resolved.reasoning_enabled is False


def test_observed_capacity_caps_operator_request():
    resolved = resolve_execution_preset(
        _capacity(tokens=8192),
        operator={"input_tokens": 35000},
    )

    assert resolved.input_token_limit == 8192
    assert resolved.source_chain[0] == "workflow_invariants"
    assert "observed_backend_capacity" in resolved.source_chain


def test_35b_requires_both_matching_identity_and_observed_capacity():
    observed = resolve_execution_preset(
        _capacity(model_id="Qwen3.5-35B-A3B", tokens=65536)
    )
    unobserved = resolve_execution_preset(
        _capacity(model_id="Qwen3.5-35B-A3B", tokens=65536, observed=False)
    )

    assert observed.preset_id == "qwen-35b-extended"
    assert observed.input_token_limit == 65536
    assert observed.parallel_read_limit > 1
    assert unobserved.preset_id == "qwen-9b-restrictive"


def test_requested_context_is_not_silently_capped_by_factory_when_unobserved():
    resolved = resolve_execution_preset(
        _capacity(tokens=None, observed=False),
        operator={"input_tokens": 32768},
    )

    assert resolved.input_token_limit == 32768


def test_observed_context_narrows_larger_requested_context():
    resolved = resolve_execution_preset(
        _capacity(tokens=16384),
        operator={"input_tokens": 32768},
    )

    assert resolved.input_token_limit == 16384


def test_observed_context_is_used_when_request_has_no_context_override():
    resolved = resolve_execution_preset(_capacity(tokens=32768))

    assert resolved.input_token_limit == 32768
    assert resolved.generation_reserve_tokens == 4096


def test_9b_uses_proven_window_instead_of_architecture_maximum():
    resolved = resolve_execution_preset(_capacity(tokens=262144))

    assert resolved.input_token_limit == 32768
    assert resolved.generation_reserve_tokens == 4096


def test_35b_with_small_observed_kv_stays_on_restrictive_limits():
    resolved = resolve_execution_preset(
        _capacity(model_id="Qwen3.5-35B-A3B", tokens=8192)
    )

    assert resolved.preset_id == "qwen-9b-restrictive"
    assert resolved.max_tools == 5
    assert resolved.max_batch_items == 5
    assert resolved.parallel_read_limit == 1


def test_operator_and_workflow_can_only_narrow_factory_limits():
    resolved = resolve_execution_preset(
        _capacity(model_id="Qwen3.5-35B-A3B", tokens=65536),
        operator={"input_tokens": 50000, "max_tools": 20, "reasoning_enabled": True},
        restrictions={"input_tokens": 12000, "max_tools": 2},
    )

    assert resolved.input_token_limit == 12000
    assert resolved.max_tools == 2
    assert resolved.normal_tool_count == 2
    assert resolved.reasoning_enabled is False
    assert resolved.source_chain[-1] == "workflow_profile_restrictions"


def test_preset_diagnostics_are_redacted_and_explain_effective_source():
    resolved = resolve_execution_preset(_capacity(tokens=8192))

    diagnostics = resolved.diagnostics(requested_input_tokens=35000)

    assert diagnostics["context_input_tokens"] == {
        "requested": 35000,
        "effective": resolved.input_token_limit,
        "source": "workflow_invariants > observed_backend_capacity > factory_preset",
        "restart_required": False,
    }
    assert "token" not in diagnostics
    assert "api_key" not in diagnostics
