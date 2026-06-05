from __future__ import annotations
"""
Е.Ж.И.К. // pst_reader.py
==========================
Парсер PST-архивов Outlook через pypff.

Особенности:
- Инкрементальный обход с checkpoint (JSON) — при падении продолжаем с места
- Каждое письмо → dict с метаданными для Qdrant payload
- Вложения → через ConverterRouter (PDF/DOCX/XLSX)
- Тред-реконструкция по Message-ID / In-Reply-To
- Нормализация subject для group_id (убираем Re:/Fwd:)

Зависимости:
    pip install pypff extract-msg --break-system-packages
    # pypff требует libpff: brew install libpff (macOS)
    # или сборка из исходников: https://github.com/libyal/libpff

Запуск вручную (тест):
    python3 pst_reader.py /path/to/archive.pst --out /tmp/pst_out
"""

import hashlib
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

logger = logging.getLogger("ejik.pst")

# ─────────────────────────────────────────
# DATACLASS: одно письмо
# ─────────────────────────────────────────

@dataclass
class MailMessage:
    message_id: str          # <xxx@domain> или синтетический
    thread_id: str           # hash нормализованного subject
    in_reply_to: str         # <yyy@domain> или ""
    subject: str
    from_addr: str
    to_addrs: list           # list[str]
    cc_addrs: list           # list[str]
    date: str                # ISO 8601
    body_text: str           # plain text тело
    body_html: str           # HTML тело (если есть)
    attachments: list        # list[AttachmentInfo]
    folder_path: str         # "Inbox/Проект X"
    source_pst: str          # имя PST файла
    has_attachments: bool = False
    importance: str = "normal"   # low / normal / high


@dataclass
class AttachmentInfo:
    filename: str
    size_bytes: int
    content_type: str
    local_path: str          # путь к временному файлу после извлечения
    parent_message_id: str


# ─────────────────────────────────────────
# CHECKPOINT
# ─────────────────────────────────────────

class PSTCheckpoint:
    """
    Хранит прогресс обхода PST.
    Структура: {"processed": ["entry_id_1", ...], "total": N, "done": bool}
    """

    def __init__(self, checkpoint_path: Path):
        self.path = checkpoint_path
        self._data: dict = {"processed": [], "total": 0, "done": False}
        if checkpoint_path.exists():
            try:
                self._data = json.loads(checkpoint_path.read_text())
                logger.info(f"[CHECKPOINT] Восстановлен: {len(self._data['processed'])} писем обработано")
            except Exception as e:
                logger.warning(f"[CHECKPOINT] Не удалось прочитать: {e}, начинаем заново")

    def is_done(self) -> bool:
        return self._data.get("done", False)

    def is_processed(self, entry_id: str) -> bool:
        return entry_id in self._data["processed"]

    def mark_processed(self, entry_id: str):
        self._data["processed"].append(entry_id)
        self._save()

    def set_total(self, total: int):
        self._data["total"] = total
        self._save()

    def mark_done(self):
        self._data["done"] = True
        self._save()

    def progress(self) -> tuple:
        return len(self._data["processed"]), self._data.get("total", 0)

    def _save(self):
        try:
            self.path.write_text(json.dumps(self._data, ensure_ascii=False))
        except Exception as e:
            logger.error(f"[CHECKPOINT] Ошибка сохранения: {e}")


# ─────────────────────────────────────────
# УТИЛИТЫ
# ─────────────────────────────────────────

def _normalize_subject(subject: str) -> str:
    """Убирает Re:/Fwd:/Ответ: и пробелы для group_id."""
    s = re.sub(r"^(re|fwd?|ответ|отв|перес|fw)\s*:\s*", "", subject.strip(), flags=re.IGNORECASE)
    return s.strip().lower()


def _thread_id(subject: str) -> str:
    """Стабильный hash нормализованного subject."""
    normalized = _normalize_subject(subject)
    return hashlib.md5(normalized.encode()).hexdigest()[:16]


def _synthetic_message_id(folder: str, index: int, subject: str) -> str:
    """Генерируем message-id если у письма нет оригинального."""
    raw = f"{folder}:{index}:{subject}"
    h = hashlib.md5(raw.encode()).hexdigest()[:12]
    return f"<synthetic-{h}@ejik.local>"


def _parse_date(dt_value) -> str:
    """Конвертируем datetime-like объект pypff в ISO строку."""
    if dt_value is None:
        return datetime.now(timezone.utc).isoformat()
    try:
        if hasattr(dt_value, "isoformat"):
            return dt_value.isoformat()
        # pypff возвращает целое число (FILETIME) или строку
        if isinstance(dt_value, int):
            # Windows FILETIME → Unix timestamp
            unix_ts = (dt_value - 116444736000000000) / 10_000_000
            return datetime.fromtimestamp(unix_ts, tz=timezone.utc).isoformat()
        return str(dt_value)
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def _parse_recipients(message) -> tuple:
    """Извлекаем to/cc из pypff message object."""
    to_list = []
    cc_list = []
    try:
        recipients = message.recipients
        if recipients:
            for r in recipients:
                addr = ""
                try:
                    addr = r.email_address or r.display_name or ""
                except Exception:
                    pass
                rtype = 0
                try:
                    rtype = r.type
                except Exception:
                    pass
                if rtype == 1:  # CC
                    cc_list.append(addr)
                else:
                    to_list.append(addr)
    except Exception:
        pass
    return to_list, cc_list


def _extract_body(message) -> tuple:
    """Возвращает (plain_text, html)."""
    plain = ""
    html = ""
    try:
        plain = message.plain_text_body or ""
        if isinstance(plain, bytes):
            plain = plain.decode("utf-8", errors="replace")
    except Exception:
        pass
    try:
        html = message.html_body or ""
        if isinstance(html, bytes):
            html = html.decode("utf-8", errors="replace")
    except Exception:
        pass
    return plain, html


# ─────────────────────────────────────────
# ОСНОВНОЙ ПАРСЕР
# ─────────────────────────────────────────

class PSTReader:
    """
    Читает PST-файл и выдаёт MailMessage через итератор.

    Пример:
        reader = PSTReader("/path/to/archive.pst", attach_dir="/tmp/attach")
        for msg in reader.iter_messages():
            print(msg.subject, msg.from_addr)
    """

    def __init__(
        self,
        pst_path: str,
        attach_dir: str = "/tmp/ejik_attachments",
        checkpoint_dir: str = "/tmp/ejik_checkpoints",
        max_attachment_mb: int = 50,
    ):
        self.pst_path = Path(pst_path)
        self.attach_dir = Path(attach_dir)
        self.attach_dir.mkdir(parents=True, exist_ok=True)
        self.max_attach_bytes = max_attachment_mb * 1024 * 1024

        cp_name = f"{self.pst_path.stem}.checkpoint.json"
        self.checkpoint = PSTCheckpoint(Path(checkpoint_dir) / cp_name)
        Path(checkpoint_dir).mkdir(parents=True, exist_ok=True)

    def iter_messages(self) -> Iterator[MailMessage]:
        """Итератор по всем письмам PST с checkpoint."""
        try:
            import pypff
        except ImportError:
            raise RuntimeError(
                "pypff не установлен. Установи: pip install pypff --break-system-packages\n"
                "macOS: brew install libpff && pip install pypff --break-system-packages"
            )

        if self.checkpoint.is_done():
            logger.info(f"[PST] {self.pst_path.name} уже полностью обработан (checkpoint)")
            return

        pst = pypff.file()
        pst.open(str(self.pst_path))

        try:
            root = pst.get_root_folder()
            # Считаем всего писем для прогресса
            total = self._count_messages(root)
            self.checkpoint.set_total(total)
            logger.info(f"[PST] {self.pst_path.name}: {total} писем найдено")

            yield from self._walk_folder(root, folder_path="", pst_name=self.pst_path.name)
            self.checkpoint.mark_done()
            logger.info(f"[PST] {self.pst_path.name}: обход завершён")

        finally:
            pst.close()

    def _count_messages(self, folder) -> int:
        """Рекурсивный подсчёт писем."""
        count = 0
        try:
            count += folder.number_of_messages
        except Exception:
            pass
        try:
            for i in range(folder.number_of_sub_folders):
                sf = folder.get_sub_folder(i)
                count += self._count_messages(sf)
        except Exception:
            pass
        return count

    def _walk_folder(self, folder, folder_path: str, pst_name: str) -> Iterator[MailMessage]:
        """Рекурсивный обход папок PST."""
        folder_name = ""
        try:
            folder_name = folder.name or ""
        except Exception:
            pass

        current_path = f"{folder_path}/{folder_name}".strip("/")

        # Письма в текущей папке
        try:
            n_messages = folder.number_of_messages
        except Exception:
            n_messages = 0

        for i in range(n_messages):
            try:
                msg = folder.get_message(i)
                mail = self._parse_message(msg, current_path, pst_name, i)
                if mail:
                    if not self.checkpoint.is_processed(mail.message_id):
                        yield mail
                        self.checkpoint.mark_processed(mail.message_id)
                    else:
                        logger.debug(f"[PST] Пропуск (уже обработано): {mail.message_id}")
            except Exception as e:
                logger.warning(f"[PST] Ошибка парсинга письма {i} в {current_path}: {e}")

        # Подпапки
        try:
            n_folders = folder.number_of_sub_folders
        except Exception:
            n_folders = 0

        for i in range(n_folders):
            try:
                sub = folder.get_sub_folder(i)
                yield from self._walk_folder(sub, current_path, pst_name)
            except Exception as e:
                logger.warning(f"[PST] Ошибка входа в подпапку {i}: {e}")

    def _parse_message(self, msg, folder_path: str, pst_name: str, index: int) -> Optional[MailMessage]:
        """Парсим одно письмо в MailMessage."""
        # Subject
        subject = ""
        try:
            subject = msg.subject or ""
            if isinstance(subject, bytes):
                subject = subject.decode("utf-8", errors="replace")
        except Exception:
            pass

        # From
        from_addr = ""
        try:
            from_addr = msg.sender_email_address or msg.sender_name or ""
        except Exception:
            pass

        # Message-ID
        message_id = ""
        try:
            message_id = msg.message_identifier or ""
            if isinstance(message_id, bytes):
                message_id = message_id.decode("utf-8", errors="replace")
        except Exception:
            pass

        if not message_id:
            message_id = _synthetic_message_id(folder_path, index, subject)

        # In-Reply-To
        in_reply_to = ""
        try:
            in_reply_to = msg.in_reply_to_identifier or ""
            if isinstance(in_reply_to, bytes):
                in_reply_to = in_reply_to.decode("utf-8", errors="replace")
        except Exception:
            pass

        # Date
        date_str = ""
        try:
            date_str = _parse_date(msg.delivery_time)
        except Exception:
            date_str = datetime.now(timezone.utc).isoformat()

        # Recipients
        to_addrs, cc_addrs = _parse_recipients(msg)

        # Body
        body_text, body_html = _extract_body(msg)

        # Importance
        importance = "normal"
        try:
            imp = msg.importance
            importance = {0: "low", 1: "normal", 2: "high"}.get(imp, "normal")
        except Exception:
            pass

        # Attachments
        attachments = self._extract_attachments(msg, message_id)

        return MailMessage(
            message_id=message_id,
            thread_id=_thread_id(subject),
            in_reply_to=in_reply_to,
            subject=subject,
            from_addr=from_addr,
            to_addrs=to_addrs,
            cc_addrs=cc_addrs,
            date=date_str,
            body_text=body_text,
            body_html=body_html,
            attachments=attachments,
            folder_path=folder_path,
            source_pst=pst_name,
            has_attachments=len(attachments) > 0,
            importance=importance,
        )

    def _extract_attachments(self, msg, parent_message_id: str) -> list:
        """Извлекаем вложения во временную папку."""
        result = []
        try:
            n = msg.number_of_attachments
        except Exception:
            return result

        for i in range(n):
            try:
                att = msg.get_attachment(i)
                filename = ""
                try:
                    filename = att.name or att.long_filename or f"attachment_{i}"
                    if isinstance(filename, bytes):
                        filename = filename.decode("utf-8", errors="replace")
                except Exception:
                    filename = f"attachment_{i}"

                size = 0
                try:
                    size = att.data_size or 0
                except Exception:
                    pass

                if size > self.max_attach_bytes:
                    logger.info(f"[PST] Пропуск большого вложения {filename} ({size/1024/1024:.1f} MB)")
                    continue

                # Безопасное имя файла
                safe_name = re.sub(r"[^\w\-_\.\s]", "_", filename)
                msg_hash = hashlib.md5(parent_message_id.encode()).hexdigest()[:8]
                local_path = self.attach_dir / f"{msg_hash}_{i}_{safe_name}"

                try:
                    data = att.read_buffer(size) if size > 0 else b""
                    if data:
                        local_path.write_bytes(data)
                        # Определяем content-type по расширению
                        ext = Path(filename).suffix.lower()
                        ct_map = {
                            ".pdf": "application/pdf",
                            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            ".doc": "application/msword",
                            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            ".xls": "application/vnd.ms-excel",
                            ".msg": "application/vnd.ms-outlook",
                            ".eml": "message/rfc822",
                        }
                        content_type = ct_map.get(ext, "application/octet-stream")

                        result.append(AttachmentInfo(
                            filename=filename,
                            size_bytes=size,
                            content_type=content_type,
                            local_path=str(local_path),
                            parent_message_id=parent_message_id,
                        ))
                except Exception as e:
                    logger.warning(f"[PST] Не удалось извлечь вложение {filename}: {e}")

            except Exception as e:
                logger.warning(f"[PST] Ошибка вложения {i}: {e}")

        return result

    def progress(self) -> dict:
        done, total = self.checkpoint.progress()
        return {
            "processed": done,
            "total": total,
            "pct": round(done / total * 100, 1) if total > 0 else 0,
            "done": self.checkpoint.is_done(),
        }


# ─────────────────────────────────────────
# КОНВЕРТЕР: MailMessage → Qdrant чанки
# ─────────────────────────────────────────

def message_to_chunks(msg: MailMessage) -> list:
    """
    Разбиваем письмо на чанки для Qdrant.
    Возвращает list[dict] с полями text + metadata.

    Один email → 1 чанк тела + N чанков вложений.
    """
    chunks = []

    # ── Чанк тела письма ──────────────────
    body = msg.body_text.strip()
    if not body and msg.body_html:
        # Грубая очистка HTML если нет plain text
        body = re.sub(r"<[^>]+>", " ", msg.body_html)
        body = re.sub(r"\s+", " ", body).strip()

    if body:
        # Формируем текст чанка с заголовком для контекста
        header = (
            f"Письмо: {msg.subject}\n"
            f"От: {msg.from_addr}\n"
            f"Кому: {', '.join(msg.to_addrs)}\n"
            f"Дата: {msg.date}\n"
            f"Папка: {msg.folder_path}\n"
            f"---\n"
            f"{body}"
        )
        chunks.append({
            "text": header,
            "metadata": {
                "type": "email_body",
                "message_id": msg.message_id,
                "thread_id": msg.thread_id,
                "in_reply_to": msg.in_reply_to,
                "subject": msg.subject,
                "from": msg.from_addr,
                "to": msg.to_addrs,
                "cc": msg.cc_addrs,
                "date": msg.date,
                "folder": msg.folder_path,
                "source_pst": msg.source_pst,
                "has_attachments": msg.has_attachments,
                "importance": msg.importance,
            }
        })

    # ── Чанки вложений ────────────────────
    # Вложения конвертируются через ConverterRouter в proxy_server
    # Здесь только добавляем метаданные-ссылки
    for att in msg.attachments:
        chunks.append({
            "text": f"Вложение к письму '{msg.subject}': {att.filename}",
            "metadata": {
                "type": "email_attachment_ref",
                "message_id": msg.message_id,
                "thread_id": msg.thread_id,
                "subject": msg.subject,
                "from": msg.from_addr,
                "date": msg.date,
                "attachment_filename": att.filename,
                "attachment_path": att.local_path,
                "attachment_size": att.size_bytes,
                "attachment_content_type": att.content_type,
                "source_pst": msg.source_pst,
            }
        })

    return chunks


# ─────────────────────────────────────────
# ЯНДЕКС IMAP
# ─────────────────────────────────────────

class YandexIMAPReader:
    """
    IMAP-коннектор для Яндекс Почты.
    Инкрементальный: хранит последний UID в checkpoint.

    Требует: pip install aioimaplib --break-system-packages
    Яндекс: включить IMAP в настройках + App Password если 2FA.
    """

    IMAP_HOST = "imap.yandex.ru"
    IMAP_PORT = 993

    def __init__(
        self,
        login: str,
        password: str,  # App Password при 2FA
        checkpoint_dir: str = "/tmp/ejik_checkpoints",
        folders: list = None,  # None = все папки
    ):
        self.login = login
        self.password = password
        self.folders = folders or ["INBOX", "Sent", "Отправленные"]
        cp_path = Path(checkpoint_dir) / f"imap_{login.replace('@','_')}.json"
        Path(checkpoint_dir).mkdir(parents=True, exist_ok=True)
        self._cp_path = cp_path
        self._cp: dict = {}
        if cp_path.exists():
            try:
                self._cp = json.loads(cp_path.read_text())
            except Exception:
                pass

    def _last_uid(self, folder: str) -> int:
        return self._cp.get(folder, {}).get("last_uid", 0)

    def _save_uid(self, folder: str, uid: int):
        if folder not in self._cp:
            self._cp[folder] = {}
        self._cp[folder]["last_uid"] = uid
        self._cp_path.write_text(json.dumps(self._cp, ensure_ascii=False))

    async def fetch_new_messages(self) -> list:
        """
        Возвращает list[MailMessage] новых писем с момента последнего запуска.
        """
        try:
            import aioimaplib
        except ImportError:
            raise RuntimeError(
                "aioimaplib не установлен: pip install aioimaplib --break-system-packages"
            )

        import email as email_lib
        from email.header import decode_header

        client = aioimaplib.IMAP4_SSL(host=self.IMAP_HOST, port=self.IMAP_PORT)
        await client.wait_hello_from_server()
        await client.login(self.login, self.password)

        messages = []

        for folder in self.folders:
            try:
                status, _ = await client.select(f'"{folder}"')
                if status != "OK":
                    logger.warning(f"[IMAP] Папка не найдена: {folder}")
                    continue

                last_uid = self._last_uid(folder)
                search_criteria = f"UID {last_uid + 1}:*" if last_uid > 0 else "ALL"
                status, data = await client.uid("search", None, search_criteria)

                if status != "OK" or not data[0]:
                    continue

                uids = data[0].decode().split()
                if not uids or uids == [""]:
                    continue

                logger.info(f"[IMAP] {folder}: {len(uids)} новых писем")
                max_uid = last_uid

                for uid_str in uids:
                    try:
                        uid = int(uid_str)
                        status, msg_data = await client.uid("fetch", uid_str, "(RFC822)")
                        if status != "OK":
                            continue

                        raw = msg_data[1]
                        parsed = email_lib.message_from_bytes(raw)

                        # Subject
                        raw_subject = parsed.get("Subject", "")
                        subject_parts = decode_header(raw_subject)
                        subject = ""
                        for part, enc in subject_parts:
                            if isinstance(part, bytes):
                                subject += part.decode(enc or "utf-8", errors="replace")
                            else:
                                subject += part

                        # From
                        from_addr = parsed.get("From", "")

                        # Message-ID
                        message_id = parsed.get("Message-ID", "").strip()
                        if not message_id:
                            message_id = _synthetic_message_id(folder, uid, subject)

                        # In-Reply-To
                        in_reply_to = parsed.get("In-Reply-To", "").strip()

                        # Date
                        from email.utils import parsedate_to_datetime
                        date_str = datetime.now(timezone.utc).isoformat()
                        try:
                            dt = parsedate_to_datetime(parsed.get("Date", ""))
                            date_str = dt.isoformat()
                        except Exception:
                            pass

                        # To / CC
                        to_addrs = [a.strip() for a in parsed.get("To", "").split(",") if a.strip()]
                        cc_addrs = [a.strip() for a in parsed.get("CC", "").split(",") if a.strip()]

                        # Body
                        body_text = ""
                        body_html = ""
                        attachments = []

                        if parsed.is_multipart():
                            for part in parsed.walk():
                                ct = part.get_content_type()
                                disp = str(part.get("Content-Disposition", ""))
                                if ct == "text/plain" and "attachment" not in disp:
                                    try:
                                        body_text += part.get_payload(decode=True).decode(
                                            part.get_content_charset() or "utf-8", errors="replace"
                                        )
                                    except Exception:
                                        pass
                                elif ct == "text/html" and "attachment" not in disp:
                                    try:
                                        body_html += part.get_payload(decode=True).decode(
                                            part.get_content_charset() or "utf-8", errors="replace"
                                        )
                                    except Exception:
                                        pass
                                elif "attachment" in disp or part.get_filename():
                                    fname = part.get_filename() or f"attach_{uid}"
                                    try:
                                        data = part.get_payload(decode=True)
                                        if data:
                                            safe = re.sub(r"[^\w\-_\.\s]", "_", fname)
                                            ap = Path("/tmp/ejik_attachments") / f"imap_{uid}_{safe}"
                                            ap.parent.mkdir(parents=True, exist_ok=True)
                                            ap.write_bytes(data)
                                            attachments.append(AttachmentInfo(
                                                filename=fname,
                                                size_bytes=len(data),
                                                content_type=ct,
                                                local_path=str(ap),
                                                parent_message_id=message_id,
                                            ))
                                    except Exception as e:
                                        logger.warning(f"[IMAP] Вложение {fname}: {e}")
                        else:
                            try:
                                body_text = parsed.get_payload(decode=True).decode(
                                    parsed.get_content_charset() or "utf-8", errors="replace"
                                )
                            except Exception:
                                pass

                        messages.append(MailMessage(
                            message_id=message_id,
                            thread_id=_thread_id(subject),
                            in_reply_to=in_reply_to,
                            subject=subject,
                            from_addr=from_addr,
                            to_addrs=to_addrs,
                            cc_addrs=cc_addrs,
                            date=date_str,
                            body_text=body_text,
                            body_html=body_html,
                            attachments=attachments,
                            folder_path=folder,
                            source_pst=f"imap:{self.login}",
                            has_attachments=len(attachments) > 0,
                        ))

                        max_uid = max(max_uid, uid)

                    except Exception as e:
                        logger.warning(f"[IMAP] Ошибка письма UID {uid_str}: {e}")

                self._save_uid(folder, max_uid)

            except Exception as e:
                logger.error(f"[IMAP] Папка {folder}: {e}")

        await client.logout()
        return messages


# ─────────────────────────────────────────
# CLI: тест вручную
# ─────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Е.Ж.И.К. PST Reader")
    parser.add_argument("pst_file", help="Путь к PST файлу")
    parser.add_argument("--out", default="/tmp/pst_out", help="Папка для вложений")
    parser.add_argument("--limit", type=int, default=0, help="Максимум писем (0 = все)")
    args = parser.parse_args()

    reader = PSTReader(args.pst_file, attach_dir=args.out)
    count = 0
    for msg in reader.iter_messages():
        chunks = message_to_chunks(msg)
        print(f"[{count+1}] {msg.date[:10]} | {msg.from_addr[:30]:30s} | {msg.subject[:50]}")
        if msg.attachments:
            for a in msg.attachments:
                print(f"      📎 {a.filename} ({a.size_bytes//1024} KB)")
        count += 1
        if args.limit and count >= args.limit:
            print(f"\n[LIMIT] Остановка на {args.limit} письмах")
            break

    prog = reader.progress()
    print(f"\n[ИТОГ] Обработано: {prog['processed']}/{prog['total']} ({prog['pct']}%)")
