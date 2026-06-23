"""Группируемая агрегация по табличным датасетам (Ц6): sum/count/avg по полю + фильтр + group-by.

Закрывает «table_query top-k не SQL»: вместо substring-скана только retrieved-чанков — агрегация по
ПОЛНОМУ parquet датасета(ов) с группировкой («сумма по разделам», «по типу документа», …).
Числа считает код (ADR-11). Поля и группировка — ТОЛЬКО из белого списка схемы (без инъекций).

Бэкенд — pandas (есть в рантайме). DuckDB (настоящий SQL + джойны + скорость) — drop-in на тот же
интерфейс, когда установится (сейчас блокирован сетью). Схема — `backend.parquet_writer.STANDARD_SCHEMA`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

# По чему можно агрегировать / группировать (из STANDARD_SCHEMA).
_NUMERIC = {"qty", "price", "amount", "amount_mat", "amount_work", "weight_total",
            "work_done", "work_volume", "work_since_start"}
_GROUPABLE = {"section", "subsection", "doc_type", "doc_title", "unit", "name", "code",
              "mark", "source_file"}
_OPS = {"sum", "count", "avg", "min", "max"}

# Эвристика «какой ключ raw_row соответствует типизированному полю» (фолбэк, когда
# типизированная колонка пуста/null — числа осели в raw_row при индексации). Подход —
# как в table_query_service: substring по нормализованному имени ключа, без LLM (ADR-11).
def _norm_key(key: Any) -> str:
    """Имя ключа raw_row → сравнимая форма: схлопнуть пробелы и PDF-переносы «коли- чество»→«количество»."""
    text = re.sub(r"\s+", " ", str(key)).strip().casefold()
    return text.replace("- ", "")  # перенос по дефису из PDF-шапок


_RAW_KEY_HINTS: dict[str, tuple[str, ...]] = {
    "qty": ("кол-во", "колич", "объем", "объём"),
    "price": ("расцен", "цена", "цен"),
    "amount": ("сумм", "стоимост", "итого", "руб"),
    "amount_mat": ("материал",),
    "amount_work": ("работ", "труд", "зп"),
    "weight_total": ("масса", "вес"),
    "work_done": ("выполнено",),
    "work_volume": ("объем работ", "объём работ"),
    "work_since_start": ("с начала",),
}
# Группировочные поля → ключи raw_row (фолбэк для group_by, если типизированная колонка пуста).
_RAW_GROUP_HINTS: dict[str, tuple[str, ...]] = {
    "section": ("раздел", "глава", "этап"),
    "subsection": ("подраздел", "подэтап"),
    "unit": ("ед.изм", "ед. изм", "единица", "ед-ца"),
    "name": ("наименован",),
    "code": ("код", "шифр"),
    "mark": ("марка", "обозначен"),
}


def _raw_row_dict(raw: Any) -> dict[str, Any]:
    """raw_row (JSON-строка оригинальной строки) → dict, иначе {} (как table_query._raw_row_data)."""
    if not isinstance(raw, str) or not raw.startswith("{"):
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _as_float(value: Any) -> Optional[float]:
    """Число из произвольной ячейки raw_row («1 019,39», «134559.22», «137,39 м2»). NaN/мусор → None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return None if f != f else f  # отсев NaN
    text = re.sub(r"\s+", "", str(value))
    if not text:
        return None
    m = re.search(r"-?\d[\d.,]*", text)  # первое число в ячейке
    if not m:
        return None
    num = m.group(0).rstrip(".,")
    if "," in num and "." in num:
        # и точка, и запятая: правый разделитель — десятичный, левый — тысячный.
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    elif "," in num:
        num = num.replace(",", ".")
    try:
        return float(num)
    except ValueError:
        return None


def _raw_value_for_field(raw: dict[str, Any], field: str) -> Optional[float]:
    """Найти число в raw_row по эвристике ключа для числового field. None если не нашли."""
    hints = _RAW_KEY_HINTS.get(field)
    if not hints:
        return None
    for key, value in raw.items():
        key_text = _norm_key(key)
        if any(h in key_text for h in hints):
            num = _as_float(value)
            if num is not None:
                return num
    return None


def _raw_value_for_group(raw: dict[str, Any], group_by: str) -> Optional[str]:
    """Найти значение для group_by по эвристике ключа. None если не нашли."""
    hints = _RAW_GROUP_HINTS.get(group_by)
    if not hints:
        return None
    for key, value in raw.items():
        key_text = _norm_key(key)
        if any(h in key_text for h in hints):
            text = re.sub(r"\s+", " ", str(value or "")).strip()
            if text and text.casefold() not in {"nan", "none"}:
                return text
    return None


def _parquet_paths(dataset_ids: list[str], storage_root: str | Path) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for ds in dataset_ids or []:
        root = Path(storage_root) / str(ds).strip() / "_parquet"
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.parquet")):
            sp = str(p)
            if sp not in seen:
                seen.add(sp)
                paths.append(sp)
    return paths


def aggregate(
    dataset_ids: list[str],
    *,
    field: str = "amount",
    op: str = "sum",
    contains: Optional[str] = None,
    group_by: Optional[str] = None,
    storage_root: str | Path = "storage/datasets",
    limit: int = 100,
) -> dict[str, Any]:
    """Агрегация по полному parquet датасетов. group_by → разбивка; contains → фильтр по name/code."""
    if op not in _OPS:
        raise ValueError(f"op ∈ {sorted(_OPS)}")
    if op != "count" and field not in _NUMERIC:
        raise ValueError(f"field ∈ {sorted(_NUMERIC)}")
    if group_by and group_by not in _GROUPABLE:
        raise ValueError(f"group_by ∈ {sorted(_GROUPABLE)}")

    paths = _parquet_paths(dataset_ids, storage_root)
    if not paths:
        return {"rows": [], "total": None, "note": "нет parquet у датасетов", "field": field, "op": op}

    import pandas as pd

    df = pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)

    # Фолбэк на raw_row: типизированные qty/amount/section часто null на реальных датасетах —
    # число/значение осело в оригинальной строке (raw_row) с произвольным русским ключом.
    # Достаём по эвристике ключа (без LLM, ADR-11), только если типизированная ячейка пуста.
    if "raw_row" in df.columns:
        need_field = (op != "count") and (field in _RAW_KEY_HINTS)
        need_group = bool(group_by) and (group_by in _RAW_GROUP_HINTS)
        if need_field or need_group:
            raw_dicts = df["raw_row"].map(_raw_row_dict)
            if need_field:
                typed = pd.to_numeric(df[field], errors="coerce") if field in df.columns else pd.Series(
                    [None] * len(df), index=df.index, dtype="float64")
                fallback = raw_dicts.map(lambda r, f=field: _raw_value_for_field(r, f))
                # пусто/null/0 в типизированной колонке → берём из raw_row.
                df[field] = [
                    t if (t is not None and t == t and t != 0.0) else fb
                    for t, fb in zip(typed.tolist(), fallback.tolist())
                ]
            if need_group:
                if group_by in df.columns:
                    typed_g = df[group_by]
                    fallback_g = raw_dicts.map(lambda r, g=group_by: _raw_value_for_group(r, g))
                    df[group_by] = [
                        gv if (gv is not None and str(gv).strip() != "") else fb
                        for gv, fb in zip(typed_g.tolist(), fallback_g.tolist())
                    ]
                else:
                    df[group_by] = raw_dicts.map(lambda r, g=group_by: _raw_value_for_group(r, g)).tolist()

    matched = len(df)
    if contains:
        c = str(contains)
        mask = df["name"].astype(str).str.contains(c, case=False, na=False) if "name" in df else False
        if "code" in df:
            mask = mask | df["code"].astype(str).str.contains(c, case=False, na=False)
        df = df[mask]
        matched = len(df)

    if op == "count":
        if not group_by:
            return {"rows": [], "total": int(matched), "field": "count", "op": op, "matched": matched}
        g = df.groupby(group_by, dropna=False).size().reset_index(name="value")
    else:
        df = df.copy()
        df[field] = pd.to_numeric(df[field], errors="coerce")
        if not group_by:
            series = df[field].dropna()
            total = float(getattr(series, op)()) if len(series) else 0.0
            return {"rows": [], "total": round(total, 2), "field": field, "op": op,
                    "count": int(len(series)), "matched": matched}
        g = df.groupby(group_by, dropna=False)[field].agg(op).reset_index().rename(columns={field: "value"})

    g = g.sort_values("value", ascending=False).head(limit)
    rows = [{"group": ("" if r[group_by] is None else str(r[group_by])),
             "value": round(float(r["value"]), 2)} for _, r in g.iterrows()]
    return {"rows": rows, "total": round(float(sum(x["value"] for x in rows)), 2),
            "group_by": group_by, "field": field, "op": op, "matched": matched}
