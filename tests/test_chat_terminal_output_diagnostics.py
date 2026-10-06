"""Actual terminal guards retain public model output for diagnosis, never execution."""

from dataclasses import replace
import hashlib
import json
import sqlite3

import pytest

from proxy.services import chat_evidence_application_service as service
from proxy.services.openai_compatible_transport_service import InferenceResponse
from test_chat_evidence_application_service import (
    test_actual_chat_shadow_failure_preserves_legacy_answer_history_and_model_count
    as _run_actual_chat_fixture,
)


_NOTICE = (
    "Ответ не завершён: после окончания поиска модель запросила дополнительные "
    "действия вместо итогового ответа. Найденные источники сохранены в истории запроса."
)
_XML = (
    '<tool_call>\n<function=web_search>\n<parameter=q>\nещё данные\n'
    '</parameter>\n</function>\n</tool_call>'
)
_PRIVATE_REASONING = "PRIVATE_TERMINAL_REASONING_905"


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["xml", "unfenced_quote", "json", "native"])
async def test_actual_terminal_guard_saves_exact_public_output_without_executing_it(
    monkeypatch, tmp_path, shape,
):
    # A quote/fragment can trigger the existing detector. Capture it for review;
    # this change must neither interpret it nor change that detector's decision.
    literal = {
        "xml": "  " + _XML + "\n",
        "unfenced_quote": 'Модель процитировала: «пример».\n' + "длинный текст " * 260
            + "\n<tool_call>\n<function=read_source>\n",
        "json": '{ "calls" : [{"tool":"web_search","args":{"q":"ещё данные"}}] }',
        "native": 'Публичное сообщение: «нужно прочитать источник».\n',
    }[shape]
    arguments = '{  "q" : "PRIVATE_ARGUMENT_VALUE_905" }'
    native_calls = ({
        "id": "terminal-must-not-execute", "type": "function",
        "function": {"name": "web_search", "arguments": arguments},
        "reasoning_content": _PRIVATE_REASONING,
    },) if shape == "native" else ()

    async def setup(request, runtime, boundary):
        transport = runtime.model_connection_transport(None, None)
        transport.responses[-1] = InferenceResponse(
            text=literal, tool_calls=native_calls,
            reasoning_content=_PRIVATE_REASONING,
            finish_reason="tool_calls" if native_calls else "stop",
            usage={"completion_tokens": 49},
        )
        snapshots, events = [], []

        def save_history(**row):
            snapshots.append(json.dumps(row, ensure_ascii=False))
            return boundary.save_chat_history(**row)

        async def sink(event):
            events.append(event)

        result = await service.run_chat_evidence_application(
            request, runtime,
            replace(boundary, save_chat_history=save_history, token_sink=sink),
        )
        assert result["answer"] == _NOTICE
        assert result["crag_status"] == "MODEL_OUTPUT_INCOMPLETE"
        assert len(transport.requests) == 4 and not transport.responses
        assert len(snapshots) == 1
        durable = json.loads(snapshots[0])
        diagnostic = durable["retrieval_trace"]["model_generation"]
        assert diagnostic["terminal_output"].encode("utf-8") == literal.encode("utf-8")
        assert diagnostic["terminal_output_sha256"] == hashlib.sha256(literal.encode("utf-8")).hexdigest()
        assert diagnostic["terminal_output_bytes"] == len(literal.encode("utf-8"))
        assert diagnostic["terminal_output_source"] == "provider_response_text"
        assert diagnostic["finish_reason"] == ("tool_calls" if native_calls else "stop")
        assert diagnostic["terminal_native_calls"] == ([{
            "call_id": "terminal-must-not-execute", "tool": "web_search",
            "arguments_sha256": hashlib.sha256(arguments.encode("utf-8")).hexdigest(),
        }] if native_calls else [])
        loop = durable["retrieval_trace"]["tool_loop"]
        assert diagnostic["research_allowed_tools"] == ["web_read", "web_search"]
        assert diagnostic["research_calls_remaining"] == loop["calls_remaining"] == loop["max_calls_total"] - 2
        assert [item["tool"] for item in loop["selected_calls"]] == ["web_search", "web_read"]
        assert len(loop["results"]) == 2
        assert "terminal-must-not-execute" not in json.dumps(loop, ensure_ascii=False)
        assert result["model_connection"]["pending_tool_calls"] == len(native_calls)
        assert literal not in result["answer"]
        assert literal not in json.dumps([event for event in events if event.get("event") == "token"], ensure_ascii=False)
        public_snapshot = json.dumps([result, events, durable], ensure_ascii=False)
        assert _PRIVATE_REASONING not in public_snapshot
        assert "PRIVATE_ARGUMENT_VALUE_905" not in public_snapshot
        assert "canonical_request_body" not in public_snapshot

        # Existing history projections read the human answer and explicitly
        # selected evidence fields; the audit output is not dialogue memory.
        from proxy.services import memory_service
        db = sqlite3.connect(tmp_path / "terminal-history.sqlite3")
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE chat_history (id INTEGER, session_id TEXT, question TEXT, answer TEXT, retrieval_trace_json TEXT)")
        db.execute("INSERT INTO chat_history VALUES (?, ?, ?, ?, ?)", (
            1, "terminal-session", "контроль", durable["answer"],
            json.dumps(durable["retrieval_trace"], ensure_ascii=False),
        ))
        db.commit()
        monkeypatch.setattr(memory_service, "_connect_read_only", lambda: db)
        dialogue = memory_service.session_memory("terminal-session")
        assert _NOTICE in dialogue
        assert literal not in dialogue
        recalled = memory_service.session_recent_retrieval_traces("terminal-session")
        assert recalled[0]["model_generation"]["terminal_output"] == literal
        from proxy.services.chat_evidence_manifest_service import compact_prior_evidence_index, format_prior_evidence_index
        index = format_prior_evidence_index(compact_prior_evidence_index([
            trace["evidence_manifest"] for trace in recalled if isinstance(trace.get("evidence_manifest"), dict)
        ]))
        assert literal not in index
        db.close()

    await _run_actual_chat_fixture(monkeypatch, tmp_path, "active_web_research", application_setup=setup)


@pytest.mark.asyncio
async def test_native_terminal_guard_does_not_invent_unknown_research_budget(monkeypatch, tmp_path):
    async def setup(request, runtime, boundary):
        request = replace(request, profile_snapshot={**request.profile_snapshot, "tools": []})
        transport = runtime.model_connection_transport(None, None)
        transport.responses = [InferenceResponse(
            text="Public terminal content", tool_calls=({
                "id": "pending", "type": "function",
                "function": {"name": "read_source", "arguments": "{}"},
            },), finish_reason="tool_calls", usage={},
        )]
        result = await service.run_chat_evidence_application(request, runtime, boundary)
        assert len(transport.requests) == 1
        assert result["answer"] == _NOTICE
        diagnostic = result["retrieval_trace"]["model_generation"]
        assert diagnostic["terminal_output"] == "Public terminal content"
        assert diagnostic["research_allowed_tools"] == []
        assert diagnostic["research_calls_remaining"] is None

    await _run_actual_chat_fixture(monkeypatch, tmp_path, "active", application_setup=setup)


@pytest.mark.asyncio
async def test_completed_answer_does_not_gain_terminal_diagnostic_capture(monkeypatch, tmp_path):
    async def setup(request, runtime, boundary):
        transport = runtime.model_connection_transport(None, None)
        transport.responses[-1] = InferenceResponse(
            text="Evidence is insufficient; please clarify.", tool_calls=(),
            reasoning_content=_PRIVATE_REASONING, finish_reason="stop", usage={},
        )
        result = await service.run_chat_evidence_application(request, runtime, boundary)
        assert result["answer"] == "Evidence is insufficient; please clarify."
        assert len(transport.requests) == 4
        assert "terminal_output" not in json.dumps(result)
        assert _PRIVATE_REASONING not in json.dumps(result)

    await _run_actual_chat_fixture(monkeypatch, tmp_path, "active_web_research", application_setup=setup)
