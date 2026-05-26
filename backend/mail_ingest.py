"""Е.Ж.И.К. local mail ingest helpers.

The first mail slice is deliberately local-file only: EML/MSG files are read
from a safe RAG_Content subfolder and registered into MAIL_Index. Live IMAP
credentials belong to the next step.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any


MAIL_DATASET_NAME = "MAIL_Index"
MAIL_SUFFIXES = {".eml", ".msg"}
SAFE_SOURCE_PART_RE = re.compile(r"^[\w .@()+\-=]+$", re.UNICODE)


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
    if suffix == ".eml":
        return _summarize_eml(path, source_dir)
    return _summarize_msg(path, source_dir)


def summarize_mail_files(source_dir: Path, *, max_files: int = 500) -> list[MailFileSummary]:
    return [summarize_mail_file(path, source_dir) for path in iter_mail_files(source_dir, max_files=max_files)]


def _summarize_eml(path: Path, source_dir: Path) -> MailFileSummary:
    with path.open("rb") as handle:
        msg = BytesParser(policy=policy.default).parse(handle)
    attachments: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            filename = part.get_filename()
            disposition = (part.get_content_disposition() or "").lower()
            if filename or disposition == "attachment":
                attachments.append(filename or "(без имени)")
    return MailFileSummary(
        path=path.as_posix(),
        relative_path=path.relative_to(source_dir).as_posix(),
        suffix=".eml",
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
