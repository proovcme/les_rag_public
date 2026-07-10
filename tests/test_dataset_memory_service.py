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
    select_topic_retrieval_plan,
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
    assert memory["topic_map"]["schema"] == "dataset_topic_map_v1"
    assert memory["topic_map"]["is_evidence"] is False
    topic_ids = {item["id"] for item in memory["topic_map"]["topics"]}
    assert "project_overview" in topic_ids
    assert "estimate_cost" in topic_ids
    assert memory["section_map"]["schema"] == "dataset_section_map_v1"
    assert memory["section_map"]["is_evidence"] is False


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
    assert "Карта тем датасета" in brief
    assert "сначала ВОР/спецификация/ЛСР" in brief
    assert "не источник фактов" in brief


def test_dataset_brief_includes_project_pdf_extract_as_navigation(tmp_path):
    db = tmp_path / "meta.db"
    _seed_db(db)
    memory = build_typed_dataset_memory("ds", meta_db_path=str(db), force=True)
    memory["project_pdf_extract"] = {
        "context_role": "navigation_not_evidence",
        "coverage": {"pdf_documents": 2, "files_extracted": 2, "pz_files": 1, "vor_files": 1, "so_files": 0},
        "source_navigation": [
            {
                "file_name": "PD/ИОС.ЭС.ПЗ.pdf",
                "role": "пояснительная записка",
                "use_for": "проектные решения",
                "source_refs": ["PD/ИОС.ЭС.ПЗ.pdf#page=1"],
            }
        ],
        "files": [
            {"file_name": "PD/ИОС.ЭС.ПЗ.pdf", "status": "ok"},
            {"file_name": "PD/ИОС.ЭС.ВОР.pdf", "status": "ok"},
        ],
    }

    brief = dataset_brief_for_model([memory], question="что есть в проекте по ЭС?")

    assert "PDF project source-map" in brief
    assert "навигация, не evidence" in brief
    assert "Где искать в PDF-проекте" in brief
    assert "PD/ИОС.ЭС.ПЗ.pdf" in brief
    assert "проектные решения" in brief


def test_topic_and_section_maps_use_lexical_headings(tmp_path):
    db = tmp_path / "meta.db"
    _seed_db(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "5",
                "ds",
                "BAI/OUT/ИОС 5.2/03_Пояснительная записка.docx",
                "INDEXED",
                32,
                "DOCUMENT",
                "text",
                "",
                "",
                "markdown",
                "",
            ),
        )
        conn.execute(
            """
            CREATE TABLE lexical_chunks (
                dataset_id TEXT,
                doc_name TEXT,
                section_heading TEXT DEFAULT '',
                parent_heading TEXT DEFAULT ''
            )
            """
        )
        conn.executemany(
            "INSERT INTO lexical_chunks(dataset_id, doc_name, section_heading, parent_heading) VALUES (?,?,?,?)",
            [
                (
                    "ds",
                    "BAI/OUT/ИОС 5.2/03_Пояснительная записка.docx",
                    "5.2 Автоматическая установка пожарной сигнализации и противопожарная автоматика",
                    "",
                ),
                (
                    "ds",
                    "BAI/OUT/ИОС 5.2/03_Пояснительная записка.docx",
                    "Алгоритмы управления пожаротушением и противодымной вентиляцией",
                    "",
                ),
                (
                    "ds",
                    "BAI/OUT/ИОС 5.2/03_Пояснительная записка.docx",
                    "Интеграция АУПС с ОПС, СКУД и инженерным оборудованием",
                    "",
                ),
            ],
        )
        conn.commit()

    memory = build_typed_dataset_memory("ds", meta_db_path=str(db), force=True)
    topic = next(item for item in memory["topic_map"]["topics"] if item["id"] == "fire_alarm_automation")

    assert topic["is_evidence"] is False
    assert topic["top_sections"]
    assert any("Автоматическая установка пожарной сигнализации" in item["heading"] for item in topic["top_sections"])
    assert topic["top_sections"][0]["file_name"].endswith("03_Пояснительная записка.docx")
    assert memory["section_map"]["coverage"]["files_with_sections"] == 1

    brief = dataset_brief_for_model([memory], question="сводка технических решений по пожарной сигнализации")
    assert "Карта тем датасета" in brief
    assert "пожарная сигнализация и противопожарная автоматика" in brief
    assert "Оглавление/разделы" in brief
    assert "Автоматическая установка пожарной сигнализации" in brief


def test_topic_retrieval_plan_selects_topic_files_and_fallback(tmp_path):
    db = tmp_path / "meta.db"
    _seed_db(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "5",
                "ds",
                "BAI/IN/КСБ.pdf",
                "INDEXED",
                20,
                "DOCUMENT",
                "text",
                "",
                "",
                "markdown",
                "",
            ),
        )
        conn.execute(
            """
            CREATE TABLE lexical_chunks (
                dataset_id TEXT,
                doc_name TEXT,
                section_heading TEXT DEFAULT '',
                parent_heading TEXT DEFAULT ''
            )
            """
        )
        conn.execute(
            "INSERT INTO lexical_chunks(dataset_id, doc_name, section_heading, parent_heading) VALUES (?,?,?,?)",
            (
                "ds",
                "BAI/IN/КСБ.pdf",
                "5.2 Автоматическая установка пожарной сигнализации (АУПС), противопожарная автоматика",
                "",
            ),
        )
        conn.commit()

    memory = build_typed_dataset_memory("ds", meta_db_path=str(db), force=True)
    plan = select_topic_retrieval_plan(
        [memory],
        "дай сводку технических решений по пожарной сигнализации и автоматике",
    )

    assert plan["schema"] == "dataset_topic_selection_v1"
    assert plan["is_evidence"] is False
    assert plan["fallback"] == "wide_retrieval"
    assert plan["selected_topics"][0]["id"] == "fire_alarm_automation"
    assert plan["selected_files"][0]["file_name"] == "BAI/IN/КСБ.pdf"
    assert plan["selected_files"][0]["reason"] == "topic_section"
    assert "АУПС" in plan["selected_sections"][0]["heading"]


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
    assert "шифр" in typing["navigation_terms"]


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
    assert "шифр нормы" in norm_table["navigation_terms"]
    assert "ресурсы нормы" in resource_table["navigation_terms"]
    assert "машины" in resource_table["navigation_terms"]


def test_pricebook_files_get_navigation_terms():
    typing = infer_file_typing(
        {
            "file_name": "RAG_Content/TABLE_SMETA/SMETA_SERVICE/pricebook_spb_2kv2026.md",
            "domain": "TABLE_SMETA",
            "doc_type": "SMETA",
            "content_type": "text",
        }
    )

    assert "ФГИС ЦС" in typing["navigation_terms"]
    assert "цены ресурсов" in typing["navigation_terms"]
    assert "квартал" in typing["navigation_terms"]


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


def test_project_ntd_domain_is_technical_not_normative_without_norm_doc_type():
    typing = infer_file_typing(
        {
            "file_name": "ns/27_05-22-Р-ЭОМ.1_19.06.2025.pdf",
            "domain": "NTD_ELECTRICAL",
            "doc_type": "DOCUMENT",
            "content_type": "mixed",
            "pipeline": "markdown_pdf_tables",
        }
    )

    assert typing["file_kind"] == "technical_document"
    assert "technical_docs" in typing["content_layers"]
    assert "normative" not in typing["content_layers"]
    assert typing["document_role"] == "документ"
    assert "рабочая документация" in typing["navigation_terms"]
    assert "электроснабжение" in typing["navigation_terms"]


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
    assert "шифр" in memory["important_files"][0]["navigation_terms"]
    norm_files = memory["source_graph"]["top_files_by_layer"]["normative"]
    assert norm_files[0]["file_name"].endswith("gesnm10-06-001-01.md")
    assert "шифр" in norm_files[0]["navigation_terms"]
    route = next(item for item in memory["retrieval_routes"] if item["id"] == "normative_answer")
    assert route["target_files"][0]["file_name"].endswith("gesnm10-06-001-01.md")
    assert "шифр" in route["target_files"][0]["navigation_terms"]
    brief = dataset_brief_for_model([memory], question="найди нормативное требование")
    nav = brief.split("Нормативная навигация:", 1)[1]
    assert nav.find("gesnm10-06-001-01.md") < nav.find("00_dataset_card.md")
    assert "искать как" in nav


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
        "operator_guidance": "Сначала читать состав проекта и ПЗ.",
        "operator_guidance_role": "navigation_not_evidence",
        "file_cards": cards,
        "section_map": {
            "schema": "dataset_section_map_v1",
            "coverage": {"files_with_sections": 1, "section_count": 30},
            "files": [
                {
                    "file_name": "file_24.docx",
                    "sections": [{"heading": f"Раздел {idx}", "chunk_count": 1} for idx in range(30)],
                }
            ],
        },
    }
    monkeypatch.setenv("LES_DATASET_READER_FILE_LIMIT", "20")
    monkeypatch.setenv("LES_DATASET_READER_CONTEXT_CHARS", "8000")

    context = dataset_memory_service._reader_context(memory)

    assert "Сначала читать состав проекта и ПЗ." in context
    assert '"included": 20' in context
    assert '"total": 25' in context
    assert '"corpus_groups"' in context
    assert '"corpus_groups_scope"' in context
    assert "file_24.docx" in context
    assert "file_4.docx" not in context
    assert "Раздел 4" in context
    assert "Раздел 5" not in context
    assert "TRUNCATED" not in context


def test_reader_context_spreads_cards_across_actual_folder_groups(monkeypatch):
    memory = {
        "dataset_id": "arbitrary",
        "file_cards": [
            {"file_name": "alpha/high.pdf", "status": "INDEXED", "chunk_count": 90},
            {"file_name": "alpha/low.pdf", "status": "INDEXED", "chunk_count": 1},
            {"file_name": "beta/table.xlsx", "status": "INDEXED", "chunk_count": 8},
            {"file_name": "gamma/scan.pdf", "status": "PENDING", "chunk_count": 0},
            {"file_name": "delta/notes.txt", "status": "INDEXED", "chunk_count": 2},
        ],
        "section_map": {},
    }
    monkeypatch.setenv("LES_DATASET_READER_FILE_LIMIT", "4")

    context = dataset_memory_service._reader_context(memory)
    reader_input = json.loads(context)
    selected_names = [item["file_name"] for item in reader_input["file_cards"]]

    assert selected_names == ["alpha/high.pdf", "beta/table.xlsx", "delta/notes.txt", "gamma/scan.pdf"]
    assert reader_input["corpus_groups_scope"]["total"] == 4


def test_reader_compact_prompt_avoids_full_json_schema():
    prompt = dataset_memory_service._reader_compact_prompt("Инструкция", '{"dataset_id":"ds"}')

    assert "ВХОДНАЯ КАРТА ДАТАСЕТА JSON" in prompt
    assert '"schema": "dataset_reader_map_v1"' in prompt
    assert "JSON-схема" not in prompt
    assert '"properties"' not in prompt


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


def test_reader_output_discards_model_file_names_absent_from_real_corpus(tmp_path):
    db = tmp_path / "meta.db"
    _seed_db(db)
    memory = build_typed_dataset_memory("ds", meta_db_path=str(db), force=True)

    clean = dataset_memory_service._sanitize_reader_output(
        {
            "schema": "dataset_reader_map_v1",
            "corpus_kind": "смешанный комплект",
            "reader_summary": "Карта корпуса",
            "where_to_look": [
                {"question_type": "обзор", "target_files": ["BAI/OUT/КР/03_Пояснительная записка.pdf", "invented.pdf"], "reason": "test"}
            ],
            "file_roles": [
                {"file_name": "BAI/OUT/КР/03_Пояснительная записка.pdf", "role": "документ", "what_inside": "текст", "confidence": 0.8},
                {"file_name": "invented.pdf", "role": "ложный", "what_inside": "нет", "confidence": 1},
            ],
            "known_gaps": [],
            "answer_guidance": "Открыть реальные файлы.",
            "confidence": 0.7,
        },
        memory,
    )

    assert clean["file_roles"] == [{
        "file_name": "BAI/OUT/КР/03_Пояснительная записка.pdf",
        "role": "документ",
        "what_inside": "текст",
        "confidence": 0.8,
    }]
    assert clean["where_to_look"][0]["target_files"] == ["BAI/OUT/КР/03_Пояснительная записка.pdf"]
