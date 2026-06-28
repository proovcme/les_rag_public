import pytest

from backend.interface import Chunk
from proxy.services.notebook_study_service import (
    build_notebook_study_pack,
    build_reading_plan,
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
    }


def test_notebook_study_query_is_explicit_and_does_not_hijack_smeta_or_lookup():
    assert is_notebook_study_query("расскажи про проект котельной")
    assert is_notebook_study_query("сделай инженерную сводку по блокноту")
    assert not is_notebook_study_query("дай смету по проекту")
    assert not is_notebook_study_query("где лежит схема теплоснабжения")


def test_reading_plan_uses_notebook_map_for_engineering_and_tables():
    plan = build_reading_plan("расскажи про проект", [_notebook()])
    ids = [section.id for section in plan]

    assert "composition" in ids
    assert "engineering_systems" in ids
    assert "specs_tables" in ids
    assert all("шаблон" not in section.query.casefold() for section in plan)


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

    pack = await build_notebook_study_pack(question="расскажи про проект", dataset_ids=["ds-1"], retrieve=retrieve)
    payload = pack.payload()
    artifact = format_study_artifact("расскажи про проект", pack)

    assert payload["schema"] == "notebook_study_v1"
    assert payload["context_role"] == "navigation"
    assert payload["is_evidence"] is False
    assert any(item["hits"] for item in payload["retrieval_by_section"])
    assert "План чтения" in artifact
    assert "Источники по разделам" in artifact
    assert "ИОС4.pdf" in artifact
    assert "Спецификация.xlsx" in artifact
    assert "Блокнот и план — navigation, не evidence" in prompt_block(pack)
