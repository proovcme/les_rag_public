from proxy.services.capability_broker_service import BrokerRequest, CapabilityBroker
from proxy.services.context_governor_service import (
    ContextCandidate,
    ContextGovernor,
    ContextKind,
    ContextObject,
)
from proxy.services.model_execution_preset_service import (
    BackendCapacity,
    resolve_execution_preset,
)
from proxy.services.tool_registry_service import canonical_tool_registry
from proxy.services.typed_memory_projection_service import (
    MemoryLimits,
    project_memory_from_records,
)


_PROFILE_TOOLS = ("dataset_map", "search_sources", "read_source")


def _preset(*, model_id: str, context_tokens: int):
    return resolve_execution_preset(
        BackendCapacity(
            provider="openai-compatible",
            model_id=model_id,
            context_tokens=context_tokens,
            observed=True,
            source="test_runtime_probe",
        )
    )


def _shortlist_snapshot(preset_id: str) -> tuple[dict[str, object], ...]:
    registry = canonical_tool_registry()
    shortlist = CapabilityBroker(registry).shortlist(
        BrokerRequest(
            profile_tools=_PROFILE_TOOLS,
            dataset_ids=("dataset-1",),
            workflow_phase="research",
            model_preset=preset_id,
            runtime_available=frozenset(_PROFILE_TOOLS),
            calls_remaining=3,
            result_chars_remaining=20_000,
        )
    )
    return tuple(contract.public_payload() for contract in shortlist.contracts)


def _memory_projection():
    return project_memory_from_records(
        session_id="session-1",
        project_id=7,
        dataset_ids=("dataset-1",),
        chat_profile={"last_status": "working", "blockers": ["Нужен источник"]},
        dialogue=(
            {"turn_id": "turn-1", "question": "Что известно?", "answer": "Черновик"},
        ),
        notes=(
            {"id": 11, "project_id": 7, "text": "Проверить раздел АР"},
        ),
        traces=(),
        advisory_items=(),
        limits=MemoryLimits(),
    )


def _context_snapshot(
    preset,
) -> tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]:
    memory_candidates = _memory_projection().as_context_candidates()
    packet = ContextGovernor(preset).pack(
        [
            ContextCandidate(
                ContextKind.PROFILE_PREFIX,
                (ContextObject("profile", {"role": "professional"}),),
                required=True,
            ),
            ContextCandidate(
                ContextKind.TOOL_SHORTLIST,
                (ContextObject("tools", {"names": list(_PROFILE_TOOLS)}),),
            ),
            ContextCandidate(
                ContextKind.REQUEST,
                (ContextObject("request", {"question": "Проверь документ"}),),
                required=True,
            ),
            *memory_candidates,
        ]
    )
    return tuple(
        (
            section.kind.value,
            section.object_ids,
            tuple(item.render() for item in section.objects),
        )
        for section in packet.sections
    )


def _memory_snapshot():
    projection = _memory_projection()
    return tuple(item.as_payload() for item in projection.items)


def test_9b_and_35b_keep_the_same_workflow_contract() -> None:
    nine = _preset(model_id="qwen3.5:9b", context_tokens=8192)
    thirty_five = _preset(model_id="qwen3.5:35b", context_tokens=65536)

    assert nine.preset_id == "qwen-9b-restrictive"
    assert thirty_five.preset_id == "qwen-35b-extended"

    # These are the real model-visible contracts. Their schemas, effects and
    # approval requirements must not depend on model size.
    assert _shortlist_snapshot(nine.preset_id) == _shortlist_snapshot(
        thirty_five.preset_id
    )

    # A packet that fits the restrictive preset has the same semantic objects
    # and canonical order under the extended preset.
    assert _context_snapshot(nine) == _context_snapshot(thirty_five)

    # The same typed projection enters both governed packets as advisory state;
    # model capacity does not create another memory or turn it into evidence.
    memory = _memory_snapshot()
    assert memory
    assert {item["context_role"] for item in memory} == {"advisory_state"}
    assert {item["is_evidence"] for item in memory} == {False}


def test_9b_and_35b_differ_only_in_capacity_envelope() -> None:
    nine = _preset(model_id="qwen3.5:9b", context_tokens=8192)
    thirty_five = _preset(model_id="qwen3.5:35b", context_tokens=65536)

    assert thirty_five.input_token_limit > nine.input_token_limit
    assert thirty_five.max_tools > nine.max_tools
    assert thirty_five.max_batch_items > nine.max_batch_items
    assert thirty_five.parallel_read_limit > nine.parallel_read_limit
    assert nine.reasoning_enabled is thirty_five.reasoning_enabled is False
