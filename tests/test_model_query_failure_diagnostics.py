"""Query failures keep bounded final-output facts in history, never in errors."""
import json

import pytest
from fastapi import HTTPException

from proxy.routers import chat
from proxy.routers.chat_history import get_chat_history
from proxy.services import chat_evidence_application_service as application


def _query_failure():
    return application.model_query_failure(
        "MODEL_RAG_QUERY_LIST_EMPTY", session_id="query-failure", provider="freetoken", model="fixed-35b",
        secret_values=("credential-do-not-store",),
        trace={"model_query_outputs": [{"purpose": "model_rag_queries", "finish_reason": "stop",
            "completion_tokens": 83, "final_chars": 11000, "output_incomplete": False,
            "final_text": "<think>hidden-thought-do-not-store</think>\n{\"queries\": [\"literal query\"]}\n"
                          "api_key=credential-do-not-store\n"
                          '{"password": "json-password-do-not-store", "api_key": "json key do-not-store"}\n'
                          + "x" * 11000,
            "budget": {"requested": 8192, "effective": 8192, "source": "profile_model_policy.query_output_tokens"},
            "declared_parse": {"accepted_count": 0, "rejected_count": 0,
                               "reason_counts": {}, "output_shape": "unsupported_structured_output"}}],
               "model_connection": {"connection_id": "shown-connection", "model_id": "fixed-35b",
                                    "api_key": "connection-secret-do-not-store"},
               "reasoning_content": "trace-secret-do-not-store"})


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [True, False])
async def test_query_failure_history_retains_diagnostics_without_public_leak(tmp_path, monkeypatch, streaming):
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "history.sqlite"))
    async def fail(req, token_sink=None):
        raise _query_failure()
    monkeypatch.setattr(chat, "_run_chat", fail)
    request = chat.ChatRequest(question="original question", session_id="query-failure")
    if streaming:
        response = await chat.chat_stream(request, _user=None)
        body = "".join([piece if isinstance(piece, str) else piece.decode("utf-8")
                        async for piece in response.body_iterator])
        public = json.loads(body.split("event: error\ndata: ", 1)[1].split("\n\n", 1)[0])
    else:
        with pytest.raises(HTTPException) as caught:
            await chat._run_chat_public(request)
        public = caught.value.detail
        body = json.dumps(public)
    assert public["code"] == "MODEL_RAG_QUERY_LIST_EMPTY"
    assert "literal query" not in body and "model_query_outputs" not in body
    assert "do-not-store" not in body
    messages = await get_chat_history(session_id="query-failure", _user=object())
    saved = messages[-1]["meta"]["retrieval_trace"]
    assert saved["session_id"] == "query-failure"
    assert saved["model_execution"] == {"provider": "freetoken", "model": "fixed-35b"}
    assert saved["model_connection"] == {"connection_id": "shown-connection", "model_id": "fixed-35b"}
    output, = saved["model_query_outputs"]
    assert output["finish_reason"] == "stop" and output["completion_tokens"] == 83
    assert output["budget"]["effective"] == 8192
    assert output["declared_parse"]["output_shape"] == "unsupported_structured_output"
    assert "literal query" in output["final_text"]
    assert len(output["final_text"]) <= 8192 and output["final_text_truncated"]
    assert "do-not-store" not in json.dumps(saved)
    assert messages[-1]["meta"]["cache"] == "stream_error"


@pytest.mark.asyncio
async def test_arbitrary_http_detail_cannot_promote_a_trace_to_failure_history(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "history.sqlite"))
    async def fail(req, token_sink=None):
        raise HTTPException(503, detail={"error": "MODEL_RAG_QUERY_LIST_EMPTY",
                                       "retrieval_trace": {"final_text": "untrusted-do-not-store"}})
    monkeypatch.setattr(chat, "_run_chat", fail)
    response = await chat.chat_stream(chat.ChatRequest(question="q", session_id="untrusted"), _user=None)
    body = "".join([piece if isinstance(piece, str) else piece.decode("utf-8")
                    async for piece in response.body_iterator])
    assert "untrusted-do-not-store" not in body
    messages = await get_chat_history(session_id="untrusted", _user=object())
    assert messages[-1]["meta"]["retrieval_trace"] == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [True, False])
async def test_budget_failure_keeps_spend_in_history_through_public_boundary(tmp_path, monkeypatch, streaming):
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "history.sqlite"))
    budget = {"limit_tokens": 300000, "accounted_tokens": 47000,
              "reported_tokens": 47000, "unsettled_reservation_tokens": 0,
              "last_attempt": {"sent": False, "reservation_tokens": 290000}}
    async def fail(req, token_sink=None):
        raise application.ModelExecutionFailure(
            {"code": "CLOUD_TURN_TOKEN_BUDGET", "message": "Budget exhausted"},
            status_code=429, diagnostics={"schema": "les.model-budget-failure.v1",
                "session_id": "budget-failure", "cloud_token_budget": budget, "job_id": "wrj_paused"})
    monkeypatch.setattr(chat, "_run_chat", fail)
    request = chat.ChatRequest(question="original question", session_id="budget-failure")
    if streaming:
        response = await chat.chat_stream(request, _user=None)
        body = "".join([piece if isinstance(piece, str) else piece.decode("utf-8")
                        async for piece in response.body_iterator])
        public = json.loads(body.split("event: error\ndata: ", 1)[1].split("\n\n", 1)[0])
        assert public["status"] == 429
    else:
        with pytest.raises(HTTPException) as caught:
            await chat._run_chat_public(request)
        assert caught.value.status_code == 429
        public = caught.value.detail
    assert public["code"] == "CLOUD_TURN_TOKEN_BUDGET"
    assert "cloud_token_budget" not in public
    messages = await get_chat_history(session_id="budget-failure", _user=object())
    saved = messages[-1]["meta"]["retrieval_trace"]
    assert saved["cloud_token_budget"] == budget
    assert saved["job_id"] == "wrj_paused"
