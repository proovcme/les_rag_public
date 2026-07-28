"""W5.1 — офлайн-проверки SSE-стриминга чата.

Живой end-to-end (первый токен < 2с на MLX) — [live]; здесь проверяем плумбинг
без сервисов: серверный кадр/события и клиентский парсер SSE.
"""
import asyncio
import json

import httpx
import pytest

from proxy.routers import chat as chat_router
from proxy.routers.chat import ChatRequest, _sse_event, chat_stream
from sovushka import state as sov_state


# ── серверная сторона ───────────────────────────────────────────────

def test_sse_event_framing():
    frame = _sse_event("token", "Привет")
    # event + одно data + пустая строка-разделитель; юникод не эскейпится
    assert frame == 'event: token\ndata: "Привет"\n\n'
    final = _sse_event("final", {"answer": "ок", "crag_status": "VERIFIED"})
    assert final.startswith("event: final\ndata: ")
    body = final.split("data: ", 1)[1].rstrip("\n")
    assert json.loads(body)["crag_status"] == "VERIFIED"
    progress = _sse_event("progress", {"step": 1, "total": 2, "label": "Ищу"})
    assert progress.startswith("event: progress\ndata: ")
    assert json.loads(progress.split("data: ", 1)[1])["label"] == "Ищу"


def test_recovered_stream_answer_is_persisted_for_session_reopen(monkeypatch):
    captured = {}

    def save_chat_history(**kwargs):
        captured.update(kwargs)
        return 73

    monkeypatch.setattr(chat_router, "save_chat_history", save_chat_history)
    payload = chat_router._persist_recovered_stream_history(
        ChatRequest(question="Собери смету", session_id="session-1"),
        {
            "answer": "Восстановленный ответ",
            "crag_status": "UNVALIDATED",
            "sources": [{"source_ref": "source.pdf#page=1"}],
            "retrieval_trace": {"stream_recovery": {"tokens": 12}},
            "cache": "stream_recovered",
        },
    )

    assert payload["history_id"] == 73
    assert captured["session_id"] == "session-1"
    assert captured["sources"] == ["source.pdf#page=1"]
    assert captured["tokens"] == 12


async def _drain(resp) -> str:
    out = []
    async for chunk in resp.body_iterator:
        out.append(chunk if isinstance(chunk, str) else chunk.decode("utf-8"))
    return "".join(out)


@pytest.mark.asyncio
async def test_chat_stream_emits_tokens_then_final(monkeypatch):
    async def fake_run_chat(req, token_sink=None):
        assert token_sink is not None
        for piece in ("При", "вет", "!"):
            await token_sink({"event": "token", "data": piece})
        return {"answer": "Привет!", "crag_status": "VERIFIED", "sources": ["doc.pdf"]}

    monkeypatch.setattr(chat_router, "_run_chat", fake_run_chat)
    resp = await chat_stream(ChatRequest(question="привет"), _user=None)
    assert resp.media_type == "text/event-stream"
    body = await _drain(resp)

    # progress, три token-события в порядке, затем final с вердиктом
    assert "event: progress" in body
    assert body.index('data: "При"') < body.index('data: "вет"') < body.index('data: "!"')
    assert "event: final" in body
    final_blob = body.split("event: final\ndata: ", 1)[1].split("\n\n", 1)[0]
    final = json.loads(final_blob)
    assert final["answer"] == "Привет!"
    assert final["crag_status"] == "VERIFIED"
    assert final["sources"] == ["doc.pdf"]
    assert final["scenario"]["id"]
    assert final["answer_contract"]["id"]
    assert final["answer_contract_check"]["status"] in {"pass", "warn"}
    assert body.index("event: token") < body.index("event: final")


@pytest.mark.asyncio
async def test_chat_stream_emits_error_event_on_http_exception(monkeypatch):
    from fastapi import HTTPException

    async def boom(req, token_sink=None):
        raise HTTPException(503, "LLM недоступен")

    monkeypatch.setattr(chat_router, "_run_chat", boom)
    resp = await chat_stream(ChatRequest(question="привет"), _user=None)
    body = await _drain(resp)
    assert "event: error" in body
    err = json.loads(body.split("event: error\ndata: ", 1)[1].split("\n\n", 1)[0])
    assert err["status"] == 503
    assert "недоступен" in err["detail"]


@pytest.mark.asyncio
async def test_chat_stream_reset_then_final(monkeypatch):
    async def with_reset(req, token_sink=None):
        await token_sink({"event": "token", "data": "черновик"})
        await token_sink({"event": "reset", "data": ""})
        await token_sink({"event": "token", "data": "финал"})
        return {"answer": "финал", "crag_status": "VERIFIED", "sources": []}

    monkeypatch.setattr(chat_router, "_run_chat", with_reset)
    resp = await chat_stream(ChatRequest(question="q"), _user=None)
    body = await _drain(resp)
    assert body.index("event: reset") < body.index('data: "финал"')


@pytest.mark.asyncio
async def test_chat_stream_recovers_long_answer_instead_of_late_reset_error(monkeypatch):
    monkeypatch.setenv("LES_STREAM_RECOVERY_MIN_CHARS", "20")
    monkeypatch.setenv("LES_STREAM_RESET_PRESERVE_CHARS", "20")

    async def long_answer_then_tail_failure(req, token_sink=None):
        await token_sink({"event": "sources", "data": {"sources": ["project.pdf"]}})
        for piece in ("Готовый ", "инженерный ", "ответ по проекту."):
            await token_sink({"event": "token", "data": piece})
        await token_sink({"event": "reset", "data": ""})
        await token_sink({"event": "token", "data": "дубль после reset"})
        raise RuntimeError("tail stream timeout")

    monkeypatch.setattr(chat_router, "_run_chat", long_answer_then_tail_failure)
    resp = await chat_stream(ChatRequest(question="расскажи про проект"), _user=None)
    body = await _drain(resp)

    assert "event: reset" not in body
    assert "дубль после reset" not in body
    assert "event: error" not in body
    assert "event: final" in body
    final_blob = body.split("event: final\ndata: ", 1)[1].split("\n\n", 1)[0]
    final = json.loads(final_blob)
    assert final["answer"] == "Готовый инженерный ответ по проекту."
    assert final["crag_status"] == "UNVALIDATED"
    assert final["sources"] == ["project.pdf"]
    assert final["retrieval_trace"]["stream_recovery"]["reason"] == "RuntimeError"
    assert final["retrieval_trace"]["stream_recovery"]["reset_suppressed"] is True


@pytest.mark.asyncio
async def test_chat_stream_synthesizes_tokens_when_path_returns_final_only(monkeypatch):
    async def final_only(req, token_sink=None):
        assert token_sink is not None
        return {"answer": "Готовый ответ без родных токенов.", "crag_status": "VERIFIED", "sources": []}

    monkeypatch.setattr(chat_router, "_run_chat", final_only)
    resp = await chat_stream(ChatRequest(question="q"), _user=None)
    body = await _drain(resp)

    assert "event: token" in body
    assert body.index("event: token") < body.index("event: final")
    assert "Готовый ответ" in body


@pytest.mark.asyncio
async def test_chat_stream_finishes_runner_after_client_iterator_closes(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    state = {"completed": False, "cancelled": False}

    async def slow_final(req, token_sink=None):
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise
        state["completed"] = True
        return {"answer": "Смета готова", "crag_status": "VERIFIED", "sources": []}

    monkeypatch.setattr(chat_router, "_run_chat", slow_final)
    response = await chat_stream(ChatRequest(question="Собери смету"), _user=None)
    iterator = response.body_iterator
    await anext(iterator)
    await started.wait()

    close_task = asyncio.create_task(iterator.aclose())
    await asyncio.sleep(0)
    assert close_task.done() is False
    assert state["cancelled"] is False

    release.set()
    await close_task
    assert state["completed"] is True
    assert state["cancelled"] is False


# ── клиентская сторона (sovushka/state.api_post_stream) ──────────────

class _FakeStream:
    def __init__(self, lines, status=200):
        self._lines = lines
        self.status_code = status
        self.text = "error-body"
        self.request = httpx.Request("POST", "http://x/api/chat/stream")

    def json(self):
        raise ValueError("not json")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
        for ln in self._lines:
            yield ln

    async def aread(self):
        return b"error-body"


class _FakeClient:
    def __init__(self, lines, status=200):
        self._lines = lines
        self._status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, **kw):
        return _FakeStream(self._lines, self._status)


@pytest.mark.asyncio
async def test_api_post_stream_parses_sse(monkeypatch):
    lines = [
        "event: progress", 'data: {"step": 1, "total": 2, "label": "Ищу"}', "",
        "event: token", 'data: "При"', "",
        "event: token", 'data: "вет"', "",
        "event: final", 'data: {"answer": "Привет", "crag_status": "VERIFIED"}', "",
    ]
    monkeypatch.setattr(sov_state.httpx, "AsyncClient", lambda *a, **k: _FakeClient(lines))

    events = []
    got_final = await sov_state.api_post_stream("/api/chat/stream", {"question": "q"}, lambda e, p: events.append((e, p)))

    assert got_final is True
    assert ("progress", {"step": 1, "total": 2, "label": "Ищу"}) in events
    assert ("token", "При") in events
    assert ("token", "вет") in events
    assert events[-1][0] == "final"
    assert events[-1][1]["crag_status"] == "VERIFIED"


@pytest.mark.asyncio
async def test_api_post_stream_handles_non_200(monkeypatch):
    monkeypatch.setattr(sov_state.httpx, "AsyncClient", lambda *a, **k: _FakeClient([], status=503))
    events = []
    got_final = await sov_state.api_post_stream("/api/chat/stream", {"question": "q"}, lambda e, p: events.append((e, p)))
    assert got_final is False
    assert events == []  # ошибка ушла в state.last_api_error, не как событие
    assert sov_state.state["last_api_error"] is not None
