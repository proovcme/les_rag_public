"""
converter.py — конвертация документов в Markdown для RAG.

Поддерживаемые форматы:
  PDF, DOCX, EML/EMLX, MSG, XLSX/XLS/CSV, JSON/JSONL, MD, TXT
"""
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Лимит текста на файл — защита от огромных документов
MAX_FILE_CHARS = 500_000  # ~125k токенов
PDF_MAX_FILE_CHARS = 2_000_000
BOOK_PDF_MIN_PAGES = 200

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}

SUPPORTED = {
    ".pdf", ".docx", ".doc",
    ".eml", ".emlx", ".msg",
    ".xlsx", ".xlsm", ".xls", ".csv",
    ".pptx",
    ".json", ".jsonl",
    ".md", ".txt",
    ".p7m",                       # подписанный PKCS#7 (обычно PDF внутри) → разворачиваем
    *IMAGE_SUFFIXES,              # сканы-картинки → vision-OCR
}


def _parse_with_markitdown(file_path: Path) -> Optional[str]:
    """Конвертация с использованием универсального конвертера Microsoft MarkItDown."""
    try:
        from markitdown import MarkItDown
        md = MarkItDown()
        result = md.convert(str(file_path))
        if result and result.text_content:
            return result.text_content
    except Exception as e:
        logger.warning(f"[CONVERT] MarkItDown failed for {file_path.name}: {e}")
    return None


def convert_to_markdown(file_path: Path, route=None) -> Optional[str]:
    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED:
        logger.warning(f"[CONVERT] Неподдерживаемый формат: {suffix} ({file_path.name})")
        return None

    logger.info(f"[CONVERT] {file_path.name} ({suffix}, {file_path.stat().st_size // 1024} KB)")
    try:
        if suffix == ".pdf":
            result = _parse_pdf(file_path, route=route)
        elif suffix == ".p7m":
            result = _parse_p7m(file_path, route=route)
        elif suffix in IMAGE_SUFFIXES:
            result = _parse_image_ocr(file_path)
        elif suffix == ".docx":
            result = _parse_with_markitdown(file_path) or _parse_docx(file_path)
        elif suffix == ".doc":
            # legacy бинарный .doc: markitdown/mammoth (только .docx) не берут → нативный textutil
            result = _parse_with_markitdown(file_path) or _parse_legacy_doc(file_path)
        elif suffix in (".eml", ".emlx", ".msg"):
            result = _parse_email(file_path)
        elif suffix in (".xlsx", ".xlsm", ".xls", ".csv"):
            result = _parse_with_markitdown(file_path) or _parse_spreadsheet(file_path)
        elif suffix == ".pptx":
            result = _parse_with_markitdown(file_path)
        elif suffix in (".json", ".jsonl"):
            result = _parse_json(file_path)
        elif suffix in (".md", ".txt"):
            result = file_path.read_text(encoding="utf-8", errors="ignore")
        else:
            return None

        max_chars = _max_file_chars(file_path)
        if result and len(result) > max_chars:
            logger.warning(f"[CONVERT] {file_path.name}: обрезан до {max_chars} символов")
            result = result[:max_chars]

        return result if result and result.strip() else None

    except Exception as e:
        logger.error(f"[CONVERT] Ошибка {file_path.name}: {e}", exc_info=True)
        return None


def _parse_pdf(path: Path, route=None) -> str:
    # Проверяем настройки OCR из переменных окружения
    ocr_enabled = os.getenv("RAG_OCR_ENABLED", "true").lower() in ("true", "1", "yes", "on")
    ocr_dpi = int(os.getenv("RAG_OCR_DPI", "150"))

    force_ocr = False
    if route and getattr(route, "pipeline", None) == "markdown_needs_ocr":
        force_ocr = True

    # Скан без текстового слоя → сразу НАШ OCR (make_ocr_parser, напр. tesseract rus+eng),
    # не пуская встроенный eng-OCR pymupdf4llm (он даёт латинскую кашу на кириллице).
    if not force_ocr and ocr_enabled:
        try:
            import fitz
            with fitz.open(str(path)) as _d:
                _real = sum(len(_d[i].get_text() or "") for i in range(min(3, _d.page_count)))
            if _real < 80:
                logger.info("[CONVERT] %s: нет текстового слоя → наш OCR (минуя eng-OCR pymupdf)", path.name)
                force_ocr = True
        except Exception:  # noqa: BLE001
            pass

    # 1. Если роутер явно сказал делать OCR, делаем его сразу
    if force_ocr and ocr_enabled:
        logger.info(f"[CONVERT] Запуск OCR конвейера для {path.name} по требованию роутера")
        try:
            from .ocr_parser import make_ocr_parser
            parser = make_ocr_parser()
            md = parser.parse_pdf(path, dpi=ocr_dpi)
            if md and md.strip():
                return md
        except Exception as ocr_err:
            logger.error(f"[CONVERT] Ошибка OCR для {path.name}: {ocr_err}", exc_info=True)

    # 1.5 (W1.5, ADR-5): опциональный layout-aware парсер Docling — таблицы через
    # TableFormer. Включается RAG_PDF_PARSER=docling (нужен extra: uv sync --extra parsers).
    # Любой сбой → тихий fallback на штатный pymupdf-путь ниже.
    if os.getenv("RAG_PDF_PARSER", "pymupdf").strip().lower() == "docling":
        try:
            md = _docling_pdf_markdown(path)
            if md and len(md.strip()) > 100:
                return md
            logger.warning("[CONVERT] docling вернул слишком мало текста для %s — fallback pymupdf", path.name)
        except Exception as docling_err:
            logger.warning("[CONVERT] docling failed для %s (%s) — fallback pymupdf", path.name, docling_err)

    # 2. Пытаемся извлечь стандартный текстовый слой.
    # W1.4: большие PDF конвертируются постраничными батчами — ограничивает пик памяти
    # и даёт прогресс в логе (лечение причины таймаутов на 60+ МБ комплектах).
    md_content = ""
    try:
        import pymupdf4llm
        image_dir = _pdf_image_dir(path) if _pdf_image_extraction_enabled(path) else None
        kwargs = dict(
            write_images=image_dir is not None,
            image_path=str(image_dir) if image_dir is not None else "",
            image_format=os.getenv("PDF_IMAGE_FORMAT", "png"),
            show_progress=False,
        )
        page_count = _pdf_page_count(path)
        paged_threshold = int(os.getenv("RAG_PDF_PAGED_THRESHOLD", "80"))
        page_batch = max(10, int(os.getenv("RAG_PDF_PAGE_BATCH", "40")))
        if page_count > paged_threshold:
            parts = []
            for start in range(0, page_count, page_batch):
                batch_pages = list(range(start, min(start + page_batch, page_count)))
                parts.append(pymupdf4llm.to_markdown(str(path), pages=batch_pages, **kwargs))
                logger.info(
                    "[CONVERT] %s: страницы %s-%s из %s",
                    path.name, batch_pages[0] + 1, batch_pages[-1] + 1, page_count,
                )
            md_content = "\n\n".join(parts)
        else:
            md_content = pymupdf4llm.to_markdown(str(path), pages=None, **kwargs)
        if md_content and md_content.strip():
            # Если текст слишком короткий, возможно это скан с парой символов мусора
            if len(md_content.strip()) < 100 and ocr_enabled:
                logger.warning(f"[CONVERT] Текст слишком короткий ({len(md_content)} симв.), подозрение на скан. Пробуем OCR.")
                force_ocr = True
            else:
                return strip_legal_boilerplate(md_content)
    except Exception as e:
        logger.warning(f"[CONVERT] pymupdf4llm failed ({e}), пробуем fitз fallback")

    # 3. Fallback на базовый fitz, если мы ещё не решили делать OCR
    if not force_ocr:
        try:
            import fitz
            doc = fitz.open(str(path))
            pages = []
            for i, page in enumerate(doc):
                text = page.get_text()
                if text.strip():
                    pages.append(f"## Стр. {i+1}\n{text}")
            doc.close()
            extracted = "\n\n".join(pages)
            if extracted.strip() and len(extracted.strip()) > 100:
                return strip_legal_boilerplate(extracted)
        except Exception as e:
            logger.warning(f"[CONVERT] fitz fallback failed: {e}")

    # 4. Если обычный текст пустой или мусорный, и включен OCR — запускаем распознавание
    if ocr_enabled:
        logger.info(f"[CONVERT] Обнаружен пустой или отсканированный PDF: {path.name}. Запуск OCR...")
        try:
            from .ocr_parser import make_ocr_parser
            parser = make_ocr_parser()
            md = parser.parse_pdf(path, dpi=ocr_dpi)
            if md and md.strip():
                return md
        except Exception as ocr_err:
            logger.error(f"[CONVERT] Ошибка фонового OCR для {path.name}: {ocr_err}", exc_info=True)

    return f"[WARN] {path.name}: текст не извлечён (сканированный PDF?)"


# Колонтитулы правовых систем («КонсультантПлюс … Страница N из M») превращаются
# конвертацией в заголовки-чанки и засоряют выдачу с высокими скорами (кейс
# Постановления 87, 2026-06-14). Чистим детерминированно (ADR-11).
_BOILERPLATE_LINE_RE = re.compile(
    r"^\s*#{0,6}\s*\**\s*("
    r"КонсультантПлюс|www\.consultant\.ru|consultant\.ru|"
    r"Страница\s+\d+\s+из\s+\d+|"
    r"надежная правовая поддержка|"
    r"Документ предоставлен КонсультантПлюс"
    r")[\s.*]*$",
    re.IGNORECASE | re.MULTILINE,
)


def strip_legal_boilerplate(md: str) -> str:
    """Удаляет строки-колонтитулы правовых систем из markdown."""
    if not md:
        return md
    cleaned = _BOILERPLATE_LINE_RE.sub("", md)
    return re.sub(r"\n{4,}", "\n\n\n", cleaned)


_docling_converter = None  # ленивая инициализация: тяжёлые layout-модели грузятся один раз


def _docling_pdf_markdown(path: Path) -> str:
    """W1.5: PDF → markdown через Docling (layout-aware, TableFormer для таблиц)."""
    global _docling_converter
    if _docling_converter is None:
        from docling.document_converter import DocumentConverter

        _docling_converter = DocumentConverter()
        logger.info("[CONVERT] docling инициализирован (первый вызов грузит модели)")
    result = _docling_converter.convert(str(path))
    return result.document.export_to_markdown()


def _max_file_chars(path: Path) -> int:
    if path.suffix.lower() == ".pdf" and _pdf_page_count(path) >= BOOK_PDF_MIN_PAGES:
        default = PDF_MAX_FILE_CHARS
    else:
        default = MAX_FILE_CHARS
    env_name = "RAG_PDF_MAX_FILE_CHARS" if path.suffix.lower() == ".pdf" else "RAG_MAX_FILE_CHARS"
    try:
        return max(1, int(os.getenv(env_name, str(default))))
    except ValueError:
        return default


def _pdf_image_extraction_enabled(path: Path) -> bool:
    raw = os.getenv("PDF_IMAGE_EXTRACTION_ENABLED")
    if raw is not None:
        return raw.lower() in {"1", "true", "yes", "on"}
    return _pdf_page_count(path) >= BOOK_PDF_MIN_PAGES


def _pdf_page_count(path: Path) -> int:
    try:
        import fitz

        with fitz.open(str(path)) as doc:
            return int(doc.page_count)
    except Exception:
        return 0


def _pdf_image_dir(path: Path) -> Path:
    image_dir = path.parent / f"{_safe_pdf_asset_stem(path)}_images"
    image_dir.mkdir(parents=True, exist_ok=True)
    return image_dir


def _safe_pdf_asset_stem(path: Path) -> str:
    stem = re.sub(r"[^\w.-]+", "_", path.stem, flags=re.UNICODE).strip("._-")
    return stem or "pdf"


def _parse_docx(path: Path) -> str:
    import mammoth
    with open(path, "rb") as f:
        result = mammoth.convert_to_markdown(f)
    if result.messages:
        for msg in result.messages:
            logger.debug(f"[CONVERT] mammoth: {msg}")
    return result.value


def _parse_legacy_doc(path: Path) -> Optional[str]:
    """Бинарный .doc (Word 97-2003): mammoth/markitdown их не читают (только .docx).

    macOS-нативный ``textutil`` конвертирует .doc/.rtf в txt без сторонних зависимостей.
    Если textutil недоступен (не macOS) — мягко вернуть None (фолбэк на antiword/catdoc, если есть).
    """
    import shutil
    import subprocess

    tu = shutil.which("textutil")
    if tu:
        try:
            out = subprocess.run([tu, "-convert", "txt", "-stdout", str(path)],
                                 capture_output=True, timeout=60)
            text = out.stdout.decode("utf-8", errors="ignore").strip()
            if text:
                return text
            logger.warning("[CONVERT] textutil вернул пусто для %s", path.name)
        except Exception as err:  # noqa: BLE001
            logger.warning("[CONVERT] textutil не справился с %s: %s", path.name, err)
    for tool in ("antiword", "catdoc"):  # фолбэк для не-macOS, если установлены
        exe = shutil.which(tool)
        if exe:
            try:
                out = subprocess.run([exe, str(path)], capture_output=True, timeout=60)
                text = out.stdout.decode("utf-8", errors="ignore").strip()
                if text:
                    return text
            except Exception:  # noqa: BLE001
                continue
    return None


def _parse_image_ocr(path: Path) -> Optional[str]:
    """Скан-картинка (jpg/png/tiff) → текст через тот же vision-OCR, что и скан-PDF."""
    if os.getenv("RAG_OCR_ENABLED", "true").lower() not in ("true", "1", "yes", "on"):
        return None
    try:
        from PIL import Image

        from .ocr_parser import make_ocr_parser

        parser = make_ocr_parser()
        with Image.open(path) as img:
            text = parser.ocr_page(img.convert("RGB"))
        return text if text and text.strip() else None
    except Exception as err:  # noqa: BLE001 — OCR не должен ронять индексацию
        logger.error("[CONVERT] image-OCR %s: %s", path.name, err)
        return None


def _parse_p7m(path: Path, route=None) -> Optional[str]:
    """Подписанный контейнер PKCS#7 (.p7m, обычно PDF внутри): развернуть openssl → распарсить.

    `openssl smime -verify -noverify` снимает подпись без проверки цепочки (нам нужен контент,
    не валидация). Пробуем DER и PEM. Развёрнутый PDF идёт штатным PDF-путём (текст/OCR).
    """
    import shutil
    import subprocess
    import tempfile

    openssl = shutil.which("openssl")
    if not openssl:
        logger.warning("[CONVERT] openssl недоступен — .p7m %s пропущен", path.name)
        return None
    # «Лесной64_АС.pdf.p7m» рядом с «Лесной64_АС.pdf» → открепленная подпись: контента нет,
    # оригинал индексируется сам — тихо пропускаем.
    sibling = path.with_suffix("")  # снять .p7m
    detached = sibling.exists() and sibling.suffix.lower() in SUPPORTED
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "content.bin"
        # cms — современный путь для CAdES/PKCS#7; smime — запасной; оба формата DER/PEM
        attempts = [[openssl, "cms", "-verify", "-noverify", "-in", str(path), "-inform", inf, "-out", str(out)]
                    for inf in ("DER", "PEM")]
        attempts += [[openssl, "smime", "-verify", "-noverify", "-in", str(path), "-inform", inf, "-out", str(out)]
                     for inf in ("DER", "PEM")]
        for cmd in attempts:
            try:
                subprocess.run(cmd, capture_output=True, timeout=60)
                if out.exists() and out.stat().st_size > 0:
                    if out.read_bytes()[:5].startswith(b"%PDF"):
                        pdf = out.with_suffix(".pdf"); out.rename(pdf)
                        return _parse_pdf(pdf, route=route)
                    txt = out.read_text(encoding="utf-8", errors="ignore").strip()
                    if txt:
                        return txt
            except Exception:  # noqa: BLE001
                continue
    if detached:
        logger.info("[CONVERT] .p7m %s — открепленная подпись (оригинал %s индексируется отдельно)",
                    path.name, sibling.name)
    else:
        logger.warning("[CONVERT] .p7m %s: не удалось развернуть контейнер", path.name)
    return None


def _parse_email(path: Path) -> str:
    from .mail_profile import build_mail_vector_profile

    profile = build_mail_vector_profile(path)
    return profile.message_embedding_text(include_attachment_text=True)


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
