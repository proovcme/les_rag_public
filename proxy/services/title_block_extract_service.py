"""Извлечение основной надписи (штампа) по ГОСТ Р 21.101 — Phase 5 нормоконтроля.

Зачем: проверка D4-002 «Основная надпись (штамп)» в doc_review была всегда manual_required (layout).
Этот сервис даёт ей computed-evidence: детектит ПРИСУТСТВИЕ штампа по сигнатурам полей основной
надписи (Изм./Кол.уч./№ док./Подп./Стадия/Листов/Разраб./Н.контр.…) в тексте листа. 0 LLM.

Детект по УЖЕ ИЗВЛЕЧЁННОМУ тексту (надёжнее layout-парсинга PDF — см. риск в плане: PDF плохо
извлекается). Поля (обозначение/стадия) — best-effort бонус; присутствие штампа — основной вердикт.
Неуверенно (мало сигнатур) → не врём: остаётся manual_required.
"""

from __future__ import annotations

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


def extract_from_pdf(pdf_path: str | Path, *, max_pages: int = 3) -> TitleBlock:
    """PDF → текст первых/последних страниц → детект штампа. Штамп есть на каждом листе → хватает
    нескольких страниц. fitz (как normcontrol_service); сбой/нет fitz → пустой вердикт (не падаем)."""
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
    if len(joined.strip()) < 60:  # пустой текст-слой → скан: штамп текстом не извлечь (нужен OCR)
        return TitleBlock(False, 0.0, [], {}, p.name, "нет текст-слоя (скан) — штамп текстом не извлечь", scan=True)
    return detect_in_text(joined, source=p.name)


def detect_dataset(source_paths: list[str], *, sample: int = 8) -> dict[str, Any]:
    """Сэмпл PDF-документов комплекта → агрегат присутствия штампа. Возвращает сводку для D4-002:
    checked / present / maybe / absent + примеры. Сэмпл (не все) — чтобы не молотить 600+ файлов."""
    pdfs = [sp for sp in source_paths if sp and str(sp).lower().endswith(".pdf")]
    picked = pdfs[:sample]
    present = scan = no_stamp = 0   # штамп есть · скан (нет текста) · текст-лист без штампа/нечитаем
    examples: list[dict[str, Any]] = []
    for sp in picked:
        tb = extract_from_pdf(sp)
        if tb.scan:
            scan += 1
        elif tb.present:
            present += 1
        else:
            no_stamp += 1
        if len(examples) < 6:
            examples.append({"file": Path(sp).name, "present": tb.present, "scan": tb.scan,
                             "confidence": tb.confidence, "signatures": tb.signatures})
    return {
        "pdf_total": len(pdfs),
        "checked": len(picked),
        "present": present,
        "scan": scan,
        "no_stamp": no_stamp,
        "examples": examples,
    }
