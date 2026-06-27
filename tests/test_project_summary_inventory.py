"""Фикс №1: «Сводка проекта» строит реестр из ОПИСИ MetaDB, а не только из Parquet-таблиц.

Симптом: датасет без табличных документов (BAI — PDF/docx-тома ИОС) давал document_count=0 →
project_summary пуст → проваливался в RAG → NO_DATA. Котельная (с .xlsx → Parquet-таблицы) работала.
Теперь inventory_from_metadb перечисляет ВСЕ файлы датасета из documents → реестр есть всегда.
"""

import sqlite3
from pathlib import Path

from proxy.services.project_summary_service import (
    build_project_summary,
    format_project_summary,
    inventory_from_metadb,
)


def _mk_meta(tmp_path: Path, rows: list[tuple[str, str, str]]) -> str:
    db = tmp_path / "meta.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, dataset_id TEXT, file_name TEXT, status TEXT)")
    con.executemany("INSERT INTO documents (dataset_id, file_name, status) VALUES (?,?,?)", rows)
    con.commit(); con.close()
    return str(db)


def test_inventory_lists_all_files_grouped(tmp_path):
    db = _mk_meta(tmp_path, [
        ("bai", "BAI/OUT/ИОС 5.1/03_Пояснительная записка.docx", "PENDING"),
        ("bai", "BAI/OUT/ИОС 5.1/СО1Б-ИОС5.1.pdf", "PENDING"),
        ("bai", "BAI/OUT/ИОС 5.2/02_Состав проекта.docx", "INDEXED"),
        ("bai", "BAI/.pdf_preprocess_state.json", "INDEXED"),   # артефакт — должен отсеяться
        ("other", "X/y.pdf", "INDEXED"),                         # чужой датасет — не считаем
    ])
    inv = inventory_from_metadb(["bai"], meta_db_path=db)
    assert inv["total"] == 3                       # 4 файла bai минус артефакт
    assert inv["indexed"] == 1                     # только Состав проекта INDEXED
    assert "OUT/ИОС 5.1" in inv["folders"] and len(inv["folders"]["OUT/ИОС 5.1"]) == 2
    exts = dict(inv["by_ext"])
    assert exts.get(".docx") == 2 and exts.get(".pdf") == 1
    assert ".json" not in exts                     # артефакт не попал


def test_build_summary_has_inventory_without_parquet(tmp_path):
    # storage_root пустой → нет Parquet-таблиц (как у BAI), но опись из MetaDB есть
    db = _mk_meta(tmp_path, [("bai", "BAI/OUT/ИОС 5.1/03_ПЗ.docx", "PENDING")])
    summ = build_project_summary(["bai"], storage_root=tmp_path / "no_parquet", meta_db_path=db)
    assert summ["table_rows"] == 0 and summ["documents"] == []     # таблиц нет
    assert summ["file_count"] == 1                                  # но реестр есть → gate пропустит
    txt = format_project_summary(summ, label="BAI")
    assert "Реестр документов" in txt and "ИОС 5.1" in txt and "03_ПЗ.docx" in txt


def test_empty_dataset_no_inventory(tmp_path):
    db = _mk_meta(tmp_path, [])
    inv = inventory_from_metadb(["nope"], meta_db_path=db)
    assert inv["total"] == 0 and inv["folders"] == {}


def test_missing_db_is_safe():
    inv = inventory_from_metadb(["x"], meta_db_path="/nonexistent/meta.db")
    assert inv["total"] == 0   # best-effort, не падает
