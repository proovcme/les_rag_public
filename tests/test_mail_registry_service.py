from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

import pytest
from llama_index.core.node_parser import SentenceSplitter

from backend.mail_ingest import ImapSettings
from backend.document_router import route_document
from backend.qdrant_adapter import QdrantLlamaIndexAdapter
from proxy.services.mail_registry_service import (
    MailRegistry,
    MemoryMailSecretStore,
    mail_dataset_name,
    set_mail_registry,
)
from proxy.services.mail_sync_service import parse_imap_list_row, sync_imap_account


def _eml(message_id: str, subject: str = "Test") -> bytes:
    message = EmailMessage()
    message["Message-ID"] = message_id
    message["Subject"] = subject
    message["From"] = "sender@example.com"
    message["To"] = "recipient@example.com"
    message["Date"] = "Thu, 17 Jul 2026 12:00:00 +0300"
    message.set_content("Evidence body")
    return message.as_bytes()


def _registry(tmp_path: Path) -> MailRegistry:
    return MailRegistry(tmp_path / "mail.db", secret_store=MemoryMailSecretStore())


def _account(registry: MailRegistry, label: str, suffix: str) -> dict:
    account_id = f"account-{suffix}"
    return registry.create_account(
        kind="imap",
        label=label,
        account_id=account_id,
        dataset_id=f"dataset-{suffix}",
        dataset_name=mail_dataset_name(label, account_id),
        config={"host": "imap.example.com", "login": f"{suffix}@example.com"},
        secret=f"secret-{suffix}",
    )


def test_each_mailbox_owns_a_separate_dataset_and_secret_is_not_persisted(tmp_path: Path):
    registry = _registry(tmp_path)
    first = _account(registry, "First", "one")
    second = _account(registry, "Second", "two")

    assert first["dataset_id"] != second["dataset_id"]
    assert first["dataset_name"] != second["dataset_name"]
    assert first["secret_set"] is True
    assert "secret-one" not in (tmp_path / "mail.db").read_bytes().decode("latin1")
    assert "password" not in first["config"]


def test_message_id_dedup_keeps_multiple_folder_locations_and_snapshot(tmp_path: Path):
    registry = _registry(tmp_path)
    account = _account(registry, "Mailbox", "one")
    raw_path = tmp_path / "message.eml"
    raw_path.write_bytes(_eml("<same@example.com>"))

    first, created = registry.register_message(
        account_id=account["id"],
        raw_path=raw_path,
        relative_path="Inbox/message.eml",
        source_kind="imap",
        native_id="Inbox:1",
        folder_native_id="Inbox",
        folder_path="Inbox",
    )
    second, created_again = registry.register_message(
        account_id=account["id"],
        raw_path=raw_path,
        relative_path="Archive/message.eml",
        source_kind="imap",
        native_id="Archive:9",
        folder_native_id="Archive",
        folder_path="Archive",
    )

    assert created is True
    assert created_again is False
    assert first["id"] == second["id"]
    assert {item["folder_path"] for item in second["locations"]} == {"Inbox", "Archive"}

    registry.reconcile_folder_locations(account["id"], "Inbox", set())
    snapshot = registry.get_message(first["id"])
    assert snapshot["raw_path"]
    assert next(item for item in snapshot["locations"] if item["folder_path"] == "Inbox")["is_current"] == 0


def test_attachment_sha256_has_one_context_owner_but_keeps_message_provenance(tmp_path: Path):
    registry = _registry(tmp_path)
    account = _account(registry, "Mailbox", "one")
    first_path = tmp_path / "first.eml"
    second_path = tmp_path / "second.eml"
    first_path.write_bytes(_eml("<first@example.com>"))
    second_path.write_bytes(_eml("<second@example.com>"))
    first_message, _ = registry.register_message(
        account_id=account["id"], raw_path=first_path, relative_path="first.eml",
        source_kind="imap", native_id="1",
    )
    second_message, _ = registry.register_message(
        account_id=account["id"], raw_path=second_path, relative_path="second.eml",
        source_kind="imap", native_id="2",
    )
    first = registry.register_attachment_provenance(
        account_id=account["id"], message_id=first_message["id"],
        attachment_id="attachment-one", attachment_sha256="a" * 64,
    )
    duplicate = registry.register_attachment_provenance(
        account_id=account["id"], message_id=second_message["id"],
        attachment_id="attachment-two", attachment_sha256="a" * 64,
    )

    assert first["canonical"] is True
    assert duplicate["canonical"] is False
    assert duplicate["canonical_message_id"] == first_message["id"]
    assert duplicate["provenance_count"] == 2


def test_registered_eml_projects_exact_account_provenance_and_deduplicated_attachment_nodes(tmp_path: Path):
    registry = _registry(tmp_path)
    account = _account(registry, "Mailbox", "one")

    def write(path: Path, message_id: str) -> None:
        message = EmailMessage()
        message["Message-ID"] = message_id
        message["Subject"] = "Одинаковое доказательство"
        message["From"] = "sender@example.com"
        message["To"] = "recipient@example.com"
        message.set_content("Подробное содержание письма для индексируемого evidence context. " * 4)
        message.add_attachment(
            b"same attachment evidence text",
            maintype="text", subtype="plain", filename="evidence.txt",
        )
        path.write_bytes(message.as_bytes())

    first_path = tmp_path / "first.eml"
    second_path = tmp_path / "second.eml"
    write(first_path, "<first-projection@example.com>")
    write(second_path, "<second-projection@example.com>")
    for path in (first_path, second_path):
        registry.register_message(
            account_id=account["id"], raw_path=path, relative_path=path.name,
            source_kind="imap", native_id=path.stem,
            folder_native_id="INBOX", folder_path="INBOX",
        )

    adapter = QdrantLlamaIndexAdapter.__new__(QdrantLlamaIndexAdapter)
    splitter = SentenceSplitter(chunk_size=1400, chunk_overlap=100)
    set_mail_registry(registry)
    try:
        first_nodes = adapter._sync_mail_nodes(
            first_path, tmp_path, first_path.name, account["dataset_id"], splitter,
            route_document(first_path),
        )
        second_nodes = adapter._sync_mail_nodes(
            second_path, tmp_path, second_path.name, account["dataset_id"], splitter,
            route_document(second_path),
        )
    finally:
        set_mail_registry(None)

    first_payloads = [node["payload"] for node in first_nodes]
    second_payloads = [node["payload"] for node in second_nodes]
    assert any(payload["mail_node_kind"] == "attachment" for payload in first_payloads)
    assert not any(payload["mail_node_kind"] == "attachment" for payload in second_payloads)
    second_message = next(payload for payload in second_payloads if payload["mail_node_kind"] == "message")
    assert second_message["mail_account_id"] == account["id"]
    assert second_message["mail_dataset_id"] == account["dataset_id"]
    assert second_message["mail_folders"] == ["INBOX"]
    assert len(second_message["mail_content_sha256"]) == 64
    assert len(second_message["mail_attachments"][0]["sha256"]) == 64


class FakeImap:
    def __init__(self, messages: dict[int, bytes], *, uid_validity: str = "10", fail_uid: int = 0):
        self.messages = messages
        self.uid_validity = uid_validity
        self.fail_uid = fail_uid
        self.fetch_specs: list[str] = []
        self.readonly: list[bool] = []

    def login(self, _login: str, _password: str):
        return "OK", []

    def list(self):
        return "OK", [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\Junk) "/" "Spam"',
            b'(\\Drafts) "/" "Drafts"',
        ]

    def select(self, _folder: str, readonly: bool = False):
        self.readonly.append(readonly)
        return "OK", [str(len(self.messages)).encode()]

    def response(self, _name: str):
        return "UIDVALIDITY", [self.uid_validity.encode()]

    def uid(self, command: str, _arg: object, value: str):
        if command == "SEARCH":
            minimum = 1
            if value.startswith("UID "):
                minimum = int(value.split()[1].split(":", 1)[0])
            found = " ".join(str(uid) for uid in self.messages if uid >= minimum)
            return "OK", [found.encode()]
        uid = int(_arg)
        self.fetch_specs.append(value)
        if uid == self.fail_uid:
            return "NO", []
        raw = self.messages[uid]
        return "OK", [(f"{uid} (BODY[] {{{len(raw)}}})".encode(), raw)]

    def logout(self):
        return "BYE", []


def _settings(tmp_path: Path) -> ImapSettings:
    return ImapSettings(
        host="imap.example.com",
        port=993,
        login="one@example.com",
        password="app-password",
        ssl=True,
        folders=["*"],
        checkpoint_dir=tmp_path / "checkpoints",
        storage_root=tmp_path / "raw",
    )


def test_imap_is_read_only_peek_excludes_special_folders_and_advances_after_registration(tmp_path: Path):
    registry = _registry(tmp_path)
    account = _account(registry, "Mailbox", "one")
    fake = FakeImap({1: _eml("<one@example.com>"), 2: _eml("<two@example.com>")})

    files = sync_imap_account(
        _settings(tmp_path),
        registry,
        account_id=account["id"],
        client_factory=lambda _host, _port: fake,
    )

    assert len(files) == 2
    assert fake.readonly == [True]
    assert fake.fetch_specs == ["(BODY.PEEK[])", "(BODY.PEEK[])"]
    assert registry.get_folder(account["id"], "INBOX")["last_uid"] == 2
    assert {folder["path"] for folder in registry.list_folders(account["id"])} == {"INBOX"}


def test_failed_message_does_not_advance_cursor_past_failure(tmp_path: Path):
    registry = _registry(tmp_path)
    account = _account(registry, "Mailbox", "one")
    fake = FakeImap(
        {1: _eml("<one@example.com>"), 2: _eml("<two@example.com>"), 3: _eml("<three@example.com>")},
        fail_uid=2,
    )

    with pytest.raises(RuntimeError, match="UID 2"):
        sync_imap_account(
            _settings(tmp_path),
            registry,
            account_id=account["id"],
            client_factory=lambda _host, _port: fake,
        )

    assert registry.get_folder(account["id"], "INBOX")["last_uid"] == 1


def test_sync_error_does_not_persist_app_password(tmp_path: Path):
    registry = _registry(tmp_path)
    account = _account(registry, "Mailbox", "one")

    class LoginFailure(FakeImap):
        def login(self, _login: str, password: str):
            raise RuntimeError(f"authentication failed for {password}")

    with pytest.raises(RuntimeError):
        sync_imap_account(
            _settings(tmp_path), registry, account_id=account["id"],
            client_factory=lambda *_: LoginFailure({}),
        )

    saved = registry.get_account(account["id"], include_secret_state=False)
    assert "app-password" not in saved["last_error"]
    assert "[redacted]" in saved["last_error"]


def test_uidvalidity_change_resets_cursor_for_safe_deduplicated_reconciliation(tmp_path: Path):
    registry = _registry(tmp_path)
    account = _account(registry, "Mailbox", "one")
    first = FakeImap({1: _eml("<same@example.com>")}, uid_validity="10")
    sync_imap_account(
        _settings(tmp_path), registry, account_id=account["id"], client_factory=lambda *_: first
    )
    second = FakeImap({1: _eml("<same@example.com>")}, uid_validity="20")
    result = sync_imap_account(
        _settings(tmp_path), registry, account_id=account["id"], client_factory=lambda *_: second
    )

    assert len(result) == 1
    assert result[0].created is False
    assert registry.get_folder(account["id"], "INBOX")["uid_validity"] == "20"
    assert len(registry.list_messages(account_id=account["id"])) == 1


def test_full_backfill_resumes_after_confirmed_batch_instead_of_repeating_first_page(tmp_path: Path):
    registry = _registry(tmp_path)
    account = _account(registry, "Mailbox", "one")
    messages = {
        1: _eml("<one@example.com>"),
        2: _eml("<two@example.com>"),
        3: _eml("<three@example.com>"),
    }
    first = FakeImap(messages)
    first_batch = sync_imap_account(
        _settings(tmp_path), registry, account_id=account["id"], mode="full", max_messages=2,
        client_factory=lambda *_: first,
    )
    second = FakeImap(messages)
    second_batch = sync_imap_account(
        _settings(tmp_path), registry, account_id=account["id"], mode="full", max_messages=2,
        client_factory=lambda *_: second,
    )

    assert [item.file.uid for item in first_batch] == [1, 2]
    assert [item.file.uid for item in second_batch] == [3]
    assert registry.get_folder(account["id"], "INBOX")["backfill_complete"] is True


def test_parse_imap_list_row_uses_special_use_not_localized_name():
    folder = parse_imap_list_row('(\\Junk \\HasNoChildren) "/" "Нежелательная почта"')
    assert folder is not None
    assert folder.special_use == "\\junk"
