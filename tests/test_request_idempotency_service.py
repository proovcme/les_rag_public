from __future__ import annotations

import io

import pytest
from fastapi import HTTPException, UploadFile

from proxy.routers import chat, datasets
from proxy.security import RequestUser
from proxy.services import request_idempotency_service as idem


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
