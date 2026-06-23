"""Группируемая агрегация по табличным датасетам (Ц6): sum/count/avg по полю + фильтр + group-by.

Закрывает «table_query top-k не SQL»: вместо substring-скана только retrieved-чанков — агрегация по
ПОЛНОМУ parquet датасета(ов) с группировкой («сумма по разделам», «по типу документа», …).
Числа считает код (ADR-11). Поля и группировка — ТОЛЬКО из белого списка схемы (без инъекций).

Бэкенд — pandas (есть в рантайме). DuckDB (настоящий SQL + джойны + скорость) — drop-in на тот же
интерфейс, когда установится (сейчас блокирован сетью). Схема — `backend.parquet_writer.STANDARD_SCHEMA`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

# По чему можно агрегировать / группировать (из STANDARD_SCHEMA).
_NUMERIC = {"qty", "price", "amount", "amount_mat", "amount_work", "weight_total",
            "work_done", "work_volume", "work_since_start"}
_GROUPABLE = {"section", "subsection", "doc_type", "doc_title", "unit", "name", "code",
              "mark", "source_file"}
_OPS = {"sum", "count", "avg", "min", "max"}


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
