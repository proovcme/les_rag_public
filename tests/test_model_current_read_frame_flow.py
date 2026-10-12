"""Actual B0/B1 native reads keep current literal evidence after completed history."""
import copy
import json

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.smeta_core import norm_browser
from test_chat_model_source_frame import _frames, _run_frame
from test_model_rag_sheet_evidence_reads import RESOURCE_A, RESOURCE_B, _native, _shown_full_resource


OPAQUE_REASONING = "SYNTHETIC_OPAQUE_NATIVE_REASONING_Ж_Ω"
LITERAL_CARD_TABLE = "| Узел Ω | Размер, м |\n| --- | --- |\n| Линия Ж | 12,25 |"


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_actual_current_cards_follow_completed_native_history_without_rewriting(
        tmp_path, monkeypatch, variant):
    original = service.run_chat_evidence_application
    originals = {}

    async def capture_literal_inputs(request, runtime, boundary):
        request.req.question += '\nДополнение инженера: «Линия Ω / секция Ж», проверять буквально.'
        originals["question"] = request.req.question
        originals["profile"] = copy.deepcopy(request.profile_snapshot)
        source_reader = norm_browser.read_norm_card_exact

        def unicode_card(**pointer):
            result = copy.deepcopy(source_reader(**pointer))
            result["card"]["work_steps"].append(LITERAL_CARD_TABLE)
            return result

        monkeypatch.setattr(norm_browser, "read_norm_card_exact", unicode_card)
        return await original(request, runtime, boundary)

    monkeypatch.setattr(service, "run_chat_evidence_application", capture_literal_inputs)
    run = await _run_frame(tmp_path, monkeypatch, cap=2, reads=True, variant=variant,
                           reasoning_enabled=True, query_reasoning_enabled=False,
                           native_reasoning=OPAQUE_REASONING, temperature=0.7)

    # One query, initial answer and two model-authored READ batches; no added turn.
    assert len(run.requests) == 4 and not run.responses
    assert run.queries[:len(run.declared_queries)] == run.declared_queries
    assert len(run.exact_reads) == 1 and len(run.executions) == 1
    assert run.request.profile_snapshot == originals["profile"]
    assert run.requests[0].reasoning_enabled is False
    assert all(request.reasoning_enabled is True for request in run.requests[1:])
    assert run.requests[0].max_output_tokens == 1600
    assert {request.max_output_tokens for request in run.requests[1:]} == {8192}
    assert {request.temperature for request in run.requests} == {0.7}
    assert all(request.tools == run.requests[1].tools and request.tools
               for request in run.requests[2:])
    assert not run.requests[0].tools

    final = run.requests[-1]
    messages = list(final.messages)
    native_history = [message for message in messages if message["role"] in {"assistant", "tool"}]
    assert [message["role"] for message in native_history] == ["assistant", "tool", "assistant", "tool", "tool"]
    expected_calls = [_native("read_norm_card", norm_key="immutable-norm"),
                      _native("read_resource_price", code=RESOURCE_A),
                      _native("read_resource_price", code=RESOURCE_B)]
    actual_calls = [call for message in native_history for call in message.get("tool_calls", ())]
    assert actual_calls == expected_calls
    replies = [message for message in native_history if message["role"] == "tool"]
    assert [message["tool_call_id"] for message in replies] == [call["id"] for call in expected_calls]
    assert [message["reasoning_content"] for message in native_history if message["role"] == "assistant"] == [
        OPAQUE_REASONING, OPAQUE_REASONING]
    prior_native = [message for message in run.requests[-2].messages
                    if message["role"] in {"assistant", "tool"}]
    assert native_history[:len(prior_native)] == prior_native
    assert originals["profile"]["prompt_text"] in messages[0]["content"]
    assert originals["question"] in messages[1]["content"]
    assert messages[0]["role"] == "system" and messages[1]["role"] == "user"

    # Source hashes, literal rows and data are unchanged across all wire requests.
    source_frames = [_frames(request) for request in run.requests]
    assert all(len(frames) == 1 for frames in source_frames)
    assert all(frames == source_frames[0] for frames in source_frames[1:])
    assert source_frames[0][0]["requested_source_rows"] == ["S!R2", "S!R3"]
    call, workbook = run.executions[0]
    assert call["tool"] == "build_lsr_workbook"
    assert [(row["source_row"], row["resource_code"], row["quantity"]) for row in call["args"]["decisions"]] == [
        ("S!R2", RESOURCE_A, 12), ("S!R3", RESOURCE_B, 3)]
    assert workbook["confirmed_amount"] == 1800 and workbook["preliminary_amount"] == 0

    # This intentional semantic transition changes provider last-user selection;
    # canonical native history is immutable, but tokenizer rendering is not
    # asserted to be byte-identical to the old ordering.
    assert messages[-1]["role"] == "user", "current evidence must follow the completed tool history"
    assert messages[-2]["role"] == "tool"
    assert not any("previously_shown_evidence_registry" in message.get("content", "")
                   for message in messages[:-1])
    registries = []
    for line in messages[-1]["content"].splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            registries.extend(value.get("previously_shown_evidence_registry", ()))
    full_card = [item["content"] for item in registries if "fixture-resource-21" in item.get("content", "")]
    assert len(full_card) == 1 and LITERAL_CARD_TABLE in full_card[0]
    # The JSONL and columns/records carriers must expose the same complete,
    # ordered resource list. Metadata alone cannot satisfy the body proof.
    shown_resources = [_shown_full_resource(run, full_card[0], slot)
                       for slot in range(1, len(run.exact_resources) + 1)]
    assert json.dumps(shown_resources, ensure_ascii=False, sort_keys=True) == json.dumps(
        run.exact_resources, ensure_ascii=False, sort_keys=True)
    assert shown_resources[21]["per_unit"] == 21.25
    assert "resources_complete=True" in full_card[0]
    assert sum(message.get("content", "").count("fixture-resource-21") for message in messages) == 1

    trace = run.result["retrieval_trace"]["context_governor"]["calls"]
    assert all(section["kind"] != "current_read_frame" for entry in trace[:2] for section in entry["sections"])
    continuation = [entry for entry in trace if any(section["kind"] == "current_read_frame"
                    for section in entry["sections"])]
    assert len(continuation) == 2
    assert len({entry["input_budget_tokens"] for entry in continuation}) == 1
    assert all(entry["generation_reserve_tokens"] == final.max_output_tokens for entry in continuation)
    assert len({entry["safety_reserve_tokens"] for entry in continuation}) == 1
    assert run.connection.effective_preset.input_token_limit == 100_000
    assert all(entry["included_tokens"] <= entry["input_budget_tokens"] for entry in continuation)
    public = json.dumps(continuation, ensure_ascii=False)
    assert "fixture-resource-21" in public and "Линия Ж" in public
    assert OPAQUE_REASONING not in public
