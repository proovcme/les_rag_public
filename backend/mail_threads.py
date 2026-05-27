"""Mail conversation extraction for Е.Ж.И.К.

This module intentionally works from stored .eml/.msg files, so existing mail
imports can get a conversation view without a mandatory reindex.
"""

from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass
from datetime import timezone
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any

from .mail_emlx import read_email_message_bytes
from .mail_ingest import MAIL_SUFFIXES


MESSAGE_ID_RE = re.compile(r"<[^>]+>|[A-Za-z0-9.!#$%&'*+/=?^_`{|}~@-]+")
REPLY_PREFIX_RE = re.compile(r"^\s*((re|fw|fwd|ответ|пересл)\s*(\[\d+\])?\s*:\s*)+", re.I)
HTML_TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class MailMessageRecord:
    path: str
    relative_path: str
    suffix: str
    size_bytes: int
    subject: str
    normalized_subject: str
    sender: str
    sender_email: str
    to: list[str]
    cc: list[str]
    bcc: list[str]
    date: str
    timestamp: float
    message_id: str
    in_reply_to: str
    references: list[str]
    thread_key: str
    thread_root: str
    attachments: list[str]
    body_snippet: str

    @property
    def recipients(self) -> list[str]:
        return [*self.to, *self.cc, *self.bcc]

    @property
    def participants(self) -> list[str]:
        values = [self.sender, *self.recipients]
        return sorted({value for value in values if value}, key=str.casefold)

    def payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["recipients"] = self.recipients
        data["participants"] = self.participants
        data["who_to_whom"] = {
            "from": self.sender,
            "to": self.to,
            "cc": self.cc,
            "bcc": self.bcc,
        }
        data["what"] = {
            "subject": self.subject,
            "snippet": self.body_snippet,
            "attachments": self.attachments,
        }
        return data


@dataclass(frozen=True)
class MailThreadRecord:
    thread_key: str
    thread_root: str
    subject: str
    messages: list[MailMessageRecord]

    @property
    def participants(self) -> list[str]:
        values: set[str] = set()
        for message in self.messages:
            values.update(message.participants)
        return sorted(values, key=str.casefold)

    @property
    def first_date(self) -> str:
        return self.messages[0].date if self.messages else ""

    @property
    def last_date(self) -> str:
        return self.messages[-1].date if self.messages else ""

    @property
    def latest(self) -> MailMessageRecord | None:
        return self.messages[-1] if self.messages else None

    def summary_payload(self) -> dict[str, Any]:
        latest = self.latest
        return {
            "thread_key": self.thread_key,
            "thread_root": self.thread_root,
            "subject": self.subject,
            "message_count": len(self.messages),
            "participants": self.participants,
            "first_date": self.first_date,
            "last_date": self.last_date,
            "latest": latest.payload() if latest else None,
            "who_to_whom": latest.payload()["who_to_whom"] if latest else {},
            "what": latest.payload()["what"] if latest else {},
        }

    def payload(self) -> dict[str, Any]:
        message_ids = {message.message_id: message for message in self.messages if message.message_id}
        edges: list[dict[str, str]] = []
        for message in self.messages:
            parent = message.in_reply_to
            if parent and parent in message_ids:
                edges.append({"from_message_id": parent, "to_message_id": message.message_id})
                continue
            for ref in reversed(message.references):
                if ref in message_ids:
                    edges.append({"from_message_id": ref, "to_message_id": message.message_id})
                    break
        return {
            **self.summary_payload(),
            "messages": [message.payload() for message in self.messages],
            "edges": edges,
        }


def read_mail_messages(source_dir: Path, *, max_files: int = 2000) -> list[MailMessageRecord]:
    root = source_dir.resolve()
    if not root.exists() or not root.is_dir():
        return []
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in MAIL_SUFFIXES and not _hidden_path(path, root)
    ]
    records = [parse_mail_message(path, root) for path in sorted(files)[: max(1, int(max_files))]]
    return sorted(records, key=lambda item: (item.timestamp, item.relative_path.casefold()))


def group_mail_threads(messages: list[MailMessageRecord]) -> list[MailThreadRecord]:
    grouped: dict[str, list[MailMessageRecord]] = {}
    for message in messages:
        grouped.setdefault(message.thread_key, []).append(message)
    threads = [
        MailThreadRecord(
            thread_key=thread_key,
            thread_root=_thread_root_for(messages_in_thread),
            subject=_thread_subject(messages_in_thread),
            messages=sorted(messages_in_thread, key=lambda item: (item.timestamp, item.relative_path.casefold())),
        )
        for thread_key, messages_in_thread in grouped.items()
    ]
    return sorted(threads, key=lambda thread: (thread.messages[-1].timestamp if thread.messages else 0), reverse=True)


def filter_mail_messages(
    messages: list[MailMessageRecord],
    *,
    q: str = "",
    participant: str = "",
    thread_key: str = "",
) -> list[MailMessageRecord]:
    query = _fold(q)
    person = _fold(participant)
    thread = str(thread_key or "").strip()
    result: list[MailMessageRecord] = []
    for message in messages:
        if thread and message.thread_key != thread:
            continue
        if person and person not in _fold(" ".join(message.participants)):
            continue
        if query:
            haystack = _fold(
                " ".join(
                    [
                        message.subject,
                        message.body_snippet,
                        message.sender,
                        " ".join(message.recipients),
                        " ".join(message.attachments),
                    ]
                )
            )
            if query not in haystack:
                continue
        result.append(message)
    return result


def parse_mail_message(path: Path, source_dir: Path) -> MailMessageRecord:
    if path.suffix.lower() == ".msg":
        return _parse_msg(path, source_dir)
    return _parse_eml(path, source_dir)


def _parse_eml(path: Path, source_dir: Path) -> MailMessageRecord:
    msg = BytesParser(policy=policy.default).parsebytes(read_email_message_bytes(path))
    subject = str(msg.get("Subject", "") or "")
    sender_values = _format_addresses(str(msg.get("From", "") or ""))
    sender = sender_values[0] if sender_values else str(msg.get("From", "") or "")
    sender_email = _first_email(str(msg.get("From", "") or ""))
    to = _format_addresses(str(msg.get("To", "") or ""))
    cc = _format_addresses(str(msg.get("Cc", "") or ""))
    bcc = _format_addresses(str(msg.get("Bcc", "") or ""))
    attachments: list[str] = []
    body_parts: list[str] = []
    html_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            filename = part.get_filename()
            disposition = (part.get_content_disposition() or "").lower()
            if filename or disposition == "attachment":
                attachments.append(filename or "(без имени)")
                continue
            content_type = part.get_content_type()
            if content_type == "text/plain":
                try:
                    body_parts.append(str(part.get_content()))
                except Exception:
                    pass
            elif content_type == "text/html":
                try:
                    html_parts.append(str(part.get_content()))
                except Exception:
                    pass
    else:
        try:
            body_parts.append(str(msg.get_content()))
        except Exception:
            pass
    body = "\n".join(body_parts) or _strip_html("\n".join(html_parts))
    message_id = _canonical_message_id(str(msg.get("Message-ID", "") or ""))
    in_reply_to = _first_message_id(str(msg.get("In-Reply-To", "") or ""))
    references = _message_ids(str(msg.get("References", "") or ""))
    return _record(
        path=path,
        source_dir=source_dir,
        subject=subject,
        sender=sender,
        sender_email=sender_email,
        to=to,
        cc=cc,
        bcc=bcc,
        date=str(msg.get("Date", "") or ""),
        message_id=message_id,
        in_reply_to=in_reply_to,
        references=references,
        attachments=attachments,
        body=body,
    )


def _parse_msg(path: Path, source_dir: Path) -> MailMessageRecord:
    subject = path.stem
    sender = ""
    sender_email = ""
    to: list[str] = []
    cc: list[str] = []
    bcc: list[str] = []
    date = ""
    message_id = ""
    in_reply_to = ""
    references: list[str] = []
    attachments: list[str] = []
    body = ""
    try:
        import extract_msg

        msg = extract_msg.Message(str(path))
        subject = msg.subject or subject
        sender = msg.sender or ""
        sender_email = _first_email(sender)
        to = _format_addresses(getattr(msg, "to", "") or "")
        cc = _format_addresses(getattr(msg, "cc", "") or "")
        bcc = _format_addresses(getattr(msg, "bcc", "") or "")
        date = str(msg.date or "")
        message_id = _canonical_message_id(str(getattr(msg, "messageId", "") or getattr(msg, "message_id", "") or ""))
        in_reply_to = _first_message_id(str(getattr(msg, "inReplyTo", "") or getattr(msg, "in_reply_to", "") or ""))
        references = _message_ids(str(getattr(msg, "references", "") or ""))
        attachments = [
            getattr(item, "longFilename", "") or getattr(item, "shortFilename", "") or "(без имени)"
            for item in msg.attachments
        ]
        body = msg.body or ""
    except Exception:
        pass
    return _record(
        path=path,
        source_dir=source_dir,
        subject=subject,
        sender=sender,
        sender_email=sender_email,
        to=to,
        cc=cc,
        bcc=bcc,
        date=date,
        message_id=message_id,
        in_reply_to=in_reply_to,
        references=references,
        attachments=attachments,
        body=body,
    )


def _record(
    *,
    path: Path,
    source_dir: Path,
    subject: str,
    sender: str,
    sender_email: str,
    to: list[str],
    cc: list[str],
    bcc: list[str],
    date: str,
    message_id: str,
    in_reply_to: str,
    references: list[str],
    attachments: list[str],
    body: str,
) -> MailMessageRecord:
    normalized_subject = normalize_subject(subject)
    thread_root = references[0] if references else in_reply_to or message_id
    if thread_root:
        thread_key = "msg_" + _short_hash(thread_root)
    elif normalized_subject:
        thread_key = "subject_" + _short_hash(normalized_subject)
        thread_root = normalized_subject
    else:
        thread_key = "file_" + _short_hash(path.as_posix())
        thread_root = path.name
    return MailMessageRecord(
        path=path.as_posix(),
        relative_path=path.relative_to(source_dir).as_posix(),
        suffix=path.suffix.lower(),
        size_bytes=path.stat().st_size,
        subject=subject.strip() or "(без темы)",
        normalized_subject=normalized_subject,
        sender=sender.strip(),
        sender_email=sender_email,
        to=to,
        cc=cc,
        bcc=bcc,
        date=date,
        timestamp=_timestamp(date, path),
        message_id=message_id,
        in_reply_to=in_reply_to,
        references=references,
        thread_key=thread_key,
        thread_root=thread_root,
        attachments=attachments,
        body_snippet=_snippet(body),
    )


def normalize_subject(subject: str) -> str:
    value = str(subject or "").strip()
    previous = None
    while value and value != previous:
        previous = value
        value = REPLY_PREFIX_RE.sub("", value).strip()
    return SPACE_RE.sub(" ", value).strip()


def _format_addresses(value: str) -> list[str]:
    out: list[str] = []
    for name, address in getaddresses([value or ""]):
        name = SPACE_RE.sub(" ", str(name or "")).strip()
        address = str(address or "").strip()
        if name and address:
            out.append(f"{name} <{address}>")
        elif address:
            out.append(address)
        elif name:
            out.append(name)
    return out


def _first_email(value: str) -> str:
    for _, address in getaddresses([value or ""]):
        if address:
            return address
    return ""


def _message_ids(value: str) -> list[str]:
    ids: list[str] = []
    for match in MESSAGE_ID_RE.findall(value or ""):
        canonical = _canonical_message_id(match)
        if canonical and canonical not in ids:
            ids.append(canonical)
    return ids


def _first_message_id(value: str) -> str:
    ids = _message_ids(value)
    return ids[0] if ids else ""


def _canonical_message_id(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    if "<" in value and ">" in value:
        value = value[value.find("<") + 1 : value.rfind(">")]
    return value.strip().strip("<>").casefold()


def _timestamp(date: str, path: Path) -> float:
    try:
        parsed = parsedate_to_datetime(date)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except Exception:
        try:
            return path.stat().st_mtime
        except Exception:
            return 0.0


def _snippet(body: str, limit: int = 420) -> str:
    value = SPACE_RE.sub(" ", str(body or "")).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _strip_html(value: str) -> str:
    return html.unescape(HTML_TAG_RE.sub(" ", value or ""))


def _thread_root_for(messages: list[MailMessageRecord]) -> str:
    for message in messages:
        if message.thread_root:
            return message.thread_root
    return ""


def _thread_subject(messages: list[MailMessageRecord]) -> str:
    for message in messages:
        if message.normalized_subject:
            return message.normalized_subject
    return messages[0].subject if messages else "(без темы)"


def _fold(value: str) -> str:
    return SPACE_RE.sub(" ", str(value or "").casefold()).strip()


def _short_hash(value: str) -> str:
    import hashlib

    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _hidden_path(path: Path, root: Path) -> bool:
    return any(part.startswith(".") for part in path.relative_to(root).parts)
