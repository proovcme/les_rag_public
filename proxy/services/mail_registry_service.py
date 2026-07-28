"""Typed local registry for the E.ZH.I.K. mail collector.

The registry is deliberately separate from Qdrant: it owns exact account,
folder, cursor and source identities while ``MAIL_Index`` remains the hybrid
retrieval projection.  Raw messages are immutable snapshots; upstream deletes
never remove local evidence implicitly.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import uuid
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from backend.mail_threads import parse_mail_message


MAIL_ACCOUNT_KINDS = {"imap", "outlook_classic"}
CREDENTIAL_SERVICE_PREFIX = "me.ovc.les.mail"
DATASET_SAFE_RE = re.compile(r"[^A-Za-z0-9А-Яа-яЁё_.@+-]+")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_message_id(value: str) -> str:
    return str(value or "").strip().strip("<>").casefold()


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        payload = json.loads(str(value))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def mail_dataset_name(label: str, account_id: str) -> str:
    """Return the stable display name for one mailbox's private P0 dataset."""
    safe = DATASET_SAFE_RE.sub("_", str(label or "mailbox").strip()).strip("_.")
    return f"MAIL_{safe or 'mailbox'}_{account_id[:8]}_Index"


class MailSecretStore:
    def set(self, account_id: str, secret: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def get(self, account_id: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def delete(self, account_id: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def is_set(self, account_id: str) -> bool:
        try:
            return bool(self.get(account_id))
        except Exception:
            return False


class MemoryMailSecretStore(MailSecretStore):
    """Explicit test backend; never selected silently in production."""

    _values: dict[str, str] = {}

    def set(self, account_id: str, secret: str) -> None:
        self._values[account_id] = secret

    def get(self, account_id: str) -> str:
        return self._values.get(account_id, "")

    def delete(self, account_id: str) -> None:
        self._values.pop(account_id, None)


class MacOSKeychainMailSecretStore(MailSecretStore):
    def _service(self, account_id: str) -> str:
        return f"{CREDENTIAL_SERVICE_PREFIX}.{account_id}"

    def set(self, account_id: str, secret: str) -> None:
        subprocess.run(
            [
                "/usr/bin/security",
                "add-generic-password",
                "-U",
                "-a",
                "les",
                "-s",
                self._service(account_id),
                "-w",
                secret,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

    def get(self, account_id: str) -> str:
        result = subprocess.run(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-a",
                "les",
                "-s",
                self._service(account_id),
                "-w",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout.rstrip("\r\n") if result.returncode == 0 else ""

    def delete(self, account_id: str) -> None:
        subprocess.run(
            [
                "/usr/bin/security",
                "delete-generic-password",
                "-a",
                "les",
                "-s",
                self._service(account_id),
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


class WindowsCredentialMailSecretStore(MailSecretStore):
    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    class _CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", wintypes.LPVOID),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    def __init__(self) -> None:
        self._advapi = ctypes.WinDLL("Advapi32.dll")
        self._advapi.CredWriteW.argtypes = [ctypes.POINTER(self._CREDENTIALW), wintypes.DWORD]
        self._advapi.CredWriteW.restype = wintypes.BOOL
        self._advapi.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(self._CREDENTIALW)),
        ]
        self._advapi.CredReadW.restype = wintypes.BOOL
        self._advapi.CredFree.argtypes = [wintypes.LPVOID]
        self._advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self._advapi.CredDeleteW.restype = wintypes.BOOL

    @staticmethod
    def _target(account_id: str) -> str:
        return f"{CREDENTIAL_SERVICE_PREFIX}.{account_id}"

    def set(self, account_id: str, secret: str) -> None:
        raw = secret.encode("utf-8")
        blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        credential = self._CREDENTIALW()
        credential.Type = self.CRED_TYPE_GENERIC
        credential.TargetName = self._target(account_id)
        credential.UserName = "LES mail account"
        credential.CredentialBlobSize = len(raw)
        credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        if not self._advapi.CredWriteW(ctypes.byref(credential), 0):
            raise ctypes.WinError()

    def get(self, account_id: str) -> str:
        ptr = ctypes.POINTER(self._CREDENTIALW)()
        ok = self._advapi.CredReadW(
            self._target(account_id), self.CRED_TYPE_GENERIC, 0, ctypes.byref(ptr)
        )
        if not ok:
            return ""
        try:
            credential = ptr.contents
            raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            return raw.decode("utf-8")
        finally:
            self._advapi.CredFree(ptr)

    def delete(self, account_id: str) -> None:
        self._advapi.CredDeleteW(self._target(account_id), self.CRED_TYPE_GENERIC, 0)


def default_mail_secret_store() -> MailSecretStore:
    backend = os.getenv("LES_MAIL_SECRET_BACKEND", "").strip().casefold()
    if backend == "memory":
        return MemoryMailSecretStore()
    if sys.platform.startswith("win"):
        return WindowsCredentialMailSecretStore()
    if sys.platform == "darwin" and Path("/usr/bin/security").exists():
        return MacOSKeychainMailSecretStore()
    raise RuntimeError("secure mail secret storage is unavailable on this platform")


class MailRegistry:
    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        secret_store: MailSecretStore | None = None,
    ) -> None:
        self.db_path = Path(
            db_path or os.getenv("LES_MAIL_REGISTRY_DB", "data/mail_registry.db")
        ).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.secret_store = secret_store
        self._lock = RLock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS mail_accounts (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    label TEXT NOT NULL,
                    dataset_id TEXT NOT NULL DEFAULT '',
                    dataset_name TEXT NOT NULL DEFAULT '',
                    native_account_id TEXT NOT NULL DEFAULT '',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    sync_state TEXT NOT NULL DEFAULT 'idle',
                    last_sync TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uq_mail_account_native
                    ON mail_accounts(kind, native_account_id)
                    WHERE native_account_id <> '';

                CREATE TABLE IF NOT EXISTS mail_folders (
                    account_id TEXT NOT NULL,
                    native_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    special_use TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    uid_validity TEXT NOT NULL DEFAULT '',
                    last_uid INTEGER NOT NULL DEFAULT 0,
                    backfill_complete INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(account_id, native_id),
                    FOREIGN KEY(account_id) REFERENCES mail_accounts(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS mail_messages (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    native_id TEXT NOT NULL DEFAULT '',
                    internet_message_id TEXT NOT NULL DEFAULT '',
                    content_sha256 TEXT NOT NULL,
                    subject TEXT NOT NULL DEFAULT '',
                    sender TEXT NOT NULL DEFAULT '',
                    recipients_json TEXT NOT NULL DEFAULT '[]',
                    received_at TEXT NOT NULL DEFAULT '',
                    sent_at TEXT NOT NULL DEFAULT '',
                    thread_key TEXT NOT NULL DEFAULT '',
                    raw_path TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    outlook_store_id TEXT NOT NULL DEFAULT '',
                    outlook_entry_id TEXT NOT NULL DEFAULT '',
                    index_status TEXT NOT NULL DEFAULT 'pending',
                    rag_doc_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(account_id) REFERENCES mail_accounts(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS ix_mail_messages_account_date
                    ON mail_messages(account_id, received_at DESC);
                CREATE INDEX IF NOT EXISTS ix_mail_messages_thread
                    ON mail_messages(thread_key);
                CREATE INDEX IF NOT EXISTS ix_mail_messages_hash
                    ON mail_messages(content_sha256);

                CREATE TABLE IF NOT EXISTS mail_message_locations (
                    message_id TEXT NOT NULL,
                    folder_native_id TEXT NOT NULL,
                    folder_path TEXT NOT NULL,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    is_current INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY(message_id, folder_native_id),
                    FOREIGN KEY(message_id) REFERENCES mail_messages(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS mail_attachment_provenance (
                    account_id TEXT NOT NULL,
                    attachment_sha256 TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    attachment_id TEXT NOT NULL,
                    first_seen TEXT NOT NULL,
                    PRIMARY KEY(account_id,attachment_sha256,message_id,attachment_id),
                    FOREIGN KEY(account_id) REFERENCES mail_accounts(id) ON DELETE CASCADE,
                    FOREIGN KEY(message_id) REFERENCES mail_messages(id) ON DELETE CASCADE
                );
                """
            )
            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(mail_accounts)").fetchall()
            }
            if "dataset_id" not in columns:
                conn.execute(
                    "ALTER TABLE mail_accounts ADD COLUMN dataset_id TEXT NOT NULL DEFAULT ''"
                )
            if "dataset_name" not in columns:
                conn.execute(
                    "ALTER TABLE mail_accounts ADD COLUMN dataset_name TEXT NOT NULL DEFAULT ''"
                )

    def _store(self) -> MailSecretStore:
        if self.secret_store is None:
            self.secret_store = default_mail_secret_store()
        return self.secret_store

    def create_account(
        self,
        *,
        kind: str,
        label: str,
        config: dict[str, Any] | None = None,
        secret: str = "",
        native_account_id: str = "",
        account_id: str | None = None,
        dataset_id: str,
        dataset_name: str,
    ) -> dict[str, Any]:
        kind = str(kind or "").strip().casefold()
        if kind not in MAIL_ACCOUNT_KINDS:
            raise ValueError(f"unsupported mail account kind: {kind}")
        label = str(label or "").strip()
        if not label:
            raise ValueError("mail account label is required")
        config = dict(config or {})
        config.pop("password", None)
        account_id = account_id or str(uuid.uuid4())
        if not str(dataset_id or "").strip() or not str(dataset_name or "").strip():
            raise ValueError("every mail account requires its own dataset_id and dataset_name")
        now = _utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mail_accounts(
                    id,kind,label,dataset_id,dataset_name,native_account_id,config_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    account_id,
                    kind,
                    label,
                    dataset_id,
                    dataset_name,
                    native_account_id,
                    json.dumps(config, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
        if secret:
            self._store().set(account_id, secret)
        return self.get_account(account_id)

    def find_outlook_account(self, *, store_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM mail_accounts WHERE kind='outlook_classic' AND native_account_id=?",
                (store_id,),
            ).fetchone()
        return self.get_account(str(row["id"])) if row else None

    def update_account(
        self,
        account_id: str,
        *,
        label: str | None = None,
        enabled: bool | None = None,
        config: dict[str, Any] | None = None,
        secret: str | None = None,
    ) -> dict[str, Any]:
        current = self.get_account(account_id, include_secret_state=False)
        merged = dict(current["config"])
        if config is not None:
            merged.update(config)
            merged.pop("password", None)
        now = _utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE mail_accounts
                SET label=?, enabled=?, config_json=?, updated_at=?
                WHERE id=?
                """,
                (
                    str(label).strip() if label is not None else current["label"],
                    int(enabled) if enabled is not None else int(current["enabled"]),
                    json.dumps(merged, ensure_ascii=False, sort_keys=True),
                    now,
                    account_id,
                ),
            )
        if secret is not None:
            if secret:
                self._store().set(account_id, secret)
            else:
                self._store().delete(account_id)
        return self.get_account(account_id)

    def get_account(self, account_id: str, *, include_secret_state: bool = True) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM mail_accounts WHERE id=?", (account_id,)).fetchone()
        if not row:
            raise KeyError(account_id)
        payload = dict(row)
        payload["config"] = _json_dict(payload.pop("config_json", "{}"))
        payload["enabled"] = bool(payload["enabled"])
        if include_secret_state:
            try:
                payload["secret_set"] = (
                    self._store().is_set(account_id) if payload["kind"] == "imap" else False
                )
            except RuntimeError:
                payload["secret_set"] = False
        return payload

    def list_accounts(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id FROM mail_accounts ORDER BY label COLLATE NOCASE").fetchall()
        return [self.get_account(str(row["id"])) for row in rows]

    def status_summary(self) -> dict[str, Any]:
        """Small operator summary; no message bodies or secret state."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT index_status,COUNT(*) AS count FROM mail_messages GROUP BY index_status"
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM mail_messages").fetchone()[0]
        by_status = {str(row["index_status"]): int(row["count"]) for row in rows}
        indexed = sum(
            count
            for status, count in by_status.items()
            if status in {"indexed", "registered"}
        )
        errors = sum(
            count
            for status, count in by_status.items()
            if status in {"error", "failed"}
        )
        pending = max(0, int(total) - indexed - errors)
        return {
            "messages": int(total),
            "indexed": indexed,
            "pending": pending,
            "errors": errors,
            "by_status": by_status,
        }

    def account_secret(self, account_id: str) -> str:
        return self._store().get(account_id)

    def update_sync_state(self, account_id: str, state: str, *, error: str = "") -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE mail_accounts SET sync_state=?, last_sync=?, last_error=?, updated_at=? WHERE id=?",
                (state, now if state in {"completed", "idle"} else "", error[:500], now, account_id),
            )

    def upsert_folder(
        self,
        account_id: str,
        native_id: str,
        *,
        path: str,
        special_use: str = "",
        enabled: bool = True,
        uid_validity: str = "",
        last_uid: int | None = None,
        backfill_complete: bool | None = None,
    ) -> dict[str, Any]:
        current = self.get_folder(account_id, native_id) or {}
        if current and uid_validity and current.get("uid_validity") not in {"", uid_validity}:
            current["last_uid"] = 0
            current["backfill_complete"] = False
        now = _utc_now()
        payload = {
            "account_id": account_id,
            "native_id": native_id,
            "path": path,
            "special_use": special_use,
            "enabled": bool(enabled),
            "uid_validity": uid_validity or str(current.get("uid_validity") or ""),
            "last_uid": int(current.get("last_uid") or 0) if last_uid is None else int(last_uid),
            "backfill_complete": bool(current.get("backfill_complete"))
            if backfill_complete is None
            else bool(backfill_complete),
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mail_folders(
                    account_id,native_id,path,special_use,enabled,uid_validity,last_uid,backfill_complete,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(account_id,native_id) DO UPDATE SET
                    path=excluded.path,
                    special_use=excluded.special_use,
                    enabled=excluded.enabled,
                    uid_validity=excluded.uid_validity,
                    last_uid=excluded.last_uid,
                    backfill_complete=excluded.backfill_complete,
                    updated_at=excluded.updated_at
                """,
                (
                    account_id,
                    native_id,
                    path,
                    special_use,
                    int(payload["enabled"]),
                    payload["uid_validity"],
                    payload["last_uid"],
                    int(payload["backfill_complete"]),
                    now,
                ),
            )
        return payload

    def get_folder(self, account_id: str, native_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mail_folders WHERE account_id=? AND native_id=?",
                (account_id, native_id),
            ).fetchone()
        if not row:
            return None
        payload = dict(row)
        payload["enabled"] = bool(payload["enabled"])
        payload["backfill_complete"] = bool(payload["backfill_complete"])
        return payload

    def list_folders(self, account_id: str = "") -> list[dict[str, Any]]:
        with self._connect() as conn:
            if account_id:
                rows = conn.execute(
                    "SELECT * FROM mail_folders WHERE account_id=? ORDER BY path COLLATE NOCASE",
                    (account_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM mail_folders ORDER BY account_id,path COLLATE NOCASE"
                ).fetchall()
        payloads = []
        for row in rows:
            item = dict(row)
            item["enabled"] = bool(item["enabled"])
            item["backfill_complete"] = bool(item["backfill_complete"])
            payloads.append(item)
        return payloads

    @staticmethod
    def canonical_message_id(
        account_id: str,
        *,
        internet_message_id: str = "",
        native_id: str = "",
        content_sha256: str = "",
    ) -> str:
        message_id = _normalize_message_id(internet_message_id)
        if message_id:
            identity = f"mid:{message_id}"
        elif native_id:
            identity = f"native:{native_id}"
        else:
            identity = f"sha256:{content_sha256}"
        return hashlib.sha256(f"{account_id}|{identity}".encode("utf-8")).hexdigest()[:32]

    def register_message(
        self,
        *,
        account_id: str,
        raw_path: str | Path,
        relative_path: str,
        source_kind: str,
        native_id: str = "",
        internet_message_id: str = "",
        folder_native_id: str = "",
        folder_path: str = "",
        outlook_store_id: str = "",
        outlook_entry_id: str = "",
        received_at: str = "",
        sent_at: str = "",
    ) -> tuple[dict[str, Any], bool]:
        path = Path(raw_path)
        content_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        record = parse_mail_message(path, path.parent)
        internet_message_id = internet_message_id or record.message_id
        internal_id = self.canonical_message_id(
            account_id,
            internet_message_id=internet_message_id,
            native_id=native_id,
            content_sha256=content_sha256,
        )
        now = _utc_now()
        with self._lock, self._connect() as conn:
            exists = conn.execute("SELECT 1 FROM mail_messages WHERE id=?", (internal_id,)).fetchone()
            conn.execute(
                """
                INSERT INTO mail_messages(
                    id,account_id,native_id,internet_message_id,content_sha256,subject,sender,
                    recipients_json,received_at,sent_at,thread_key,raw_path,relative_path,source_kind,
                    outlook_store_id,outlook_entry_id,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    native_id=CASE WHEN excluded.native_id<>'' THEN excluded.native_id ELSE mail_messages.native_id END,
                    internet_message_id=CASE WHEN excluded.internet_message_id<>'' THEN excluded.internet_message_id ELSE mail_messages.internet_message_id END,
                    subject=excluded.subject,
                    sender=excluded.sender,
                    recipients_json=excluded.recipients_json,
                    received_at=CASE WHEN excluded.received_at<>'' THEN excluded.received_at ELSE mail_messages.received_at END,
                    sent_at=CASE WHEN excluded.sent_at<>'' THEN excluded.sent_at ELSE mail_messages.sent_at END,
                    thread_key=excluded.thread_key,
                    raw_path=excluded.raw_path,
                    relative_path=excluded.relative_path,
                    outlook_store_id=CASE WHEN excluded.outlook_store_id<>'' THEN excluded.outlook_store_id ELSE mail_messages.outlook_store_id END,
                    outlook_entry_id=CASE WHEN excluded.outlook_entry_id<>'' THEN excluded.outlook_entry_id ELSE mail_messages.outlook_entry_id END,
                    updated_at=excluded.updated_at
                """,
                (
                    internal_id,
                    account_id,
                    native_id,
                    _normalize_message_id(internet_message_id),
                    content_sha256,
                    record.subject,
                    record.sender,
                    json.dumps(record.recipients, ensure_ascii=False),
                    received_at or record.date,
                    sent_at,
                    record.thread_key,
                    path.as_posix(),
                    relative_path,
                    source_kind,
                    outlook_store_id,
                    outlook_entry_id,
                    now,
                    now,
                ),
            )
            if folder_native_id or folder_path:
                conn.execute(
                    """
                    INSERT INTO mail_message_locations(
                        message_id,folder_native_id,folder_path,first_seen,last_seen,is_current
                    ) VALUES(?,?,?,?,?,1)
                    ON CONFLICT(message_id,folder_native_id) DO UPDATE SET
                        folder_path=excluded.folder_path,
                        last_seen=excluded.last_seen,
                        is_current=1
                    """,
                    (internal_id, folder_native_id or folder_path, folder_path, now, now),
                )
        return self.get_message(internal_id), not bool(exists)

    def reconcile_folder_locations(
        self,
        account_id: str,
        folder_native_id: str,
        current_message_ids: set[str],
    ) -> None:
        """Mark disappeared source locations without deleting immutable messages."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT l.message_id
                FROM mail_message_locations l
                JOIN mail_messages m ON m.id=l.message_id
                WHERE m.account_id=? AND l.folder_native_id=?
                """,
                (account_id, folder_native_id),
            ).fetchall()
            missing = [str(row["message_id"]) for row in rows if str(row["message_id"]) not in current_message_ids]
            conn.executemany(
                """
                UPDATE mail_message_locations
                SET is_current=0,last_seen=?
                WHERE message_id=? AND folder_native_id=?
                """,
                [(_utc_now(), message_id, folder_native_id) for message_id in missing],
            )

    def mark_indexed(self, message_id: str, *, rag_doc_id: str = "", status: str = "registered") -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE mail_messages
                   SET index_status=?,
                       rag_doc_id=CASE WHEN ?<>'' THEN ? ELSE rag_doc_id END,
                       updated_at=?
                   WHERE id=?""",
                (status, rag_doc_id, rag_doc_id, _utc_now(), message_id),
            )

    def get_message(self, message_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM mail_messages WHERE id=?", (message_id,)).fetchone()
            locations = conn.execute(
                "SELECT * FROM mail_message_locations WHERE message_id=? ORDER BY last_seen DESC",
                (message_id,),
            ).fetchall()
        if not row:
            raise KeyError(message_id)
        payload = dict(row)
        payload["recipients"] = json.loads(payload.pop("recipients_json", "[]") or "[]")
        payload["locations"] = [dict(item) for item in locations]
        return payload

    def find_message_by_relative_path(self, relative_path: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM mail_messages WHERE relative_path=? ORDER BY updated_at DESC LIMIT 1",
                (relative_path,),
            ).fetchone()
        return self.get_message(str(row["id"])) if row else None

    def register_attachment_provenance(
        self,
        *,
        account_id: str,
        message_id: str,
        attachment_id: str,
        attachment_sha256: str,
    ) -> dict[str, Any]:
        if not attachment_sha256:
            return {"canonical": True, "canonical_message_id": message_id, "provenance_count": 1}
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT message_id FROM mail_attachment_provenance
                WHERE account_id=? AND attachment_sha256=?
                ORDER BY first_seen,message_id LIMIT 1
                """,
                (account_id, attachment_sha256),
            ).fetchone()
            conn.execute(
                """
                INSERT OR IGNORE INTO mail_attachment_provenance(
                    account_id,attachment_sha256,message_id,attachment_id,first_seen
                ) VALUES(?,?,?,?,?)
                """,
                (account_id, attachment_sha256, message_id, attachment_id, _utc_now()),
            )
            canonical_message_id = str(existing["message_id"]) if existing else message_id
            count = conn.execute(
                """
                SELECT COUNT(DISTINCT message_id) FROM mail_attachment_provenance
                WHERE account_id=? AND attachment_sha256=?
                """,
                (account_id, attachment_sha256),
            ).fetchone()[0]
        return {
            "canonical": canonical_message_id == message_id,
            "canonical_message_id": canonical_message_id,
            "provenance_count": int(count),
        }

    def list_messages(
        self,
        *,
        account_id: str = "",
        folder: str = "",
        q: str = "",
        participant: str = "",
        date_from: str = "",
        date_to: str = "",
        index_status: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        joins = ""
        if account_id:
            clauses.append("m.account_id=?")
            params.append(account_id)
        if folder:
            joins = " JOIN mail_message_locations l ON l.message_id=m.id "
            clauses.append("l.is_current=1 AND l.folder_path=?")
            params.append(folder)
        if q:
            clauses.append("(m.subject LIKE ? OR m.sender LIKE ? OR m.recipients_json LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like, like])
        if participant:
            clauses.append("(m.sender LIKE ? OR m.recipients_json LIKE ?)")
            like = f"%{participant}%"
            params.extend([like, like])
        if date_from:
            clauses.append("m.received_at>=?")
            params.append(date_from)
        if date_to:
            clauses.append("m.received_at<=?")
            params.append(date_to)
        if index_status:
            clauses.append("m.index_status=?")
            params.append(index_status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = (
            "SELECT DISTINCT m.id FROM mail_messages m"
            + joins
            + where
            + " ORDER BY m.received_at DESC,m.created_at DESC LIMIT ?"
        )
        params.append(max(1, min(int(limit), 1000)))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self.get_message(str(row["id"])) for row in rows]


_registry: MailRegistry | None = None
_registry_explicit = False


def get_mail_registry() -> MailRegistry:
    global _registry
    if _registry_explicit and _registry is not None:
        return _registry
    expected = Path(os.getenv("LES_MAIL_REGISTRY_DB", "data/mail_registry.db")).expanduser()
    if _registry is None or _registry.db_path != expected:
        _registry = MailRegistry(expected)
    return _registry


def set_mail_registry(registry: MailRegistry | None) -> None:
    global _registry, _registry_explicit
    _registry = registry
    _registry_explicit = registry is not None
