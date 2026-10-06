"""An ordinary answer continues its existing native READ producer state."""

from copy import deepcopy
from dataclasses import replace
import asyncio
import json
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services.openai_compatible_transport_service import InferenceResponse
from proxy.services.tool_harness_service import ToolHarness
from proxy.services.web_research_config_service import WebResearchConfig
from test_chat_evidence_application_service import (
    test_actual_chat_shadow_failure_preserves_legacy_answer_history_and_model_count as _run_actual_chat,
)


def _call(identity, *, name="web_search", arguments='{ "q" : "literal late query" }'):
    return {"id": identity, "type": "function", "function": {"name": name, "arguments": arguments}}


def _response(calls=(), text=""):
    return InferenceResponse(text=text, tool_calls=tuple(calls), finish_reason="tool_calls" if calls else "stop",
                             usage={"completion_tokens": 3})


def _payload(tool, args):
    return {"tool": tool, "status": "ok", "spec": {"effect": "read"}, "result": {
        "query": args.get("q"), "text": "WHOLE_BODY_START_" + "literal source line\n" * 80 + "_WHOLE_BODY_END",
    }, "sources": [{"url": "https://example.test/literal", "title": "Exact source"}],
        "missing": [], "warnings": [], "trace": "exact read result"}


async def _ordinary(monkeypatch, tmp_path, *, late_calls, max_calls=3, late_text="", expire_after_answer=False,
                    expire_after_first_late_read=False, late_body_size=0, change_connection=False,
                    cancel_late_read=False, final_calls=(), expected_failure=None):
    from proxy.services import tool_harness_service
    broker = ToolHarness(web_config=WebResearchConfig("extended", "http://127.0.0.1:8888", "", ""))
    executions = []
    captures = {}
    clock = SimpleNamespace(now=100.0)
    if expire_after_answer or expire_after_first_late_read:
        import time
        monkeypatch.setattr(service, "time", SimpleNamespace(monotonic=lambda: clock.now, time=time.time))

    class Harness:
        def shortlist(self, *args, **kwargs):
            return broker.shortlist(*args, **kwargs)

        def call(self, tool, args):
            executions.append((tool, deepcopy(args)))
            if cancel_late_read and args.get("q") != "original query":
                raise asyncio.CancelledError()
            result = _payload(tool, args)
            if expire_after_first_late_read and args.get("q") != "original query":
                clock.now = 1000.0
            if late_body_size and args.get("q") != "original query":
                result["result"]["text"] += "x" * late_body_size
            return result

    async def setup(request, runtime, boundary):
        original_env_int = runtime.env_int
        runtime = replace(runtime, env_int=lambda key, default=0: max_calls
                          if key == "LES_CHAT_TOOL_MAX_CALLS" else original_env_int(key, default))
        monkeypatch.setattr(tool_harness_service, "harness", lambda **kwargs: Harness())
        transport = runtime.model_connection_transport(None, None)
        events = []
        async def sink(event):
            events.append(event)
        boundary = replace(boundary, token_sink=sink)
        captures["events"] = events
        transport.responses = [
            _response([_call("original-read", arguments='{  "q" : "original query" }')]),
            _response(text="The current evidence permits an answer."),
            _response(late_calls, text=late_text),
            _response(final_calls, text="Verified answer from the original and additional sources."),
        ]
        if expire_after_answer:
            original_complete = transport.complete

            async def complete(connection, request):
                response = await original_complete(connection, request)
                if len(transport.requests) == 3:
                    clock.now = 1000.0
                return response
            monkeypatch.setattr(transport, "complete", complete)
        if change_connection:
            original_resolver, secret_store = runtime.model_connection_resolver()
            class Resolver:
                def resolve(self, role, **kwargs):
                    current = original_resolver.resolve(role, **kwargs)
                    return SimpleNamespace(**{**vars(current), "revision_id": "changed:r99"}) if len(transport.requests) >= 3 else current

                def resolve_fallback(self, *args, **kwargs):
                    pytest.fail("ordinary continuation changed its assigned model via fallback")
            runtime = replace(runtime, model_connection_resolver=lambda: (Resolver(), secret_store))
        captures["transport"] = transport
        captures["request"] = request
        captures["executions"] = executions
        if expected_failure is None:
            captures["result"] = await service.run_chat_evidence_application(request, runtime, boundary)
        else:
            with pytest.raises(expected_failure) as error:
                await service.run_chat_evidence_application(request, runtime, boundary)
            captures["error"] = error.value
    await _run_actual_chat(monkeypatch, tmp_path, "active_web_research", application_setup=setup)
    return SimpleNamespace(**captures)


@pytest.mark.asyncio
async def test_late_native_reads_keep_the_same_budget_model_scope_and_whole_protocol(monkeypatch, tmp_path):
    literal = '{  "q" : "\\u041b\\u0435\\u0441\\u043d\\u043e\\u0439 64" }'
    late = [_call("late-one", arguments=literal), _call("late-two")]
    run = await _ordinary(monkeypatch, tmp_path, late_calls=late)

    assert len(run.executions) == 3 and len(run.transport.requests) == 4
    assert run.executions[1][1]["q"] == "Лесной 64"
    assert run.result["answer"] == "Verified answer from the original and additional sources."
    loop = run.result["retrieval_trace"]["tool_loop"]
    assert loop["max_calls_total"] == 3 and loop["calls_remaining"] == 0
    assert [item["tool"] for item in loop["selected_calls"]] == ["web_search"] * 3
    assert run.transport.requests[2].tools
    assert {item["function"]["name"] for item in run.transport.requests[2].tools} == {"web_search", "web_read"}
    assert run.transport.requests[-1].tools == ()
    assert len(set(run.transport.revisions)) == 1
    messages = list(run.transport.requests[-1].messages)
    replies = [message for message in messages if message["role"] == "tool"]
    assert [message["tool_call_id"] for message in replies] == ["original-read", "late-one", "late-two"]
    assert all("_WHOLE_BODY_END" in message["content"] for message in replies)
    late_frame = next(message for message in messages if message.get("tool_calls") == late)
    assert late_frame["tool_calls"][0]["function"]["arguments"] == literal
    assert all(request.temperature == run.transport.requests[2].temperature for request in run.transport.requests[2:])
    assert run.result["model_connection"]["pending_tool_calls"] == 0
    assert [event["data"] for event in run.events if event.get("event") == "token"] == [run.result["answer"]]


@pytest.mark.asyncio
async def test_late_repeat_reuses_the_existing_read_snapshot_without_a_second_execution(monkeypatch, tmp_path):
    repeat = _call("later-provider-id", arguments='{ "q": "original query" }')
    run = await _ordinary(monkeypatch, tmp_path, late_calls=[repeat])

    assert len(run.executions) == 1 and len(run.transport.requests) == 4
    protocol = [message for message in run.transport.requests[-1].messages if message["role"] == "tool"]
    assert [message["tool_call_id"] for message in protocol] == ["original-read", "later-provider-id"]
    assert json.loads(protocol[0]["content"]) == json.loads(protocol[1]["content"])
    assert run.result["retrieval_trace"]["tool_loop"]["calls_remaining"] == 1
    assert run.result["retrieval_trace"]["tool_loop"]["rounds"][-1]["replayed"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("late_calls,reason", [
    ([_call("too-many-1"), _call("too-many-2"), _call("too-many-3")], "calls_budget"),
    ([_call("valid-first"), _call("hidden", name="filesystem_hash")], "native_read_unknown_tool"),
    ([_call("valid-first"), _call("write", name="build_lsr_workbook")], "native_read_unknown_tool"),
    ([_call("valid-first"), _call("bad-schema", arguments='{"q":17}')], "native_read_schema_invalid"),
    ([_call("valid-first"), _call("original-read")], "native_read_exchange_invalid"),
])
async def test_invalid_late_native_batch_executes_nothing_and_keeps_original_evidence(monkeypatch, tmp_path, late_calls, reason):
    run = await _ordinary(monkeypatch, tmp_path, late_calls=late_calls)

    assert len(run.executions) == 1 and len(run.transport.requests) == 3
    assert run.result["crag_status"] == "MODEL_OUTPUT_INCOMPLETE"
    loop = run.result["retrieval_trace"]["tool_loop"]
    assert loop["calls_remaining"] == 2
    assert loop["ordinary_read_stop"] == reason
    assert len(loop["results"]) == 1 and "_WHOLE_BODY_END" in json.dumps(loop["results"])
    assert run.result["retrieval_trace"]["model_generation"]["unconsumed_tool_calls"] == len(late_calls)


@pytest.mark.asyncio
async def test_expired_original_deadline_does_not_execute_a_late_native_read(monkeypatch, tmp_path):
    late = [_call("blocked-one"), _call("blocked-two", arguments='{"q":"second late read"}')]
    run = await _ordinary(monkeypatch, tmp_path, late_calls=late, expire_after_answer=True)

    assert len(run.executions) == 1 and len(run.transport.requests) == 4
    loop = run.result["retrieval_trace"]["tool_loop"]
    assert loop["ordinary_read_stop"] == "deadline" and loop["calls_remaining"] == 0
    assert loop["ordinary_read_counts"] == {"admitted": 2, "executed": 0, "replayed": 0, "blocked": 2}
    replies = [message for message in run.transport.requests[-1].messages if message["role"] == "tool"]
    assert [message["tool_call_id"] for message in replies] == ["original-read", "blocked-one", "blocked-two"]
    assert "_WHOLE_BODY_END" in replies[0]["content"]
    assert all(json.loads(reply["content"])["result"] == {
        "code": "ORDINARY_RESEARCH_DEADLINE", "executed": False, "expired_read_window": True,
    } for reply in replies[1:])
    assert run.transport.requests[-1].tools == ()
    assert len(set(run.transport.revisions)) == 1
    assert run.result["model_connection"]["pending_tool_calls"] == 0
    assert run.result["answer"] == "Verified answer from the original and additional sources."


@pytest.mark.asyncio
async def test_deadline_between_late_reads_preserves_complete_exchange_with_unexecuted_tail(monkeypatch, tmp_path):
    late = [_call("completed-late", arguments='{"q":"first late read"}'),
            _call("blocked-late", arguments='{"q":"second late read"}')]
    run = await _ordinary(monkeypatch, tmp_path, late_calls=late, expire_after_first_late_read=True)

    assert [args["q"] for _, args in run.executions] == ["original query", "first late read"]
    assert len(run.transport.requests) == 4
    assert run.transport.requests[-1].tools == ()
    assert len(set(run.transport.revisions)) == 1
    replies = [message for message in run.transport.requests[-1].messages if message["role"] == "tool"]
    assert [message["tool_call_id"] for message in replies] == ["original-read", "completed-late", "blocked-late"]
    assert all("_WHOLE_BODY_END" in message["content"] for message in replies[:2])
    blocked = json.loads(replies[-1]["content"])
    assert blocked["status"] == "blocked"
    assert blocked["result"] == {"code": "ORDINARY_RESEARCH_DEADLINE", "executed": False, "expired_read_window": True}
    assert blocked["sources"] == [] and blocked["missing"] == []
    loop = run.result["retrieval_trace"]["tool_loop"]
    assert loop["calls_remaining"] == 0 and loop["max_calls_total"] == 3
    assert loop["ordinary_read_stop"] == "deadline"
    assert loop["ordinary_read_counts"] == {"admitted": 2, "executed": 1, "replayed": 0, "blocked": 1}
    assert loop["rounds"][-1]["admitted"] == 2
    assert loop["rounds"][-1]["executed"] == 1 and loop["rounds"][-1]["blocked"] == 1
    assert len(loop["selected_calls"]) == 2
    assert run.result["model_connection"]["pending_tool_calls"] == 0
    assert run.result["answer"] == "Verified answer from the original and additional sources."


@pytest.mark.asyncio
async def test_expired_read_window_final_output_cannot_start_another_read_loop(monkeypatch, tmp_path):
    run = await _ordinary(monkeypatch, tmp_path, late_calls=[_call("blocked-late")],
                          expire_after_answer=True, final_calls=[_call("final-unfinished")])

    assert len(run.executions) == 1 and len(run.transport.requests) == 4
    assert run.transport.requests[-1].tools == ()
    assert run.result["crag_status"] == "MODEL_OUTPUT_INCOMPLETE"
    assert run.result["retrieval_trace"]["model_generation"]["unconsumed_tool_calls"] == 1
    assert not any(event.get("event") == "token" for event in run.events)


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [
    '<tool_call>\n<function=web_search>\n<parameter=q>\nnot a native call\n</parameter>\n</function>\n</tool_call>',
    'A quoted example:\n```xml\n<tool_call>\n<function=web_search>\n</function>\n</tool_call>\n```',
])
async def test_public_xml_is_never_executed_as_a_native_tool_decision(monkeypatch, tmp_path, text):
    run = await _ordinary(monkeypatch, tmp_path, late_calls=[], late_text=text)

    assert len(run.executions) == 1 and len(run.transport.requests) == 3
    if text.startswith("<tool_call>"):
        assert run.result["crag_status"] == "MODEL_OUTPUT_INCOMPLETE"
    else:
        assert run.result["answer"] == text


@pytest.mark.asyncio
async def test_whole_native_result_overflow_stops_before_next_model_request_instead_of_clipping(monkeypatch, tmp_path):
    run = await _ordinary(monkeypatch, tmp_path, late_calls=[_call("large-body")], late_body_size=40000,
                          expected_failure=service.HTTPException)

    assert run.error.status_code == 422
    assert run.error.detail["code"] == "CONTEXT_REQUIRED_SECTION_OVERFLOW"
    assert len(run.executions) == 2 and len(run.transport.requests) == 3
    assert not any(event.get("event") == "token" for event in run.events)


@pytest.mark.asyncio
async def test_bound_connection_revision_change_cannot_send_a_continuation_to_another_model(monkeypatch, tmp_path):
    run = await _ordinary(monkeypatch, tmp_path, late_calls=[_call("late")], change_connection=True,
                          expected_failure=service.HTTPException)

    assert run.error.status_code == 502 and "TOKEN_COUNT_CONNECTION_CHANGED" in str(run.error.detail)
    assert len(run.transport.requests) == 3 and len(run.executions) == 2
    assert set(run.transport.revisions) == {"conn:active:r3"}


@pytest.mark.asyncio
async def test_cancellation_during_late_read_propagates_without_new_model_generation(monkeypatch, tmp_path):
    run = await _ordinary(monkeypatch, tmp_path, late_calls=[_call("late")], cancel_late_read=True,
                          expected_failure=asyncio.CancelledError)

    assert len(run.transport.requests) == 3 and len(run.executions) == 2
    assert not any(event.get("event") == "token" for event in run.events)
