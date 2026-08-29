"""Read-only multi-account IMAP synchronization for E.ZH.I.K."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from backend.runtime_paths import mutable_path
from typing import Any

from backend.mail_ingest import (
    ImapFetchedFile,
    ImapSettings,
    _extract_fetch_bytes,
    _open_imap_client,
    _quote_imap_folder,
    _save_imap_eml,
)
from proxy.services.mail_registry_service import MailRegistry


EXCLUDED_IMAP_SPECIAL_USES = {"\\junk", "\\trash", "\\drafts"}
LIST_RE = re.compile(rb"^\((?P<flags>[^)]*)\)\s+(?P<delimiter>\S+|\".*?\")\s+(?P<name>.+)$")


@dataclass(frozen=True)
class ImapFolder:
    native_id: str
    path: str
    special_use: str = ""


@dataclass(frozen=True)
class RegisteredImapFile:
    file: ImapFetchedFile
    message_id: str
    created: bool

    def payload(self) -> dict[str, Any]:
        return {**self.file.payload(), "registry_message_id": self.message_id, "created": self.created}


def _decode_list_name(value: bytes) -> str:
    raw = value.strip()
    if raw.startswith(b'"') and raw.endswith(b'"'):
        raw = raw[1:-1].replace(b'\\"', b'"').replace(b"\\\\", b"\\")
    return raw.decode("utf-8", errors="replace")


def parse_imap_list_row(row: bytes | str) -> ImapFolder | None:
    raw = row.encode("utf-8") if isinstance(row, str) else bytes(row)
    match = LIST_RE.match(raw.strip())
    if not match:
        return None
    flags = [value.decode("ascii", errors="ignore").casefold() for value in match.group("flags").split()]
    if "\\noselect" in flags:
        return None
    special_use = next((flag for flag in flags if flag in EXCLUDED_IMAP_SPECIAL_USES), "")
    path = _decode_list_name(match.group("name"))
    return ImapFolder(native_id=path, path=path, special_use=special_use)


def discover_imap_folders(client: Any, configured: list[str] | None = None) -> list[ImapFolder]:
    explicit = [str(value).strip() for value in (configured or []) if str(value).strip() not in {"", "*"}]
    if explicit:
        return [ImapFolder(native_id=path, path=path) for path in explicit]
    status, rows = client.list()
    if status != "OK":
        raise RuntimeError("IMAP LIST failed")
    folders = [folder for row in (rows or []) if row and (folder := parse_imap_list_row(row))]
    return [folder for folder in folders if folder.special_use not in EXCLUDED_IMAP_SPECIAL_USES]


def _uid_validity(client: Any) -> str:
    try:
        _status, values = client.response("UIDVALIDITY")
    except Exception:
        return ""
    if not values:
        return ""
    value = values[-1]
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="ignore")
    match = re.search(r"\d+", str(value))
    return match.group(0) if match else ""


def sync_imap_account(
    settings: ImapSettings,
    registry: MailRegistry,
    *,
    account_id: str,
    mode: str = "incremental",
    max_messages: int = 200,
    client_factory: Any | None = None,
    progress_callback: Any | None = None,
) -> list[RegisteredImapFile]:
    """Save and register messages before advancing each folder cursor.

    The source is always selected read-only and fetched with BODY.PEEK[], so
    synchronization cannot set Seen or mutate the mailbox.
    """
    if mode not in {"full", "incremental"}:
        raise ValueError("mode must be full or incremental")
    if not settings.configured:
        raise RuntimeError("IMAP host, login and app password are required")

    limit = max(1, int(max_messages))
    client = _open_imap_client(settings, client_factory=client_factory)
    registered: list[RegisteredImapFile] = []
    registry.update_sync_state(account_id, "running")
    try:
        client.login(settings.login, settings.password)
        folders = discover_imap_folders(client, settings.folders)
        for folder in folders:
            if len(registered) >= limit:
                break
            selected, _count = client.select(_quote_imap_folder(folder.path), readonly=True)
            if selected != "OK":
                continue
            uid_validity = _uid_validity(client)
            state = registry.upsert_folder(
                account_id,
                folder.native_id,
                path=folder.path,
                special_use=folder.special_use,
                uid_validity=uid_validity,
            )
            if not state["enabled"] or folder.special_use in EXCLUDED_IMAP_SPECIAL_USES:
                continue
            # A requested full sync is resumable: until the backfill is complete
            # it continues after the confirmed UID. A later full sync starts at
            # ALL again for safe deduplicated reconciliation.
            last_uid = int(state.get("last_uid") or 0)
            if mode == "full" and state.get("backfill_complete"):
                last_uid = 0
            scanning_all = last_uid <= 0
            criteria = "ALL" if last_uid <= 0 else f"UID {last_uid + 1}:*"
            status, data = client.uid("SEARCH", None, criteria)
            if status != "OK" or not data:
                continue
            raw_uids = data[0] or b""
            if isinstance(raw_uids, bytes):
                uid_values = raw_uids.decode("ascii", errors="ignore").split()
            else:
                uid_values = str(raw_uids).split()
            all_uids = sorted(int(value) for value in uid_values if str(value).isdigit())
            remaining = max(0, limit - len(registered))
            selected_uids = all_uids[:remaining]
            current_message_ids: set[str] = set()
            for uid in selected_uids:
                status, msg_data = client.uid("FETCH", str(uid), "(BODY.PEEK[])")
                if status != "OK":
                    raise RuntimeError(f"IMAP FETCH failed for {folder.path} UID {uid}")
                raw = _extract_fetch_bytes(msg_data)
                if not raw:
                    raise RuntimeError(f"IMAP returned empty message for {folder.path} UID {uid}")
                item = _save_imap_eml(settings, folder=folder.path, uid=uid, raw=raw)
                message, created = registry.register_message(
                    account_id=account_id,
                    raw_path=item.path,
                    relative_path=item.relative_path,
                    source_kind="imap",
                    native_id=f"{folder.native_id}:{uid}",
                    internet_message_id=item.message_id,
                    folder_native_id=folder.native_id,
                    folder_path=folder.path,
                )
                current_message_ids.add(str(message["id"]))
                registered.append(RegisteredImapFile(item, str(message["id"]), created))
                registry.upsert_folder(
                    account_id,
                    folder.native_id,
                    path=folder.path,
                    special_use=folder.special_use,
                    uid_validity=uid_validity,
                    last_uid=uid,
                    backfill_complete=len(selected_uids) == len(all_uids),
                )
                if progress_callback:
                    progress_callback(
                        {
                            "stage": "registered",
                            "account_id": account_id,
                            "folder": folder.path,
                            "uid": uid,
                            "fetched": len(registered),
                            "max_messages": limit,
                        }
                    )
            if mode == "full" and scanning_all and len(selected_uids) == len(all_uids):
                registry.reconcile_folder_locations(account_id, folder.native_id, current_message_ids)
        registry.update_sync_state(account_id, "completed")
        return registered
    except Exception as error:
        detail = str(error)
        if settings.password:
            detail = detail.replace(settings.password, "[redacted]")
        registry.update_sync_state(account_id, "failed", error=detail)
        raise
    finally:
        try:
            client.logout()
        except Exception:
            pass


def settings_for_account(account: dict[str, Any], password: str) -> ImapSettings:
    config = dict(account.get("config") or {})
    root = Path(config.get("storage_root") or "RAG_Content/MAIL/accounts") / str(account["id"])
    return ImapSettings(
        host=str(config.get("host") or ""),
        port=int(config.get("port") or 993),
        login=str(config.get("login") or ""),
        password=password,
        ssl=bool(config.get("ssl", True)),
        folders=list(config.get("folders") or ["*"]),
        checkpoint_dir=mutable_path("data/mail_imap_checkpoints") / str(account["id"]),
        storage_root=root,
        timeout_sec=float(config.get("timeout_sec") or 45),
    )
