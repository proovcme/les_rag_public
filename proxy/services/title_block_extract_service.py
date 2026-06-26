"""Извлечение основной надписи (штампа) по ГОСТ Р 21.101 — Phase 5 нормоконтроля.

Зачем: проверка D4-002 «Основная надпись (штамп)» в doc_review была всегда manual_required (layout).
Этот сервис даёт ей computed-evidence: детектит ПРИСУТСТВИЕ штампа по сигнатурам полей основной
надписи (Изм./Кол.уч./№ док./Подп./Стадия/Листов/Разраб./Н.контр.…) в тексте листа. 0 LLM.

Детект по УЖЕ ИЗВЛЕЧЁННОМУ тексту (надёжнее layout-парсинга PDF — см. риск в плане: PDF плохо
извлекается). Поля (обозначение/стадия) — best-effort бонус; присутствие штампа — основной вердикт.
Неуверенно (мало сигнатур) → не врём: остаётся manual_required.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Сигнатуры полей основной надписи (ГОСТ Р 21.101, форма 3) — нормализованные (без пробелов/точек,
# нижний регистр, ё→е). Это метки штампа, редкие вне него; их кластер = штамп присутствует.
_STAMP_SIGNS: tuple[str, ...] = (
    "колуч",        # Кол.уч.
    "ндок", "№док", # № док.
    "стадия",
    "листов",
    "разраб",       # Разраб.
    "нконтр", "нормоконтр",  # Н.контр. / Нормоконтр.
    "масштаб",
    "взамин", "взаминв",     # Взам. инв. №
    "инвн",         # Инв. №
    "подп",         # Подп.
)
# Порог: ≥4 разных сигнатур → штамп есть (высокая уверенность); 3 → средняя; <3 → нет/неуверенно.
_PRESENT_MIN = 4
_MAYBE_MIN = 3

_STAGE_RE = re.compile(r"стади[яи][^а-яё]{0,4}([прПР]{1,2}|рабоч|проект)", re.IGNORECASE)


@dataclass
class TitleBlock:
    present: bool
    confidence: float            # 0..1
    signatures: list[str] = field(default_factory=list)  # какие метки нашли
    fields: dict[str, Any] = field(default_factory=dict)  # best-effort: stage, designation
    source: str = ""             # имя файла/листа
    note: str = ""
    scan: bool = False           # нет текст-слоя (скан) — штамп текстом не извлечь (нужен OCR)
    ocr_used: bool = False       # для скана попробовали Tesseract-OCR штампа

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _norm(text: str) -> str:
    return re.sub(r"[\s.\-—]+", "", (text or "").lower().replace("ё", "е"))


def detect_in_text(text: str, *, source: str = "") -> TitleBlock:
    """Текст листа → вердикт о штампе. Сигнатуры считаются по нормализованной форме."""
    norm = _norm(text)
    found = sorted({s for s in _STAMP_SIGNS if s in norm})
    n = len(found)
    fields: dict[str, Any] = {}
    m = _STAGE_RE.search(text or "")
    if m:
        fields["stage_raw"] = m.group(0).strip()[:40]
    if n >= _PRESENT_MIN:
        return TitleBlock(True, min(1.0, 0.6 + 0.1 * n), found, fields, source,
                          f"штамп: {n} сигнатур основной надписи")
    if n >= _MAYBE_MIN:
        return TitleBlock(False, 0.4, found, fields, source,
                          f"возможен штамп ({n} сигнатуры) — нужна ручная проверка")
    return TitleBlock(False, 0.0, found, fields, source, "признаков штампа не найдено")


def _ocr_enabled() -> bool:
    """OCR штампа для сканов — за флагом ``LES_TITLE_BLOCK_OCR`` (вне hot-path: рендер+Tesseract медленны,
    нормоконтроль по умолчанию быстрый). Оператор включает на скан-комплект."""
    return os.getenv("LES_TITLE_BLOCK_OCR", "").strip().lower() in ("1", "true", "yes", "on")


def _render_page_image(pdf_path: str | Path, page_index: int = 0):
    """Страница PDF → PIL.Image для OCR штампа. По умолчанию клип нижне-правого угла (основная надпись,
    форма 3 ГОСТ 21.101) ДО растеризации — мелкий быстрый pixmap вместо листа A1 целиком. fitz+PIL; нет
    любого — None. Регион/DPI: ``LES_TITLE_BLOCK_OCR_REGION`` (br|full), ``LES_TITLE_BLOCK_OCR_DPI``."""
    try:
        import fitz
        from PIL import Image
    except Exception:
        return None
    region = os.getenv("LES_TITLE_BLOCK_OCR_REGION", "br").strip().lower()
    dpi = float(os.getenv("LES_TITLE_BLOCK_OCR_DPI", "300") or 300)
    try:
        with fitz.open(str(pdf_path)) as doc:
            if page_index >= doc.page_count:
                return None
            page = doc[page_index]
            r = page.rect
            clip = None
            if region != "full":  # нижне-правый угол: правые ~55% × нижние ~42% листа
                clip = fitz.Rect(r.x0 + r.width * 0.45, r.y0 + r.height * 0.58, r.x1, r.y1)
            pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), clip=clip)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    except Exception:
        return None


def _ocr_title_block_text(pdf_path: str | Path, *, page_index: int = 0) -> tuple[str, bool]:
    """OCR штампа скан-PDF через Tesseract (бинарь, изолирован от venv — backend.ocr_parser). Штамп на
    каждом листе → хватает первой страницы. Возвращает (распознанный_текст, попытка_была)."""
    img = _render_page_image(pdf_path, page_index)
    if img is None:
        return "", False
    try:
        from backend.ocr_parser import TesseractOCRParser

        return (TesseractOCRParser().ocr_page(img) or ""), True
    except Exception:
        return "", True


def extract_from_pdf(pdf_path: str | Path, *, max_pages: int = 3, ocr: bool | None = None) -> TitleBlock:
    """PDF → текст первых/последних страниц → детект штампа. Штамп есть на каждом листе → хватает
    нескольких страниц. fitz (как normcontrol_service); сбой/нет fitz → пустой вердикт (не падаем).

    Скан (нет текст-слоя) + ``ocr`` (None → флаг ``LES_TITLE_BLOCK_OCR``): пробуем Tesseract по штампу.
    OCR может только ПОДТВЕРДИТЬ штамп (скан→present); если не подтвердил — остаётся ``scan`` (manual),
    «нет штампа» по шумному OCR НЕ утверждаем (анти-галлюцинация)."""
    p = Path(pdf_path)
    if not p.exists() or p.suffix.lower() != ".pdf":
        return TitleBlock(False, 0.0, [], {}, p.name, "не PDF / файл отсутствует")
    try:
        import fitz
    except Exception:
        return TitleBlock(False, 0.0, [], {}, p.name, "fitz недоступен")
    text_parts: list[str] = []
    try:
        with fitz.open(str(p)) as doc:
            pc = doc.page_count
            idxs = sorted(set(list(range(min(max_pages, pc))) + ([pc - 1] if pc else [])))
            for i in idxs:
                text_parts.append(doc[i].get_text() or "")
    except Exception as e:  # noqa: BLE001
        return TitleBlock(False, 0.0, [], {}, p.name, f"чтение PDF не удалось: {e}")
    joined = "\n".join(text_parts)
    if len(joined.strip()) >= 60:  # есть текст-слой → детект по тексту (быстрый путь)
        return detect_in_text(joined, source=p.name)

    # пустой текст-слой → скан: штамп текстом не извлечь
    if ocr is None:
        ocr = _ocr_enabled()
    if not ocr:
        return TitleBlock(False, 0.0, [], {}, p.name, "нет текст-слоя (скан) — штамп текстом не извлечь", scan=True)

    ocr_text, attempted = _ocr_title_block_text(p)
    if ocr_text:
        tb = detect_in_text(ocr_text, source=p.name)
        tb.ocr_used = True
        if tb.present:
            tb.note = "штамп распознан OCR — " + tb.note
            return tb  # scan=False по умолчанию: OCR подтвердил штамп на скане
        # OCR прочитал текст, но штамп не подтверждён — не утверждаем «нет штампа» по шуму
        return TitleBlock(False, tb.confidence, tb.signatures, tb.fields, p.name,
                          "скан: OCR не подтвердил штамп — проверить вручную", scan=True, ocr_used=True)
    return TitleBlock(False, 0.0, [], {}, p.name,
                      "скан: OCR недоступен/пуст — штамп проверить вручную", scan=True, ocr_used=attempted)


def detect_dataset(source_paths: list[str], *, sample: int = 8, ocr: bool | None = None) -> dict[str, Any]:
    """Сэмпл PDF-документов комплекта → агрегат присутствия штампа. Возвращает сводку для D4-002:
    checked / present / scan / no_stamp + примеры. Сэмпл (не все) — чтобы не молотить 600+ файлов.

    ``ocr`` (None → флаг ``LES_TITLE_BLOCK_OCR``): для сканов пробуем Tesseract по штампу — подтверждённый
    OCR'ом штамп уходит из ``scan`` в ``present`` (D4-002 → supported вместо вечного manual)."""
    if ocr is None:
        ocr = _ocr_enabled()
    pdfs = [sp for sp in source_paths if sp and str(sp).lower().endswith(".pdf")]
    picked = pdfs[:sample]
    present = scan = no_stamp = ocr_used = 0   # штамп есть · скан · текст-лист без штампа · OCR-попыток
    examples: list[dict[str, Any]] = []
    for sp in picked:
        tb = extract_from_pdf(sp, ocr=ocr)
        if tb.ocr_used:
            ocr_used += 1
        if tb.scan:
            scan += 1
        elif tb.present:
            present += 1
        else:
            no_stamp += 1
        if len(examples) < 6:
            examples.append({"file": Path(sp).name, "present": tb.present, "scan": tb.scan,
                             "confidence": tb.confidence, "signatures": tb.signatures,
                             "ocr_used": tb.ocr_used})
    return {
        "pdf_total": len(pdfs),
        "checked": len(picked),
        "present": present,
        "scan": scan,
        "no_stamp": no_stamp,
        "ocr_used": ocr_used,
        "examples": examples,
    }
