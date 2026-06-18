"""Спецификация (форма 9, ГОСТ 21.110) → ВОР (объёмы монтажных работ) — W11.10.

Детерминированное преобразование: каждая позиция спецификации → строка работы, где
объём работы = количество из спецификации, а глагол работы выбирается по категории
предмета (словарь). Ноль LLM (ADR-11). Алгоритм — `docs/ALGO-spec-to-bor.md`.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from proxy.services.bor_service import (
    BorLine,
    _normalize_name,
    bor_to_xlsx,
    collect_spec_rows,
    normalize_unit,
)

logger = logging.getLogger(__name__)

# qty-приоритет + data-aware fallback (как в reconcile/table).
_QTY_FIELDS = ("qty", "work_volume", "work_done", "work_since_start")

# Заголовки секций / нечисловой мусор — не позиции (как в сверке).
_SECTION_RE = re.compile(r"^\d+\s*[.)]\s")

# Категория предмета → глагол работы. Порядок ВАЖЕН: конкретные предметы выше «Прокладки»,
# иначе прилагательное «кабельный» (лоток/наконечник кабельный) ложно цепляет «Прокладку».
# (глагол, кортеж ключевых слов наименования)
_WORK_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Установка", ("коробка", "клемм", "наконечник", "крепеж", "крепёж", "закладн",
                   "дюбель", "хомут", "скоба", "зажим", "розетк", "выключател")),
    ("Монтаж", ("лоток", "короб", "труба", "гофр", "канал", "стойк", "полка", "подвес",
                "светильник", "прожектор", "щит", "шкаф", "бокс", "датчик", "извещател",
                "прибор", "блок", "автомат", "трансформатор", "привод", "двигател",
                "насос", "вентилятор", "агрегат")),
    ("Прокладка", ("кабель", "провод", "шнур")),
)
_DEFAULT_VERB = "Монтаж"


def _is_noise_name(name: str) -> bool:
    s = (name or "").strip()
    if len(s) < 3 or _SECTION_RE.match(s):
        return True
    return sum(ch.isalpha() for ch in s) < 2


def _row_qty(row: dict) -> float | None:
    for key in _QTY_FIELDS:
        val = row.get(key)
        if val is None:
            continue
        try:
            return float(val)
        except (TypeError, ValueError):
            continue
    return None


def work_verb(name: str) -> str:
    """Глагол работы по категории предмета (словарь). Без LLM."""
    low = f" {(name or '').lower().replace('ё', 'е')} "
    for verb, tokens in _WORK_RULES:
        if any(tok.replace("ё", "е") in low for tok in tokens):
            return verb
    return _DEFAULT_VERB


def spec_rows_to_work_lines(rows: list[dict]) -> list[BorLine]:
    """Свод работ из позиций спецификации: группировка по (раздел, работа, ед.), сумма qty."""
    lines: dict[tuple, BorLine] = {}
    for row in rows:
        raw_name = str(row.get("name") or row.get("work_name") or "").strip()
        if not raw_name or _is_noise_name(raw_name):
            continue
        name = re.sub(r"\s+", " ", raw_name)
        verb = work_verb(name)
        work_name = f"{verb}: {name}"
        section = str(row.get("section") or "").strip()
        code = str(row.get("code") or "").strip()
        mark = str(row.get("mark") or "").strip()
        unit = normalize_unit(row.get("unit"))
        key = (section.casefold(), _normalize_name(work_name), unit)

        line = lines.get(key)
        if line is None:
            line = BorLine(section=section, name=work_name, code=code, mark=mark, unit=unit, qty=None)
            lines[key] = line

        qty = _row_qty(row)
        if qty is None:
            line.qty_missing_rows += 1
        else:
            line.qty = (line.qty or 0.0) + qty
        line.source_rows += 1
        source = str(row.get("source_file") or "").strip()
        pos = str(row.get("pos") or row.get("position") or "").strip()
        ref = f"{source}#{pos}" if pos else source
        if ref and ref not in line.sources:
            line.sources.append(ref)

    return sorted(lines.values(), key=lambda l: (l.section.casefold(), l.name.casefold()))


def is_spec_to_bor_query(question: str) -> bool:
    """Намерение «сделай ВОР из спецификации»: упоминание спецификации + ВОР/объёмов работ."""
    q = (question or "").lower().replace("ё", "е")
    if "спецификац" not in q and "форм" not in q:
        return False
    return ("вор" in q or "ведомост" in q or "объем работ" in q
            or "объемов работ" in q or "в вор" in q)


def format_spec_bor_answer(result: dict, dataset_label: str = "") -> str:
    lines = result.get("lines", [])
    head = (f"ВОР из спецификации (форма 9): {result['bor_lines']} работ "
            f"из {result['source_rows']} позиций"
            + (f" · {dataset_label}" if dataset_label else "") + ".")
    sample = []
    for l in lines[:12]:
        qty = l.get("qty")
        qty_s = f"{round(qty, 2)} {l.get('unit', '')}".strip() if qty is not None else "— (нет кол-ва)"
        sample.append(f"  • {l['name']} — {qty_s}")
    tail = ("\nПолная таблица: Инструменты → ВОР (режим «работы из спецификации») "
            "или POST /api/bor/{id}/from-spec/generate. Числа — Parquet, 0 LLM.")
    return head + ("\n" + "\n".join(sample) if sample else "") + tail


def generate_spec_bor(
    dataset_id: str,
    *,
    storage_root: Path = Path("storage/datasets"),
    output_dir: Path | None = None,
) -> dict:
    """Полный цикл: спецификация датасета (Parquet) → ВОР работ → xlsx. Без LLM."""
    rows = collect_spec_rows(dataset_id, storage_root=storage_root)
    lines = spec_rows_to_work_lines(rows)
    result: dict = {
        "dataset_id": dataset_id,
        "source_rows": len(rows),
        "bor_lines": len(lines),
        "lines": [line.payload() for line in lines],
        "xlsx_path": None,
    }
    if output_dir is not None and lines:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        xlsx_path = output_dir / f"specbor_{dataset_id}_{stamp}.xlsx"
        bor_to_xlsx(lines, xlsx_path, title=f"ВОР из спецификации (Ф9) — {dataset_id}")
        result["xlsx_path"] = str(xlsx_path)
    return result
