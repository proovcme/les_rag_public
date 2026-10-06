"""Initial ordinary READ admission uses the same deadline as continuations."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import time
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services.openai_compatible_transport_service import InferenceResponse
from proxy.services.tool_harness_service import ToolHarness
from proxy.services.web_research_config_service import WebResearchConfig
from tests.test_chat_ordinary_native_continuation import _call, _payload
from test_chat_evidence_application_service import (
    test_actual_chat_shadow_failure_preserves_legacy_answer_history_and_model_count as _run_actual_chat,
)


async def _initial_deadline_run(monkeypatch, tmp_path, *, expire_after_selector: bool):
    from proxy.services import tool_harness_service

    clock = SimpleNamespace(now=100.0)
    executions = []
    captures = {}
    broker = ToolHarness(web_config=WebResearchConfig("extended", "http://127.0.0.1:8888", "", ""))
    calls = [_call("initial-one", arguments='{ "q": "first literal query" }')]
    if not expire_after_selector:
        calls.append(_call("initial-two", arguments='{  "q" : "second literal query" }'))

    class Harness:
        def shortlist(self, *args, **kwargs):
            return broker.shortlist(*args, **kwargs)

        def call(self, tool, args):
            executions.append((tool, deepcopy(args), clock.now))
            if not expire_after_selector and len(executions) == 1:
                clock.now = 1000.0
            return _payload(tool, args)

    async def setup(request, runtime, boundary):
        monkeypatch.setattr(service, "time", SimpleNamespace(monotonic=lambda: clock.now, time=time.time))
        original_env_int = runtime.env_int
        runtime = replace(runtime, env_int=lambda key, default=0: 3
                          if key == "LES_CHAT_TOOL_MAX_CALLS" else original_env_int(key, default))
        monkeypatch.setattr(tool_harness_service, "harness", lambda **kwargs: Harness())
        transport = runtime.model_connection_transport(None, None)
        transport.responses = [
            InferenceResponse(text="", tool_calls=tuple(calls), finish_reason="tool_calls", usage={}),
            InferenceResponse(text="Final answer with the retained evidence and explicit gaps.",
                              tool_calls=(), finish_reason="stop", usage={}),
        ]
        original_complete = transport.complete

        async def complete(connection, inference_request):
            response = await original_complete(connection, inference_request)
            if expire_after_selector and len(transport.requests) == 1:
                clock.now = 1000.0
            return response

        monkeypatch.setattr(transport, "complete", complete)
        captures["transport"] = transport
        captures["result"] = await service.run_chat_evidence_application(request, runtime, boundary)

    await _run_actual_chat(monkeypatch, tmp_path, "active_web_research", application_setup=setup)
    return SimpleNamespace(**captures, executions=executions, calls=calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("expire_after_selector", [True, False],
                         ids=["selector-exhausts-window", "first-read-exhausts-window"])
async def test_initial_read_batch_never_starts_a_read_after_original_deadline(
    monkeypatch, tmp_path, expire_after_selector
):
    run = await _initial_deadline_run(monkeypatch, tmp_path, expire_after_selector=expire_after_selector)
    expected_executed = 0 if expire_after_selector else 1
    assert len(run.executions) == expected_executed, "an expired READ must not call the executor or cache"
    assert all(start_clock == 100.0 for _tool, _args, start_clock in run.executions)
    assert len(run.transport.requests) == 2, "one selector and one tools-off final render; no retry loop"
    assert not run.transport.requests[-1].tools
    assert len(set(run.transport.revisions)) == 1
    loop = run.result["retrieval_trace"]["tool_loop"]
    assert loop["deadline_seconds"] == 120.0
    assert loop["stop_reason"] == "deadline"
    assert loop["calls_remaining"] == 3 - len(run.calls)
    assert len(loop["selected_calls"]) == expected_executed
    first_round = loop["rounds"][0]
    assert first_round["executed"] == expected_executed
    assert first_round["blocked"] == 1

    messages = run.transport.requests[-1].messages
    frame = next(message for message in messages if message.get("tool_calls"))
    assert frame["tool_calls"] == run.calls
    replies = [message for message in messages if message["role"] == "tool"]
    assert [message["tool_call_id"] for message in replies] == [call["id"] for call in run.calls]
    blocked = json.loads(replies[-1]["content"])
    assert blocked["status"] == "blocked"
    assert blocked["result"] == {"code": "ORDINARY_RESEARCH_DEADLINE", "executed": False,
                                 "expired_read_window": True}
    assert blocked["sources"] == []
    assert run.result["answer"] == "Final answer with the retained evidence and explicit gaps."
    assert run.result["model_connection"]["pending_tool_calls"] == 0


@pytest.mark.asyncio
async def test_expired_native_read_does_not_block_workbook_write_or_overstate_execution(monkeypatch, tmp_path):
    from proxy.services import tool_harness_service

    clock = SimpleNamespace(now=100.0)
    read_executions, write_executions, exchanges = [], [], []
    captures = {}
    broker = ToolHarness(web_config=WebResearchConfig("extended", "http://127.0.0.1:8888", "", ""))
    calls = [
        _call("expired-read", arguments='{  "q" : "literal read before packaging" }'),
        _call("allowed-write", name="build_vor_workbook",
              arguments='{ "attachment_id" : "read_123456abcdef" }'),
    ]

    class Harness:
        def shortlist(self, *args, **kwargs):
            return broker.shortlist(*args, **kwargs)

        def call(self, tool, args):
            read_executions.append((tool, deepcopy(args), clock.now))
            return _payload(tool, args)

    async def setup(request, runtime, boundary):
        monkeypatch.setattr(service, "time", SimpleNamespace(monotonic=lambda: clock.now, time=time.time))
        original_env_int = runtime.env_int
        original_write = runtime.workbook_tool_executor
        assert original_write is not None, "the WRITE must be supplied by the existing runtime executor"

        async def write(call, context, progress):
            write_executions.append((deepcopy(call), clock.now))
            return await original_write(call, context, progress)

        runtime = replace(runtime, workbook_tool_executor=write,
                          env_int=lambda key, default=0: 3 if key == "LES_CHAT_TOOL_MAX_CALLS"
                          else original_env_int(key, default))
        request.req.mode = "agent"
        request = replace(request, profile_snapshot={**request.profile_snapshot, "mode": "agent",
                                                    "tools": ["web_search", "build_vor_workbook"]})
        monkeypatch.setattr(tool_harness_service, "harness", lambda **kwargs: Harness())
        transport = runtime.model_connection_transport(None, None)
        transport.responses = [
            InferenceResponse(text="", tool_calls=tuple(calls), finish_reason="tool_calls", usage={}),
            InferenceResponse(text="The existing workbook revision is ready.",
                              tool_calls=(), finish_reason="stop", usage={}),
        ]
        original_complete = transport.complete

        async def complete(connection, inference_request):
            response = await original_complete(connection, inference_request)
            if len(transport.requests) == 1:
                clock.now = 1000.0
            return response

        original_exchange = service.native_research_exchange

        def capture_exchange(*args, **kwargs):
            exchange = original_exchange(*args, **kwargs)
            exchanges.append(exchange)
            return exchange

        monkeypatch.setattr(transport, "complete", complete)
        monkeypatch.setattr(service, "native_research_exchange", capture_exchange)
        captures["transport"] = transport
        captures["result"] = await service.run_chat_evidence_application(request, runtime, boundary)

    await _run_actual_chat(monkeypatch, tmp_path, "active_workbook", application_setup=setup)
    assert read_executions == [], "expired READ must not reach its executor or cached evidence"
    assert len(write_executions) == 1
    assert write_executions[0][0]["tool"] == "build_vor_workbook"
    assert write_executions[0][1] == 1000.0, "the READ window does not gate workbook packaging"
    assert len(captures["transport"].requests) == 2, "one selector and one final rendering; no new research loop"
    assert len(set(captures["transport"].revisions)) == 1
    assert captures["result"]["artifact"]["revision_id"] == "rev-2"
    loop = captures["result"]["retrieval_trace"]["tool_loop"]
    assert loop["stop_reason"] == "workbook_complete"
    assert loop["calls_remaining"] == 1
    assert [call["tool"] for call in loop["selected_calls"]] == ["build_vor_workbook"]
    assert loop["rounds"][0]["admitted"] == 2
    assert loop["rounds"][0]["executed"] == 1
    assert loop["rounds"][0]["blocked"] == 1
    assert len(exchanges) == 1
    messages = exchanges[0].as_messages()
    assert messages[0]["tool_calls"] == calls
    replies = messages[1:]
    assert [reply["tool_call_id"] for reply in replies] == [call["id"] for call in calls]
    blocked, packaged = [json.loads(reply["content"]) for reply in replies]
    assert blocked["status"] == "blocked"
    assert blocked["result"] == {"code": "ORDINARY_RESEARCH_DEADLINE", "executed": False,
                                 "expired_read_window": True}
    assert blocked["sources"] == []
    assert packaged["status"] == "complete"
    assert packaged["artifact"]["revision_id"] == "rev-2"


@pytest.mark.asyncio
async def test_actual_call_ledger_includes_every_initial_selector_and_native_continuation(monkeypatch, tmp_path):
    from proxy.services import tool_harness_service

    captures, executions = {}, []
    broker = ToolHarness(web_config=WebResearchConfig("extended", "http://127.0.0.1:8888", "", ""))
    native_calls = [_call(f"selector-read-{number}", arguments=json.dumps({"q": f"literal query {number}"}))
                    for number in range(1, 4)]
    native_calls.append(_call("answer-read", arguments='{  "q" : "literal final read" }'))

    class Harness:
        def shortlist(self, *args, **kwargs):
            return broker.shortlist(*args, **kwargs)

        def call(self, tool, args):
            executions.append((tool, deepcopy(args)))
            return _payload(tool, args)

    async def setup(request, runtime, boundary):
        original_env_int = runtime.env_int
        runtime = replace(runtime, env_int=lambda key, default=0: 5
                          if key == "LES_CHAT_TOOL_MAX_CALLS" else original_env_int(key, default))
        monkeypatch.setattr(tool_harness_service, "harness", lambda **kwargs: Harness())
        transport = runtime.model_connection_transport(None, None)
        responses = [
            *[InferenceResponse(text="", tool_calls=(call,), finish_reason="tool_calls", usage={})
              for call in native_calls[:3]],
            InferenceResponse(text="The current evidence permits an answer.", tool_calls=(),
                              finish_reason="stop", usage={}),
            InferenceResponse(text="", tool_calls=(native_calls[3],), finish_reason="tool_calls", usage={}),
            InferenceResponse(text="Final answer from the original and additional sources.", tool_calls=(),
                              finish_reason="stop", usage={}),
        ]
        usages = []
        for number, response in enumerate(responses, 1):
            usage = {"prompt_tokens": 100 + number, "completion_tokens": 10 + number,
                     "total_tokens": 110 + 2 * number, "messages": "PRIVATE_USAGE_CONTENT"}
            if number == 2:
                usage["input_tokens"] = 0
            usages.append(usage)
            responses[number - 1] = replace(response, usage=usage,
                                            reasoning_content="PRIVATE_PROVIDER_REASONING")
        transport.responses = responses
        captures["transport"] = transport
        captures["usages"] = usages
        captures["result"] = await service.run_chat_evidence_application(request, runtime, boundary)

    await _run_actual_chat(monkeypatch, tmp_path, "active_web_research", application_setup=setup)
    requests = captures["transport"].requests
    trace = captures["result"]["retrieval_trace"]
    ledger = trace["actual_model_calls"]["calls"]
    assert len(requests) == len(ledger) == 6, "successful selectors belong to the full provider-call ledger"
    assert [call["purpose"] for call in ledger] == ["tool_decision"] * 4 + ["answer", "ordinary_evidence_read"]
    assert len(set(captures["transport"].revisions)) == 1
    selected_model = captures["result"]["model_connection"]["model_id"]
    for call, request, usage in zip(ledger, requests, captures["usages"]):
        assert call["provider_usage"] == {key: usage.get(key) for key in (
            "prompt_tokens", "input_tokens", "completion_tokens", "total_tokens")}
        assert call["completion_tokens"] == usage["completion_tokens"]
        frame = {"schema": "canonical_inference_request.v1", "model_id": selected_model,
                 "messages": list(request.messages), "max_output_tokens": request.max_output_tokens,
                 "temperature": request.temperature, "tools": list(request.tools),
                 "response_format": request.response_format, "reasoning_enabled": request.reasoning_enabled}
        expected_sha = hashlib.sha256(json.dumps(frame, ensure_ascii=False, sort_keys=True,
                                                separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        assert call["canonical_request_sha256"] == expected_sha
        assert call["canonical_request_source"] == "canonical_inference_request"
    assert sum(call["provider_usage"]["total_tokens"] for call in ledger) == sum(
        usage["total_tokens"] for usage in captures["usages"])
    assert "PRIVATE" not in json.dumps(ledger), "receipts must not retain raw messages or provider reasoning"
    assert len(executions) == 4
    assert trace["tool_loop"]["calls_remaining"] == 1
    assert trace["tool_loop"]["ordinary_read_counts"] == {
        "admitted": 1, "executed": 1, "replayed": 0, "blocked": 0}
    final_messages = requests[-1].messages
    returned_calls = [call for message in final_messages for call in message.get("tool_calls", ())]
    assert returned_calls == native_calls, "diagnostic append must not change provider call IDs or literal arguments"
    replies = [message for message in final_messages if message.get("role") == "tool"]
    assert [message["tool_call_id"] for message in replies] == [call["id"] for call in native_calls]
    assert captures["result"]["answer"] == "Final answer from the original and additional sources."
