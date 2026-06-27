"""Спецификация (форма 9, ГОСТ 21.110) → ВОР (объёмы монтажных работ) — W11.10.

Детерминированное преобразование: каждая позиция спецификации → строка работы, где
объём работы = количество из спецификации, а глагол работы выбирается по категории
предмета (словарь). Ноль LLM (ADR-11). Алгоритм — `docs/ALGO-spec-to-bor.md`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
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


# ── v2: декомпозиция позиции в НАБОР работ (методика ВОР, ГОСТ 21.111) ──
# Категория → перечень работ. Все под-работы наследуют ЕД.+КОЛ-ВО позиции (объём один и тот
# же — линейный/поштучный), поэтому чисел НЕ выдумываем (ADR-11). Работы по числу концов
# (маркировка, расключение) в авто-объём не попадают — отмечаем в примечании.
_DECOMPOSE: tuple[tuple[tuple[str, ...], tuple[str, ...], str], ...] = (
    # (ключевые слова категории, перечень работ, примечание о доп. работах)
    (("кабель", "провод", "шнур"),
     ("Разметка трассы", "Прокладка кабеля"),
     "доп.: маркировка и расключение — по числу концов, добавить отдельно"),
    (("лоток", "короб", "труба", "гофр", "канал"),
     ("Разметка трассы", "Монтаж {предмет}"),
     ""),
    (("стойк", "полка", "подвес", "конструкц", "закладн"),
     ("Монтаж {предмет}",),
     ""),
    (("коробка", "клемм", "наконечник", "крепеж", "крепёж", "дюбель", "хомут", "скоба", "зажим"),
     ("Установка {предмет}",),
     ""),
    (("светильник", "прожектор", "щит", "шкаф", "бокс", "розетк", "выключател", "датчик",
      "извещател", "прибор", "блок", "автомат", "трансформатор", "привод", "двигател",
      "насос", "вентилятор", "агрегат", "оповещател", "модул"),
     ("Установка {предмет}", "Подключение"),
     ""),
)
_DEFAULT_DECOMPOSE = (("Монтаж {предмет}",), "")


def _decompose(name: str) -> tuple[tuple[str, ...], str]:
    low = f" {(name or '').lower().replace('ё', 'е')} "
    for tokens, works, note in _DECOMPOSE:
        if any(t.replace("ё", "е") in low for t in tokens):
            return works, note
    return _DEFAULT_DECOMPOSE


@dataclass
class WorkLine:
    """Строка ВОР (форма ГОСТ 21.111): работа + объём + ссылка на чертёж + примечание."""
    section: str
    work: str
    unit: str
    qty: float | None = None
    chertezh: str = ""           # ссылка на чертёж (шифр/марка позиции)
    note: str = ""               # примечание/формула/доп. работы
    source_rows: int = 0
    qty_missing_rows: int = 0
    sources: list[str] = field(default_factory=list)

    def payload(self) -> dict:
        return {"section": self.section, "name": self.work, "unit": self.unit,
                "qty": (round(self.qty, 3) if self.qty is not None else None),
                "chertezh": self.chertezh, "note": self.note,
                "source_rows": self.source_rows, "sources": self.sources}


def spec_rows_to_work_lines_v2(rows: list[dict]) -> list[WorkLine]:
    """Декомпозиция: позиция → набор работ; свод по (раздел, работа, ед.), сумма qty."""
    lines: dict[tuple, WorkLine] = {}
    for row in rows:
        raw_name = str(row.get("name") or row.get("work_name") or "").strip()
        if not raw_name or _is_noise_name(raw_name):
            continue
        name = re.sub(r"\s+", " ", raw_name)
        unit = normalize_unit(row.get("unit"))
        qty = _row_qty(row)
        section = str(row.get("section") or "").strip()
        chertezh = str(row.get("mark") or row.get("code") or "").strip()
        works, dnote = _decompose(name)
        pos = str(row.get("pos") or row.get("position") or "").strip()
        src = str(row.get("source_file") or "").strip()
        ref = f"{src}#{pos}" if pos else src
        for tmpl in works:
            work = tmpl.replace("{предмет}", name)
            key = (section.casefold(), _normalize_name(work), unit)
            line = lines.get(key)
            if line is None:
                note = f"объём = кол-ву по спецификации (поз. {pos})" if pos else "объём = кол-ву по спецификации"
                if dnote:
                    note += "; " + dnote
                line = WorkLine(section=section, work=work, unit=unit, chertezh=chertezh, note=note)
                lines[key] = line
            if qty is None:
                line.qty_missing_rows += 1
            else:
                line.qty = (line.qty or 0.0) + qty
            line.source_rows += 1
            if ref and ref not in line.sources:
                line.sources.append(ref)
    return sorted(lines.values(), key=lambda l: (l.section.casefold(), l.work.casefold()))


def work_lines_to_xlsx(lines: list[WorkLine], path: Path, *, title: str) -> int:
    """xlsx ВОР по графам ГОСТ 21.111: №/Наименование работ/Ед./Кол-во/Чертёж/Примечание."""
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "ВОР"
    ws.append([title])
    ws.merge_cells("A1:F1")
    ws["A1"].font = Font(bold=True, size=12)
    hdr = ["№", "Наименование работ", "Ед. изм.", "Кол-во", "Ссылка на чертёж", "Примечание"]
    ws.append(hdr)
    fill = PatternFill("solid", fgColor="1F4E78")
    for c in range(1, len(hdr) + 1):
        cell = ws.cell(row=2, column=c)
        cell.fill = fill
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
    cur_section = None
    n = 0
    for line in lines:
        if line.section and line.section != cur_section:
            cur_section = line.section
            ws.append([f"Раздел: {cur_section}"])
            ws.cell(row=ws.max_row, column=1).font = Font(bold=True, italic=True)
        n += 1
        ws.append([n, line.work, line.unit,
                   (round(line.qty, 3) if line.qty is not None else "—"),
                   line.chertezh, line.note])
    widths = [5, 52, 9, 12, 18, 40]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return n


def is_spec_to_bor_query(question: str) -> bool:
    """Намерение «сделай ВОР из спецификации»: упоминание спецификации + ВОР/объёмов работ."""
    q = (question or "").lower().replace("ё", "е")
    if "спецификац" not in q and "форм" not in q:
        return False
    # «вор» — по границе слова: иначе «пОВОРоты», «творог», «забор» ложно триггерят
    # канал ВОР (баг: «собери спецификацию ... повороты» уходил в spec_to_bor).
    return (bool(re.search(r"\bвор\b", q)) or "ведомост" in q or "объем работ" in q
            or "объемов работ" in q)


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
    decompose: bool = True,
) -> dict:
    """Спецификация датасета (Parquet) → ВОР работ → xlsx. Без LLM.

    decompose=True (v2, методика ГОСТ 21.111): позиция → НАБОР работ + графы чертёж/примечание,
    группировка по разделам. decompose=False (v1): 1 позиция → 1 монтажная работа.
    """
    rows = collect_spec_rows(dataset_id, storage_root=storage_root)
    if decompose:
        wlines = spec_rows_to_work_lines_v2(rows)
        result: dict = {
            "dataset_id": dataset_id, "mode": "decompose",
            "source_rows": len(rows), "bor_lines": len(wlines),
            "lines": [w.payload() for w in wlines], "xlsx_path": None,
        }
        if output_dir is not None and wlines:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            xlsx_path = output_dir / f"specbor_{dataset_id}_{stamp}.xlsx"
            work_lines_to_xlsx(wlines, xlsx_path, title=f"ВОР из спецификации (ГОСТ 21.111) — {dataset_id}")
            result["xlsx_path"] = str(xlsx_path)
        return result

    lines = spec_rows_to_work_lines(rows)
    result = {
        "dataset_id": dataset_id, "mode": "simple",
        "source_rows": len(rows), "bor_lines": len(lines),
        "lines": [line.payload() for line in lines], "xlsx_path": None,
    }
    if output_dir is not None and lines:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        xlsx_path = output_dir / f"specbor_{dataset_id}_{stamp}.xlsx"
        bor_to_xlsx(lines, xlsx_path, title=f"ВОР из спецификации (Ф9) — {dataset_id}")
        result["xlsx_path"] = str(xlsx_path)
    return result
