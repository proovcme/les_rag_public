from dataclasses import FrozenInstanceError

import pytest

from proxy.services.tool_contract_service import (
    EffectClass,
    IdempotencyPolicy,
    ResultBudget,
    RetryPolicy,
    ToolContract,
)


def _contract(**overrides):
    values = {
        "name": "read_source",
        "version": "1.0.0",
        "title": "Read source",
        "category": "source",
        "summary": "Read bounded evidence",
        "input_schema": {"type": "object"},
        "result_schema": "les_tool_result_v1",
        "effect": EffectClass.READ,
        "scopes": ("dataset",),
        "timeout_seconds": 30,
        "retry": RetryPolicy.SAFE,
        "idempotency": IdempotencyPolicy.DERIVED,
        "result_budget": ResultBudget(max_chars=7000, max_items=20),
        "model_owned_fields": (),
        "provenance": "source_refs_required",
    }
    values.update(overrides)
    return ToolContract(**values)


def test_tool_contract_contains_execution_policy() -> None:
    payload = _contract().public_payload()

    assert payload["effect"] == "read"
    assert payload["retry"] == "safe"
    assert payload["idempotency"] == "derived"
    assert payload["result_budget"] == {"max_chars": 7000, "max_items": 20}
    assert payload["scopes"] == ["dataset"]


def test_tool_contract_is_immutable() -> None:
    contract = _contract()

    with pytest.raises(FrozenInstanceError):
        contract.name = "changed"


def test_tool_contract_deep_freezes_input_schema() -> None:
    contract = _contract(
        input_schema={"type": "object", "properties": {"doc_id": {"type": "string"}}}
    )

    with pytest.raises(TypeError):
        contract.input_schema["properties"]["doc_id"]["type"] = "integer"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"name": "Read Source"}, "tool name"),
        ({"version": "v1"}, "semantic version"),
        ({"timeout_seconds": 0}, "timeout"),
    ],
)
def test_tool_contract_rejects_invalid_policy(overrides, message) -> None:
    with pytest.raises(ValueError, match=message):
        _contract(**overrides)


def test_result_budget_rejects_non_positive_limits() -> None:
    with pytest.raises(ValueError, match="result budget"):
        ResultBudget(max_chars=0, max_items=20)
