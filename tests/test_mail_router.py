import asyncio
from collections import deque
from dataclasses import dataclass
from email.message import EmailMessage

import pytest

from backend.mail_ingest import ImapFetchedFile
from proxy.routers import datasets, mail


@dataclass
class Dataset:
    id: str
    name: str
    status: str = "IDLE"
    doc_count: int = 0
    chunk_count: int = 0


class FakeBackend:
    def __init__(self):
        self.datasets: list[Dataset] = []
        self.uploads = []
        self.parses = []

    async def list_datasets(self):
        return self.datasets

    async def create_dataset(self, name):
        dataset_id = f"ds-{len(self.datasets) + 1}"
        self.datasets.append(Dataset(dataset_id, name))
        return dataset_id

    async def upload_file(self, dataset_id, file_path, relative_path=None):
        self.uploads.append((dataset_id, file_path.name, relative_path))
        return f"doc-{len(self.uploads)}"

    async def parse_dataset(self, dataset_id, limit=None):
        self.parses.append((dataset_id, limit))
        return {"status": "completed", "chunks": 1, "remaining_pending": 0, "errors": 0}

    async def health(self):
        return True


class FakeJobService:
    def create(self, *args, **kwargs):
        return {"id": "job-1", "started_at": "2026-05-26T00:00:00"}

    def update(self, *args, **kwargs):
        return {}


@pytest.fixture()
def mail_state():
    previous = datasets._state
    backend = FakeBackend()
    datasets.set_dataset_state(
        datasets.DatasetRouterState(
            rag_backend=backend,
            job_service=FakeJobService(),
            job_tracker={},
            log_history=deque(maxlen=10),
            parse_semaphore=asyncio.Semaphore(1),
            sync_parse_semaphore=asyncio.Semaphore(1),
        )
    )
    yield backend
    datasets._state = previous


def _write_eml(path):
    msg = EmailMessage()
    msg["Subject"] = "Письмо по проекту"
    msg["From"] = "author@example.com"
    msg["To"] = "les@example.com"
    msg.set_content("Прошу проверить вложения.")
    path.write_bytes(msg.as_bytes())


def _write_thread_eml(path, *, subject, sender, to, message_id, body, date, in_reply_to="", references=""):
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


@pytest.mark.asyncio
async def test_mail_status_reports_missing_mail_dataset(mail_state):
    status = await mail.mail_status(_user=object())

    assert status["component"] == "Е.Ж.И.К."
    assert status["status"] == "not_created"
    assert status["dataset_name"] == "MAIL_Index"


@pytest.mark.asyncio
async def test_import_local_mail_creates_mail_dataset_and_registers_files(tmp_path, monkeypatch, mail_state):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "RAG_Content" / "MAIL" / "ProjectA"
    source.mkdir(parents=True)
    _write_eml(source / "letter.eml")

    result = await mail.import_local_mail(
        mail.MailLocalImportRequest(source_folder="MAIL", parse=False),
        _admin=object(),
    )

    assert result["status"] == "registered"
    assert result["dataset_name"] == "MAIL_Index"
    assert result["dataset_created"] is True
    assert result["files"] == 1
    assert mail_state.uploads == [("ds-1", "letter.eml", "MAIL/ProjectA/letter.eml")]
    assert result["summaries"][0]["subject"] == "Письмо по проекту"
    assert result["parse_started"] is False


@pytest.mark.asyncio
async def test_import_local_mail_defers_parse_during_indexing_mode(tmp_path, monkeypatch, mail_state):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "RAG_Content" / "MAIL"
    source.mkdir(parents=True)
    _write_eml(source / "letter.eml")
    datasets.get_dataset_state().current_mode = {"mode": "indexing"}

    result = await mail.import_local_mail(
        mail.MailLocalImportRequest(source_folder="MAIL", parse=True),
        _admin=object(),
    )

    assert result["parse_started"] is False
    assert result["parse_blocked"] == "indexing mode active"
    assert mail_state.parses == []


@pytest.mark.asyncio
async def test_import_local_mail_defers_parse_during_guarded_reindex(tmp_path, monkeypatch, mail_state):
    class FakeDispatcher:
        def __init__(self, **kwargs):
            pass

        def reindex_status_payload(self):
            return {"running": True}

    monkeypatch.setattr(mail, "RuntimeDispatcher", FakeDispatcher)
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "RAG_Content" / "MAIL"
    source.mkdir(parents=True)
    _write_eml(source / "letter.eml")
    datasets.get_dataset_state().current_mode = {"mode": "chat"}

    result = await mail.import_local_mail(
        mail.MailLocalImportRequest(source_folder="MAIL", parse=True),
        _admin=object(),
    )

    assert result["parse_started"] is False
    assert result["parse_blocked"] == "guarded reindex active"
    assert mail_state.parses == []


@pytest.mark.asyncio
async def test_mail_status_reports_imap_config(monkeypatch, mail_state):
    monkeypatch.setenv("MAIL_IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("MAIL_IMAP_LOGIN", "mail@example.com")
    monkeypatch.setenv("MAIL_IMAP_PASSWORD", "secret")
    monkeypatch.setenv("MAIL_IMAP_FOLDERS", "INBOX,Archive")

    status = await mail.mail_status(_user=object())

    assert status["imap"]["enabled"] is True
    assert status["imap"]["host"] == "imap.example.com"
    assert status["imap"]["login"] == "ma***l@example.com"
    assert status["imap"]["folders"] == ["INBOX", "Archive"]


@pytest.mark.asyncio
async def test_import_imap_mail_registers_fetched_eml(tmp_path, monkeypatch, mail_state):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAIL_IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("MAIL_IMAP_LOGIN", "mail@example.com")
    monkeypatch.setenv("MAIL_IMAP_PASSWORD", "secret")
    source = tmp_path / "RAG_Content" / "MAIL" / "IMAP" / "mail@example.com" / "INBOX"
    source.mkdir(parents=True)
    eml = source / "0000000001_test.eml"
    _write_eml(eml)

    monkeypatch.setattr(
        mail,
        "fetch_imap_eml_files",
        lambda settings, max_messages: [
            ImapFetchedFile(
                path=eml,
                relative_path="MAIL/IMAP/mail@example.com/INBOX/0000000001_test.eml",
                folder="INBOX",
                uid=1,
                subject="Письмо по проекту",
                message_id="<m1>",
            )
        ],
    )

    result = await mail.import_imap_mail(mail.MailImapImportRequest(parse=False), _admin=object())

    assert result["status"] == "registered"
    assert result["dataset_name"] == "MAIL_Index"
    assert result["files"] == 1
    assert mail_state.uploads == [
        ("ds-1", "0000000001_test.eml", "MAIL/IMAP/mail@example.com/INBOX/0000000001_test.eml")
    ]


@pytest.mark.asyncio
async def test_mail_threads_endpoint_returns_who_to_whom_and_chain(tmp_path, mail_state):
    content_dir = tmp_path / "storage" / "datasets"
    mail_state.content_dir = content_dir
    mail_state.datasets.append(Dataset("mail-ds", "MAIL_Index"))
    root = content_dir / "mail-ds" / "MAIL"
    root.mkdir(parents=True)
    _write_thread_eml(
        root / "01.eml",
        subject="Проект Б: письмо",
        sender="Alice <alice@example.com>",
        to="Bob <bob@example.com>",
        message_id="<b1@example.com>",
        body="Кто кому что отправил.",
        date="Tue, 26 May 2026 09:00:00 +0300",
    )
    _write_thread_eml(
        root / "02.eml",
        subject="Re: Проект Б: письмо",
        sender="Bob <bob@example.com>",
        to="Alice <alice@example.com>",
        message_id="<b2@example.com>",
        in_reply_to="<b1@example.com>",
        references="<b1@example.com>",
        body="Ответ по цепочке.",
        date="Tue, 26 May 2026 10:00:00 +0300",
    )

    result = await mail.list_mail_threads(
        q="Проект Б",
        participant="",
        limit=10,
        max_files=100,
        _user=object(),
    )

    assert result["total_threads"] == 1
    assert result["total_messages"] == 2
    thread = result["threads"][0]
    assert thread["subject"] == "Проект Б: письмо"
    assert thread["who_to_whom"]["from"] == "Bob <bob@example.com>"
    assert thread["who_to_whom"]["to"] == ["Alice <alice@example.com>"]
    assert thread["what"]["snippet"] == "Ответ по цепочке."

    detail = await mail.get_mail_thread(thread["thread_key"], max_files=100, _user=object())
    assert [message["sender"] for message in detail["messages"]] == [
        "Alice <alice@example.com>",
        "Bob <bob@example.com>",
    ]
    assert detail["edges"] == [{"from_message_id": "b1@example.com", "to_message_id": "b2@example.com"}]


@pytest.mark.asyncio
async def test_mail_messages_endpoint_filters_by_participant(tmp_path, mail_state):
    content_dir = tmp_path / "storage" / "datasets"
    mail_state.content_dir = content_dir
    mail_state.datasets.append(Dataset("mail-ds", "MAIL_Index"))
    root = content_dir / "mail-ds"
    root.mkdir(parents=True)
    _write_thread_eml(
        root / "01.eml",
        subject="Фильтр",
        sender="Alice <alice@example.com>",
        to="Bob <bob@example.com>",
        message_id="<f1@example.com>",
        body="Письмо для поиска.",
        date="Tue, 26 May 2026 09:00:00 +0300",
    )

    result = await mail.list_mail_messages(
        q="",
        participant="bob@example.com",
        thread_key="",
        limit=10,
        max_files=100,
        _user=object(),
    )

    assert result["total"] == 1
    assert result["messages"][0]["who_to_whom"]["to"] == ["Bob <bob@example.com>"]
