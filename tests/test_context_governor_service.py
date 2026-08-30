import json

import pytest

from proxy.services.context_governor_service import (
    ContextCandidate,
    ContextGovernor,
    ContextKind,
    ContextObject,
    ContextRequiredSectionOverflow,
)
from proxy.services.model_execution_preset_service import ModelExecutionPreset


def _preset(*, limit: int = 1000, generation: int = 200, safety: int = 100):
    return ModelExecutionPreset(
        preset_id="test-preset",
        model_family="test",
        input_token_limit=limit,
        generation_reserve_tokens=generation,
        safety_reserve_tokens=safety,
        normal_tool_count=3,
        max_tools=5,
        max_batch_items=5,
        parallel_read_limit=1,
        reasoning_enabled=False,
        source_chain=("workflow_invariants", "factory_preset"),
    )


def _candidate(kind: ContextKind, object_id: str, payload, *, required: bool = False):
    return ContextCandidate(
        kind=kind,
        objects=(ContextObject(object_id=object_id, payload=payload),),
        required=required,
    )


def test_governor_reserves_generation_before_evidence():
    governor = ContextGovernor(_preset(), estimate_tokens=len)
    packet = governor.pack(
        [
            _candidate(ContextKind.EVIDENCE, "ev-1", "evidence"),
            _candidate(ContextKind.PROFILE_PREFIX, "profile", "profile", required=True),
        ]
    )

    assert packet.input_budget_tokens == 700
    assert packet.sections[0].kind == ContextKind.PROFILE_PREFIX


def test_governor_never_cuts_json_objects():
    payload = {"id": "a", "text": "x" * 800}
    governor = ContextGovernor(_preset(limit=300, generation=0, safety=0), estimate_tokens=len)

    packet = governor.pack([_candidate(ContextKind.EVIDENCE, "a", payload)])

    assert packet.sections == ()
    assert packet.omissions[0].object_ids == ("a",)
    assert packet.omissions[0].cursor.startswith("ctx:evidence:")
    assert packet.omissions[0].omitted == 1
    assert json.loads(json.dumps(payload)) == payload


def test_packing_priority_matches_canonical_spec():
    order = [
        ContextKind.PROFILE_PREFIX,
        ContextKind.TOOL_SHORTLIST,
        ContextKind.REQUEST,
        ContextKind.EVIDENCE,
        ContextKind.SOURCE_MAP,
        ContextKind.TOOL_EXCHANGE,
        ContextKind.CHECKPOINT,
        ContextKind.WORKING_MEMORY,
        ContextKind.DIALOGUE,
    ]
    shuffled = [
        _candidate(kind, kind.value, kind.value, required=kind == ContextKind.REQUEST)
        for kind in reversed(order)
    ]

    packet = ContextGovernor(
        _preset(limit=10000, generation=0, safety=0), estimate_tokens=len
    ).pack(shuffled)

    assert [section.kind for section in packet.sections] == order


def test_evidence_is_kept_before_working_memory_when_budget_is_tight():
    governor = ContextGovernor(
        _preset(limit=23, generation=5, safety=3), estimate_tokens=len
    )

    packet = governor.pack(
        [
            _candidate(ContextKind.REQUEST, "request", "ask", required=True),
            _candidate(ContextKind.WORKING_MEMORY, "memory", "remember"),
            _candidate(ContextKind.EVIDENCE, "evidence", "document"),
        ]
    )

    assert [section.kind for section in packet.sections] == [
        ContextKind.REQUEST,
        ContextKind.EVIDENCE,
    ]
    assert packet.input_budget_tokens == 15
    assert packet.omissions[0].object_ids == ("memory",)


def test_required_overflow_is_typed_and_happens_before_partial_packet():
    governor = ContextGovernor(_preset(limit=20, generation=5, safety=5), estimate_tokens=len)

    with pytest.raises(ContextRequiredSectionOverflow) as error:
        governor.pack(
            [_candidate(ContextKind.REQUEST, "request", "question-too-large", required=True)]
        )

    assert error.value.code == "CONTEXT_REQUIRED_SECTION_OVERFLOW"
    assert error.value.object_ids == ("request",)


def test_required_sections_reserve_space_before_earlier_optional_priority():
    governor = ContextGovernor(_preset(limit=10, generation=0, safety=0), estimate_tokens=len)

    packet = governor.pack(
        [
            _candidate(ContextKind.PROFILE_PREFIX, "optional-profile", "123456"),
            _candidate(ContextKind.REQUEST, "request", "abcdef", required=True),
        ]
    )

    assert [section.kind for section in packet.sections] == [ContextKind.REQUEST]
    assert packet.sections[0].object_ids == ("request",)
    assert packet.omissions[0].object_ids == ("optional-profile",)


def test_partial_candidate_keeps_complete_objects_and_omits_the_rest():
    governor = ContextGovernor(_preset(limit=12, generation=0, safety=0), estimate_tokens=len)
    candidate = ContextCandidate(
        kind=ContextKind.EVIDENCE,
        objects=(
            ContextObject(object_id="a", payload="12345"),
            ContextObject(object_id="b", payload="67890"),
            ContextObject(object_id="c", payload="too-large"),
        ),
    )

    packet = governor.pack([candidate])

    assert packet.sections[0].object_ids == ("a", "b")
    assert packet.omissions[0].object_ids == ("c",)
    assert packet.omissions[0].total == 3


def test_rendered_message_content_stays_within_governed_budget():
    governor = ContextGovernor(_preset(limit=12, generation=0, safety=0), estimate_tokens=len)
    packet = governor.pack(
        [
            _candidate(ContextKind.TOOL_SHORTLIST, "tool", "12345"),
            _candidate(ContextKind.REQUEST, "request", "abcde", required=True),
        ]
    )

    rendered_chars = sum(len(message["content"]) for message in packet.as_messages())
    assert rendered_chars <= packet.input_budget_tokens
