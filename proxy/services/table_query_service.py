"""Parquet-backed table queries for retrieved table chunks."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol


class RetrievedChunk(Protocol):
    content: str
    doc_name: str
    meta: dict[str, Any]


NUMERIC_FIELDS = {
    "amount": ("сумм", "стоимост", "итого", "руб"),
    "qty": ("колич", "кол-во", "объем", "объём", "сколько"),
    "price": ("цен", "расцен"),
    "amount_mat": ("материал",),
    "amount_work": ("работ", "зп", "труд"),
    "work_done": ("выполнено",),
    "weight_total": ("масса", "вес"),
}

TABLE_QUERY_TOKENS = (
    "сумм",
    "итого",
    "посчитай",
    "сколько",
    "колич",
    "кол-во",
    "объем",
    "объём",
    "стоимост",
    "цена",
    "расцен",
    "позици",
    "строк",
    "таблиц",
)

STOPWORDS = {
    "сумма",
    "сумму",
    "суммарно",
    "итого",
    "посчитай",
    "сколько",
    "какая",
    "какой",
    "какие",
    "найди",
    "покажи",
    "строки",
    "строку",
    "позиции",
    "позицию",
    "таблице",
    "таблица",
    "по",
    "для",
    "в",
    "на",
    "из",
    "и",
    "или",
    "руб",
    "рублей",
}


@dataclass(frozen=True)
class TableQueryResult:
    matched: bool
    operation: str
    field: str
    answer: str
    rows: list[dict[str, Any]]
    sources: list[str]
    parquet_paths: list[str]
    total: Optional[float] = None
    count: int = 0

    def payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["total"] = self.total
        return data


def maybe_answer_table_query(
    question: str,
    chunks: Iterable[RetrievedChunk],
    *,
    storage_root: Path = Path("storage/datasets"),
    max_rows: int = 20,
) -> Optional[TableQueryResult]:
    if not _looks_like_table_query(question):
        return None

    table_chunks = [chunk for chunk in chunks if _chunk_parquet_ref(chunk)]
    if not table_chunks:
        return None

    field = _select_numeric_field(question)
    operation = _select_operation(question)
    rows = _load_relevant_rows(question, table_chunks, storage_root=storage_root, max_rows=max_rows)
    if not rows:
        return None

    sources = _dedupe(str(row.get("source_file") or row.get("_doc_name") or "") for row in rows)
    parquet_paths = _dedupe(str(row.get("_parquet_path") or "") for row in rows)

    if operation == "sum":
        values = [_as_float(row.get(field)) for row in rows]
        numbers = [value for value in values if value is not None]
        if not numbers:
            return None
        total = sum(numbers)
        answer = _sum_answer(field, total, len(numbers), sources)
        return TableQueryResult(
            matched=True,
            operation=operation,
            field=field,
            answer=answer,
            rows=rows[:max_rows],
            sources=sources,
            parquet_paths=parquet_paths,
            total=total,
            count=len(numbers),
        )

    answer = _list_answer(rows, sources)
    return TableQueryResult(
        matched=True,
        operation=operation,
        field=field,
        answer=answer,
        rows=rows[:max_rows],
        sources=sources,
        parquet_paths=parquet_paths,
        count=len(rows),
    )


def _looks_like_table_query(question: str) -> bool:
    q = question.casefold()
    return any(token in q for token in TABLE_QUERY_TOKENS)


def _select_numeric_field(question: str) -> str:
    q = question.casefold()
    scores = {
        field: sum(1 for token in tokens if token in q)
        for field, tokens in NUMERIC_FIELDS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "amount"


def _select_operation(question: str) -> str:
    q = question.casefold()
    if any(token in q for token in ("сумм", "итого", "посчитай", "сколько всего", "общ")):
        return "sum"
    return "list"


def _chunk_parquet_ref(chunk: RetrievedChunk) -> Optional[tuple[str, str]]:
    meta = getattr(chunk, "meta", {}) or {}
    parquet_path = meta.get("parquet_path")
    dataset_id = meta.get("dataset_id")
    if parquet_path and dataset_id:
        return str(dataset_id), str(parquet_path)
    return None


def _load_relevant_rows(
    question: str,
    chunks: list[RetrievedChunk],
    *,
    storage_root: Path,
    max_rows: int,
) -> list[dict[str, Any]]:
    keywords = _query_keywords(question)
    rows: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, int]] = set()

    for chunk in chunks:
        ref = _chunk_parquet_ref(chunk)
        if not ref:
            continue
        dataset_id, parquet_rel = ref
        parquet_path = _resolve_parquet_path(storage_root, dataset_id, parquet_rel)
        if parquet_path is None:
            continue
        table_rows = _read_parquet_rows(parquet_path)
        for index, row in enumerate(table_rows):
            if keywords and not _row_matches(row, keywords):
                continue
            key = (parquet_path.as_posix(), index)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            enriched = dict(row)
            enriched["_parquet_path"] = parquet_rel
            enriched["_doc_name"] = getattr(chunk, "doc_name", "")
            rows.append(enriched)
            if len(rows) >= max_rows:
                return rows

    if rows or keywords:
        return rows

    # No useful keyword was present, so use the retrieved row order as focus.
    for chunk in chunks:
        meta = getattr(chunk, "meta", {}) or {}
        row = _row_from_chunk_meta(chunk)
        if not row:
            continue
        row["_parquet_path"] = meta.get("parquet_path", "")
        row["_doc_name"] = getattr(chunk, "doc_name", "")
        rows.append(row)
        if len(rows) >= max_rows:
            break
    return rows


def _resolve_parquet_path(storage_root: Path, dataset_id: str, parquet_rel: str) -> Optional[Path]:
    candidate = Path(parquet_rel)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    root = (storage_root / dataset_id).resolve()
    path = (root / candidate).resolve()
    if root != path and root not in path.parents:
        return None
    if not path.exists() or not path.is_file():
        return None
    return path


def _read_parquet_rows(path: Path) -> list[dict[str, Any]]:
    import pandas as pd

    df = pd.read_parquet(path)
    df = df.where(pd.notnull(df), None)
    return df.to_dict(orient="records")


def _query_keywords(question: str) -> list[str]:
    tokens = re.findall(r"[0-9A-Za-zА-Яа-яЁё_.-]{3,}", question.casefold())
    return [token for token in tokens if token not in STOPWORDS and not token.isdigit()]


def _row_matches(row: dict[str, Any], keywords: list[str]) -> bool:
    text = _row_text(row)
    return all(keyword in text for keyword in keywords)


def _row_text(row: dict[str, Any]) -> str:
    parts = []
    for value in row.values():
        if value is None or isinstance(value, (int, float)):
            continue
        if isinstance(value, str) and value.startswith("{"):
            try:
                raw = json.loads(value)
                parts.extend(str(v) for v in raw.values())
                continue
            except Exception:
                pass
        parts.append(str(value))
    return " ".join(parts).casefold()


def _row_from_chunk_meta(chunk: RetrievedChunk) -> dict[str, Any]:
    meta = getattr(chunk, "meta", {}) or {}
    row = {
        "doc_type": meta.get("doc_type", ""),
        "source_file": meta.get("source_file") or getattr(chunk, "doc_name", ""),
        "name": meta.get("name", ""),
        "code": meta.get("code", ""),
        "unit": meta.get("unit", ""),
        "qty": meta.get("qty"),
        "amount": meta.get("amount"),
    }
    return {key: value for key, value in row.items() if value not in (None, "")}


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sum_answer(field: str, total: float, count: int, sources: list[str]) -> str:
    label = {
        "amount": "Сумма",
        "qty": "Количество",
        "price": "Цена",
        "amount_mat": "Материалы",
        "amount_work": "Работы",
        "work_done": "Выполнено",
        "weight_total": "Масса",
    }.get(field, field)
    source_text = f" Источник: {', '.join(sources)}." if sources else ""
    return f"{label} по найденным строкам: {_format_number(total)}. Строк учтено: {count}.{source_text}"


def _list_answer(rows: list[dict[str, Any]], sources: list[str]) -> str:
    source_text = f" Источник: {', '.join(sources)}." if sources else ""
    return f"Найдено строк: {len(rows)}.{source_text}"


def _format_number(value: float) -> str:
    if abs(value - round(value)) < 0.000001:
        return f"{round(value):,}".replace(",", " ")
    return f"{value:,.2f}".replace(",", " ")


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
