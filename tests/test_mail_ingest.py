from email.message import EmailMessage

import pytest

from backend.mail_ingest import ImapSettings, fetch_imap_eml_files, resolve_mail_source_folder, summarize_mail_files


def test_mail_ingest_summarizes_eml_headers_and_attachments(tmp_path):
    source = tmp_path / "RAG_Content" / "MAIL"
    source.mkdir(parents=True)
    msg = EmailMessage()
    msg["Subject"] = "Исполнительная документация"
    msg["From"] = "author@example.com"
    msg["To"] = "les@example.com"
    msg["Date"] = "Sat, 23 May 2026 10:00:00 +0300"
    msg["Message-ID"] = "<mail-1@example.com>"
    msg.set_content("Добрый день.")
    msg.add_attachment(b"pdf", maintype="application", subtype="pdf", filename="aosr.pdf")
    (source / "letter.eml").write_bytes(msg.as_bytes())

    summaries = summarize_mail_files(source)

    assert len(summaries) == 1
    assert summaries[0].relative_path == "letter.eml"
    assert summaries[0].subject == "Исполнительная документация"
    assert summaries[0].sender == "author@example.com"
    assert summaries[0].attachments == ["aosr.pdf"]


def test_mail_source_folder_must_stay_under_rag_content(tmp_path):
    base = tmp_path / "RAG_Content"
    base.mkdir()

    with pytest.raises(ValueError):
        resolve_mail_source_folder("../Secrets", base=base)


def test_fetch_imap_eml_files_saves_new_messages_and_checkpoint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raw = EmailMessage()
    raw["Subject"] = "Новая заявка"
    raw["From"] = "author@example.com"
    raw["To"] = "les@example.com"
    raw["Message-ID"] = "<imap-1@example.com>"
    raw.set_content("Письмо из IMAP.")

    class FakeImap:
        def __init__(self, host, port):
            self.host = host
            self.port = port

        def login(self, login, password):
            assert login == "mail@example.com"
            assert password == "secret"
            return "OK", []

        def select(self, folder, readonly=True):
            assert folder == '"INBOX"'
            return "OK", []

        def uid(self, command, *args):
            if command == "SEARCH":
                return "OK", [b"101"]
            if command == "FETCH":
                return "OK", [(b"101 (RFC822 {10}", raw.as_bytes()), b")"]
            raise AssertionError(command)

        def logout(self):
            return "OK", []

    settings = ImapSettings(
        host="imap.example.com",
        port=993,
        login="mail@example.com",
        password="secret",
        ssl=True,
        folders=["INBOX"],
        checkpoint_dir=tmp_path / "checkpoints",
        storage_root=tmp_path / "RAG_Content" / "MAIL" / "IMAP",
    )

    fetched = fetch_imap_eml_files(settings, max_messages=10, client_factory=FakeImap)

    assert len(fetched) == 1
    assert fetched[0].uid == 101
    assert fetched[0].relative_path.startswith("MAIL/IMAP/mail@example.com/INBOX/")
    assert fetched[0].path.exists()
    assert '"last_uid": 101' in next(settings.checkpoint_dir.glob("*.json")).read_text(encoding="utf-8")
