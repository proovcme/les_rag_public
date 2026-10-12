from __future__ import annotations

import io
import asyncio
import threading

import pytest
from fastapi import HTTPException, UploadFile

from proxy.routers import chat, datasets
from proxy.security import RequestUser
from proxy.services import request_idempotency_service as idem


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["begin", "workflow", "workflow_error"])
async def test_chat_cleanup_error_preserves_original_failure(tmp_path, monkeypatch, stage):
    monkeypatch.setattr(idem, "DEFAULT_DB_PATH", tmp_path / "idempotency.db")
    entered = asyncio.Event()
    resume = threading.Event()
    loop = asyncio.get_running_loop()
    original_begin = idem.begin
    original_error = ValueError("workflow failed")

    def begin(**kwargs):
        result = original_begin(**kwargs)
        if stage == "begin":
            loop.call_soon_threadsafe(entered.set)
            assert resume.wait(5)
        return result

    def release(**kwargs):
        raise OSError("cleanup failed")

    async def run(req):
        if stage == "workflow_error":
            raise original_error
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(idem, "begin", begin)
    monkeypatch.setattr(idem, "release", release)
    monkeypatch.setattr(chat, "_run_chat", run)
    if stage == "workflow_error":
        monkeypatch.setattr(chat, "_run_chat_public", run)
    user = RequestUser(role="user", holder="integrator", key_value="test", source="api_key")
    task = asyncio.create_task(chat.chat(chat.ChatRequest(question="cleanup", mode="chat"),
                                        _user=user, idempotency_key="cleanup-request-001"))
    if stage != "workflow_error":
        try:
            await asyncio.wait_for(entered.wait(), 5)
            task.cancel()
            await asyncio.sleep(0)
        finally:
            resume.set()
    expected = ValueError if stage == "workflow_error" else asyncio.CancelledError
    with pytest.raises(expected) as failure:
        await task
    assert isinstance(failure.value.__cause__, OSError)
    assert str(failure.value.__cause__) == "cleanup failed"
    if stage == "workflow_error":
        assert failure.value is original_error


def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(data))


def test_idempotency_store_replays_completed_response_and_rejects_payload_change(tmp_path):
    db = tmp_path / "idem.db"
    args = {
        "operation": "chat",
        "caller": "caller-1",
        "idempotency_key": "lsr-request-001",
        "request_hash": idem.request_fingerprint({"question": "Сделай ЛСР"}),
        "db_path": db,
    }

    assert idem.begin(**args) == ("started", None)
    assert idem.begin(**args) == ("in_progress", None)
    idem.complete(**args, response={"answer": "готово"})
    assert idem.begin(**args) == ("completed", {"answer": "готово"})

    with pytest.raises(idem.IdempotencyConflict):
        idem.begin(**{**args, "request_hash": idem.request_fingerprint({"question": "другое"})})


@pytest.mark.asyncio
async def test_external_chat_attachment_is_user_authorized_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(idem, "DEFAULT_DB_PATH", tmp_path / "idempotency.db")
    user = RequestUser(role="user", holder="integrator", key_value="les-user-test", source="api_key")

    first = await datasets.create_chat_attachment(
        file=_upload("ВОР.txt", "Монтаж кабеля 160 м".encode()),
        idempotency_key="ladcraft-attachment-001",
        _user=user,
    )
    second = await datasets.create_chat_attachment(
        file=_upload("ВОР.txt", "Монтаж кабеля 160 м".encode()),
        idempotency_key="ladcraft-attachment-001",
        _user=user,
    )

    assert first == second
    assert first["attachment_id"].startswith("read_")
    assert (tmp_path / "storage" / "chat_attachments" / f"{first['attachment_id']}.json").is_file()

    with pytest.raises(HTTPException) as conflict:
        await datasets.create_chat_attachment(
            file=_upload("ВОР.txt", "Другой файл".encode()),
            idempotency_key="ladcraft-attachment-001",
            _user=user,
        )
    assert conflict.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("stage,foreign", [("begin", False), ("begin", True), ("workflow", False), ("release", False), ("complete", False), ("complete_error", False)])
async def test_chat_cancellation_settles_only_owned_claim(tmp_path, monkeypatch, stage, foreign):
    monkeypatch.setattr(idem, "DEFAULT_DB_PATH", tmp_path / "idempotency.db")
    user = RequestUser(role="user", holder="integrator", key_value="test", source="api_key")
    request = chat.ChatRequest(question="cancel", mode="chat")
    key = "cancel-request-001"
    args = dict(operation="chat", caller=idem.caller_scope(user), idempotency_key=key,
                request_hash=idem.request_fingerprint(chat._idempotency_payload(request)))
    if foreign:
        assert idem.begin(**args) == ("started", None)
    entered = asyncio.Event()
    resume = threading.Event()
    loop = asyncio.get_running_loop()
    calls = 0
    target = "begin" if stage == "begin" else "release" if stage == "release" else "complete"
    original = getattr(idem, target)

    def blocked(**kwargs):
        loop.call_soon_threadsafe(entered.set)
        assert resume.wait(5), "test did not unblock SQLite worker"
        if stage == "complete_error":
            raise RuntimeError("synthetic persistence failure")
        return original(**kwargs)

    if stage != "workflow":
        monkeypatch.setattr(idem, target, blocked)

    async def run(req):
        nonlocal calls
        calls += 1
        if stage in ("workflow", "release"):
            if stage == "workflow":
                entered.set()
            await asyncio.Event().wait()
        return {"answer": "paid result"}

    monkeypatch.setattr(chat, "_run_chat", run)
    monkeypatch.setattr(chat, "decorate_payload", lambda value: value)
    task = asyncio.create_task(chat.chat(request, _user=user, idempotency_key=key))
    try:
        if stage == "release":
            while not calls:
                await asyncio.sleep(0)
            task.cancel()
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()  # cancellation while protected settlement is pending
    finally:
        resume.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    # Inspect through the real store, never the temporarily blocked wrapper.
    state, payload = (original if target == "begin" else idem.begin)(**args)
    if foreign:
        assert state == "in_progress"
        assert calls == 0
    elif stage == "complete":
        assert (state, payload) == ("completed", {"answer": "paid result"})
        assert calls == 1
    elif stage == "complete_error":
        assert state == "in_progress"  # keep existing persistence-failure policy
        assert calls == 1
    else:
        assert state == "started"
        assert calls == (0 if stage == "begin" else 1)


@pytest.mark.asyncio
async def test_chat_idempotency_replays_without_second_model_call(tmp_path, monkeypatch):
    monkeypatch.setattr(idem, "DEFAULT_DB_PATH", tmp_path / "idempotency.db")
    calls = 0

    async def fake_run_chat(req):
        nonlocal calls
        calls += 1
        return {"answer": f"ЛСР для {req.question}", "artifact": {"downloads": {"xlsx": "/x.xlsx"}}}

    monkeypatch.setattr(chat, "_run_chat", fake_run_chat)
    monkeypatch.setattr(chat, "decorate_payload", lambda payload: payload)
    user = RequestUser(role="user", holder="integrator", key_value="les-user-test", source="api_key")
    request = chat.ChatRequest(question="Сделай ЛСР", mode="smeta", attachment_id="read_123456abcdef")

    first = await chat.chat(request, _user=user, idempotency_key="ladcraft-chat-001")
    second = await chat.chat(request, _user=user, idempotency_key="ladcraft-chat-001")

    assert first == second
    assert calls == 1

    with pytest.raises(HTTPException) as conflict:
        await chat.chat(
            chat.ChatRequest(question="Другая ЛСР", mode="smeta", attachment_id="read_123456abcdef"),
            _user=user,
            idempotency_key="ladcraft-chat-001",
        )
    assert conflict.value.status_code == 409
