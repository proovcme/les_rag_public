"""Е.Ж.И.К. // olm_reader.py — архив Outlook для Mac (.olm) → письма. Без внешних зависимостей.

.olm = ZIP с XML-сообщениями в формате OPF (Outlook Property Format). Достаём из каждого
сообщения тему/отправителя/получателей/дату/тело и пишем минимальный .eml (RFC822), чтобы
дальше его жевал штатный почтовый конвейер (mail_profile/.eml). Только stdlib (zipfile/xml/email).
"""

from __future__ import annotations

import html
import logging
import re
import zipfile
from email.message import EmailMessage
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger("ejik.olm")

_TAG_RE = re.compile(r"\{.*\}")  # снять namespace из тега
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _localname(tag: str) -> str:
    return _TAG_RE.sub("", tag or "")


def _strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    return html.unescape(_HTML_TAG_RE.sub("", text)).strip()


def _message_xml_names(zf: zipfile.ZipFile) -> list[str]:
    # Сообщения OLM — xml-файлы внутри папок аккаунта; служебные (например, *_categories.xml) отсеиваем.
    return [
        n for n in zf.namelist()
        if n.lower().endswith(".xml") and "message" in n.lower()
    ]


def _parse_olm_xml(raw: bytes) -> dict[str, Any] | None:
    from xml.etree import ElementTree

    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return None

    subject = body = html_body = sent = ""
    addresses: dict[str, list[str]] = {"from": [], "to": [], "cc": []}
    current_kind = None

    for el in root.iter():
        name = _localname(el.tag)
        text = (el.text or "").strip()
        if name == "OPFMessageCopySubject" and text:
            subject = text
        elif name == "OPFMessageCopyBody" and text:
            body = text
        elif name == "OPFMessageCopyHTMLBody" and text:
            html_body = text
        elif name in ("OPFMessageCopySentTime", "OPFMessageCopyReceivedTime") and text and not sent:
            sent = text
        elif name == "OPFMessageCopySenderAddress":
            current_kind = "from"
        elif name == "OPFMessageCopyToAddresses":
            current_kind = "to"
        elif name == "OPFMessageCopyCCAddresses":
            current_kind = "cc"
        elif name == "emailAddress":
            addr = el.get("OPFContactEmailAddressAddress", "").strip()
            nm = el.get("OPFContactEmailAddressName", "").strip()
            who = f"{nm} <{addr}>" if nm and addr else (addr or nm)
            if who and current_kind in addresses:
                addresses[current_kind].append(who)

    text_body = body or _strip_html(html_body)
    if not (subject or text_body or addresses["from"]):
        return None
    return {"subject": subject, "body": text_body, "sent": sent, **addresses}


def _build_eml(msg: dict[str, Any]) -> bytes:
    em = EmailMessage()
    em["Subject"] = msg.get("subject") or "(без темы)"
    if msg.get("from"):
        em["From"] = ", ".join(msg["from"])
    if msg.get("to"):
        em["To"] = ", ".join(msg["to"])
    if msg.get("cc"):
        em["Cc"] = ", ".join(msg["cc"])
    sent = msg.get("sent") or ""
    if sent:
        try:
            em["Date"] = format_datetime(parsedate_to_datetime(sent))
        except (TypeError, ValueError):
            em["Date"] = sent
    em.set_content(msg.get("body") or "")
    return em.as_bytes()


def iter_olm_messages(olm_path: Path) -> Iterator[dict[str, Any]]:
    """Сообщения из .olm как словари (subject/body/from/to/cc/sent). Без записи на диск."""
    with zipfile.ZipFile(olm_path) as zf:
        for name in _message_xml_names(zf):
            try:
                parsed = _parse_olm_xml(zf.read(name))
            except (KeyError, zipfile.BadZipFile) as err:
                logger.warning("[OLM] %s: %s", name, err)
                continue
            if parsed:
                parsed["_source"] = name
                yield parsed


def extract_olm_to_eml(olm_path: Path, out_dir: Path) -> list[Path]:
    """Извлечь .olm → по .eml на письмо в out_dir. Возвращает список путей."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for idx, msg in enumerate(iter_olm_messages(olm_path), 1):
        eml_path = out_dir / f"olm_{idx:05d}.eml"
        try:
            eml_path.write_bytes(_build_eml(msg))
            written.append(eml_path)
        except OSError as err:
            logger.warning("[OLM] write %s failed: %s", eml_path.name, err)
    logger.info("[OLM] %s → %s писем", olm_path.name, len(written))
    return written
