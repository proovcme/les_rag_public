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


@dataclass(frozen=True)
class TableRefChunk:
    content: str
    doc_name: str
    meta: dict[str, Any]


NUMERIC_FIELDS = {
    "amount": ("стоимост", "руб", "затрат"),
    "qty": ("колич", "кол-во", "объем", "объём", "сколько", "метраж", "метр", "длин", "погон"),
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
    "сравн",
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
    "сравни",
    "сравнить",
    "сравнение",
    "строки",
    "строку",
    "строкам",
    "позиции",
    "позицию",
    "позиций",
    "таблице",
    "таблица",
    "таблицу",
    "таблицы",
    "смета",
    "смету",
    "смете",
    "сметы",
    "стоимость",
    "стоимости",
    "цена",
    "цену",
    "цены",
    "общая",
    "общую",
    "общий",
    "общее",
    "общие",
    "всего",
    "все",
    "всем",
    "всех",
    "по",
    "для",
    "про",
    "в",
    "на",
    "из",
    "и",
    "или",
    "руб",
    "рублей",
    "ведомость", "ведомости", "ведомостям", "ведомостей", "вор",
    "объём", "объем", "объёма", "объема", "объёмов", "объемов",
    "метраж", "метр", "метра", "метров", "длина", "длину", "длины",
    "количество", "количества", "штук", "штука", "число", "погонн",
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
        return _json_safe(data)


def parquet_ref_chunks_for_datasets(
    dataset_ids: Iterable[str] | None,
    *,
    storage_root: Path = Path("storage/datasets"),
    limit: int = 64,
) -> list[TableRefChunk]:
    chunks: list[TableRefChunk] = []
    if not dataset_ids:
        return chunks

    seen_paths: set[Path] = set()
    for raw_dataset_id in dataset_ids:
        dataset_id = str(raw_dataset_id).strip()
        if not dataset_id:
            continue
        dataset_root = storage_root / dataset_id
        parquet_root = dataset_root / "_parquet"
        if not parquet_root.exists():
            continue
        for parquet_path in sorted(parquet_root.rglob("*.parquet")):
            if parquet_path in seen_paths:
                continue
            seen_paths.add(parquet_path)
            try:
                parquet_rel = parquet_path.relative_to(dataset_root).as_posix()
                doc_name = parquet_path.relative_to(parquet_root).with_suffix("").as_posix()
            except ValueError:
                continue
            chunks.append(
                TableRefChunk(
                    content=doc_name,
                    doc_name=doc_name,
                    meta={
                        "dataset_id": dataset_id,
                        "parquet_path": parquet_rel,
                        "type": "table_row",
                    },
                )
            )
            if len(chunks) >= limit:
                return chunks
    return chunks


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
    if operation == "sum":
        # Полная детерминированная агрегация: суммируем по ВСЕМ parquet задействованных
        # датасетов, а не только по retrieved top-k чанкам (иначе сумма частична — кейс
        # кабель 3х1,5: 5900 вместо 15030.72). ADR-11: числа считает код, не LLM.
        ds_ids = [
            d for d in _dedupe(
                str((getattr(c, "meta", {}) or {}).get("dataset_id") or "") for c in table_chunks
            ) if d
        ]
        full_refs = parquet_ref_chunks_for_datasets(ds_ids, storage_root=storage_root)
        rows = _load_relevant_rows(
            question, full_refs or table_chunks, storage_root=storage_root, max_rows=10 ** 9
        )
    else:
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
    if "сравн" in q:
        return "compare"
    tokens = set(re.findall(r"[0-9A-Za-zА-Яа-яЁё_.-]{3,}", q))
    if any(token in q for token in ("сумм", "итого", "посчитай", "сколько всего")):
        return "sum"
    if tokens & {"общая", "общую", "общий", "общее", "общие", "всего"}:
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

    if not rows and len(keywords) > 1:
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
                text = _row_text(row)
                if not any(keyword in text for keyword in keywords):
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
    df = df.astype(object).where(pd.notnull(df), None)
    return df.to_dict(orient="records")


def _query_keywords(question: str) -> list[str]:
    tokens = re.findall(r"[0-9A-Za-zА-Яа-яЁё_.-]{3,}", question.casefold())
    out: list[str] = []
    for token in tokens:
        if token.isdigit():
            continue
        # Лёгкий стем: чисто кириллическое слово >5 → 5-симв. префикс (кабеля/кабель→кабел),
        # чтобы морфология не мешала substring-матчу. Токены с цифрами/спецсимволами
        # (3х1,5, марки) — как есть.
        stem = token[:5] if (len(token) > 5 and token.isalpha()) else token
        # Стоп-слово ловим и по полной форме, и по стему (суммарный→сумма∈STOPWORDS).
        if token in STOPWORDS or stem in STOPWORDS:
            continue
        out.append(stem)
    return out


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
                if isinstance(raw, dict):
                    for key, raw_value in raw.items():
                        parts.append(str(key))
                        parts.append(str(raw_value))
                elif isinstance(raw, list):
                    parts.extend(str(item) for item in raw)
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
    preview = "; ".join(_row_summary(row) for row in rows[:10])
    detail = f" {preview}." if preview else ""
    return f"Найдено строк: {len(rows)}.{detail}{source_text}"


def _row_summary(row: dict[str, Any]) -> str:
    label = str(row.get("pos") or row.get("position") or row.get("code") or "").strip()
    name = str(row.get("name") or row.get("work_name") or row.get("designation") or "").strip()
    if not name:
        name = _raw_row_name(row)
    qty = _format_optional_number(row.get("qty"))
    unit = str(row.get("unit") or "").strip()
    amount = _format_optional_number(row.get("amount"))
    parts = []
    if label:
        parts.append(f"#{label}")
    if name:
        parts.append(name)
    if qty:
        parts.append(f"кол-во {qty}{(' ' + unit) if unit else ''}")
    if amount:
        parts.append(f"сумма {amount}")
    if not (qty or amount):
        parts.extend(_raw_row_details(row, skip_value=name)[:3])
    return ", ".join(parts) if parts else _row_text(row)[:120]


def _raw_row_data(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("raw_row")
    if not isinstance(raw, str) or not raw.startswith("{"):
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _raw_row_name(row: dict[str, Any]) -> str:
    data = _raw_row_data(row)
    for key, value in data.items():
        key_text = str(key).casefold()
        if any(token in key_text for token in ("наименован", "объект", "работ", "материал", "оборуд")):
            text = _compact_cell(value, limit=140)
            if text:
                return text
    return ""


def _raw_row_details(row: dict[str, Any], *, skip_value: str = "") -> list[str]:
    data = _raw_row_data(row)
    details: list[str] = []
    skip_text = _compact_cell(skip_value).casefold()
    for key, value in data.items():
        key_text = _compact_cell(key, limit=56)
        value_text = _compact_cell(value, limit=92)
        if not key_text or not value_text:
            continue
        key_folded = key_text.casefold()
        if key_folded in {"table_index", "extractor"}:
            continue
        if any(token in key_folded for token in ("наименован", "объект", "работ", "материал", "оборуд")):
            continue
        if skip_text and value_text.casefold() == skip_text:
            continue
        details.append(f"{key_text}: {value_text}")
    return details


def _compact_cell(value: Any, *, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text or text.casefold() in {"nan", "none"}:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _format_optional_number(value: Any) -> str:
    number = _as_float(value)
    if number is None:
        return ""
    return _format_number(number)


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


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
