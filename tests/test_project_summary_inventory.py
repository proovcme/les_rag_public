"""Фикс №1: «Сводка проекта» строит реестр из ОПИСИ MetaDB, а не только из Parquet-таблиц.

Симптом: датасет без табличных документов (BAI — PDF/docx-тома ИОС) давал document_count=0 →
project_summary пуст → проваливался в RAG → NO_DATA. Котельная (с .xlsx → Parquet-таблицы) работала.
Теперь inventory_from_metadb перечисляет ВСЕ файлы датасета из documents → реестр есть всегда.
"""

import sqlite3
from pathlib import Path

from proxy.services.project_summary_service import (
    build_project_summary,
    format_project_inventory_context,
    format_project_inventory_prompt,
    format_project_summary,
    inventory_from_metadb,
    is_project_inventory_query,
    resolve_inventory_file_reference,
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
    assert any(f["file_name"] == "BAI/OUT/ИОС 5.2/02_Состав проекта.docx" for f in inv["files"])
    assert {f["name"] for f in inv["files"]} >= {"03_Пояснительная записка.docx", "СО1Б-ИОС5.1.pdf"}
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
    ctx = format_project_inventory_context(summ, label="BAI")
    assert "ПРОВЕРЯЕМАЯ ОПИСЬ ФАЙЛОВ ДАТАСЕТА · BAI" in ctx
    assert "03_ПЗ.docx [PENDING]" in ctx
    assert "Источник: внутренняя таблица документов ЛЕС (MetaDB documents)" in ctx
    prompt = format_project_inventory_prompt(summ, label="BAI")
    assert "КАРТА РЕЕСТРА ДАТАСЕТА · BAI" in prompt
    assert "Полный реестр доступен отдельным артефактом/project_inventory" in prompt
    assert "03_ПЗ.docx [PENDING]" in prompt


def test_project_inventory_prompt_is_compact_navigation_map(tmp_path):
    rows = [
        ("bai", f"BAI/OUT/ИОС 5.1/{idx:03d}_Рядовой файл {idx}.docx", "INDEXED")
        for idx in range(40)
    ]
    rows.extend([
        ("bai", "BAI/OUT/ИОС 5.1/02_Состав проекта.docx", "INDEXED"),
        ("bai", "BAI/OUT/ИОС 5.1/03_Пояснительная записка.docx", "INDEXED"),
    ])
    db = _mk_meta(tmp_path, rows)
    summ = build_project_summary(["bai"], storage_root=tmp_path / "no_parquet", meta_db_path=db)
    full = format_project_inventory_context(summ, label="BAI")
    prompt = format_project_inventory_prompt(summ, label="BAI", max_files=6)
    assert len(prompt) < len(full)
    assert "КАРТА РЕЕСТРА ДАТАСЕТА" in prompt
    assert "ПРОВЕРЯЕМАЯ ОПИСЬ ФАЙЛОВ ДАТАСЕТА" not in prompt
    assert "02_Состав проекта.docx" in prompt
    assert "03_Пояснительная записка.docx" in prompt
    assert "039_Рядовой файл 39.docx" not in prompt


def test_project_inventory_intent_is_file_register_not_project_summary_hijack():
    assert is_project_inventory_query("дай перечень файлов в датасете и описание проекта")
    assert is_project_inventory_query("составь реестр документации котельной")
    assert is_project_inventory_query("какие документы в датасете BAI")
    assert is_project_inventory_query("что это за датасет НС")
    assert not is_project_inventory_query("расскажи про проект котельной")


def test_resolve_inventory_file_reference_matches_exact_file_name(tmp_path):
    db = _mk_meta(tmp_path, [
        ("bai", "BAI/OUT/ИОС 5.2/02_Состав проекта.docx", "INDEXED"),
        ("bai", "BAI/OUT/ИОС 5.3/02_Состав проекта.docx", "PENDING"),
    ])
    match = resolve_inventory_file_reference(
        "02_Состав проекта.docx - а это что?",
        ["bai"],
        meta_db_path=db,
    )
    assert match and match["match_status"] == "ambiguous"
    exact = resolve_inventory_file_reference(
        "расскажи про файл BAI/OUT/ИОС 5.2/02_Состав проекта.docx",
        ["bai"],
        meta_db_path=db,
    )
    assert exact and exact["match_status"] == "matched"
    assert exact["file_name"] == "BAI/OUT/ИОС 5.2/02_Состав проекта.docx"
    assert exact["status"] == "INDEXED"


def test_resolve_inventory_file_reference_matches_path_suffix_without_substring_ambiguity(tmp_path):
    db = _mk_meta(tmp_path, [
        ("bai", "BAI/OUT/ИОС 5.1/001_Содержание тома.docx", "INDEXED"),
        ("bai", "BAI/OUT/ИОС 5.2/01_Содержание тома.docx", "INDEXED"),
        ("bai", "BAI/OUT/ИОС 5.3/01_Содержание тома.docx", "INDEXED"),
    ])

    match = resolve_inventory_file_reference(
        "расскажи, что в файле OUT/ИОС 5.1/001_Содержание тома.docx",
        ["bai"],
        meta_db_path=db,
    )

    assert match and match["match_status"] == "matched"
    assert match["file_name"] == "BAI/OUT/ИОС 5.1/001_Содержание тома.docx"


def test_empty_dataset_no_inventory(tmp_path):
    db = _mk_meta(tmp_path, [])
    inv = inventory_from_metadb(["nope"], meta_db_path=db)
    assert inv["total"] == 0 and inv["folders"] == {}


def test_missing_db_is_safe():
    inv = inventory_from_metadb(["x"], meta_db_path="/nonexistent/meta.db")
    assert inv["total"] == 0   # best-effort, не падает
