"""The actual ordinary chat must preserve its provider-native read protocol."""

from dataclasses import replace
import json

import pytest
import test_chat_evidence_application_service as actual_chat_fixture

from proxy.services import chat_evidence_application_service as service
from proxy.services.context_governor_service import ContextRequiredSectionOverflow
from proxy.services.openai_compatible_transport_service import InferenceResponse
from test_chat_evidence_application_service import (
    _governor_preset,
    test_actual_chat_shadow_failure_preserves_legacy_answer_history_and_model_count
    as _run_actual_chat_fixture,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,effect,replayed", [
    ("ok", "read", True), ("missing", "read", True),
    ("error", "read", False), ("ok", "write", False),
])
async def test_repeated_read_batch_reuses_exact_evidence_and_finishes_without_new_search(
    monkeypatch, tmp_path, status, effect, replayed,
):
    from proxy.services import tool_harness_service
    from proxy.services.tool_harness_service import ToolHarness
    from proxy.services.web_research_config_service import WebResearchConfig
    broker = ToolHarness(web_config=WebResearchConfig("simple", "", "", ""))
    executions = []
    original = {**_payload("original", status=status), "spec": {"effect": effect}}

    class Harness:
        def shortlist(self, *args, **kwargs):
            return broker.shortlist(*args, **kwargs)

        def call(self, tool, args):
            executions.append((tool, dict(args)))
            return original

    async def setup(request, runtime, boundary):
        transport = runtime.model_connection_transport(None, None)
        final = InferenceResponse(text="Evidence is insufficient; please specify the project.",
                                  tool_calls=(), finish_reason="stop", usage={})
        transport.responses = [_response(["first"]), _response(["repeat"]), final]
        if not replayed:
            transport.responses.append(final)
        monkeypatch.setattr(tool_harness_service, "harness", lambda **kwargs: Harness())
        result = await service.run_chat_evidence_application(request, runtime, boundary)
        loop = result["retrieval_trace"]["tool_loop"]
        assert len(executions) == (1 if replayed else 2)
        assert loop["stop_reason"] == ("repeated_read_batch" if replayed else "model_stop")
        assert result["answer"] == final.text
        protocol = [m for m in transport.requests[-1].messages if m["role"] == "tool"]
        assert [m["tool_call_id"] for m in protocol] == ["first", "repeat"]
        assert [json.loads(m["content"]) for m in protocol] == [original, original]
        if replayed:
            assert loop["rounds"][-1]["replayed"] == 1
            assert loop["rounds"][-1]["executed"] == 0
        assert len(transport.requests) == (3 if replayed else 4)
    await _run_actual_chat_fixture(monkeypatch, tmp_path, "active_web_research", application_setup=setup)


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["qwen_xml", "mixed_xml", "json", "native", "fenced_example", "final"])
async def test_final_research_request_is_final_only_and_unfinished_protocol_is_not_published(monkeypatch, tmp_path, shape):
    from proxy.services.model_output_protocol_service import FINAL_RESEARCH_INSTRUCTION
    raw_xml = '<tool_call>\n<function=web_search>\n<parameter=q>\nmore\n</parameter>\n</function>\n</tool_call>'
    text = {"qwen_xml": raw_xml, "mixed_xml": "Need another lookup.\n" + raw_xml,
            "json": '{"calls":[{"tool":"web_search","args":{"q":"more"}}]}',
            "native": "", "fenced_example": "Example:\n```xml\n" + raw_xml + "\n```",
            "final": "A complete answer from the supplied evidence."}[shape]
    incomplete = shape not in {"fenced_example", "final"}

    async def setup(request, runtime, boundary):
        transport = runtime.model_connection_transport(None, None)
        transport.responses[-1] = InferenceResponse(
            text=text, tool_calls=_response(["unexpected-final-call"]).tool_calls if shape == "native" else (),
            reasoning_content="PRIVATE_888_REASONING", finish_reason="tool_calls" if shape == "native" else "stop", usage={})
        events, histories = [], []
        async def sink(event):
            events.append(event)
        def history(**row):
            histories.append(row)
            return boundary.save_chat_history(**row)
        result = await service.run_chat_evidence_application(request, runtime,
            replace(boundary, token_sink=sink, save_chat_history=history))
        assert len(transport.requests) == 4 and not transport.responses
        assert transport.requests[-1].messages[-1]["role"] == "user"
        assert FINAL_RESEARCH_INSTRUCTION in transport.requests[-1].messages[-1]["content"]
        assert transport.requests[-1].tools == ()
        assert "PRIVATE_888_REASONING" not in json.dumps([result, events, histories], default=str)
        if incomplete:
            assert result["crag_status"] == "MODEL_OUTPUT_INCOMPLETE"
            assert result["retrieval_trace"]["model_generation"]["reason"] == "model_tool_request_in_final_answer"
            # Raw public content is retained only in the controlled diagnostic
            # trace; it must still never become the visible answer/token stream.
            assert "<tool_call>" not in result["answer"]
            assert "<tool_call>" not in json.dumps(
                [event for event in events if event.get("event") == "token"], default=str)
            assert "native_reasoning_content" not in result["answer"]
            assert result["model_connection"]["pending_tool_calls"] == (1 if shape == "native" else 0)
        else:
            assert result["answer"] == text
            assert result["crag_status"] != "MODEL_OUTPUT_INCOMPLETE"
    await _run_actual_chat_fixture(monkeypatch, tmp_path, "active_web_research", application_setup=setup)


@pytest.mark.asyncio
async def test_two_native_web_rounds_preserve_ids_literal_arguments_and_results(monkeypatch, tmp_path):
    """Replay two real application rounds, not a mocked context packer.

    Like live 704, the provider emits native calls with empty/ordinary content
    and receives multiple successive web results. Only inference is synthetic.
    """
    original_runner = service.BoundModelChatRunner
    requests = []
    emitted_calls = []
    emitted_content = []
    literal_arguments = [
        '{  "q" : "цены цемента и арматуры" }',
        '{ "url" : "https://public.example/materials"  }',
    ]

    class CapturingRunner(original_runner):
        async def complete(self, *, request, **kwargs):
            requests.append(request)
            result = await super().complete(request=request, **kwargs)
            if result.response.tool_calls:
                index = len(emitted_calls)
                raw = result.response.tool_calls[0]
                native = {
                    **raw,
                    "function": {**raw["function"], "arguments": literal_arguments[index]},
                }
                content = f"Read round {index + 1}; this is provider assistant content."
                emitted_calls.append(native)
                emitted_content.append(content)
                result = replace(result, response=replace(
                    result.response, text=content, tool_calls=(native,),
                    reasoning_content=f"private reasoning round {index + 1}",
                ))
            return result

    monkeypatch.setattr(service, "BoundModelChatRunner", CapturingRunner)
    await _run_actual_chat_fixture(monkeypatch, tmp_path, "active_web_research")
    assert len(requests) == 4
    for request_index, completed in ((1, 1), (2, 2), (3, 2)):
        messages = list(requests[request_index].messages)
        protocol = [message for message in messages if message["role"] in {"assistant", "tool"}]
        assert len(protocol) == completed * 2
        for index in range(completed):
            assistant, reply = protocol[index * 2:index * 2 + 2]
            assert assistant["content"] == emitted_content[index]
            assert assistant["reasoning_content"] == f"private reasoning round {index + 1}"
            assert assistant["tool_calls"] == [emitted_calls[index]]
            assert reply["tool_call_id"] == emitted_calls[index]["id"]
            assert reply["name"] == emitted_calls[index]["function"]["name"]
            payload = json.loads(reply["content"])
            assert payload["status"] == "ok"
            if index == 0:
                assert payload["result"]["query"] == "цены цемента и арматуры"
                assert payload["result"]["results"][0]["snippet"] == "Цены на цемент и арматуру"
                assert payload["sources"][0]["url"] == "https://public.example/materials"
            else:
                assert payload["result"]["text"] == "Цемент — 650 руб.; арматура — 72 000 руб./т."
        user_content = "\n".join(message.get("content", "") for message in messages if message["role"] == "user")
        assert all("private reasoning" not in message.get("content", "") for message in messages)
        assert "tool result trimmed for prompt only" not in user_content
        assert '"operation":"search"' not in user_content
        if request_index < 3:
            assert requests[request_index].tools == requests[0].tools


def _response(call_ids, arguments='{  "q" : "same query" }'):
    return InferenceResponse(
        text="Literal assistant content.",
        tool_calls=tuple({"id":call_id, "type":"function", "function":{
            "name":"web_search", "arguments":arguments,
        }} for call_id in call_ids),
        finish_reason="tool_calls", usage={},
    )


def _executed(response):
    return [{"call_id":call["id"], "tool":call["function"]["name"],
             "args":json.loads(call["function"]["arguments"])} for call in response.tool_calls]


def _payload(suffix, *, status="ok"):
    return {"tool":"web_search", "status":status, "result":{
        "query":"same query", "results":[{"title":f"Title {suffix}",
        "snippet":f"Whole literal snippet {suffix}", "url":f"https://public.example/{suffix}"}],
    }, "sources":[{"url":f"https://public.example/{suffix}"}],
        "missing":[] if status == "ok" else ["web search returned no results"],
        "warnings":[], "trace":f"provider trace {suffix}"}


def test_parallel_and_repeated_semantic_calls_keep_distinct_provider_ids_and_full_results():
    response = _response(["parallel-1", "parallel-2"])
    calls = service.native_research_call_batch(response, _executed(response))
    first = service.native_research_exchange(calls, [_payload("one"), _payload("two")],
                                            assistant_content=response.text)
    later_response = _response(["later-3"])
    later_calls = service.native_research_call_batch(later_response, _executed(later_response), [first])
    later = service.native_research_exchange(later_calls, [_payload("three")],
                                            assistant_content=later_response.text)
    messages, packet = service.govern_inference_messages(
        preset=_governor_preset(input_tokens=12000), profile_prefix="profile", request_payload="request",
        native_exchanges=[first, later],
    )
    assert packet.omissions == ()
    protocol = messages[2:]
    assert [message["role"] for message in protocol] == ["assistant", "tool", "tool", "assistant", "tool"]
    assert protocol[0]["tool_calls"] == list(response.tool_calls)
    assert protocol[3]["tool_calls"] == list(later_response.tool_calls)
    assert [message["tool_call_id"] for message in protocol if message["role"] == "tool"] == [
        "parallel-1", "parallel-2", "later-3",
    ]
    assert [json.loads(message["content"]) for message in protocol if message["role"] == "tool"] == [
        _payload("one"), _payload("two"), _payload("three"),
    ]
    assert "Whole literal snippet" not in messages[1]["content"]


@pytest.mark.parametrize("collision", ["same_batch", "prior_round"])
def test_duplicate_provider_id_is_rejected_before_execution(collision):
    previous = []
    if collision == "prior_round":
        original = _response(["same-id"])
        previous = [service.native_research_exchange(
            service.native_research_call_batch(original, _executed(original)), [_payload("prior")],
            assistant_content=original.text,
        )]
        response = _response(["same-id"])
    else:
        response = _response(["same-id", "same-id"])
    with pytest.raises(ValueError, match="duplicate provider IDs"):
        service.native_research_call_batch(response, _executed(response), previous)


@pytest.mark.parametrize("mismatch", ["partial_batch", "changed_query", "wrong_id", "wrong_tool"])
def test_native_execution_mismatch_cannot_be_replayed_as_valid_protocol(mismatch):
    response = _response(["one", "two"])
    executed = _executed(response)
    if mismatch == "partial_batch":
        executed.pop()
    elif mismatch == "changed_query":
        executed[0]["args"]["q"] = "application changed query"
    elif mismatch == "wrong_id":
        executed[0]["call_id"] = "foreign-call"
    else:
        executed[0]["tool"] = "web_read"
    with pytest.raises(ValueError, match="must execute every|changes provider arguments|another call"):
        service.native_research_call_batch(response, executed)


def test_bound_execution_scope_additions_do_not_rewrite_literal_provider_arguments():
    literal = '{ "q" : "\\u041e\\u0416\\u0420", "limit" : 4 }'
    response = _response(["literal-unicode"], arguments=literal)
    executed = _executed(response)
    executed[0]["args"]["dataset_id"] = "operator-bound-scope"
    calls = service.native_research_call_batch(response, executed)
    assert calls[0].arguments == literal


def test_missing_result_and_true_native_context_overflow_are_visible():
    response = _response(["one"])
    calls = service.native_research_call_batch(response, _executed(response))
    with pytest.raises(ValueError, match="exactly one result"):
        service.native_research_exchange(calls, [], assistant_content=response.text)
    payload = _payload("large")
    payload["result"]["results"][0]["snippet"] = "x" * 12000
    exchange = service.native_research_exchange(calls, [payload], assistant_content=response.text)
    assert json.loads(exchange.replies[0].content) == payload
    with pytest.raises(ContextRequiredSectionOverflow):
        service.govern_inference_messages(preset=_governor_preset(input_tokens=6000),
            profile_prefix="profile", request_payload="request", native_exchanges=[exchange])


def test_legacy_text_tool_calls_do_not_gain_a_fabricated_native_exchange():
    response = InferenceResponse(text='{"calls":[]}', tool_calls=(), finish_reason="stop", usage={})
    assert service.native_research_call_batch(response, [{"tool":"web_search", "args":{"q":"query"}}]) == ()
    assert service.native_research_call_batch(None, []) == ()


@pytest.mark.asyncio
async def test_oversized_native_batch_stops_before_execution_and_keeps_completed_history(monkeypatch, tmp_path):
    """A provider batch is indivisible even when the parser applies a budget cap."""
    original_runner = service.BoundModelChatRunner
    original_application = service.run_chat_evidence_application
    requests = []
    results = []
    blocked_calls = _response(["pending-one", "pending-two"]).tool_calls

    class OversizedBatchRunner(original_runner):
        async def complete(self, *, request, **kwargs):
            requests.append(request)
            result = await super().complete(request=request, **kwargs)
            if len(requests) == 3:
                assert not result.response.tool_calls
                result = replace(result, response=replace(
                    result.response, text="Additional requested reading.",
                    tool_calls=blocked_calls, finish_reason="tool_calls",
                ))
            return result

    async def capture_application(*args, **kwargs):
        result = await original_application(*args, **kwargs)
        assert result["retrieval_trace"]["tool_loop"].get("stop_reason") == "calls_budget"
        results.append(result)
        return result

    original_preset = actual_chat_fixture._governor_preset
    monkeypatch.setattr(actual_chat_fixture, "_governor_preset",
                        lambda **kwargs: replace(original_preset(**kwargs), max_batch_items=3))
    monkeypatch.setattr(service, "BoundModelChatRunner", OversizedBatchRunner)
    monkeypatch.setattr(service, "run_chat_evidence_application", capture_application)
    await _run_actual_chat_fixture(monkeypatch, tmp_path, "active_web_research")
    loop = results[0]["retrieval_trace"]["tool_loop"]
    assert loop["stop_reason"] == "calls_budget"
    assert loop["calls_remaining"] == 1
    assert loop["rounds"][-1] == {
        "round":3, "proposed":2, "executed":0, "unexecuted":2, "reason":"calls_budget",
    }
    assert loop["unexecuted_native_call_count"] == 2
    assert results[0]["model_connection"]["pending_tool_calls"] == 2
    assert len(loop["results"]) == 2
    assert [call["tool"] for call in loop["selected_calls"]] == ["web_search", "web_read"]
    final_protocol = [message for message in requests[-1].messages if message["role"] in {"assistant", "tool"}]
    assert [message["tool_call_id"] for message in final_protocol if message["role"] == "tool"] == [
        "web-search-1", "web-read-1",
    ]
    assert "pending-one" not in str(requests[-1].messages)
    assert "pending-two" not in str(requests[-1].messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("batch_shape", ["workbook_first", "workbook_last", "prior_round"])
async def test_successful_workbook_preserves_whole_native_batch_before_final_answer(
    monkeypatch, tmp_path, batch_shape,
):
    """Exercise the actual Agent application with a real registry/Broker shortlist."""
    from proxy.services import tool_harness_service
    from proxy.services.tool_harness_service import ToolHarness
    from proxy.services.web_research_config_service import WebResearchConfig

    workbook_call = {"id":"mixed-workbook", "type":"function", "function":{
        "name":"build_vor_workbook",
        "arguments":'{ "attachment_id" : "read_123456abcdef" }',
    }}
    read_call = {"id":"mixed-read", "type":"function", "function":{
        "name":"web_search", "arguments":'{  "q" : "same query" }',
    }}
    mixed_calls = (read_call, workbook_call) if batch_shape == "workbook_last" else (workbook_call, read_call)
    prior_response = _response(["prior-read"])
    read_calls = []
    broker = ToolHarness(web_config=WebResearchConfig("simple", "", "", ""))

    class MixedHarness:
        def shortlist(self, *args, **kwargs):
            return broker.shortlist(*args, **kwargs)

        def call(self, tool, args):
            assert tool == "web_search"
            read_calls.append((tool, dict(args)))
            return _payload(f"read-{len(read_calls)}")

    async def run_mixed_application(request, runtime, boundary):
        request.req.mode = "agent"
        request = replace(request, profile_snapshot={
            **request.profile_snapshot, "mode":"agent",
            "tools":["build_vor_workbook", "web_search"],
        })
        transport = runtime.model_connection_transport(None, None)
        mixed_response = InferenceResponse(
            text="Package the requested document and read the independent evidence.",
            tool_calls=mixed_calls, finish_reason="tool_calls", usage={},
        )
        transport.responses = ([prior_response] if batch_shape == "prior_round" else []) + [
            mixed_response,
            InferenceResponse(text="active visible answer", tool_calls=(), finish_reason="stop", usage={}),
        ]
        monkeypatch.setattr(tool_harness_service, "harness", lambda **_kwargs: MixedHarness())
        result = await service.run_chat_evidence_application(request, runtime, boundary)
        expected_read_count = 2 if batch_shape == "prior_round" else 1
        assert len(read_calls) == expected_read_count
        assert result["answer"] == "active visible answer"
        assert result["artifact"]["revision_id"] == "rev-2"
        loop = result["retrieval_trace"]["tool_loop"]
        assert loop["stop_reason"] == "workbook_complete"
        assert loop["rounds"][-1]["executed"] == 2
        assert len(loop["results"]) == expected_read_count + 1
        assert len(transport.requests) == expected_read_count + 1
        advertised = {tool["function"]["name"] for tool in transport.requests[0].tools}
        assert {"build_vor_workbook", "web_search"} <= advertised
        protocol = [message for message in transport.requests[-1].messages
                    if message["role"] in {"assistant", "tool"}]
        if batch_shape == "prior_round":
            assert protocol[0]["tool_calls"] == list(prior_response.tool_calls)
            assert protocol[1]["tool_call_id"] == "prior-read"
            assert json.loads(protocol[1]["content"]) == _payload("read-1")
            protocol = protocol[2:]
        assert len(protocol) == 3
        assert protocol[0]["content"] == mixed_response.text
        assert protocol[0]["tool_calls"] == list(mixed_calls)
        assert [message["tool_call_id"] for message in protocol[1:]] == [call["id"] for call in mixed_calls]
        replies = {message["tool_call_id"]:json.loads(message["content"]) for message in protocol[1:]}
        assert replies["mixed-workbook"]["artifact"]["revision_id"] == "rev-2"
        assert replies["mixed-read"] == _payload(f"read-{expected_read_count}")
        assert [message["name"] for message in protocol[1:]] == [call["function"]["name"] for call in mixed_calls]

    await _run_actual_chat_fixture(monkeypatch, tmp_path, "active_workbook",
                                   application_setup=run_mixed_application)
