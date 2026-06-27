"""Е.Ж.И.К. mail ingest helpers."""

from __future__ import annotations

import hashlib
import imaplib
import json
import os
import re
from dataclasses import asdict, dataclass
from email import policy
from email.header import decode_header
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from .mail_emlx import emlx_to_eml_bytes, read_email_message_bytes

MAIL_DATASET_NAME = "MAIL_Index"
MAIL_SUFFIXES = {".eml", ".emlx", ".msg"}
SAFE_SOURCE_PART_RE = re.compile(r"^[\w .@()+\-=]+$", re.UNICODE)
SAFE_FILE_PART_RE = re.compile(r"[^A-Za-z0-9_.@()+\-=]+")


@dataclass(frozen=True)
class MailFileSummary:
    path: str
    relative_path: str
    suffix: str
    size_bytes: int
    subject: str = ""
    sender: str = ""
    recipients: str = ""
    date: str = ""
    message_id: str = ""
    attachments: list[str] | None = None

    def payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["attachments"] = self.attachments or []
        return data


@dataclass(frozen=True)
class ImapSettings:
    host: str
    port: int
    login: str
    password: str
    ssl: bool
    folders: list[str]
    checkpoint_dir: Path
    storage_root: Path
    timeout_sec: float = 45.0

    @property
    def configured(self) -> bool:
        return bool(self.host and self.login and self.password)

    def public_payload(self) -> dict[str, Any]:
        return {
            "enabled": self.configured,
            "status": "configured" if self.configured else "missing_credentials",
            "host": self.host,
            "port": self.port,
            "ssl": self.ssl,
            "login": mask_mail_login(self.login),
            "folders": self.folders,
            "checkpoint_dir": self.checkpoint_dir.as_posix(),
            "timeout_sec": self.timeout_sec,
        }


@dataclass(frozen=True)
class ImapFetchedFile:
    path: Path
    relative_path: str
    folder: str
    uid: int
    subject: str = ""
    message_id: str = ""

    def payload(self) -> dict[str, Any]:
        return {
            "path": self.path.as_posix(),
            "relative_path": self.relative_path,
            "folder": self.folder,
            "uid": self.uid,
            "subject": self.subject,
            "message_id": self.message_id,
        }


@dataclass(frozen=True)
class AppleMailImportedFile:
    path: Path
    relative_path: str
    source_path: str
    subject: str = ""
    message_id: str = ""

    def payload(self) -> dict[str, Any]:
        return {
            "path": self.path.as_posix(),
            "relative_path": self.relative_path,
            "source_path": self.source_path,
            "subject": self.subject,
            "message_id": self.message_id,
        }


def mask_mail_login(login: str) -> str:
    login = str(login or "")
    if "@" not in login:
        return login[:2] + "***" if len(login) > 2 else "***"
    name, domain = login.split("@", 1)
    if len(name) <= 2:
        masked = name[:1] + "***"
    else:
        masked = name[:2] + "***" + name[-1:]
    return f"{masked}@{domain}"


def imap_settings_from_env() -> ImapSettings:
    folders = [
        item.strip()
        for item in os.getenv("MAIL_IMAP_FOLDERS", "INBOX").split(",")
        if item.strip()
    ]
    return ImapSettings(
        host=os.getenv("MAIL_IMAP_HOST", "").strip(),
        port=int(os.getenv("MAIL_IMAP_PORT", "993") or "993"),
        login=os.getenv("MAIL_IMAP_LOGIN", "").strip(),
        password=os.getenv("MAIL_IMAP_PASSWORD", ""),
        ssl=os.getenv("MAIL_IMAP_SSL", "true").strip().lower() in {"1", "true", "yes", "on"},
        folders=folders or ["INBOX"],
        checkpoint_dir=Path(os.getenv("MAIL_IMAP_CHECKPOINT_DIR", "data/mail_imap_checkpoints")),
        storage_root=Path(os.getenv("MAIL_IMAP_STORAGE_ROOT", "RAG_Content/MAIL/IMAP")),
        timeout_sec=float(os.getenv("MAIL_IMAP_TIMEOUT_SEC", "45") or "45"),
    )


def apple_mail_root_from_env() -> Path:
    return Path(os.getenv("MAIL_APPLE_ROOT", "~/Library/Mail")).expanduser()


def apple_mail_storage_root_from_env() -> Path:
    return Path(os.getenv("MAIL_APPLE_STORAGE_ROOT", "RAG_Content/MAIL/AppleMail"))


def apple_mail_public_payload() -> dict[str, Any]:
    root = apple_mail_root_from_env()
    exists = root.exists()
    accessible = False
    error = ""
    if exists:
        try:
            next(iter(root.iterdir()), None)
            accessible = True
        except Exception as exc:
            error = str(exc)
    return {
        "root": root.as_posix(),
        "exists": exists,
        "accessible": accessible,
        "status": "ready" if exists and accessible else ("permission_denied" if exists else "not_found"),
        "error": error,
        "storage_root": apple_mail_storage_root_from_env().as_posix(),
    }


def resolve_mail_source_folder(source_folder: str, *, base: Path = Path("./RAG_Content")) -> Path:
    """Resolve a safe folder below RAG_Content."""
    raw = (source_folder or "MAIL").strip()
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"unsafe mail source folder: {source_folder}")
    if candidate.parts and candidate.parts[0] == base.name:
        candidate = Path(*candidate.parts[1:]) if len(candidate.parts) > 1 else Path(".")
    for part in candidate.parts:
        if part in {"", "."}:
            continue
        if not SAFE_SOURCE_PART_RE.match(part):
            raise ValueError(f"unsafe mail source folder: {source_folder}")
    resolved = (base / candidate).resolve()
    root = base.resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError(f"unsafe mail source folder: {source_folder}")
    if not resolved.exists() or not resolved.is_dir():
        raise FileNotFoundError(f"mail source folder not found: {resolved}")
    return resolved


def iter_mail_files(source_dir: Path, *, max_files: int = 500) -> list[Path]:
    limit = max(1, int(max_files))
    files = [
        path
        for path in source_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in MAIL_SUFFIXES and not _hidden_path(path, source_dir)
    ]
    return sorted(files, key=lambda path: path.relative_to(source_dir).as_posix().casefold())[:limit]


def summarize_mail_file(path: Path, source_dir: Path) -> MailFileSummary:
    suffix = path.suffix.lower()
    if suffix in {".eml", ".emlx"}:
        return _summarize_eml(path, source_dir)
    return _summarize_msg(path, source_dir)


def summarize_mail_files(source_dir: Path, *, max_files: int = 500) -> list[MailFileSummary]:
    return [summarize_mail_file(path, source_dir) for path in iter_mail_files(source_dir, max_files=max_files)]


def fetch_imap_eml_files(
    settings: ImapSettings,
    *,
    max_messages: int = 25,
    client_factory: Any | None = None,
    progress_callback: Any | None = None,
) -> list[ImapFetchedFile]:
    """Fetch new IMAP messages into RAG_Content as raw .eml files."""
    if not settings.configured:
        raise RuntimeError("MAIL_IMAP_HOST, MAIL_IMAP_LOGIN and MAIL_IMAP_PASSWORD are required")

    limit = max(1, int(max_messages))
    checkpoint = _load_imap_checkpoint(settings)
    client = _open_imap_client(settings, client_factory=client_factory)
    fetched: list[ImapFetchedFile] = []
    fetched_by_folder: dict[str, int] = {}
    try:
        client.login(settings.login, settings.password)
        for folder in settings.folders:
            if len(fetched) >= limit:
                break
            selected, _ = client.select(_quote_imap_folder(folder), readonly=True)
            if selected != "OK":
                continue
            last_uid = int(checkpoint.get(folder, {}).get("last_uid") or 0)
            criteria = f"UID {last_uid + 1}:*" if last_uid > 0 else "ALL"
            status, data = client.uid("SEARCH", None, criteria)
            if status != "OK" or not data:
                continue
            raw_uids = data[0] or b""
            if isinstance(raw_uids, str):
                uid_values = raw_uids.split()
            else:
                uid_values = raw_uids.decode("ascii", errors="ignore").split()
            if not uid_values:
                continue
            for uid_value in uid_values[: max(0, limit - len(fetched))]:
                try:
                    uid = int(uid_value)
                except ValueError:
                    continue
                status, msg_data = client.uid("FETCH", str(uid), "(RFC822)")
                if status != "OK":
                    continue
                raw = _extract_fetch_bytes(msg_data)
                if not raw:
                    continue
                item = _save_imap_eml(settings, folder=folder, uid=uid, raw=raw)
                fetched.append(item)
                fetched_by_folder[folder] = max(fetched_by_folder.get(folder, last_uid), uid)
                if progress_callback:
                    progress_callback(
                        {
                            "stage": "fetching",
                            "folder": folder,
                            "uid": uid,
                            "fetched": len(fetched),
                            "max_messages": limit,
                        }
                    )
        for folder, uid in fetched_by_folder.items():
            _set_imap_checkpoint(checkpoint, folder, uid)
        if fetched_by_folder:
            _save_imap_checkpoint(settings, checkpoint)
    finally:
        try:
            client.logout()
        except Exception:
            pass
    return fetched


def import_apple_mail_eml_files(
    *,
    mail_root: Path | None = None,
    storage_root: Path | None = None,
    max_messages: int = 25,
) -> list[AppleMailImportedFile]:
    root = (mail_root or apple_mail_root_from_env()).expanduser()
    storage = storage_root or apple_mail_storage_root_from_env()
    limit = max(1, int(max_messages))
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Apple Mail storage not found: {root}")
    try:
        candidates = [path for path in root.rglob("*.emlx") if path.is_file()]
    except PermissionError as error:
        raise PermissionError(
            f"Apple Mail storage is not readable: {root}. "
            "Grant Full Disk Access to the terminal/Codex process."
        ) from error

    def _mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except Exception:
            return 0.0

    imported: list[AppleMailImportedFile] = []
    for source_path in sorted(candidates, key=_mtime, reverse=True)[:limit]:
        raw = emlx_to_eml_bytes(source_path)
        if not raw.strip():
            continue
        item = _save_apple_mail_eml(storage, source_path=source_path, raw=raw)
        imported.append(item)
    return imported


def _summarize_eml(path: Path, source_dir: Path) -> MailFileSummary:
    msg = BytesParser(policy=policy.default).parsebytes(read_email_message_bytes(path))
    attachments: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            filename = part.get_filename()
            disposition = (part.get_content_disposition() or "").lower()
            if filename or disposition == "attachment":
                attachments.append(filename or "(без имени)")
    else:
        # Однокусковое письмо-вложение (форвард .pdf/.eml как тело): не теряем вложение.
        filename = msg.get_filename()
        disposition = (msg.get_content_disposition() or "").lower()
        if filename or disposition == "attachment" or msg.get_content_maintype() not in {"text", "multipart"}:
            attachments.append(filename or "(без имени)")
    return MailFileSummary(
        path=path.as_posix(),
        relative_path=path.relative_to(source_dir).as_posix(),
        suffix=path.suffix.lower(),
        size_bytes=path.stat().st_size,
        subject=str(msg.get("Subject", "")),
        sender=str(msg.get("From", "")),
        recipients=str(msg.get("To", "")),
        date=str(msg.get("Date", "")),
        message_id=str(msg.get("Message-ID", "")),
        attachments=attachments,
    )


def _summarize_msg(path: Path, source_dir: Path) -> MailFileSummary:
    subject = ""
    sender = ""
    recipients = ""
    date = ""
    attachments: list[str] = []
    try:
        import extract_msg

        msg = extract_msg.Message(str(path))
        subject = msg.subject or ""
        sender = msg.sender or ""
        recipients = getattr(msg, "to", "") or ""
        date = str(msg.date or "")
        attachments = [getattr(item, "longFilename", "") or getattr(item, "shortFilename", "") or "(без имени)" for item in msg.attachments]
    except Exception:
        subject = path.stem
    return MailFileSummary(
        path=path.as_posix(),
        relative_path=path.relative_to(source_dir).as_posix(),
        suffix=".msg",
        size_bytes=path.stat().st_size,
        subject=subject,
        sender=sender,
        recipients=recipients,
        date=date,
        attachments=attachments,
    )


def _hidden_path(path: Path, root: Path) -> bool:
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def _open_imap_client(settings: ImapSettings, *, client_factory: Any | None = None):
    if client_factory is not None:
        return client_factory(settings.host, settings.port)
    timeout = max(1.0, float(settings.timeout_sec or 45.0))
    if settings.ssl:
        return imaplib.IMAP4_SSL(settings.host, settings.port, timeout=timeout)
    return imaplib.IMAP4(settings.host, settings.port, timeout=timeout)


def _quote_imap_folder(folder: str) -> str:
    if folder.startswith('"') and folder.endswith('"'):
        return folder
    return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _extract_fetch_bytes(data: Any) -> bytes:
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if not isinstance(data, (list, tuple)):
        return b""
    for item in data:
        if isinstance(item, tuple):
            for part in reversed(item):
                if isinstance(part, (bytes, bytearray)) and b"RFC822" not in bytes(part)[:80]:
                    return bytes(part)
        elif isinstance(item, (bytes, bytearray)) and b"\r\n" in bytes(item):
            return bytes(item)
    return b""


def _load_imap_checkpoint(settings: ImapSettings) -> dict[str, Any]:
    path = _imap_checkpoint_path(settings)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save_imap_checkpoint(settings: ImapSettings, checkpoint: dict[str, Any]) -> None:
    path = _imap_checkpoint_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _set_imap_checkpoint(checkpoint: dict[str, Any], folder: str, uid: int) -> None:
    folder_state = checkpoint.setdefault(folder, {})
    folder_state["last_uid"] = int(uid)


def _imap_checkpoint_path(settings: ImapSettings) -> Path:
    account = _safe_path_part(settings.login or "imap")
    host = _safe_path_part(settings.host or "host")
    return settings.checkpoint_dir / f"{host}_{account}.json"


def _save_imap_eml(settings: ImapSettings, *, folder: str, uid: int, raw: bytes) -> ImapFetchedFile:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    subject = _decode_header_value(str(msg.get("Subject", "")))
    message_id = str(msg.get("Message-ID", "")).strip()
    account = _safe_path_part(settings.login)
    folder_part = _safe_path_part(folder)
    digest = hashlib.sha1(raw).hexdigest()[:12]
    stem_subject = _safe_path_part(subject)[:50] or "message"
    file_name = f"{uid:010d}_{digest}_{stem_subject}.eml"
    target_dir = settings.storage_root / account / folder_part
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / file_name
    path.write_bytes(raw)
    try:
        relative_path = path.relative_to(Path("RAG_Content")).as_posix()
    except ValueError:
        relative_path = f"MAIL/IMAP/{account}/{folder_part}/{file_name}"
    return ImapFetchedFile(
        path=path,
        relative_path=relative_path,
        folder=folder,
        uid=uid,
        subject=subject,
        message_id=message_id,
    )


def _save_apple_mail_eml(storage_root: Path, *, source_path: Path, raw: bytes) -> AppleMailImportedFile:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    subject = _decode_header_value(str(msg.get("Subject", "")))
    message_id = str(msg.get("Message-ID", "")).strip()
    digest = hashlib.sha1(raw).hexdigest()[:12]
    stem_subject = _safe_path_part(subject)[:50] or "message"
    file_name = f"{digest}_{stem_subject}.eml"
    target_dir = storage_root / "local"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / file_name
    path.write_bytes(raw)
    try:
        relative_path = path.relative_to(Path("RAG_Content")).as_posix()
    except ValueError:
        relative_path = f"MAIL/AppleMail/local/{file_name}"
    return AppleMailImportedFile(
        path=path,
        relative_path=relative_path,
        source_path=source_path.as_posix(),
        subject=subject,
        message_id=message_id,
    )


def _decode_header_value(value: str) -> str:
    parts: list[str] = []
    for part, enc in decode_header(value or ""):
        if isinstance(part, bytes):
            parts.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(str(part))
    return "".join(parts).strip()


def _safe_path_part(value: str) -> str:
    value = (value or "item").strip().replace(" ", "_")
    safe = SAFE_FILE_PART_RE.sub("_", value).strip("._")
    return safe[:80] or "item"
