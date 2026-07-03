import sqlite3
from types import SimpleNamespace

import pytest

from proxy.services import dataset_memory_service
from proxy.services.dataset_memory_service import (
    build_typed_dataset_memory,
    chunk_payload_typing,
    dataset_brief_for_model,
)
from proxy.services.project_summary_service import inventory_from_metadb


def _seed_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE documents (
            id TEXT,
            dataset_id TEXT,
            file_name TEXT,
            status TEXT,
            chunk_count INTEGER,
            doc_type TEXT,
            content_type TEXT,
            domain TEXT,
            route_dataset TEXT,
            pipeline TEXT,
            source_path TEXT
        )
        """
    )
    rows = [
        ("1", "ds", "BAI/OUT/ИОС 5.2/02_Состав проекта.docx", "INDEXED", 12, "DOCUMENT", "mixed", "", "", "markdown", ""),
        ("2", "ds", "BAI/OUT/КР/03_Пояснительная записка.pdf", "INDEXED", 40, "DOCUMENT", "text", "", "", "markdown", ""),
        ("3", "ds", "BAI/OUT/АС/ведомость объемов работ.xlsx", "INDEXED", 8, "TABLE", "table", "TABLE_TABLE", "", "parquet", ""),
        ("4", "ds", "BAI/OUT/model.rvt", "PENDING", 0, "CAD_BIM", "cad_bim", "CAD_BIM", "", "json_graph_projection", ""),
    ]
    conn.executemany("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


def test_build_typed_dataset_memory_multilayer(tmp_path):
    db = tmp_path / "meta.db"
    _seed_db(db)

    memory = build_typed_dataset_memory("ds", meta_db_path=str(db), force=True)

    assert memory["schema"] == "dataset_memory_v1"
    assert memory["is_evidence"] is False
    layers = {item["id"] for item in memory["data_layers"]}
    assert {"text", "tables", "technical_docs", "cad_bim", "graphics"} <= layers
    important = {item["document_role"] for item in memory["important_files"]}
    assert "состав проекта" in important
    assert "пояснительная записка" in important


def test_dataset_brief_for_model_links_file_cards_to_chunks_and_keeps_model_primary(tmp_path):
    db = tmp_path / "meta.db"
    _seed_db(db)
    memory = build_typed_dataset_memory("ds", meta_db_path=str(db), force=True)
    memory["reader_status"] = "model"
    memory["reader_output"] = {
        "schema": "dataset_reader_map_v1",
        "corpus_kind": "project",
        "reader_summary": "Корпус похож на проектную документацию с ПЗ и ведомостью.",
        "where_to_look": [
            {
                "question_type": "смета",
                "target_files": ["BAI/OUT/АС/ведомость объемов работ.xlsx"],
                "reason": "табличный файл с объёмами",
            }
        ],
        "file_roles": [],
        "known_gaps": [],
        "answer_guidance": "Факты брать из найденных строк.",
        "confidence": 0.8,
    }

    brief = dataset_brief_for_model([memory], question="дай смету по проекту")

    assert "schema: dataset_brief_for_model_v1" in brief
    assert "модель и текущий промпт принимают профессиональное решение" in brief
    assert "file_name" in brief
    assert "Qdrant" in brief
    assert "lexical_chunks" in brief
    assert "doc_filter" in brief
    assert "BAI/OUT/АС/ведомость объемов работ.xlsx" in brief
    assert "Для сметы сначала найди ВОР/спецификации/ЛСР/таблицы объёмов" in brief
    assert "не источник фактов" in brief


def test_dataset_brief_for_model_adds_normative_navigation_without_answering():
    memory = {
        "schema": "dataset_memory_v1",
        "dataset_id": "fire",
        "document_count": 3,
        "indexed_count": 3,
        "chunk_count": 300,
        "data_layers": [{"id": "normative", "label": "нормы", "files": 2}],
        "document_roles": [{"role": "нормативный документ", "files": 2}],
        "file_cards": [
            {
                "file_name": "NTD/СП 7.13130.docx",
                "status": "INDEXED",
                "chunk_count": 216,
                "file_kind": "normative",
                "content_layers": ["normative", "text"],
                "document_role": "нормативный документ",
            },
            {
                "file_name": "NTD/СП 1.13130.docx",
                "status": "INDEXED",
                "chunk_count": 180,
                "file_kind": "normative",
                "content_layers": ["normative", "text"],
                "document_role": "нормативный документ",
            },
        ],
    }

    brief = dataset_brief_for_model(
        [memory],
        question="Для каких случаев предусматривать вытяжную противодымную вентиляцию не требуется а для каких требуется",
    )

    assert "Нормативная навигация" in brief
    assert "Сначала выбери нормативный документ-кандидат" in brief
    assert "пункт, подпункт, таблицу или приложение" in brief
    assert "ищи обе стороны нормы" in brief
    assert "NTD/СП 7.13130.docx" in brief
    assert "это карта" in brief
    assert "готовый ответ" not in brief.lower()


def test_inventory_from_metadb_includes_typed_fields(tmp_path):
    db = tmp_path / "meta.db"
    _seed_db(db)

    inventory = inventory_from_metadb(["ds"], meta_db_path=str(db))

    files = {item["name"]: item for item in inventory["files"]}
    assert files["ведомость объемов работ.xlsx"]["content_layers"] == ["tables", "technical_docs"]
    assert files["model.rvt"]["file_kind"] == "model_or_cad"
    assert files["02_Состав проекта.docx"]["document_role"] == "состав проекта"


def test_chunk_payload_typing_for_table_row():
    payload = chunk_payload_typing(
        "folder/ЛСР.xlsx",
        {"doc_type": "SMETA", "content_type": "table", "domain": "TABLE_SMETA"},
        {"type": "table_row"},
    )

    assert "tables" in payload["content_layers"]
    assert "estimate" in payload["content_layers"]
    assert payload["source_granularity"] == "table_row"


def test_reader_context_uses_env_limits(monkeypatch):
    cards = [
        {
            "file_name": f"file_{idx}.docx",
            "status": "INDEXED",
            "chunk_count": idx,
            "file_kind": "document",
            "content_layers": ["text"],
            "document_role": "документ",
            "summary": "тест",
        }
        for idx in range(25)
    ]
    memory = {
        "schema": "dataset_memory_v1",
        "dataset_id": "ds",
        "revision_id": "rev-x",
        "document_count": 25,
        "indexed_count": 25,
        "chunk_count": 250,
        "file_cards": cards,
    }
    monkeypatch.setenv("LES_DATASET_READER_FILE_LIMIT", "20")
    monkeypatch.setenv("LES_DATASET_READER_CONTEXT_CHARS", "8000")

    context = dataset_memory_service._reader_context(memory)

    assert '"included": 20' in context
    assert '"total": 25' in context
    assert "file_24.docx" in context
    assert "file_4.docx" not in context
    assert "TRUNCATED" not in context


@pytest.mark.asyncio
async def test_run_dataset_reader_pass_stores_navigation_json(tmp_path, monkeypatch):
    db = tmp_path / "meta.db"
    _seed_db(db)

    async def fake_extract(schema, instruction, context, *, max_attempts):
        assert schema["properties"]["schema"]["enum"] == ["dataset_reader_map_v1"]
        assert "02_Состав проекта.docx" in context
        assert "НЕ evidence" in instruction
        return SimpleNamespace(
            ok=True,
            data={
                "schema": "dataset_reader_map_v1",
                "corpus_kind": "project",
                "reader_summary": "Корпус похож на проект с составом, ПЗ, ведомостью и BIM-моделью.",
                "where_to_look": [
                    {
                        "question_type": "паспорт объекта",
                        "target_files": ["BAI/OUT/ИОС 5.2/02_Состав проекта.docx"],
                        "reason": "файл отмечен как состав проекта",
                    }
                ],
                "file_roles": [
                    {
                        "file_name": "BAI/OUT/ИОС 5.2/02_Состав проекта.docx",
                        "role": "состав проекта",
                        "what_inside": "навигация по томам",
                        "confidence": 0.9,
                    }
                ],
                "known_gaps": ["BIM-модель ещё не проиндексирована."],
                "answer_guidance": "Для фактов сначала открыть целевой файл.",
                "confidence": 0.82,
            },
            attempts=1,
            errors=[],
        )

    monkeypatch.setattr(dataset_memory_service, "_run_reader_extraction", fake_extract)

    memory = await dataset_memory_service.run_dataset_reader_pass("ds", meta_db_path=str(db), force=True)
    persisted = dataset_memory_service.get_typed_dataset_memory("ds", meta_db_path=str(db))

    assert memory["reader_status"] == "model"
    assert memory["is_evidence"] is False
    assert memory["reader_output"]["corpus_kind"] == "project"
    assert persisted["reader_output"]["answer_guidance"] == "Для фактов сначала открыть целевой файл."
