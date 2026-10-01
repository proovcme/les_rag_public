import pytest

from proxy.services.model_execution_preset_service import (
    BackendCapacity,
    apply_output_budget_policy,
    model_rag_answer_execution_preset,
    query_generation_budget,
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
    assert resolved.diagnostics()["reasoning"]["requested"] is True
    assert resolved.diagnostics()["reasoning"]["source"] == "unsupported_by_transport"
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


@pytest.mark.parametrize("model_id,tokens,query_default,answer_default", [
    ("qwen3.5:9b", 8192, 1200, 1200),
    ("qwen3.5:9b", 32768, 4096, 8192),
    ("Qwen3.6-35B", 65536, 4096, 8192),
])
def test_omitted_purpose_budgets_preserve_query_and_answer_defaults(
    model_id, tokens, query_default, answer_default,
):
    preset = resolve_execution_preset(_capacity(model_id=model_id, tokens=tokens))
    assert preset.generation_reserve_tokens == query_default
    answer = model_rag_answer_execution_preset(preset, model_rag=True)
    assert answer.generation_reserve_tokens == answer_default
    ordinary_answer = model_rag_answer_execution_preset(preset, model_rag=False)
    assert ordinary_answer.generation_reserve_tokens == query_default
    assert ordinary_answer.source_chain == preset.source_chain
    assert preset.diagnostics()["query_output_tokens"]["requested"] is None
    assert answer.diagnostics()["answer_output_tokens"]["requested"] is None


@pytest.mark.parametrize("policy,expected_query,expected_answer", [
    ({"query_output_tokens": 16000}, 16000, 8192),
    ({"answer_output_tokens": 24000}, 4096, 24000),
    ({"query_output_tokens": 16000, "answer_output_tokens": 24000}, 16000, 24000),
    ({"query_output_tokens": 700, "answer_output_tokens": 900}, 700, 900),
])
def test_explicit_purpose_budgets_are_independent_and_do_not_change_capacity(
    policy, expected_query, expected_answer,
):
    base = resolve_execution_preset(_capacity(model_id="Qwen3.6-35B", tokens=65536))
    preset = apply_output_budget_policy(base, policy)
    answer = model_rag_answer_execution_preset(preset, model_rag=True)
    assert preset.generation_reserve_tokens == expected_query
    assert answer.generation_reserve_tokens == expected_answer
    for value in (preset, answer):
        assert value.input_token_limit == base.input_token_limit == 65536
        assert value.safety_reserve_tokens == base.safety_reserve_tokens
        assert value.reasoning_enabled == base.reasoning_enabled
        assert value.max_tools == base.max_tools
    assert apply_output_budget_policy(preset, policy) == preset
    assert query_generation_budget(preset, reserved_tokens=expected_query)["effective"] == (
        expected_query if "query_output_tokens" in policy else 1600
    )


@pytest.mark.parametrize("field", ["query_output_tokens", "answer_output_tokens"])
@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, "4096", None, {}])
def test_invalid_profile_output_budget_is_rejected_without_coercion(field, value):
    with pytest.raises(ValueError, match=field + ":"):
        resolve_execution_preset(_capacity(), operator={field: value})


def test_observed_output_budget_respects_narrowed_window_safety_and_input_headroom():
    preset = resolve_execution_preset(
        _capacity(model_id="Qwen3.6-35B", tokens=65536),
        operator={"input_tokens": 35000, "query_output_tokens": 65536,
                  "answer_output_tokens": 65536},
        restrictions={"input_tokens": 12000},
    )
    answer = model_rag_answer_execution_preset(preset, model_rag=True)
    expected = 12000 - preset.safety_reserve_tokens - 1024
    assert preset.input_token_limit == 12000
    assert preset.generation_reserve_tokens == answer.generation_reserve_tokens == expected
    for field in ("query_output_tokens", "answer_output_tokens"):
        diagnostic = answer.diagnostics()[field]
        assert diagnostic["requested"] == 65536 and diagnostic["effective"] == expected
        assert "effective_context_window" in diagnostic["source"]
        assert diagnostic["restart_required"] is False


def test_unobserved_capacity_cannot_widen_unproven_purpose_defaults():
    preset = resolve_execution_preset(
        _capacity(model_id="Qwen3.6-35B", tokens=None, observed=False),
        operator={"input_tokens": 65536, "query_output_tokens": 16000,
                  "answer_output_tokens": 24000},
    )
    answer = model_rag_answer_execution_preset(preset, model_rag=True)
    assert preset.input_token_limit == 65536
    assert preset.generation_reserve_tokens == 1200
    assert answer.generation_reserve_tokens == 8192
    for field in ("query_output_tokens", "answer_output_tokens"):
        assert "unobserved_capacity_default" in answer.diagnostics()[field]["source"]


def test_low_observed_kv_clamps_explicit_output_and_preserves_positive_input():
    preset = resolve_execution_preset(
        _capacity(model_id="Qwen3.6-35B", tokens=2048),
        operator={"query_output_tokens": 16000, "answer_output_tokens": 24000},
    )
    answer = model_rag_answer_execution_preset(preset, model_rag=True)
    assert preset.generation_reserve_tokens == answer.generation_reserve_tokens == 512
    assert preset.input_token_limit - preset.safety_reserve_tokens - preset.generation_reserve_tokens == 1024


def test_explicit_output_budget_fails_clearly_when_window_has_no_input_headroom():
    with pytest.raises(ValueError, match="Недостаточно контекста"):
        resolve_execution_preset(_capacity(tokens=1024), operator={"query_output_tokens": 1})
