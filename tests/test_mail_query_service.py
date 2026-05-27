from email.message import EmailMessage
from types import SimpleNamespace

import pytest

from proxy.services.mail_query_service import maybe_answer_mail_query


def _write_message(path, *, subject, sender, to, message_id, body, date, in_reply_to="", references=""):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg["Date"] = date
    msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    msg.set_content(body)
    path.write_bytes(msg.as_bytes())


class FakeMailBackend:
    def __init__(self, content_dir):
        self.content_dir = content_dir

    async def list_datasets(self):
        return [SimpleNamespace(id="mail-ds", name="MAIL_Index")]


@pytest.mark.asyncio
async def test_mail_query_lists_matching_messages(tmp_path):
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

    result = await maybe_answer_mail_query(
        "Найди письма про Dropbox. Ответь коротко.",
        FakeMailBackend(tmp_path / "storage" / "datasets"),
    )

    assert result is not None
    assert result.mode == "mail_messages"
    assert result.query == "dropbox"
    assert result.total == 1
    assert "Dropbox notice" in result.answer
    assert "Welcome to Dropbox" not in result.answer
    assert result.sources == ["MAIL/01.eml"]


@pytest.mark.asyncio
async def test_mail_query_summarizes_threads(tmp_path):
    root = tmp_path / "storage" / "datasets" / "mail-ds" / "MAIL"
    root.mkdir(parents=True)
    _write_message(
        root / "01.eml",
        subject="Проект Б",
        sender="Alice <alice@example.com>",
        to="Bob <bob@example.com>",
        message_id="<m1@example.com>",
        body="Первое письмо.",
        date="Tue, 26 May 2026 09:00:00 +0300",
    )
    _write_message(
        root / "02.eml",
        subject="Re: Проект Б",
        sender="Bob <bob@example.com>",
        to="Alice <alice@example.com>",
        message_id="<m2@example.com>",
        in_reply_to="<m1@example.com>",
        references="<m1@example.com>",
        body="Ответ по цепочке.",
        date="Tue, 26 May 2026 10:00:00 +0300",
    )

    result = await maybe_answer_mail_query(
        "Покажи цепочку писем проект",
        FakeMailBackend(tmp_path / "storage" / "datasets"),
    )

    assert result is not None
    assert result.mode == "mail_threads"
    assert result.total == 1
    assert "Проект Б" in result.answer
    assert set(result.sources) == {"MAIL/01.eml", "MAIL/02.eml"}
