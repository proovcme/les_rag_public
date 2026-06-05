from email.message import EmailMessage
from types import SimpleNamespace

import pytest

from proxy.routers import chat as chat_router


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
        raise AssertionError("deterministic mail query should not call vector retrieval")


@pytest.mark.asyncio
async def test_chat_answers_mail_query_without_llm_or_vector_retrieval(tmp_path, monkeypatch):
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
            llm_semaphore=SimpleNamespace(_value=1),
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

    response = await chat_router.chat(
        chat_router.ChatRequest(
            question="Найди письма про Dropbox",
            semantic_cache_enabled=False,
        ),
        _user=object(),
    )

    assert response["crag_status"] == "VERIFIED"
    assert response["effective_dataset_filter"] == "MAIL"
    assert response["query_route"]["channel"] == "mail"
    assert response["cache"] == "deterministic_mail"
    assert response["mail_query"]["mode"] == "mail_messages"
    assert "Dropbox notice" in response["answer"]
    assert response["history_id"] is not None
