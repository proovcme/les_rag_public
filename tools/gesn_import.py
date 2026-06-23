"""Импортёр полной базы ГЭСН-2022: норма → ресурсы (xlsx/csv-выгрузка) → Parquet.

Зачем
=====
Семя ``config/domain/gesn_seed.yaml`` держит ОДНУ демо-норму эталона. Полная база
ГЭСН-2022 — это десятки тысяч норм (47 сборников, Приказ Минстроя 1046/пр), yaml для
такого объёма не годится. Как и ФГИС ЦС (``fgis_price_service``), решение —
нормализованная выгрузка → **Parquet** + O(1) чтение по коду нормы.

Источник (что реально достать программно)
-----------------------------------------
- **Официальный** (fgiscs.minstroyrf.ru / minstroyrf.gov.ru): ФСНБ-2022 раздаётся
  только **PDF** (47 сборников ГЭСН) — машиночитаемой выгрузки расхода ресурсов нет.
- **fsnb2022.ru / cs.smetnoedelo.ru**: HTML-страница на КАЖДУЮ норму
  (``…/gesn12-01-034-02.html``) с таблицей расхода (Затраты труда рабочих/машинистов,
  Машины, Материалы). Bulk-экспорта (CSV/XLSX) нет — только постраничный HTML.
- **ГРАНД-Смета / коммерческие НСИ**: экспорт нормы/сметы в **XLSX** (ресурсная часть
  построчно) — это и есть реалистичный табличный вход.

Поэтому импортёр читает **табличную выгрузку** (XLSX или CSV) одного из двух видов:

1) **flat** — одна строка на ресурс, столбцы:
   ``norm_code, norm_name, norm_unit, kind, per_unit, resource_code,
   resource_name, resource_unit[, price]``.
   Удобно для CSV из БД/скрипта; ``kind`` уже нормализован.

2) **blocks** (стиль ГРАНД-Смете / постраничного экспорта) — нормы идут блоками: строка
   с кодом нормы ``ГЭСН..-..-...-..`` открывает блок (её наименование/ед.изм. рядом),
   далее строки-ресурсы; вид ресурса определяется по русской метке категории в строке
   («Затраты труда рабочих», «…машинистов», «Машины и механизмы», «Материалы») либо по
   подсказке в столбце ``kind``.

Оба вида → одна нормализованная схема Parquet (см. ``RESOURCE_FIELDS``), которую читает
``proxy/services/gesn_service.py``.

Запуск
------
    uv run python -m tools.gesn_import IN.xlsx --out data/gesn_base/gesn2022.parquet
    uv run python -m tools.gesn_import IN.csv  --layout flat
    uv run python -m tools.gesn_import IN.xlsx --layout blocks --sheet 0

0 LLM (ADR-11): структура читается метками/кодами, не моделью.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

# Нормализованная схема ОДНОЙ строки-ресурса в Parquet-базе ГЭСН.
RESOURCE_FIELDS = (
    "norm_code",       # код нормы (ключ), напр. ГЭСН12-01-034-02
    "norm_name",       # наименование нормы
    "norm_unit",       # единица нормы, напр. «100 м2»
    "kind",            # labor | machinist | machine | material
    "per_unit",        # расход на единицу нормы
    "resource_code",   # код ресурса (для цены ФГИС ЦС); для labor — пусто
    "resource_name",   # наименование ресурса
    "resource_unit",   # единица ресурса
    "price",           # снимок цены/тариф (опц., для ОЗП/ОТм — обязателен тариф)
)

DEFAULT_OUT = Path("data/gesn_base/gesn2022.parquet")

# ── нормализация полей ───────────────────────────────────────────────

# Код нормы ГЭСН: «ГЭСН12-01-034-02», «ГЭСНм08-…», «12-01-034-02», латиница «GESN…».
_NORM_CODE_RE = re.compile(r"(?:ГЭСН[А-Яа-я]*|GESN)?\s*\d{2}-\d{2}-\d{3}-\d{2}", re.IGNORECASE)
# «голый» код нормы (формат с дефисами) — отличает норму от кода ресурса (NN.NN…).
_BARE_NORM_RE = re.compile(r"\d{2}-\d{2}-\d{3}-\d{2}")
# Код ресурса ФГИС ЦС: «91.05.01-017», «01.7.15.06-0111», «11.1.03.01-0063».
_RES_CODE_RE = re.compile(r"\d{2}[.\d-]{3,}")

# Метки категорий ресурсов → kind. Порядок: «машинист» раньше «рабоч», иначе «затраты
# труда машинистов» поймается как labor.
_KIND_MATCHERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("machinist", ("труда машинист", "от машинист", "отм", "оплата труда машинист")),
    ("labor", ("труда рабоч", "оплата труда рабоч", "озп", "от(зт)", "от(зп)")),
    ("machine", ("машины и механизм", "эксплуатация машин", "машины", "механизмы")),
    ("material", ("материал", "изделия", "конструкции")),
)


def _kind_from_text(text: Any) -> Optional[str]:
    low = str(text or "").strip().casefold()
    if not low:
        return None
    # уже нормализованный канон
    if low in {"labor", "machinist", "machine", "material"}:
        return low
    for kind, needles in _KIND_MATCHERS:
        if any(n in low for n in needles):
            return kind
    return None


def _norm_code(code: Any) -> str:
    """Канонический ключ кода нормы: trim, upper, без пробелов."""
    return str(code or "").strip().upper().replace(" ", "")


def _looks_like_norm_code(value: Any) -> bool:
    return bool(_BARE_NORM_RE.search(str(value or "")))


def _safe_float(value: Any) -> Optional[float]:
    """'12,94' / '0.0015' / '-' / '' / None → float | None (как в fgis/parquet_writer)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "—", "–", "x", "х", "X", "Х"}:
        return None
    text = text.replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _clean_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _cell(row: list[Any], pos: Optional[int]) -> str:
    if pos is None or pos >= len(row):
        return ""
    return _clean_str(row[pos])


# ── чтение входной таблицы ───────────────────────────────────────────

def _read_rows(path: str | Path, *, sheet: int = 0) -> list[list[Any]]:
    """XLSX/CSV → список строк (списки ячеек). Для xlsx — openpyxl, для csv — stdlib."""
    p = Path(path)
    suf = p.suffix.lower()
    if suf in {".xlsx", ".xlsm", ".xls"}:
        import openpyxl

        wb = openpyxl.load_workbook(str(p), read_only=True, data_only=True)
        ws = wb.worksheets[sheet]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
        return rows
    if suf in {".csv", ".tsv"}:
        import csv

        delim = "\t" if suf == ".tsv" else ","
        with p.open(encoding="utf-8-sig", newline="") as fh:
            return [list(r) for r in csv.reader(fh, delimiter=delim)]
    raise ValueError(f"Неподдерживаемый формат входа: {p.suffix} ({p.name})")


# ── flat-разметка (явная шапка) ──────────────────────────────────────

_FLAT_ALIASES: dict[str, tuple[str, ...]] = {
    "norm_code": ("norm_code", "код нормы", "код расценки", "шифр нормы"),
    "norm_name": ("norm_name", "наименование нормы", "наименование работ", "наименование расценки"),
    "norm_unit": ("norm_unit", "ед. нормы", "единица нормы", "ед.изм. нормы", "ед. изм. нормы"),
    "kind": ("kind", "вид ресурса", "категория", "тип ресурса"),
    "per_unit": ("per_unit", "расход", "норма расхода", "количество на единицу", "кол-во", "количество"),
    "resource_code": ("resource_code", "код ресурса", "шифр ресурса"),
    "resource_name": ("resource_name", "наименование ресурса", "наименование"),
    "resource_unit": ("resource_unit", "ед. ресурса", "единица измерения", "ед.изм.", "ед. изм.", "ед. изм. ресурса"),
    "price": ("price", "цена", "тариф", "сметная цена"),
}


def _header_index(rows: list[list[Any]]) -> tuple[int, dict[str, int]]:
    """Найти строку-шапку flat-выгрузки → (индекс_строки, {поле: позиция}). ( -1, {}) если нет."""
    for r_idx, row in enumerate(rows[:25]):
        cells = [_clean_str(c).casefold() for c in row]
        if not any(cells):
            continue
        mapping: dict[str, int] = {}
        for field, names in _FLAT_ALIASES.items():
            for pos, cell in enumerate(cells):
                if cell in names:
                    mapping.setdefault(field, pos)
                    break
        if "norm_code" in mapping and ("per_unit" in mapping or "resource_name" in mapping):
            return r_idx, mapping
    return -1, {}


def parse_flat(rows: list[list[Any]]) -> list[dict[str, Any]]:
    """flat-выгрузка (строка = ресурс, явная шапка) → нормализованные строки."""
    hdr_idx, hdr = _header_index(rows)
    if hdr_idx < 0:
        raise ValueError("flat-выгрузка: не найдена шапка (нужны столбцы norm_code + per_unit/resource_name)")
    out: list[dict[str, Any]] = []
    for row in rows[hdr_idx + 1:]:
        code = _cell(row, hdr.get("norm_code"))
        if not code:
            continue
        rec = {f: None for f in RESOURCE_FIELDS}
        rec["norm_code"] = _norm_code(code)
        rec["norm_name"] = _cell(row, hdr.get("norm_name"))
        rec["norm_unit"] = _cell(row, hdr.get("norm_unit"))
        kind = _kind_from_text(_cell(row, hdr.get("kind")))
        rec["kind"] = kind or _kind_from_text(_cell(row, hdr.get("resource_name"))) or "material"
        rec["per_unit"] = _safe_float(_cell(row, hdr.get("per_unit")))
        rec["resource_code"] = _cell(row, hdr.get("resource_code"))
        rec["resource_name"] = _cell(row, hdr.get("resource_name"))
        rec["resource_unit"] = _cell(row, hdr.get("resource_unit"))
        rec["price"] = _safe_float(_cell(row, hdr.get("price")))
        out.append(rec)
    return out


# ── blocks-разметка (норма-блоками, стиль ГРАНД/постраничный) ─────────

_UNIT_RE = re.compile(r"^\s*\d*\s*(100 |1000 |10 )?(м2|м3|пог\.?\s?м|м|т|шт|ц|км)\b", re.IGNORECASE)


def _find_unit(cells: list[str]) -> str:
    for c in cells:
        if len(c) < 20 and _UNIT_RE.match(c):
            return c.strip()
    return ""


def parse_blocks(rows: list[list[Any]]) -> list[dict[str, Any]]:
    """blocks-выгрузка: код нормы открывает блок, ниже идут строки-ресурсы.

    Эвристика 0-LLM: строка — заголовок нормы, если в ячейке код формата NN-NN-NNN-NN.
    Наименование/ед.изм. нормы — соседние текстовые ячейки. Далее строки-ресурсы: kind по
    русской метке категории (или столбцу вида), per_unit — первое число, код ресурса —
    ячейка вида ``NN.NN…``.
    """
    out: list[dict[str, Any]] = []
    cur_code = cur_name = cur_unit = ""

    for row in rows:
        cells = [_clean_str(c) for c in row]
        if not any(cells):
            continue
        # заголовок нормы? (код в формате с дефисами — это НОРМА, не ресурс)
        norm_cell = next((c for c in cells if _BARE_NORM_RE.search(c)), "")
        if norm_cell:
            m = _NORM_CODE_RE.search(norm_cell)
            cur_code = _norm_code(m.group(0)) if m else _norm_code(norm_cell)
            texts = [c for c in cells if c and c != norm_cell and _safe_float(c) is None
                     and not _RES_CODE_RE.fullmatch(c.replace(" ", ""))]
            cur_name = max(texts, key=len) if texts else ""
            cur_unit = _find_unit(cells)
            continue
        if not cur_code:
            continue
        # строка-ресурс: нужен вид или расход
        kind = next((_kind_from_text(c) for c in cells if _kind_from_text(c)), None)
        nums = [v for v in (_safe_float(c) for c in cells) if v is not None]
        if kind is None and not nums:
            continue
        per_unit = nums[0] if nums else None
        rcode = next((c for c in cells if _RES_CODE_RE.search(c) and not _looks_like_norm_code(c)), "")
        texts = [c for c in cells if c and _safe_float(c) is None and c != rcode
                 and _kind_from_text(c) != kind]
        rname = max(texts, key=len) if texts else ""
        out.append({
            "norm_code": cur_code,
            "norm_name": cur_name,
            "norm_unit": cur_unit,
            "kind": kind or "material",
            "per_unit": per_unit,
            "resource_code": rcode,
            "resource_name": rname,
            "resource_unit": "",
            "price": nums[1] if len(nums) > 1 else None,
        })
    return out


# ── сборка Parquet ───────────────────────────────────────────────────

def build_gesn_parquet(
    src: str | Path,
    out_path: str | Path = DEFAULT_OUT,
    *,
    layout: str = "auto",
    sheet: int = 0,
) -> dict[str, Any]:
    """Выгрузка (xlsx/csv) → нормализованный Parquet базы ГЭСН. Возвращает сводку."""
    import pandas as pd

    rows = _read_rows(src, sheet=sheet)
    if not rows:
        raise ValueError(f"Пустой вход: {src}")

    if layout == "auto":
        hdr_idx, _ = _header_index(rows)
        layout = "flat" if hdr_idx >= 0 else "blocks"
    if layout == "flat":
        records = parse_flat(rows)
    elif layout == "blocks":
        records = parse_blocks(rows)
    else:
        raise ValueError(f"Неизвестный layout: {layout!r} (flat|blocks|auto)")

    # отфильтровать мусор: нет расхода И нет имени → не ресурс
    records = [r for r in records if r.get("per_unit") is not None or r.get("resource_name")]
    if not records:
        raise ValueError("Не распознано ни одной строки-ресурса — проверь layout/файл")

    df = pd.DataFrame(records, columns=list(RESOURCE_FIELDS))
    norm_codes = sorted({r["norm_code"] for r in records if r["norm_code"]})

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, compression="snappy", index=False)

    return {
        "parquet": str(out_path),
        "layout": layout,
        "norms": len(norm_codes),
        "resources": len(records),
    }


def _main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Импорт базы ГЭСН-2022 (выгрузка → Parquet)")
    ap.add_argument("src", help="входной файл выгрузки (xlsx/xlsm/csv/tsv)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help=f"путь к Parquet (по умолч. {DEFAULT_OUT})")
    ap.add_argument("--layout", default="auto", choices=("auto", "flat", "blocks"),
                    help="разметка входа: flat (строка=ресурс+шапка) | blocks (норма-блоками) | auto")
    ap.add_argument("--sheet", type=int, default=0, help="индекс листа xlsx (по умолч. 0)")
    args = ap.parse_args(list(argv) if argv is not None else None)

    src = Path(args.src)
    if not src.is_file():
        print(f"Файл не найден: {src}", file=sys.stderr)
        return 2
    try:
        summary = build_gesn_parquet(src, args.out, layout=args.layout, sheet=args.sheet)
    except ValueError as e:
        print(f"Ошибка импорта: {e}", file=sys.stderr)
        return 1
    print(f"OK: {summary['norms']} норм / {summary['resources']} ресурсов → {summary['parquet']} "
          f"(layout={summary['layout']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
