"""The ordinary tools-off answer gets a governed final user phase boundary."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import time
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services.context_governor_service import (
    ContextCandidate, ContextGovernor, ContextKind, ContextObject, ContextRequiredSectionOverflow,
    NativeToolCall, NativeToolExchange, NativeToolReply,
)
from proxy.services.model_execution_preset_service import ModelExecutionPreset
from proxy.services.openai_compatible_transport_service import InferenceResponse
from proxy.services.tool_harness_service import ToolHarness
from proxy.services.web_research_config_service import WebResearchConfig
from tests.test_chat_ordinary_native_continuation import _call, _ordinary, _payload
from test_chat_evidence_application_service import (
    test_actual_chat_shadow_failure_preserves_legacy_answer_history_and_model_count as _run_actual_chat,
)


async def _initial_closed(monkeypatch, tmp_path, stop_reason, *, unfinished=False):
    from proxy.services import tool_harness_service
    clock = SimpleNamespace(now=100.0)
    captures, executions = {}, []
    broker = ToolHarness(web_config=WebResearchConfig("extended", "http://127.0.0.1:8888", "", ""))
    first = _call("first-read", arguments='{ "q" : "literal original query" }')
    repeat = _call("cached-new-id", arguments='{  "q": "literal original query"  }')
    content = ("<tool_call>\n<function=web_search>\n<parameter=q>\nliteral original query\n"
               "</parameter>\n</function>\n</tool_call>" if unfinished else "Model-owned final answer with the remaining unknowns.")
    responses = [InferenceResponse(text="", tool_calls=(first,), reasoning_content="SYNTHETIC_NATIVE_REASONING_A",
                                   finish_reason="tool_calls", usage={})]
    if stop_reason == "repeated_read_batch":
        responses.append(InferenceResponse(text="", tool_calls=(repeat,), reasoning_content="SYNTHETIC_NATIVE_REASONING_B",
                                           finish_reason="tool_calls", usage={}))
    responses.append(InferenceResponse(text=content, tool_calls=(), finish_reason="stop", usage={}))

    class Harness:
        def shortlist(self, *args, **kwargs):
            return broker.shortlist(*args, **kwargs)
        def call(self, tool, args):
            executions.append((tool, deepcopy(args)))
            return _payload(tool, args)

    async def setup(request, runtime, boundary):
        monkeypatch.setattr(service, "time", SimpleNamespace(monotonic=lambda: clock.now, time=time.time))
        previous_env = runtime.env_int
        runtime = replace(runtime, env_int=lambda key, default=0: (1 if stop_reason == "calls_budget" else 4)
                          if key == "LES_CHAT_TOOL_MAX_CALLS" else previous_env(key, default))
        monkeypatch.setattr(tool_harness_service, "harness", lambda **kwargs: Harness())
        transport = runtime.model_connection_transport(None, None)
        transport.responses = responses
        complete = transport.complete
        async def wrapped(connection, inference_request):
            response = await complete(connection, inference_request)
            if stop_reason == "deadline" and len(transport.requests) == 1:
                clock.now = 1000.0
            return response
        monkeypatch.setattr(transport, "complete", wrapped)
        captures["transport"] = transport
        captures["profile"] = deepcopy(request.profile_snapshot)
        captures["result"] = await service.run_chat_evidence_application(request, runtime, boundary)
    await _run_actual_chat(monkeypatch, tmp_path, "active_web_research", application_setup=setup)
    return SimpleNamespace(**captures, executions=executions, first=first, repeat=repeat, final_content=content)


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_reason", ["repeated_read_batch", "calls_budget", "deadline"])
async def test_initial_closed_answer_has_required_user_boundary_after_the_whole_native_history(monkeypatch, tmp_path, stop_reason):
    run = await _initial_closed(monkeypatch, tmp_path, stop_reason)
    final = run.transport.requests[-1]
    messages = list(final.messages)
    assert not final.tools and messages[-1]["role"] == "user"
    assert messages[-2]["role"] == "tool"
    boundary = messages[-1]["content"]
    assert '"response_kind": "user_answer"' in boundary
    assert '"read_closed": true' in boundary and f'"stop_reason": "{stop_reason}"' in boundary
    assert '"history_tool_calls": "completed"' in boundary
    assert run.profile["prompt_text"] in messages[0]["content"]
    assert '"read_closed": true' not in messages[0]["content"], "phase state belongs after the completed history"
    calls = [run.first, run.repeat] if stop_reason == "repeated_read_batch" else [run.first]
    assert [call for message in messages for call in message.get("tool_calls", ())] == calls
    replies = [message for message in messages if message["role"] == "tool"]
    assert [reply["tool_call_id"] for reply in replies] == [call["id"] for call in calls]
    assert all("_WHOLE_BODY_END" in reply["content"] for reply in replies) if stop_reason != "deadline" else (
        json.loads(replies[0]["content"])["result"]["executed"] is False)
    assert [message["reasoning_content"] for message in messages if message["role"] == "assistant"] == (
        ["SYNTHETIC_NATIVE_REASONING_A", "SYNTHETIC_NATIVE_REASONING_B"] if len(calls) == 2 else ["SYNTHETIC_NATIVE_REASONING_A"])
    # These canonical history values are preserved. The intentional new user turn
    # can change a provider template's last-user/reasoning selection; it is not a
    # promise that the rendered prompt is byte-identical to the previous phase.
    assert len(run.transport.requests) == (3 if len(calls) == 2 else 2)
    assert len(run.executions) == (0 if stop_reason == "deadline" else 1)
    assert len(set(run.transport.revisions)) == 1
    assert run.result["answer"] == run.final_content
    packet = run.result["retrieval_trace"]["context_governor"]["calls"][-1]
    section = next(item for item in packet["sections"] if item["kind"] == "terminal_request")
    assert section["object_ids"] == ["request:terminal-phase"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_reason", ["repeated_read_batch", "calls_budget", "deadline"])
async def test_late_read_closure_adds_boundary_only_to_the_existing_tools_off_final(monkeypatch, tmp_path, stop_reason):
    calls = [_call("late-repeat", arguments='{ "q": "original query" }')] if stop_reason == "repeated_read_batch" else [_call("late-one")]
    if stop_reason == "calls_budget":
        calls.append(_call("late-two", arguments='{"q":"second late read"}'))
    run = await _ordinary(monkeypatch, tmp_path, late_calls=calls, max_calls=3,
                          expire_after_answer=stop_reason == "deadline")
    opened, final = run.transport.requests[2:]
    assert opened.tools and not final.tools and len(run.transport.requests) == 4
    assert opened.messages[-1]["role"] == "tool"
    assert final.messages[-1]["role"] == "user" and final.messages[-2]["role"] == "tool"
    assert f'"stop_reason": "{stop_reason}"' in final.messages[-1]["content"]
    assert '"read_closed": true' not in json.dumps(list(opened.messages))
    assert final.temperature == opened.temperature and final.max_output_tokens == opened.max_output_tokens
    opened_history = [message for message in opened.messages if message["role"] in ("assistant", "tool")]
    final_history = [message for message in final.messages if message["role"] in ("assistant", "tool")]
    assert final_history[:len(opened_history)] == opened_history
    replies = [message for message in final.messages if message["role"] == "tool"]
    assert [reply["tool_call_id"] for reply in replies] == ["original-read", *[call["id"] for call in calls]]
    assert run.result["answer"] == "Verified answer from the original and additional sources."


@pytest.mark.asyncio
async def test_terminal_xml_remains_visible_failure_without_execution_retry_or_fake_answer(monkeypatch, tmp_path):
    run = await _initial_closed(monkeypatch, tmp_path, "repeated_read_batch", unfinished=True)
    assert len(run.transport.requests) == 3 and len(run.executions) == 1
    assert run.result["crag_status"] == "MODEL_OUTPUT_INCOMPLETE"
    generation = run.result["retrieval_trace"]["model_generation"]
    assert generation["terminal_output"] == run.final_content
    assert generation["terminal_output_sha256"] == hashlib.sha256(run.final_content.encode()).hexdigest()
    assert generation["unconsumed_tool_calls"] == 0 and generation["unparsed_tool_frame"] is True


def _context():
    preset = ModelExecutionPreset("final-phase", "test", 1000, 200, 100, 1, 5, 6, 1, False, ("test",))
    exchange = NativeToolExchange((NativeToolCall("id-1", "read_source", '{ "ref": "Q1.H1" }'),),
        (NativeToolReply("id-1", "read_source", "COMPLETE_SOURCE_LITERAL"),), reasoning_content="SYNTHETIC_REASONING")
    return preset, exchange


def test_optional_boundary_default_keeps_legacy_governed_frame_byte_identical():
    preset, exchange = _context()
    options = dict(preset=preset, profile_prefix="Literal profile", request_payload="Literal original question",
                   native_exchanges=(exchange,), required_evidence=("Literal evidence",))
    legacy, _ = service.govern_inference_messages(**options)
    absent, _ = service.govern_inference_messages(**options, terminal_instruction=None)
    assert json.dumps(legacy, ensure_ascii=False) == json.dumps(absent, ensure_ascii=False)
    assert absent[:2] == [{"role": "system", "content": "Literal profile"},
                          {"role": "user", "content": "Literal original question\nLiteral evidence"}]
    assert absent[-2:] == exchange.as_messages()


def test_boundary_is_required_and_counted_in_the_actual_whole_wire_before_admission():
    preset, exchange = _context()
    probes = []
    def count(messages):
        probes.append(deepcopy(messages))
        return 701 if messages[-1].get("content") == "REQUIRED_PHASE_BOUNDARY" else 100
    with pytest.raises(ContextRequiredSectionOverflow) as error:
        service.govern_inference_messages(preset=preset, profile_prefix="profile", request_payload="question",
            native_exchanges=(exchange,), terminal_instruction="REQUIRED_PHASE_BOUNDARY",
            count_messages_tokens=count, token_count_source="synthetic-bound-counter")
    assert probes[-1][-1] == {"role": "user", "content": "REQUIRED_PHASE_BOUNDARY"}
    assert probes[-1][-3:-1] == exchange.as_messages()
    assert error.value.required_tokens == 701 and error.value.budget == 700
    assert "request:terminal-phase" in error.value.object_ids


@pytest.mark.parametrize("payload", [{"role": "system", "content": "untrusted"}, 17, ""])
def test_terminal_context_cannot_inject_roles_or_an_empty_optional_boundary(payload):
    preset, _exchange = _context()
    candidate = ContextCandidate(ContextKind.TERMINAL_REQUEST, (ContextObject("phase", payload),), True)
    with pytest.raises(ValueError, match="terminal request"):
        ContextGovernor(preset).pack([candidate])
