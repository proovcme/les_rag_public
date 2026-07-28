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
            "revision_id": "rev-20260710",
            "reader_status": "bootstrap",
            "topic_map": {
                "topics": [{"id": "heating", "label": "Теплоснабжение"}],
            },
            "section_map": {"files": []},
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


def test_reading_plan_is_derived_from_actual_navigation_not_domain_templates():
    plan = build_reading_plan("расскажи про проект", [_notebook()])
    titles = [section.title for section in plan]
    joined = "\n".join(section.query for section in plan).casefold()

    assert any("ПД/" in title for title in titles)
    assert any(title.startswith("Файлы:") for title in titles)
    assert len(titles) <= 4
    assert "архитектур" not in joined
    assert "конструктив" not in joined


def test_reading_plan_selects_relevant_sections_without_reading_everything():
    plan = build_reading_plan("что по инженерным системам и оборудованию", [_notebook()])
    titles = [section.title for section in plan]

    assert any("ПД/" in title for title in titles)
    assert all("Архитектура" not in title for title in titles)
    assert len(titles) < 6


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


def test_target_file_plan_spreads_reads_across_actual_file_groups():
    inventory = {
        "inventory": {
            "files": [
                {"file_name": "X/alpha/one.pdf", "chunk_count": 10},
                {"file_name": "X/alpha/two.pdf", "chunk_count": 80},
                {"file_name": "X/beta/three.pdf", "chunk_count": 12},
                {"file_name": "X/gamma/four.xlsx", "chunk_count": 6},
            ]
        }
    }

    plan = build_target_file_plan([], project_inventory=inventory, question="расскажи про корпус", max_files=3)

    assert {item["coverage_group"] for item in plan} == {"X/alpha", "X/beta", "X/gamma"}
    assert "X/alpha/two.pdf" in [item["file_name"] for item in plan]


def test_target_file_plan_ignores_stale_or_invented_reader_file_names():
    notebook = _notebook()
    memory = notebook["typed_memory"]
    memory["reader_status"] = "model"
    memory["reader_output"] = {
        "file_roles": [{"file_name": "outside/invented.pdf", "role": "fake"}],
        "where_to_look": [{"target_files": ["outside/invented.pdf"], "reason": "fake"}],
    }

    plan = build_target_file_plan([notebook], max_files=8)

    assert "outside/invented.pdf" not in [item["file_name"] for item in plan]


@pytest.mark.asyncio
async def test_study_pack_retrieves_by_sections_and_formats_artifact(monkeypatch):
    from proxy.services import notebook_study_service as svc

    monkeypatch.setattr(svc, "build_dataset_notebooks", lambda dataset_ids, **_kw: [_notebook()])

    async def retrieve(query: str):
        if "Пояснительная записка" in query:
            return [
                Chunk("ОВ: котельная, вентиляция, теплоснабжение.", "doc-1", "ИОС4.pdf", 0.91, {"dataset_id": "ds-1"})
            ]
        if "Состав проекта" in query:
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
    guide = payload["research_guide"]
    assert guide["schema"] == "notebook_research_guide_v1"
    assert guide["context_role"] == "navigation"
    assert guide["is_evidence"] is False
    assert guide["source_maps"] == [{
        "dataset_id": "ds-1",
        "revision_id": "rev-20260710",
        "revision_available": True,
        "topic_map": True,
        "section_map": True,
        "reader_status": "bootstrap",
        "reader_pass": False,
        "file_cards": 2,
    }]
    assert guide["coverage"]["sections_with_hits"] > 0
    assert guide["suggested_questions"]
    assert any(item["hits"] for item in payload["retrieval_by_section"])
    assert "Карта исследования" in artifact
    assert "Вопросы для продолжения" in artifact
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
    assert "Не подставляй заранее заданные типы документов" in prompt_block(pack)


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

    assert len(pack.plan) >= 2
    assert max_active > 1


@pytest.mark.asyncio
async def test_target_file_evidence_rejects_chunks_from_another_file(monkeypatch):
    from proxy.services import notebook_study_service as svc

    monkeypatch.setattr(svc, "build_dataset_notebooks", lambda dataset_ids, **_kw: [_notebook()])

    async def retrieve(_query: str):
        return []

    async def retrieve_file(_query: str, _file_name: str):
        return [Chunk("чужой фрагмент", "wrong", "other/file.pdf", 0.99, {"dataset_id": "ds-1"})]

    pack = await build_notebook_study_pack(
        question="расскажи про датасет",
        dataset_ids=["ds-1"],
        retrieve=retrieve,
        retrieve_file=retrieve_file,
    )
    payload = pack.payload()

    assert not pack.chunks_by_file["ПД/02_Состав проекта.docx"]
    first_file = next(item for item in payload["targeted_files"] if item["file_name"] == "ПД/02_Состав проекта.docx")
    assert first_file["retrieval_candidates"] == 1
    assert first_file["discarded_mismatched_chunks"] == 1
    assert payload["research_guide"]["coverage"]["targeted_chunks_discarded_as_mismatch"] > 0
    assert any("другого файла" in gap for gap in pack.gaps)
