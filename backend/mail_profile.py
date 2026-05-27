"""Mail vector profile extraction for Е.Ж.И.К."""

from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import timezone
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any

from .mail_emlx import read_email_message_bytes


MESSAGE_ID_RE = re.compile(r"<[^>]+>|[A-Za-z0-9.!#$%&'*+/=?^_`{|}~@-]+")
REPLY_PREFIX_RE = re.compile(r"^\s*((re|fw|fwd|ответ|пересл)\s*(\[\d+\])?\s*:\s*)+", re.I)
HTML_TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".heic"}
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".json", ".jsonl", ".log", ".xml", ".html", ".htm"}
PDF_SUFFIXES = {".pdf"}
DOCX_SUFFIXES = {".docx"}


@dataclass(frozen=True)
class MailAttachmentProfile:
    attachment_id: str
    filename: str
    content_type: str
    size_bytes: int
    sha1: str
    kind: str
    extraction: str
    text: str = ""
    needs_ocr: bool = False
    needs_vlm: bool = False
    error: str = ""

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())

    def payload(self, *, text_limit: int = 1200) -> dict[str, Any]:
        data = asdict(self)
        data["has_text"] = self.has_text
        data["text"] = _compact(self.text, text_limit)
        return data

    def embedding_text(self, parent: "MailVectorProfile") -> str:
        evidence = self.text.strip()
        if not evidence:
            if self.needs_ocr or self.needs_vlm:
                evidence = "Вложение требует OCR/VLM: текст из изображения или скана пока не извлечён."
            elif self.error:
                evidence = f"Вложение не разобрано: {self.error}"
            else:
                evidence = "Вложение без извлечённого текста."
        return "\n".join(
            [
                f"# Вложение письма: {self.filename or '(без имени)'}",
                f"Тема письма: {parent.subject}",
                f"От: {parent.sender}",
                f"Кому: {', '.join(parent.to) or '-'}",
                f"Копия: {', '.join(parent.cc) or '-'}",
                f"Thread: {parent.thread_key}",
                f"Message-ID: {parent.message_id or '-'}",
                f"Attachment-ID: {self.attachment_id}",
                f"Тип вложения: {self.content_type or self.kind}",
                f"Извлечение: {self.extraction}",
                "",
                evidence,
            ]
        )


@dataclass(frozen=True)
class MailVectorProfile:
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
    importance: str
    body: str
    body_snippet: str
    attachments: list[MailAttachmentProfile]

    @property
    def recipients(self) -> list[str]:
        return [*self.to, *self.cc, *self.bcc]

    @property
    def participants(self) -> list[str]:
        values = [self.sender, *self.recipients]
        return sorted({value for value in values if value}, key=str.casefold)

    @property
    def attachment_names(self) -> list[str]:
        return [item.filename for item in self.attachments if item.filename]

    @property
    def has_attachments(self) -> bool:
        return bool(self.attachments)

    @property
    def attachment_text_available(self) -> bool:
        return any(item.has_text for item in self.attachments)

    @property
    def has_pending_visual_evidence(self) -> bool:
        return any((item.needs_ocr or item.needs_vlm) and not item.has_text for item in self.attachments)

    @property
    def who_to_whom(self) -> dict[str, Any]:
        return {
            "from": self.sender,
            "to": self.to,
            "cc": self.cc,
            "bcc": self.bcc,
        }

    def payload(self) -> dict[str, Any]:
        return {
            "mail_profile": "v1",
            "mail_subject": self.subject,
            "mail_normalized_subject": self.normalized_subject,
            "mail_from": self.sender,
            "mail_from_email": self.sender_email,
            "mail_to": self.to,
            "mail_cc": self.cc,
            "mail_bcc": self.bcc,
            "mail_recipients": self.recipients,
            "mail_participants": self.participants,
            "mail_who_to_whom": self.who_to_whom,
            "mail_date": self.date,
            "mail_timestamp": self.timestamp,
            "mail_message_id": self.message_id,
            "mail_in_reply_to": self.in_reply_to,
            "mail_references": self.references,
            "mail_thread_key": self.thread_key,
            "mail_thread_root": self.thread_root,
            "mail_importance": self.importance,
            "mail_body_snippet": self.body_snippet,
            "mail_has_attachments": self.has_attachments,
            "mail_attachment_count": len(self.attachments),
            "mail_attachment_names": self.attachment_names,
            "mail_attachment_text_available": self.attachment_text_available,
            "mail_pending_visual_evidence": self.has_pending_visual_evidence,
            "mail_attachments": [item.payload() for item in self.attachments],
        }

    def message_embedding_text(self, *, include_attachment_text: bool = False) -> str:
        attachment_lines = []
        for item in self.attachments:
            marker = item.extraction
            if item.needs_ocr or item.needs_vlm:
                marker += ", needs_ocr_vlm"
            attachment_lines.append(
                f"- {item.filename or '(без имени)'} | {item.content_type or item.kind} | {marker}"
            )
            if include_attachment_text and item.text:
                attachment_lines.append(f"  Текст вложения: {_compact(item.text, _attachment_text_limit())}")
        if not attachment_lines:
            attachment_lines.append("- нет")

        return "\n".join(
            [
                f"# {self.subject}",
                "Тип: email",
                f"Тема: {self.subject}",
                f"Нормализованная тема: {self.normalized_subject}",
                f"От: {self.sender}",
                f"Кому: {', '.join(self.to) or '-'}",
                f"Копия: {', '.join(self.cc) or '-'}",
                f"Скрытая копия: {', '.join(self.bcc) or '-'}",
                f"Участники: {', '.join(self.participants) or '-'}",
                f"Кто-кому: {self.sender} -> {', '.join(self.recipients) or '-'}",
                f"Дата: {self.date or '-'}",
                f"Важность: {self.importance}",
                f"Thread: {self.thread_key}",
                f"Thread root: {self.thread_root or '-'}",
                f"Message-ID: {self.message_id or '-'}",
                f"In-Reply-To: {self.in_reply_to or '-'}",
                f"References: {', '.join(self.references) or '-'}",
                "",
                "Вложения:",
                *attachment_lines,
                "",
                "Тело письма:",
                _compact(self.body, _body_text_limit()),
            ]
        )


def build_mail_vector_profile(path: Path, source_dir: Path | None = None) -> MailVectorProfile:
    if path.suffix.lower() == ".msg":
        return _build_msg_profile(path, source_dir)
    return _build_eml_profile(path, source_dir)


def normalize_subject(subject: str) -> str:
    value = str(subject or "").strip()
    previous = None
    while value and value != previous:
        previous = value
        value = REPLY_PREFIX_RE.sub("", value).strip()
    return SPACE_RE.sub(" ", value).strip()


def _build_eml_profile(path: Path, source_dir: Path | None) -> MailVectorProfile:
    msg = BytesParser(policy=policy.default).parsebytes(read_email_message_bytes(path))

    subject = str(msg.get("Subject", "") or "").strip() or "(без темы)"
    sender_values = _format_addresses(str(msg.get("From", "") or ""))
    sender = sender_values[0] if sender_values else str(msg.get("From", "") or "")
    sender_email = _first_email(str(msg.get("From", "") or ""))
    to = _format_addresses(str(msg.get("To", "") or ""))
    cc = _format_addresses(str(msg.get("Cc", "") or ""))
    bcc = _format_addresses(str(msg.get("Bcc", "") or ""))
    body, attachments = _body_and_attachments_from_eml(msg)
    message_id = _canonical_message_id(str(msg.get("Message-ID", "") or ""))
    in_reply_to = _first_message_id(str(msg.get("In-Reply-To", "") or ""))
    references = _message_ids(str(msg.get("References", "") or ""))
    return _profile(
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
        importance=_importance(
            str(msg.get("Importance", "") or ""),
            str(msg.get("X-Priority", "") or ""),
            str(msg.get("Priority", "") or ""),
        ),
        body=body,
        attachments=attachments,
    )


def _build_msg_profile(path: Path, source_dir: Path | None) -> MailVectorProfile:
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
    importance = "normal"
    body = ""
    attachments: list[MailAttachmentProfile] = []
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
        importance = _importance(str(getattr(msg, "importance", "") or ""), "", "")
        body = msg.body or ""
        attachments = _attachments_from_msg(msg)
    except Exception:
        pass

    return _profile(
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
        importance=importance,
        body=body,
        attachments=attachments,
    )


def _profile(
    *,
    path: Path,
    source_dir: Path | None,
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
    importance: str,
    body: str,
    attachments: list[MailAttachmentProfile],
) -> MailVectorProfile:
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
    return MailVectorProfile(
        path=path.as_posix(),
        relative_path=_relative_path(path, source_dir),
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
        importance=importance,
        body=body,
        body_snippet=_compact(body, 420),
        attachments=attachments,
    )


def _body_and_attachments_from_eml(msg: Any) -> tuple[str, list[MailAttachmentProfile]]:
    body_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[MailAttachmentProfile] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            filename = part.get_filename()
            disposition = (part.get_content_disposition() or "").lower()
            content_type = part.get_content_type()
            if filename or disposition == "attachment" or content_type.startswith("image/"):
                data = part.get_payload(decode=True) or b""
                attachments.append(_attachment_profile(filename or "(без имени)", content_type, data))
                continue
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
    body = "\n".join(body_parts).strip() or _strip_html("\n".join(html_parts))
    return body, attachments


def _attachments_from_msg(msg: Any) -> list[MailAttachmentProfile]:
    attachments = []
    for item in getattr(msg, "attachments", []) or []:
        filename = getattr(item, "longFilename", "") or getattr(item, "shortFilename", "") or "(без имени)"
        data = b""
        for attr in ("data", "content", "rawData"):
            value = getattr(item, attr, None)
            if isinstance(value, (bytes, bytearray)):
                data = bytes(value)
                break
        content_type = _content_type_from_filename(filename)
        attachments.append(_attachment_profile(filename, content_type, data))
    return attachments


def _attachment_profile(filename: str, content_type: str, data: bytes) -> MailAttachmentProfile:
    suffix = Path(filename or "").suffix.lower()
    sha1 = hashlib.sha1(data).hexdigest() if data else ""
    kind = _attachment_kind(filename, content_type)
    text = ""
    extraction = "metadata_only"
    needs_ocr = False
    needs_vlm = False
    error = ""

    if not data:
        error = "empty_attachment_bytes"
    elif len(data) > _attachment_max_bytes():
        extraction = "skipped_large"
        error = f"attachment larger than {_attachment_max_bytes()} bytes"
        needs_ocr = kind in {"image", "pdf"}
        needs_vlm = needs_ocr
    elif kind == "text":
        text = _decode_bytes(data)
        extraction = "text"
    elif kind == "html":
        text = _strip_html(_decode_bytes(data))
        extraction = "html_text"
    elif kind == "pdf":
        text, error = _extract_pdf_text(data)
        extraction = "pdf_text" if text else "pdf_needs_ocr_vlm"
        needs_ocr = not bool(text)
        needs_vlm = not bool(text)
    elif kind == "docx":
        text, error = _extract_docx_text(data)
        extraction = "docx_text" if text else "docx_unread"
    elif kind == "image":
        text, error = _ocr_image_bytes(data, suffix=suffix or ".png")
        extraction = "ocr_tesseract" if text else "image_needs_ocr_vlm"
        if not text:
            vlm_text, vlm_error = _vlm_image_bytes(data, content_type=content_type)
            if vlm_text:
                text = vlm_text
                extraction = "vlm"
            else:
                error = "; ".join(item for item in (error, vlm_error) if item)
        needs_ocr = not bool(text)
        needs_vlm = not bool(text)

    attachment_id = _short_hash(f"{filename}:{sha1}:{content_type}") if sha1 else _short_hash(filename)
    return MailAttachmentProfile(
        attachment_id=attachment_id,
        filename=filename or "(без имени)",
        content_type=content_type,
        size_bytes=len(data),
        sha1=sha1,
        kind=kind,
        extraction=extraction,
        text=_compact(text, _attachment_text_limit()),
        needs_ocr=needs_ocr,
        needs_vlm=needs_vlm,
        error=error,
    )


def _attachment_kind(filename: str, content_type: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    ctype = (content_type or "").lower()
    if ctype.startswith("image/") or suffix in IMAGE_SUFFIXES:
        return "image"
    if ctype == "application/pdf" or suffix in PDF_SUFFIXES:
        return "pdf"
    if suffix in DOCX_SUFFIXES:
        return "docx"
    if ctype == "text/html" or suffix in {".html", ".htm"}:
        return "html"
    if ctype.startswith("text/") or suffix in TEXT_SUFFIXES:
        return "text"
    return "binary"


def _content_type_from_filename(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return f"image/{suffix.lstrip('.')}"
    if suffix == ".pdf":
        return "application/pdf"
    if suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if suffix in {".html", ".htm"}:
        return "text/html"
    if suffix in TEXT_SUFFIXES:
        return "text/plain"
    return "application/octet-stream"


def _ocr_image_bytes(data: bytes, *, suffix: str) -> tuple[str, str]:
    if os.getenv("MAIL_ATTACHMENT_OCR_ENABLED", "true").lower() not in {"1", "true", "yes", "on"}:
        return "", "ocr_disabled"
    tesseract = shutil.which(os.getenv("MAIL_TESSERACT_BIN", "tesseract"))
    if not tesseract:
        return "", "tesseract_not_found"
    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
            tmp.write(data)
            tmp.flush()
            result = subprocess.run(
                [
                    tesseract,
                    tmp.name,
                    "stdout",
                    "-l",
                    os.getenv("MAIL_OCR_LANG", "rus+eng"),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=float(os.getenv("MAIL_OCR_TIMEOUT_SEC", "30")),
            )
        text = (result.stdout or "").strip()
        if result.returncode == 0 and text:
            return text, ""
        return "", (result.stderr or "tesseract_returned_no_text").strip()
    except Exception as error:
        return "", str(error)


def _vlm_image_bytes(data: bytes, *, content_type: str) -> tuple[str, str]:
    if os.getenv("MAIL_ATTACHMENT_VLM_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}:
        return "", "vlm_disabled"
    base_url = os.getenv("MAIL_VLM_URL", "").strip().rstrip("/")
    model = os.getenv("MAIL_VLM_MODEL", "").strip()
    if not base_url or not model:
        return "", "vlm_not_configured"
    try:
        import httpx

        prompt = os.getenv(
            "MAIL_VLM_PROMPT",
            "Опиши содержимое изображения как evidence для поиска по переписке. "
            "Если есть текст, перепиши его полностью.",
        )
        mime = content_type or "image/png"
        image_b64 = base64.b64encode(data).decode("ascii")
        response = httpx.post(
            f"{base_url}/v1/chat/completions",
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                        ],
                    }
                ],
                "max_tokens": int(os.getenv("MAIL_VLM_MAX_TOKENS", "512")),
            },
            timeout=float(os.getenv("MAIL_VLM_TIMEOUT_SEC", "60")),
        )
        response.raise_for_status()
        data_json = response.json()
        content = data_json.get("choices", [{}])[0].get("message", {}).get("content", "")
        return str(content or "").strip(), ""
    except Exception as error:
        return "", str(error)


def _extract_pdf_text(data: bytes) -> tuple[str, str]:
    if os.getenv("MAIL_ATTACHMENT_PDF_SUBPROCESS_ENABLED", "true").lower() in {"1", "true", "yes", "on"}:
        return _extract_pdf_text_subprocess(data)
    return _extract_pdf_text_inprocess(data)


def _extract_pdf_text_subprocess(data: bytes) -> tuple[str, str]:
    timeout = float(os.getenv("MAIL_ATTACHMENT_PDF_TIMEOUT_SEC", "30"))
    max_pages = max(1, int(os.getenv("MAIL_ATTACHMENT_PDF_MAX_PAGES", "20")))
    text_limit = _attachment_text_limit()
    tmp_path = ""
    child_code = r"""
import json
import sys

path = sys.argv[1]
max_pages = max(1, int(sys.argv[2]))
try:
    import fitz

    parts = []
    with fitz.open(path) as doc:
        for index, page in enumerate(doc):
            if index >= max_pages:
                break
            text = page.get_text("text") or ""
            if text.strip():
                parts.append(text)
    print(json.dumps({"text": "\n".join(parts), "error": ""}, ensure_ascii=False))
except BaseException as error:
    print(json.dumps({"text": "", "error": str(error)}, ensure_ascii=False))
"""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(data)
            tmp.flush()
            tmp_path = tmp.name
        result = subprocess.run(
            [sys.executable, "-c", child_code, tmp_path, str(max_pages)],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "", f"pdf_extractor_timeout_after_{timeout:g}s"
    except Exception as error:
        return "", str(error)
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return "", _compact(f"pdf_extractor_exit_{result.returncode}: {detail}", 500)
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as error:
        detail = (result.stderr or result.stdout or "").strip()
        return "", _compact(f"pdf_extractor_bad_json: {error}: {detail}", 500)
    text = str(payload.get("text") or "")
    error = str(payload.get("error") or "")
    return _compact(text, text_limit), error


def _extract_pdf_text_inprocess(data: bytes) -> tuple[str, str]:
    try:
        import fitz

        max_pages = int(os.getenv("MAIL_ATTACHMENT_PDF_MAX_PAGES", "20"))
        with fitz.open(stream=data, filetype="pdf") as doc:
            parts = []
            for page in list(doc)[:max(1, max_pages)]:
                text = page.get_text("text") or ""
                if text.strip():
                    parts.append(text)
        return _compact("\n".join(parts), _attachment_text_limit()), ""
    except Exception as error:
        return "", str(error)


def _extract_docx_text(data: bytes) -> tuple[str, str]:
    try:
        import io
        import mammoth

        result = mammoth.convert_to_markdown(io.BytesIO(data))
        return _compact(result.value or "", _attachment_text_limit()), ""
    except Exception as error:
        return "", str(error)


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


def _importance(importance: str, x_priority: str, priority: str) -> str:
    value = " ".join([importance, x_priority, priority]).casefold()
    if any(token in value for token in ("low", "non-urgent", "низк", "5")):
        return "low"
    if any(token in value for token in ("high", "urgent", "важн", "1", "2")):
        return "high"
    return "normal"


def _decode_bytes(data: bytes, charset: str = "") -> str:
    for encoding in [charset, "utf-8", "cp1251", "latin-1"]:
        if not encoding:
            continue
        try:
            return data.decode(encoding, errors="replace").strip()
        except Exception:
            pass
    return data.decode("utf-8", errors="replace").strip()


def _strip_html(value: str) -> str:
    return SPACE_RE.sub(" ", html.unescape(HTML_TAG_RE.sub(" ", value or ""))).strip()


def _compact(text: str, limit: int) -> str:
    value = SPACE_RE.sub(" ", str(text or "")).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _relative_path(path: Path, source_dir: Path | None) -> str:
    if source_dir is not None:
        try:
            return path.relative_to(source_dir).as_posix()
        except ValueError:
            pass
    return path.name


def _short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _attachment_max_bytes() -> int:
    try:
        return max(1, int(os.getenv("MAIL_ATTACHMENT_MAX_BYTES", str(20 * 1024 * 1024))))
    except ValueError:
        return 20 * 1024 * 1024


def _attachment_text_limit() -> int:
    try:
        return max(100, int(os.getenv("MAIL_ATTACHMENT_TEXT_CHARS", "20000")))
    except ValueError:
        return 20000


def _body_text_limit() -> int:
    try:
        return max(1000, int(os.getenv("MAIL_BODY_TEXT_CHARS", "100000")))
    except ValueError:
        return 100000


def deterministic_mail_node_id(dataset_id: str, file_key: str, node_key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{dataset_id}:{file_key}:{node_key}"))
