import json
import sqlite3
from types import SimpleNamespace

import pytest

from proxy.services import dataset_memory_service
from proxy.services.dataset_memory_service import (
    build_typed_dataset_memory,
    chunk_payload_typing,
    dataset_brief_for_model,
    infer_file_typing,
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
    source_layers = {item["id"]: item for item in memory["source_layers"]}
    assert source_layers["tables"]["use_for"]
    assert "числа" in source_layers["tables"]["evidence_rule"]
    route_ids = {item["id"] for item in memory["retrieval_routes"]}
    assert {"project_overview", "estimate_or_cost", "table_query", "cad_bim_query"} <= route_ids
    assert "normative_answer" not in route_ids
    graph = memory["source_graph"]
    assert graph["schema"] == "dataset_source_graph_v1"
    assert graph["is_evidence"] is False
    assert graph["top_files_by_layer"]["tables"][0]["file_name"] == "BAI/OUT/АС/ведомость объемов работ.xlsx"


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
    assert "Что означают слои" in brief
    assert "Маршруты поиска по типам вопросов" in brief
    assert "Связка слои -> файлы" in brief
    assert "сначала ВОР/спецификация/ЛСР" in brief
    assert "не источник фактов" in brief


def test_dataset_brief_includes_operator_guidance_as_navigation(tmp_path):
    db = tmp_path / "meta.db"
    _seed_db(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE les_dataset_profiles (
                dataset_id TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL,
                content_signature TEXT NOT NULL DEFAULT '',
                profile_path TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO les_dataset_profiles(dataset_id, profile_json, updated_at) VALUES(?,?,0)",
            (
                "ds",
                json.dumps(
                    {
                        "operator_guidance": "Сначала смотреть ВОР и ПЗ; архивные КП не считать актуальными.",
                        "operator_guidance_role": "navigation_not_evidence",
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        conn.commit()

    memory = build_typed_dataset_memory("ds", meta_db_path=str(db), force=True)
    brief = dataset_brief_for_model([memory], question="расскажи про проект")

    assert "Комментарий оператора для модели" in brief
    assert "архивные КП" in brief
    assert "не evidence" in brief


def test_dataset_brief_backfills_navigation_for_old_memory():
    memory = {
        "schema": "dataset_memory_v1",
        "dataset_id": "legacy",
        "document_count": 1,
        "indexed_count": 1,
        "chunk_count": 12,
        "file_cards": [
            {
                "file_name": "legacy/ВОР.xlsx",
                "status": "INDEXED",
                "chunk_count": 12,
                "file_kind": "table",
                "content_layers": ["tables", "estimate"],
                "document_role": "ведомость",
            }
        ],
    }

    brief = dataset_brief_for_model([memory], question="сделай смету")

    assert "Маршруты поиска по типам вопросов" in brief
    assert "legacy/ВОР.xlsx" in brief
    assert "dataset_source_graph_v1" not in brief


def test_dataset_brief_falls_back_to_chunk_rich_file_cards_when_important_missing(tmp_path):
    db = tmp_path / "meta.db"
    _seed_db(db)
    memory = build_typed_dataset_memory("ds", meta_db_path=str(db), force=True)
    memory["important_files"] = []

    brief = dataset_brief_for_model([memory], question="расскажи про проект")

    assert "Открывать в первую очередь" in brief
    assert "BAI/OUT/КР/03_Пояснительная записка.pdf" in brief
    assert "чанков 40" in brief


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
    assert "нормоконтроль, требования" in brief
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


def test_smeta_norm_archives_are_normative_not_generic_estimate():
    typing = infer_file_typing(
        {
            "file_name": "TABLE_SMETA/SMETA_RU_NORM/fsnb2022/gesnm10-06-001-01.md",
            "domain": "SMETA_RU_NORM_FSNB2022",
            "doc_type": "SMETA",
            "content_type": "text",
        }
    )

    assert typing["file_kind"] == "normative"
    assert "normative" in typing["content_layers"]
    assert "estimate" not in typing["content_layers"]
    assert "calculations" not in typing["content_layers"]
    assert typing["document_role"] == "ГЭСНм"


def test_smeta_norm_roles_distinguish_resource_bases():
    machine = infer_file_typing(
        {"file_name": "fsnb2022/fsbcmm/resources.md", "domain": "SMETA_RU_NORM_FSNB2022"}
    )
    materials = infer_file_typing(
        {"file_name": "fsnb2022/fsbcm/materials.md", "domain": "SMETA_RU_NORM_FSNB2022"}
    )
    equipment = infer_file_typing(
        {"file_name": "fsnb2022/fsbco/equipment.md", "domain": "SMETA_RU_NORM_FSNB2022"}
    )

    assert machine["document_role"] == "ФСЭМ"
    assert materials["document_role"] == "ФСБЦ материалы"
    assert equipment["document_role"] == "ФСБЦ оборудование"


def test_smeta_norm_nested_tables_have_human_roles():
    norm_table = infer_file_typing(
        {
            "file_name": "TABLE_SMETA/SMETA_RU_NORM/fsnb2022/projected_nested/2022_18.vnbx/A_SRF_F.json.md",
            "domain": "SMETA_RU_NORM_FSNB2022",
        }
    )
    resource_table = infer_file_typing(
        {
            "file_name": "TABLE_SMETA/SMETA_RU_NORM/fsnb2022/projected_nested/2022_18.vnbx/A_SRF_TR.json.md",
            "domain": "SMETA_RU_NORM_FSNB2022",
        }
    )

    assert norm_table["document_role"] == "таблица норм/расценок ФСНБ"
    assert resource_table["document_role"] == "таблица ресурсов нормы"


def test_project_estimate_still_keeps_estimate_role():
    typing = infer_file_typing(
        {
            "file_name": "project/ЛСР.xlsx",
            "domain": "TABLE_SMETA",
            "doc_type": "SMETA",
            "content_type": "table",
        }
    )

    assert typing["file_kind"] == "estimate"
    assert "estimate" in typing["content_layers"]
    assert typing["document_role"] == "сметный расчёт"


def test_smeta_norm_memory_downranks_service_noise(tmp_path):
    db = tmp_path / "meta.db"
    conn = sqlite3.connect(db)
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
        ("1", "norms", "TABLE_SMETA/SMETA_RU_NORM/fsnb2022/00_dataset_card.md", "INDEXED", 900, "SMETA", "text", "SMETA_RU_NORM_FSNB2022", "", "markdown", ""),
        ("2", "norms", "TABLE_SMETA/SMETA_RU_NORM/fsnb2022/01_archive_manifest.md", "INDEXED", 800, "SMETA", "text", "SMETA_RU_NORM_FSNB2022", "", "markdown", ""),
        ("3", "norms", "TABLE_SMETA/SMETA_RU_NORM/fsnb2022/projected_text/gesnm10-06-001-01.md", "INDEXED", 3, "SMETA", "text", "SMETA_RU_NORM_FSNB2022", "", "markdown", ""),
    ]
    conn.executemany("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()

    memory = build_typed_dataset_memory("norms", meta_db_path=str(db), force=True)

    assert "normative" in {item["id"] for item in memory["source_layers"]}
    assert memory["important_files"][0]["file_name"].endswith("gesnm10-06-001-01.md")
    norm_files = memory["source_graph"]["top_files_by_layer"]["normative"]
    assert norm_files[0]["file_name"].endswith("gesnm10-06-001-01.md")
    route = next(item for item in memory["retrieval_routes"] if item["id"] == "normative_answer")
    assert route["target_files"][0]["file_name"].endswith("gesnm10-06-001-01.md")
    brief = dataset_brief_for_model([memory], question="найди нормативное требование")
    nav = brief.split("Нормативная навигация:", 1)[1]
    assert nav.find("gesnm10-06-001-01.md") < nav.find("00_dataset_card.md")


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
