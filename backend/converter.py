"""
converter.py — конвертация документов в Markdown для RAG.

Поддерживаемые форматы:
  PDF, DOCX, EML, MSG, XLSX/XLS/CSV, JSON/JSONL, MD, TXT
"""
import logging
import json
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Лимит текста на файл — защита от огромных документов
MAX_FILE_CHARS = 500_000  # ~125k токенов

SUPPORTED = {
    ".pdf", ".docx", ".doc",
    ".eml", ".msg",
    ".xlsx", ".xls", ".csv",
    ".json", ".jsonl",
    ".md", ".txt",
}


def convert_to_markdown(file_path: Path) -> Optional[str]:
    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED:
        logger.warning(f"[CONVERT] Неподдерживаемый формат: {suffix} ({file_path.name})")
        return None

    logger.info(f"[CONVERT] {file_path.name} ({suffix}, {file_path.stat().st_size // 1024} KB)")
    try:
        if suffix == ".pdf":
            result = _parse_pdf(file_path)
        elif suffix in (".docx", ".doc"):
            result = _parse_docx(file_path)
        elif suffix in (".eml", ".msg"):
            result = _parse_email(file_path)
        elif suffix in (".xlsx", ".xls", ".csv"):
            result = _parse_spreadsheet(file_path)
        elif suffix in (".json", ".jsonl"):
            result = _parse_json(file_path)
        elif suffix in (".md", ".txt"):
            result = file_path.read_text(encoding="utf-8", errors="ignore")
        else:
            return None

        if result and len(result) > MAX_FILE_CHARS:
            logger.warning(f"[CONVERT] {file_path.name}: обрезан до {MAX_FILE_CHARS} символов")
            result = result[:MAX_FILE_CHARS]

        return result if result and result.strip() else None

    except Exception as e:
        logger.error(f"[CONVERT] Ошибка {file_path.name}: {e}", exc_info=True)
        return None


def _parse_pdf(path: Path) -> str:
    try:
        import pymupdf4llm
        md = pymupdf4llm.to_markdown(str(path), pages=None, write_images=False)
        if md and md.strip():
            return md
        logger.warning(f"[CONVERT] pymupdf4llm вернул пустоту для {path.name}, fallback")
    except Exception as e:
        logger.warning(f"[CONVERT] pymupdf4llm failed ({e}), fallback to fitz")

    # Fallback — базовый fitz
    import fitz
    doc = fitz.open(str(path))
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text()
        if text.strip():
            pages.append(f"## Стр. {i+1}\n{text}")
    doc.close()
    return "\n\n".join(pages) or f"[WARN] {path.name}: текст не извлечён (сканированный PDF?)"


def _parse_docx(path: Path) -> str:
    import mammoth
    with open(path, "rb") as f:
        result = mammoth.convert_to_markdown(f)
    if result.messages:
        for msg in result.messages:
            logger.debug(f"[CONVERT] mammoth: {msg}")
    return result.value


def _parse_email(path: Path) -> str:
    if path.suffix.lower() == ".msg":
        import extract_msg
        msg = extract_msg.Message(str(path))
        parts = [
            f"# {msg.subject or '(без темы)'}",
            f"От: {msg.sender}",
            f"Дата: {msg.date}",
            "",
            msg.body or "",
        ]
        return "\n".join(parts)
    else:
        import email
        from email import policy
        with open(path, "rb") as f:
            msg = email.message_from_binary_file(f, policy=policy.default)
        body_parts = []
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == "text/plain":
                    try:
                        body_parts.append(part.get_content())
                    except Exception:
                        pass
        else:
            try:
                body_parts.append(msg.get_content())
            except Exception:
                pass
        body = "\n".join(body_parts)
        return (
            f"# {msg.get('Subject', '(без темы)')}\n"
            f"От: {msg.get('From', '?')}\n"
            f"Дата: {msg.get('Date', '?')}\n\n"
            f"{body}"
        )


def _parse_spreadsheet(path: Path) -> str:
    import pandas as pd
    md_parts = []

    try:
        if path.suffix.lower() == ".csv":
            # Пробуем несколько кодировок
            for enc in ("utf-8", "cp1251", "latin-1"):
                try:
                    df = pd.read_csv(path, encoding=enc, nrows=2000)
                    break
                except UnicodeDecodeError:
                    continue
            md_parts.append(f"## Таблица: {path.stem}\n{df.to_markdown(index=False)}")
        else:
            xls = pd.ExcelFile(path)
            for sheet in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=sheet, nrows=2000)
                if df.empty:
                    continue
                md_parts.append(f"## Лист: {sheet}\n{df.to_markdown(index=False)}")
    except Exception as e:
        logger.error(f"[CONVERT] spreadsheet error {path.name}: {e}")
        return f"[ERROR] Не удалось прочитать таблицу: {e}"

    return "\n\n".join(md_parts) if md_parts else f"[WARN] {path.name}: таблица пуста"


def _parse_json(path: Path) -> str:
    md = []
    size_mb = path.stat().st_size / (1024 * 1024)
    MAX_ENTRIES = 2000

    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            first_line = f.readline().strip()
            f.seek(0)

            # Определяем JSONL по первой строке
            is_jsonl = False
            try:
                json.loads(first_line)
                is_jsonl = True
            except Exception:
                pass

            if is_jsonl or size_mb > 10:
                # Стриминг построчно
                for i, line in enumerate(f):
                    if i >= MAX_ENTRIES:
                        md.append(f"*[обрезано после {MAX_ENTRIES} записей]*")
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        txt = _extract_json_text(obj)
                        if txt:
                            md.append(f"### Запись {i+1}\n{txt}")
                    except Exception:
                        pass
            else:
                data = json.load(f)
                items = data if isinstance(data, list) else [data]
                for i, item in enumerate(items[:MAX_ENTRIES]):
                    txt = _extract_json_text(item)
                    if txt:
                        md.append(f"### Запись {i+1}\n{txt}")

    except Exception as e:
        return f"[ERROR] JSON parse failed: {e}"

    return "\n\n".join(md) if md else f"[WARN] {path.name}: нет извлекаемого текста"


# Поля которые содержат полезный текст в типичных JSON датасетах
_TEXT_KEYS = frozenset([
    "role", "user", "assistant", "system", "prompt", "response",
    "content", "message", "text", "subject", "body", "delta",
    "question", "answer", "title", "description", "summary",
])

def _extract_json_text(obj, depth: int = 0) -> str:
    """Рекурсивно извлекает текст из JSON-объекта (глубина до 2)."""
    if depth > 2:
        return ""
    if isinstance(obj, str):
        return obj[:2000] if len(obj) > 5 else ""
    if not isinstance(obj, dict):
        return ""
    parts = []
    for k, v in obj.items():
        k_lower = k.lower()
        if k_lower in _TEXT_KEYS:
            if isinstance(v, str) and len(v) > 5:
                parts.append(f"**{k}:** {v[:2000]}")
            elif isinstance(v, dict):
                nested = _extract_json_text(v, depth + 1)
                if nested:
                    parts.append(nested)
    return "\n".join(parts)
