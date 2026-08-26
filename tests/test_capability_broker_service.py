from proxy.services.capability_broker_service import (
    BrokerRequest,
    CapabilityBroker,
)
from proxy.services.tool_contract_service import (
    EffectClass,
    IdempotencyPolicy,
    ResultBudget,
    RetryPolicy,
    ToolContract,
)
from proxy.services.tool_registry_service import (
    Availability,
    ToolRegistration,
    ToolRegistry,
)


def _registration(name: str, effect: EffectClass, *, scopes=("dataset",), available=True):
    return ToolRegistration(
        contract=ToolContract(
            name=name,
            version="1.0.0",
            title=name,
            category="test",
            summary=f"Contract for {name}",
            input_schema={"type": "object"},
            result_schema="les_tool_result_v1",
            effect=effect,
            scopes=scopes,
            timeout_seconds=30,
            retry=RetryPolicy.SAFE if effect is EffectClass.READ else RetryPolicy.NEVER,
            idempotency=IdempotencyPolicy.DERIVED,
            result_budget=ResultBudget(max_chars=7000, max_items=20),
            model_owned_fields=(),
            provenance="source_refs_required",
        ),
        handler=lambda args: args,
        availability=lambda runtime: Availability(available, "available" if available else "offline"),
    )


def _registry() -> ToolRegistry:
    return ToolRegistry(
        [
            _registration("read_source", EffectClass.READ),
            _registration("build_lsr_workbook", EffectClass.DRAFT),
            _registration("delete_dataset", EffectClass.DESTRUCTIVE),
        ]
    )


def _request(**overrides) -> BrokerRequest:
    values = {
        "profile_tools": ("read_source", "build_lsr_workbook", "delete_dataset"),
        "dataset_ids": ("ds-1",),
        "workflow_phase": "research",
        "model_preset": "qwen-9b",
        "runtime_available": frozenset({"read_source", "build_lsr_workbook"}),
        "calls_remaining": 1,
        "result_chars_remaining": 7000,
    }
    values.update(overrides)
    return BrokerRequest(**values)


def test_broker_intersects_every_policy_dimension() -> None:
    result = CapabilityBroker(_registry()).shortlist(_request())

    assert result.names == ("read_source",)
    assert result.omitted_by_reason["phase"] == ("build_lsr_workbook",)
    assert result.omitted_by_reason["runtime"] == ("delete_dataset",)
    assert result.call_limit == 1
    assert result.result_chars_limit == 7000


def test_broker_preserves_profile_order_not_registry_order() -> None:
    request = _request(
        profile_tools=("build_lsr_workbook", "read_source"),
        workflow_phase="draft",
        runtime_available=frozenset({"read_source", "build_lsr_workbook"}),
        calls_remaining=2,
    )

    assert CapabilityBroker(_registry()).shortlist(request).names == (
        "build_lsr_workbook",
        "read_source",
    )


def test_broker_fails_closed_without_dataset_scope_or_budget() -> None:
    no_scope = CapabilityBroker(_registry()).shortlist(
        _request(profile_tools=("read_source",), dataset_ids=())
    )
    no_budget = CapabilityBroker(_registry()).shortlist(
        _request(profile_tools=("read_source",), calls_remaining=0)
    )

    assert no_scope.names == ()
    assert no_scope.omitted_by_reason["scope"] == ("read_source",)
    assert no_budget.names == ()
    assert no_budget.omitted_by_reason["calls_budget"] == ("read_source",)


def test_registration_availability_is_authoritative() -> None:
    registry = ToolRegistry([_registration("read_source", EffectClass.READ, available=False)])
    request = _request(profile_tools=("read_source",), runtime_available=frozenset({"read_source"}))

    result = CapabilityBroker(registry).shortlist(request)

    assert result.names == ()
    assert result.omitted_by_reason["runtime"] == ("read_source",)


def test_9b_and_35b_share_professional_tool_names() -> None:
    values = {
        "profile_tools": ("read_source", "build_lsr_workbook"),
        "workflow_phase": "draft",
        "runtime_available": frozenset({"read_source", "build_lsr_workbook"}),
        "calls_remaining": 2,
    }
    nine = CapabilityBroker(_registry()).shortlist(_request(model_preset="qwen-9b", **values))
    thirty_five = CapabilityBroker(_registry()).shortlist(
        _request(model_preset="qwen-35b", **values)
    )

    assert set(nine.names) == set(thirty_five.names)


def test_unknown_profile_tool_is_reported_not_silently_dropped() -> None:
    result = CapabilityBroker(_registry()).shortlist(
        _request(profile_tools=("missing_tool",))
    )

    assert result.names == ()
    assert result.omitted_by_reason["unknown"] == ("missing_tool",)
