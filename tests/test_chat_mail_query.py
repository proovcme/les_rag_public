import asyncio
from email.message import EmailMessage
from types import SimpleNamespace

import pytest

from proxy.routers import chat as chat_router
from proxy.services.model_connection_contracts import ConnectionLocality
from proxy.services.model_execution_preset_service import ModelExecutionPreset
from proxy.services.openai_compatible_transport_service import InferenceResponse


def _write_message(path, *, subject, sender, to, message_id, body, date):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg["Date"] = date
    msg["Message-ID"] = message_id
    msg.set_content(body)
    path.write_bytes(msg.as_bytes())


class MailBackend:
    collection_name = "test_collection"

    def __init__(self, content_dir):
        self.content_dir = content_dir

    async def list_datasets(self):
        return [SimpleNamespace(id="mail-ds", name="MAIL_Index")]

    async def retrieve(self, *args, **kwargs):
        raise AssertionError("production mail search must use the native retrieval contract")


@pytest.mark.asyncio
async def test_chat_does_not_replace_model_with_deterministic_mail_answer(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta_qwen.db"))
    root = tmp_path / "storage" / "datasets" / "mail-ds" / "MAIL"
    root.mkdir(parents=True)
    _write_message(
        root / "01.eml",
        subject="Dropbox notice",
        sender="Dropbox <no-reply@dropbox.com>",
        to="User <user@example.com>",
        message_id="<m1@example.com>",
        body="Welcome to Dropbox.",
        date="Tue, 26 May 2026 09:00:00 +0300",
    )

    chat_router.set_chat_state(
        chat_router.ChatRouterState(
            rag_backend=MailBackend(tmp_path / "storage" / "datasets"),
            llm_semaphore=asyncio.Semaphore(1),
            crag_stats={"verified": 0, "no_data": 0, "hallucination": 0},
            chat_metrics={
                "latency_search": [],
                "latency_gen": [],
                "tokens": [],
                "crag_pass": 0,
                "crag_fail": 0,
            },
            reranker_available=False,
            reranker_cls=None,
            current_mode={"mode": "chat"},
            metrics_cache={"ram_free_gb": 12.0, "swap_pct": 0.0},
        )
    )

    connection = SimpleNamespace(
        connection_id="test-answer",
        revision_id="test-answer:r1",
        display_name="Test answer model",
        model_id="test-model",
        locality=ConnectionLocality.LOOPBACK,
        base_url="http://127.0.0.1:1/v1",
        secret_ref="",
        effective_preset=ModelExecutionPreset(
            preset_id="mail-test",
            model_family="fixture",
            input_token_limit=6000,
            generation_reserve_tokens=512,
            safety_reserve_tokens=128,
            normal_tool_count=3,
            max_tools=5,
            max_batch_items=5,
            parallel_read_limit=1,
            reasoning_enabled=False,
            source_chain=("test",),
        ),
    )

    class Resolver:
        def resolve(self, _role, *, required_capabilities=frozenset()):
            return connection

    class Transport:
        async def complete(self, _connection, _request):
            return InferenceResponse(
                text="MODEL_OWNED_MAIL_ANSWER",
                tool_calls=(),
                finish_reason="stop",
                usage={},
            )

    async def skip_live_capability_refresh(_client):
        return None

    monkeypatch.setattr(
        chat_router, "_model_connection_resolver", lambda: (Resolver(), object())
    )
    monkeypatch.setattr(
        chat_router, "OpenAICompatibleTransport", lambda **_kwargs: Transport()
    )
    monkeypatch.setattr(
        chat_router,
        "_refresh_stale_bound_model_capabilities",
        skip_live_capability_refresh,
    )

    response = await chat_router.chat(
        chat_router.ChatRequest(
            question="Найди письма про Dropbox",
            semantic_cache_enabled=False,
        ),
        _user=object(),
    )

    assert response["answer"] == "MODEL_OWNED_MAIL_ANSWER"
    assert response["cache"] != "deterministic_mail"
    assert "Dropbox notice" not in response["answer"]
