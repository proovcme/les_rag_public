import asyncio

import pytest

from backend.interface import Chunk
from proxy.services.notebook_study_service import (
    build_notebook_study_pack,
    build_reading_plan,
    build_target_file_plan,
    format_study_artifact,
    is_notebook_study_query,
    prompt_block,
)


def _notebook() -> dict:
    return {
        "dataset_id": "ds-1",
        "name": "ПД_Котельная",
        "document_count": 120,
        "chunk_count": 900,
        "notebook_summary": {
            "subject_areas": ["DOCS_OTHER", "TABLE_SPEC", "NTD_HVAC", "NTD_WATER"],
            "document_types": ["PDF", "XLSX"],
            "key_terms": ["котельная", "теплоснабжение", "водоснабжение", "спецификация"],
            "norm_refs": ["СП 60.13330", "ГОСТ 21.110"],
        },
        "profile": {
            "quality": {"status": "good", "signals": {"table_signal_chunks": 12}},
            "keywords": ["оборудование", "насосы"],
            "domains": [{"value": "TABLE_SMETA"}],
            "routes": [{"value": "NTD_HVAC"}],
            "document_types": [{"value": "PDF"}],
        },
        "typed_memory": {
            "reader_status": "bootstrap",
            "file_cards": [
                {
                    "file_name": "ПД/02_Состав проекта.docx",
                    "status": "INDEXED",
                    "chunk_count": 8,
                    "document_role": "состав проекта",
                    "summary": "Состав проектной документации",
                    "content_layers": ["text", "technical_docs"],
                    "confidence": 0.8,
                },
                {
                    "file_name": "ПД/03_Пояснительная записка.docx",
                    "status": "INDEXED",
                    "chunk_count": 18,
                    "document_role": "пояснительная записка",
                    "summary": "Паспорт объекта и исходные данные",
                    "content_layers": ["text", "technical_docs"],
                    "confidence": 0.8,
                },
            ],
        },
    }


def test_notebook_study_query_is_explicit_and_does_not_hijack_smeta_or_lookup():
    assert is_notebook_study_query("расскажи про проект котельной")
    assert is_notebook_study_query("расскажи про объект")
    assert is_notebook_study_query("что это за датасет НС")
    assert is_notebook_study_query("что за проект НС")
    assert is_notebook_study_query("сделай инженерную сводку по блокноту")
    assert not is_notebook_study_query("дай смету по проекту")
    assert not is_notebook_study_query("где лежит схема теплоснабжения")


def test_reading_plan_uses_notebook_map_for_engineering_and_tables():
    plan = build_reading_plan("расскажи про проект", [_notebook()])
    ids = [section.id for section in plan]

    assert "composition" in ids
    assert "engineering_systems" in ids
    assert "specs_tables" in ids
    assert len(ids) <= 4
    assert all("шаблон" not in section.query.casefold() for section in plan)


def test_reading_plan_selects_relevant_sections_without_reading_everything():
    plan = build_reading_plan("что по инженерным системам и оборудованию", [_notebook()])
    ids = [section.id for section in plan]

    assert "engineering_systems" in ids
    assert "gaps" in ids
    assert "normative_refs" not in ids
    assert len(ids) < 6


def test_target_file_plan_selects_passport_documents_from_memory_and_inventory():
    inventory = {
        "inventory": {
            "files": [
                {
                    "file_name": "BAI/OUT/ИОС 5.2/03_Пояснительная записка.docx",
                    "name": "03_Пояснительная записка.docx",
                    "status": "INDEXED",
                    "chunk_count": 12,
                    "document_role": "пояснительная записка",
                    "content_layers": ["text", "technical_docs"],
                },
                {
                    "file_name": "BAI/RVT/model.rvt",
                    "status": "INDEXED",
                    "chunk_count": 0,
                    "document_role": "модель/графика",
                },
            ]
        }
    }
    plan = build_target_file_plan([_notebook()], project_inventory=inventory, max_files=5)
    names = [item["file_name"] for item in plan]

    assert "ПД/02_Состав проекта.docx" in names
    assert "ПД/03_Пояснительная записка.docx" in names
    assert "BAI/OUT/ИОС 5.2/03_Пояснительная записка.docx" in names
    assert "BAI/RVT/model.rvt" not in names


@pytest.mark.asyncio
async def test_study_pack_retrieves_by_sections_and_formats_artifact(monkeypatch):
    from proxy.services import notebook_study_service as svc

    monkeypatch.setattr(svc, "build_dataset_notebooks", lambda dataset_ids, **_kw: [_notebook()])

    async def retrieve(query: str):
        if "Инженерные системы" in query:
            return [
                Chunk("ОВ: котельная, вентиляция, теплоснабжение.", "doc-1", "ИОС4.pdf", 0.91, {"dataset_id": "ds-1"})
            ]
        if "Ведомости" in query:
            return [
                Chunk("| Наименование | Количество |\n| Насос | 2 |", "doc-2", "Спецификация.xlsx", 0.88, {"dataset_id": "ds-1"})
            ]
        return []

    targeted = []

    async def retrieve_file(query: str, file_name: str):
        targeted.append(file_name)
        return [
            Chunk(
                "Объект: котельная. Стадия: проектная документация.",
                "doc-passport",
                file_name,
                0.93,
                {"dataset_id": "ds-1"},
            )
        ]

    pack = await build_notebook_study_pack(
        question="расскажи про проект",
        dataset_ids=["ds-1"],
        retrieve=retrieve,
        retrieve_file=retrieve_file,
    )
    payload = pack.payload()
    artifact = format_study_artifact("расскажи про проект", pack)

    assert payload["schema"] == "notebook_study_v1"
    assert payload["context_role"] == "navigation"
    assert payload["is_evidence"] is False
    assert any(item["hits"] for item in payload["retrieval_by_section"])
    assert "Найденные материалы по разделам" in artifact
    assert "Как читалось" in artifact
    assert artifact.index("Найденные материалы по разделам") < artifact.index("Как читалось")
    assert "ИОС4.pdf" in artifact
    assert "Спецификация.xlsx" in artifact
    assert targeted
    assert payload["targeted_files"][0]["hits"] > 0
    assert "Точечно открытые файлы" in artifact
    assert "Объект: котельная" in artifact
    assert "Блокнот и план — navigation, не evidence" in prompt_block(pack)


@pytest.mark.asyncio
async def test_study_pack_retrieves_sections_in_parallel(monkeypatch):
    from proxy.services import notebook_study_service as svc

    monkeypatch.setattr(svc, "build_dataset_notebooks", lambda dataset_ids, **_kw: [_notebook()])
    monkeypatch.setenv("LES_NOTEBOOK_STUDY_PARALLELISM", "3")
    active = 0
    max_active = 0

    async def retrieve(_query: str):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return []

    pack = await build_notebook_study_pack(question="расскажи про проект", dataset_ids=["ds-1"], retrieve=retrieve)

    assert len(pack.plan) >= 3
    assert max_active > 1
