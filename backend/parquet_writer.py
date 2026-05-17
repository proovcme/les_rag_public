from __future__ import annotations
"""
Е.Ж.И.К. + С.А.М.О.В.А.Р. // parquet_writer.py
=================================================
Нормализатор табличных документов для индексации в Qdrant.

Поддерживает:
- КС-2 (Акт выполненных работ)
- АОСР (Акт освидетельствования скрытых работ)
- Спецификации оборудования (ГОСТ 21.110)
- Ведомости чертежей
- Сметы (1С / Гранд-Смета / произвольный Excel)
- Произвольные таблицы (LLM-маппинг)

Стратегия:
1. Читаем XLSX/CSV через openpyxl/pandas
2. LLM (через /api/chat или локально) анализирует заголовки → определяет тип + маппинг колонок
3. Нормализуем в единую схему → сохраняем Parquet
4. Каждая строка → отдельный чанк в Qdrant с rich payload

Зависимости:
    pip install openpyxl pandas pyarrow --break-system-packages

Запуск вручную:
    python3 parquet_writer.py /path/to/smeta.xlsx --out /tmp/parquet_out
"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("les.parquet")

# ─────────────────────────────────────────
# СТАНДАРТНАЯ СХЕМА НОРМАЛИЗОВАННОЙ СТРОКИ
# ─────────────────────────────────────────

# Все табличные документы приводим к этой схеме.
# Поля которых нет в источнике — остаются пустыми.
STANDARD_SCHEMA = {
    # Идентификация
    "doc_type":      "",   # KS2 / AOSR / SPEC / VEDOMOST / SMETA / TABLE
    "doc_title":     "",   # Название документа/листа
    "source_file":   "",   # Имя исходного файла

    # Позиция
    "pos":           "",   # Номер позиции / строки
    "section":       "",   # Раздел / глава
    "subsection":    "",   # Подраздел

    # Наименование
    "name":          "",   # Наименование работы / оборудования
    "code":          "",   # Шифр, артикул, обозначение
    "mark":          "",   # Марка, тип

    # Количество
    "unit":          "",   # Единица измерения
    "qty":           None, # Количество (float)
    "qty_per_unit":  None, # Расход на единицу

    # Стоимость
    "price":         None, # Цена единицы
    "amount":        None, # Сумма
    "amount_mat":    None, # Материалы
    "amount_work":   None, # Работы

    # Для КС-2
    "work_volume":   None, # Объём работ по договору
    "work_done":     None, # Выполнено в отчётном периоде
    "work_since_start": None, # Выполнено с начала строительства

    # Для АОСР
    "work_name":     "",   # Наименование скрытых работ
    "norms_refs":    "",   # Ссылки на нормативы
    "materials_used":"",   # Применённые материалы
    "date_start":    "",   # Начало работ
    "date_end":      "",   # Конец работ

    # Для спецификаций
    "position":      "",   # Позиция по спецификации
    "designation":   "",   # Обозначение (ГОСТ/ТУ)
    "weight_unit":   None, # Масса единицы
    "weight_total":  None, # Масса общая

    # Примечания
    "note":          "",
    "raw_row":       "",   # Оригинальная строка как JSON (резерв)
}

# ─────────────────────────────────────────
# ТИПЫ ДОКУМЕНТОВ
# ─────────────────────────────────────────

DOC_TYPES = {
    "KS2":      "Акт о приёмке выполненных работ (КС-2)",
    "AOSR":     "Акт освидетельствования скрытых работ (АОСР)",
    "SPEC":     "Спецификация оборудования (ГОСТ 21.110)",
    "VEDOMOST": "Ведомость чертежей / ссылочных документов",
    "SMETA":    "Смета / Локальный сметный расчёт",
    "TABLE":    "Произвольная таблица",
}

# Ключевые слова для автодетекта типа по заголовкам
DOC_TYPE_HINTS = {
    "KS2":      ["выполненных работ", "кс-2", "кс2", "акт приёмки", "период"],
    "AOSR":     ["скрытых работ", "аоср", "освидетельствования", "скрытые работы"],
    "SPEC":     ["спецификация", "обозначение", "масса", "поз.", "позиция", "гост 21.110"],
    "VEDOMOST": ["ведомость", "чертежей", "ссылочных документов", "лист", "формат"],
    "SMETA":    ["смета", "расценка", "норма", "гэсн", "фер", "тер", "гранд"],
}


# ─────────────────────────────────────────
# LLM-МАППИНГ КОЛОНОК
# ─────────────────────────────────────────

COLUMN_MAPPING_PROMPT = """Ты — эксперт по строительной документации России.
Тебе дан список заголовков колонок из Excel-файла.
Определи:
1. Тип документа (KS2 / AOSR / SPEC / VEDOMOST / SMETA / TABLE)
2. Маппинг каждого заголовка на стандартное поле схемы

Стандартные поля: pos, section, subsection, name, code, mark, unit, qty, qty_per_unit, 
price, amount, amount_mat, amount_work, work_volume, work_done, work_since_start,
work_name, norms_refs, materials_used, date_start, date_end, 
position, designation, weight_unit, weight_total, note

Если колонка не подходит ни к одному полю — используй "skip".

Заголовки: {headers}

Первые 3 строки данных для контекста:
{sample_rows}

Отвечай ТОЛЬКО JSON без пояснений:
{{
  "doc_type": "KS2",
  "mapping": {{
    "Наименование работ": "name",
    "Ед.изм.": "unit",
    "Кол-во": "qty",
    "Цена": "price",
    "Сумма": "amount",
    "Примечание": "note"
  }}
}}"""


def _detect_doc_type_simple(headers: list, sheet_name: str = "") -> str:
    """Быстрый детект типа по ключевым словам без LLM."""
    text = " ".join(headers + [sheet_name]).lower()
    scores = {dt: 0 for dt in DOC_TYPES}
    for dt, hints in DOC_TYPE_HINTS.items():
        for hint in hints:
            if hint in text:
                scores[dt] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "TABLE"


async def _llm_map_columns(
    headers: list,
    sample_rows: list,
    llm_url: str = "http://localhost:8050/api/chat"
) -> dict:
    """
    Запрашивает LLM для маппинга колонок.
    Возвращает {"doc_type": str, "mapping": {header: field}}
    """
    try:
        import httpx

        sample_str = "\n".join(
            json.dumps(row, ensure_ascii=False) for row in sample_rows[:3]
        )
        prompt = COLUMN_MAPPING_PROMPT.format(
            headers=json.dumps(headers, ensure_ascii=False),
            sample_rows=sample_str,
        )

        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(llm_url, json={"question": prompt})
            r.raise_for_status()
            data = r.json()
            answer = data.get("answer", data.get("response", ""))

        # Извлекаем JSON из ответа
        m = re.search(r"\{.*\}", answer, re.DOTALL)
        if m:
            result = json.loads(m.group(0))
            return result
    except Exception as e:
        logger.warning(f"[PARQUET] LLM маппинг недоступен: {e}, используем простой детект")

    # Fallback: простой детект + пустой маппинг
    doc_type = _detect_doc_type_simple(headers)
    return {"doc_type": doc_type, "mapping": {h: "skip" for h in headers}}


# ─────────────────────────────────────────
# ЧИТАЛКА XLSX
# ─────────────────────────────────────────

def _find_header_row(ws, max_scan: int = 20) -> int:
    """
    Ищем строку с заголовками — обычно это первая непустая строка
    с несколькими заполненными ячейками.
    Гранд-Смета и 1С часто имеют шапку на 3-5 строках выше данных.
    """
    best_row = 0
    best_score = 0
    for row_idx in range(1, min(max_scan, ws.max_row) + 1):
        row = [ws.cell(row_idx, c).value for c in range(1, ws.max_column + 1)]
        non_empty = sum(1 for v in row if v is not None and str(v).strip())
        text_cells = sum(1 for v in row if v is not None and isinstance(v, str) and len(str(v).strip()) > 1)
        score = text_cells * 2 + non_empty
        if score > best_score:
            best_score = score
            best_row = row_idx
    return best_row


def read_xlsx_sheets(file_path: str) -> list:
    """
    Читает XLSX и возвращает list[dict] — один элемент на лист:
    {"sheet_name": str, "headers": list, "rows": list[dict], "raw_headers_row": int}
    """
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError("openpyxl не установлен: pip install openpyxl --break-system-packages")

    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    sheets = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        if ws.max_row is None or ws.max_row < 2:
            continue

        header_row_idx = _find_header_row(ws)
        if header_row_idx == 0:
            continue

        # Заголовки
        headers = []
        for c in range(1, ws.max_column + 1):
            v = ws.cell(header_row_idx, c).value
            headers.append(str(v).strip() if v is not None else f"col_{c}")

        # Строки данных
        rows = []
        for row_idx in range(header_row_idx + 1, ws.max_row + 1):
            row_vals = [ws.cell(row_idx, c).value for c in range(1, ws.max_column + 1)]
            # Пропускаем полностью пустые строки
            if all(v is None or str(v).strip() == "" for v in row_vals):
                continue
            row_dict = {}
            for i, h in enumerate(headers):
                v = row_vals[i] if i < len(row_vals) else None
                row_dict[h] = v
            rows.append(row_dict)

        if rows:
            sheets.append({
                "sheet_name": sheet_name,
                "headers": headers,
                "rows": rows,
                "header_row": header_row_idx,
            })

    wb.close()
    return sheets


def read_csv(file_path: str) -> list:
    """Читаем CSV, возвращаем в том же формате что и read_xlsx_sheets."""
    try:
        import csv
        rows = []
        with open(file_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            for row in reader:
                rows.append(dict(row))
        if rows:
            return [{"sheet_name": "CSV", "headers": list(headers), "rows": rows, "header_row": 1}]
    except UnicodeDecodeError:
        # Пробуем cp1251
        try:
            import csv
            rows = []
            with open(file_path, encoding="cp1251", newline="") as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames or []
                for row in reader:
                    rows.append(dict(row))
            if rows:
                return [{"sheet_name": "CSV", "headers": list(headers), "rows": rows, "header_row": 1}]
        except Exception as e:
            logger.error(f"[PARQUET] CSV read error: {e}")
    return []


# ─────────────────────────────────────────
# НОРМАЛИЗАТОР СТРОК
# ─────────────────────────────────────────

def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        s = str(v).replace(",", ".").replace(" ", "").replace("\xa0", "")
        return float(s)
    except Exception:
        return None


def normalize_row(raw_row: dict, mapping: dict, doc_type: str, doc_title: str, source_file: str) -> dict:
    """Нормализует одну строку Excel в стандартную схему."""
    norm = dict(STANDARD_SCHEMA)
    norm["doc_type"] = doc_type
    norm["doc_title"] = doc_title
    norm["source_file"] = source_file
    norm["raw_row"] = json.dumps(raw_row, ensure_ascii=False, default=str)

    for orig_col, std_field in mapping.items():
        if std_field == "skip" or std_field not in norm:
            continue
        val = raw_row.get(orig_col)
        if val is None:
            continue

        # Числовые поля
        if std_field in ("qty", "qty_per_unit", "price", "amount", "amount_mat",
                         "amount_work", "work_volume", "work_done", "work_since_start",
                         "weight_unit", "weight_total"):
            norm[std_field] = _safe_float(val)
        else:
            norm[std_field] = str(val).strip() if val is not None else ""

    return norm


# ─────────────────────────────────────────
# КОНВЕРТЕР В ЧАНКИ ДЛЯ QDRANT
# ─────────────────────────────────────────

def row_to_chunk_text(row: dict) -> str:
    """
    Формирует текст чанка из нормализованной строки.
    Текст должен быть богатым — эмбеддинг по нему строится.
    """
    parts = []

    if row.get("doc_type") and row.get("doc_title"):
        parts.append(f"Документ: {DOC_TYPES.get(row['doc_type'], row['doc_type'])} — {row['doc_title']}")

    if row.get("section"):
        parts.append(f"Раздел: {row['section']}")

    if row.get("name") or row.get("work_name"):
        parts.append(f"Наименование: {row.get('name') or row.get('work_name')}")

    if row.get("code") or row.get("designation"):
        parts.append(f"Обозначение/Артикул: {row.get('code') or row.get('designation')}")

    if row.get("mark"):
        parts.append(f"Марка/Тип: {row['mark']}")

    if row.get("unit") and row.get("qty") is not None:
        parts.append(f"Количество: {row['qty']} {row['unit']}")

    if row.get("price") is not None:
        parts.append(f"Цена: {row['price']:.2f}")

    if row.get("amount") is not None:
        parts.append(f"Сумма: {row['amount']:.2f}")

    if row.get("work_done") is not None:
        parts.append(f"Выполнено: {row['work_done']}")

    if row.get("norms_refs"):
        parts.append(f"Нормативы: {row['norms_refs']}")

    if row.get("materials_used"):
        parts.append(f"Материалы: {row['materials_used']}")

    if row.get("note"):
        parts.append(f"Примечание: {row['note']}")

    return "\n".join(parts) if parts else json.dumps(row, ensure_ascii=False)


def rows_to_qdrant_chunks(rows: list, dataset_id: str = "") -> list:
    """
    Конвертирует нормализованные строки в чанки для Qdrant.
    Возвращает list[dict] с полями "text" и "metadata".
    """
    chunks = []
    for row in rows:
        text = row_to_chunk_text(row)
        if not text.strip():
            continue

        # Payload для фильтрации в Qdrant
        metadata = {
            "type": "table_row",
            "doc_type": row.get("doc_type", ""),
            "doc_title": row.get("doc_title", ""),
            "source_file": row.get("source_file", ""),
            "section": row.get("section", ""),
            "name": row.get("name", "") or row.get("work_name", ""),
            "code": row.get("code", "") or row.get("designation", ""),
            "unit": row.get("unit", ""),
            "qty": row.get("qty"),
            "amount": row.get("amount"),
            "dataset_id": dataset_id,
        }

        chunks.append({
            "text": text,
            "metadata": metadata,
            "raw": row,  # полная нормализованная строка
        })
    return chunks


# ─────────────────────────────────────────
# СОХРАНЕНИЕ В PARQUET
# ─────────────────────────────────────────

def save_parquet(rows: list, output_path: str) -> int:
    """
    Сохраняет нормализованные строки в Parquet.
    Возвращает количество записей.
    """
    try:
        import pandas as pd
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        raise RuntimeError(
            "Установи: pip install pandas pyarrow --break-system-packages"
        )

    if not rows:
        logger.warning("[PARQUET] Нет строк для сохранения")
        return 0

    df = pd.DataFrame(rows)

    # Приводим числовые колонки
    numeric_cols = ["qty", "qty_per_unit", "price", "amount", "amount_mat",
                    "amount_work", "work_volume", "work_done", "work_since_start",
                    "weight_unit", "weight_total"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    table = pa.Table.from_pandas(df)
    pq.write_table(table, output_path, compression="snappy")
    logger.info(f"[PARQUET] Сохранено {len(rows)} строк → {output_path}")
    return len(rows)


def load_parquet(parquet_path: str) -> list:
    """Загружает Parquet → list[dict]."""
    try:
        import pyarrow.parquet as pq
        table = pq.read_table(parquet_path)
        return table.to_pydict()
    except Exception as e:
        logger.error(f"[PARQUET] Ошибка чтения {parquet_path}: {e}")
        return []


# ─────────────────────────────────────────
# ГЛАВНЫЙ ПАЙПЛАЙН
# ─────────────────────────────────────────

class TableNormalizer:
    """
    Полный пайплайн: XLSX/CSV → нормализация → Parquet + Qdrant чанки.

    Пример:
        norm = TableNormalizer(llm_url="http://localhost:8050/api/chat")
        result = await norm.process("smeta.xlsx", dataset_id="uuid-xxx")
        # result: {"chunks": [...], "parquet_path": "...", "rows": N, "doc_type": "SMETA"}
    """

    def __init__(
        self,
        llm_url: str = "http://localhost:8050/api/chat",
        parquet_dir: str = "/tmp/ejik_parquet",
        use_llm: bool = True,
    ):
        self.llm_url = llm_url
        self.parquet_dir = Path(parquet_dir)
        self.parquet_dir.mkdir(parents=True, exist_ok=True)
        self.use_llm = use_llm

    async def process(self, file_path: str, dataset_id: str = "") -> dict:
        """
        Обрабатывает один файл XLSX/CSV.
        Возвращает {"chunks": list, "parquet_path": str, "rows": int, "doc_type": str, "sheets": int}
        """
        fpath = Path(file_path)
        ext = fpath.suffix.lower()

        if ext in (".xlsx", ".xls"):
            sheets = read_xlsx_sheets(str(fpath))
        elif ext == ".csv":
            sheets = read_csv(str(fpath))
        else:
            raise ValueError(f"Неподдерживаемый формат: {ext}")

        if not sheets:
            logger.warning(f"[PARQUET] Нет данных в {fpath.name}")
            return {"chunks": [], "parquet_path": "", "rows": 0, "doc_type": "TABLE", "sheets": 0}

        all_normalized = []
        all_chunks = []
        doc_type_final = "TABLE"

        for sheet in sheets:
            headers = sheet["headers"]
            rows = sheet["rows"]
            sheet_name = sheet["sheet_name"]

            if not rows:
                continue

            # Маппинг колонок
            if self.use_llm:
                mapping_result = await _llm_map_columns(headers, rows[:3], self.llm_url)
            else:
                # Простой детект без LLM
                doc_type = _detect_doc_type_simple(headers, sheet_name)
                mapping_result = {
                    "doc_type": doc_type,
                    "mapping": {h: "skip" for h in headers},
                }

            doc_type = mapping_result.get("doc_type", "TABLE")
            mapping = mapping_result.get("mapping", {})
            doc_type_final = doc_type

            logger.info(f"[PARQUET] {fpath.name} / {sheet_name}: тип={doc_type}, строк={len(rows)}")

            # Нормализация строк
            for raw_row in rows:
                norm = normalize_row(
                    raw_row=raw_row,
                    mapping=mapping,
                    doc_type=doc_type,
                    doc_title=f"{fpath.stem} / {sheet_name}",
                    source_file=fpath.name,
                )
                all_normalized.append(norm)

        # Чанки для Qdrant
        all_chunks = rows_to_qdrant_chunks(all_normalized, dataset_id=dataset_id)

        # Сохраняем Parquet
        parquet_path = ""
        if all_normalized:
            parquet_name = f"{fpath.stem}.parquet"
            parquet_path = str(self.parquet_dir / parquet_name)
            save_parquet(all_normalized, parquet_path)

        return {
            "chunks": all_chunks,
            "parquet_path": parquet_path,
            "rows": len(all_normalized),
            "doc_type": doc_type_final,
            "sheets": len(sheets),
        }


# ─────────────────────────────────────────
# CLI: тест вручную
# ─────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    import asyncio

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Е.Ж.И.К. Parquet Normalizer")
    parser.add_argument("file", help="XLSX или CSV файл")
    parser.add_argument("--out", default="/tmp/parquet_out", help="Папка для Parquet")
    parser.add_argument("--no-llm", action="store_true", help="Без LLM маппинга")
    parser.add_argument("--llm", default="http://localhost:8050/api/chat", help="URL LLM")
    args = parser.parse_args()

    norm = TableNormalizer(
        llm_url=args.llm,
        parquet_dir=args.out,
        use_llm=not args.no_llm,
    )

    result = asyncio.run(norm.process(args.file))
    print(f"\n[ИТОГ]")
    print(f"  Тип документа: {result['doc_type']} ({DOC_TYPES.get(result['doc_type'], '?')})")
    print(f"  Листов:        {result['sheets']}")
    print(f"  Строк:         {result['rows']}")
    print(f"  Чанков:        {len(result['chunks'])}")
    print(f"  Parquet:       {result['parquet_path']}")

    if result["chunks"]:
        print(f"\n[ПЕРВЫЙ ЧАНК]")
        print(result["chunks"][0]["text"])
