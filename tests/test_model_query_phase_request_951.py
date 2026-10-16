"""A query call states its technical stage without rewriting the operator task."""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services.model_execution_preset_service import ModelExecutionPreset
from tests import test_model_query_repair_context as repair_fixture
from tests import test_model_rag_sheet_evidence_reads as sheet_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_actual_query_and_repair_request_state_same_phase_and_keep_all_source_objects(
    tmp_path, monkeypatch, variant,
):
    monkeypatch.setenv("LES_LSR_SYSTEM_CANDIDATE_QUERIES", "off")
    packets = []
    caller_payloads = []
    original = service.govern_inference_messages

    def capture(**kwargs):
        before = deepcopy(kwargs["request_payload"])
        result = original(**kwargs)
        assert kwargs["request_payload"] == before
        if isinstance(before, dict) and before.get("current_phase") == "search_queries":
            caller_payloads.append(before)
            packets.append(result[1])
        return result

    monkeypatch.setattr(service, "govern_inference_messages", capture)
    run = await sheet_fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
        query_repair=repair_fixture.FAULT,
        query_declaration=json.dumps({"artifact_kind": "lsr", "queries": repair_fixture.REPAIRED}))
    initial, repaired = [repair_fixture.request_data(request) for request in run.requests[:2]]
    assert initial["current_phase"] == repaired["current_phase"] == "search_queries"
    assert initial == {key: value for key, value in repaired.items() if key != "rejected_query_attempt"}
    assert initial["question"] == "Собери ЛСР; ВОР не создавай. Санкт-Петербург, 3 квартал 2026"
    assert initial["dataset_ids"] == ["selected"]
    assert "в одном из объявленных оформлений" in initial["technical_request"]
    assert '{"artifact_kind":"vor","queries":[]}' in initial["technical_request"]
    assert "Итоговые строки документа — на следующем этапе" in initial["technical_request"]
    assert repaired["rejected_query_attempt"]["assistant_visible_final"] == repair_fixture.FAULT
    assert caller_payloads == [initial, repaired]
    assert len(packets) == 2

    def source_objects(packet):
        # The existing B0 repair promotes shown optional objects to required
        # ones (evidence:N -> source-required:N). Their literal payload and
        # section kind, rather than that internal admission ID, must match.
        return [(section.kind, obj.render())
                for section in packet.sections
                if section.kind in (service.ContextKind.EVIDENCE, service.ContextKind.CURRENT_READ_FRAME,
                                    service.ContextKind.SOURCE_MAP)
                for obj in section.objects]

    assert source_objects(packets[0]) == source_objects(packets[1])
    assert source_objects(packets[0])
    assert not packets[0].omissions and not packets[1].omissions
    assert run.queries == repair_fixture.REPAIRED
    assert len(run.requests) == 3 and not run.responses, "there is no additional model cycle"
    assert '"current_phase"' not in str(run.requests[-1].messages), "answer requests retain their own contract"


def _preset():
    return ModelExecutionPreset(preset_id="query-stage", model_family="fixture",
        input_token_limit=10000, generation_reserve_tokens=1000, safety_reserve_tokens=100,
        normal_tool_count=1, max_tools=1, max_batch_items=1, parallel_read_limit=1,
        reasoning_enabled=False, source_chain=("fixture",))


@pytest.mark.parametrize("repair", [False, True])
def test_phase_metadata_is_render_only_and_does_not_mutate_caller_payload(repair):
    question = "Literal operator question Ω; source identifiers stay unchanged"
    payload = {"question": question, "dataset_ids": ["one", "two"], "operator_data": {"quantity": 0}}
    before = deepcopy(payload)
    rejected = service.model_query_repair_attempt_data(
        repair_fixture.FAULT, finish_reason="stop", parse_diagnostics={"accepted_count": 0}) if repair else None
    messages, packet = service.govern_model_query_messages(retrieval_trace={}, purpose="fixture-query",
        rejected_attempt=rejected, preset=_preset(), profile_prefix="Literal profile Ω",
        request_payload=payload, required_evidence=["Literal source Ω; quantity 0"])
    assert payload == before
    rendered = repair_fixture.request_data(type("Request", (), {"messages": messages})())
    assert rendered["question"] == question and rendered["dataset_ids"] == before["dataset_ids"]
    assert rendered["operator_data"] == {"quantity": 0}
    assert rendered["current_phase"] == "search_queries"
    assert ("rejected_query_attempt" in rendered) is repair
    assert messages[0] == {"role": "system", "content": "Literal profile Ω"}
    assert "Literal source Ω; quantity 0" in messages[-1]["content"]
    assert not packet.omissions


def test_required_phase_metadata_is_counted_and_never_displaces_required_source_to_fit():
    kwargs = {"retrieval_trace": {}, "purpose": "fixture-query", "preset": _preset(),
        "profile_prefix": "Literal profile Ω", "request_payload": {"question": "Original operator task Ω"},
        "required_evidence": ["Literal source Ω; quantity 0"]}
    _, packet = service.govern_model_query_messages(**kwargs)
    tight_limit = packet.included_tokens + packet.generation_reserve_tokens + packet.safety_reserve_tokens - 1
    with pytest.raises(service.ContextRequiredSectionOverflow):
        service.govern_model_query_messages(**{**kwargs, "preset": replace(_preset(), input_token_limit=tight_limit)})
