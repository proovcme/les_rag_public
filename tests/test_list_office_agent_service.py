"""Л.Е.С. → Л.И.С.Т.: typed office IR, evidence and explicit review gate."""
from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


class FakeReader:
    def get_document(self, doc_id: str):
        if doc_id != "doc-1":
            return None
        return {
            "id": "doc-1",
            "dataset_id": "PROJECT_Index",
            "file_name": "Основание.pdf",
            "status": "INDEXED",
        }

    def search(self, query: str, *, doc_id: str, limit: int, max_chars: int):
        assert query and doc_id == "doc-1"
        return {
            "hits": [{
                "point_id": "p-7",
                "dataset_id": "PROJECT_Index",
                "doc_id": "doc-1",
                "doc_name": "Основание.pdf",
                "chunk_ord": 7,
                "section_heading": "Решение",
                "parent_heading": "",
                "text": "Заказчик согласовал замену оборудования письмом № 15.",
            }]
        }

    def document_chunks_by_id(self, doc_id: str, *, limit: int, max_chars: int):
        assert doc_id == "doc-1"
        return {
            "chunks": [{
                "point_id": "p-1",
                "dataset_id": "PROJECT_Index",
                "doc_id": "doc-1",
                "doc_name": "Основание.pdf",
                "chunk_ord": 1,
                "section_heading": "",
                "parent_heading": "",
                "text": "Техническое письмо по объекту Север.",
            }]
        }


@pytest.fixture()
def office_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    forms_dir = tmp_path / "forms"
    forms_dir.mkdir()
    (forms_dir / "letter.yaml").write_text(
        "id: letter\n"
        "title: Техническое письмо\n"
        "fields:\n"
        "  - { key: recipient, label: Кому, source: manual }\n"
        "  - { key: subject, label: Тема, source: manual }\n"
        "  - { key: body, label: Текст, source: manual }\n"
        "  - { key: today, label: Дата, source: date.today }\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LES_FORMS_DIR", str(forms_dir))
    monkeypatch.setenv("LES_LIST_OFFICE_DIR", str(tmp_path / "list_office"))
    import proxy.services.forms_service as forms_service
    import proxy.services.list_office_agent_service as agent_service
    import proxy.services.list_office_service as office_service

    importlib.reload(forms_service)
    importlib.reload(agent_service)
    importlib.reload(office_service)
    return agent_service, office_service, tmp_path


def test_prepare_ir_is_review_only_and_keeps_field_evidence(office_agent):
    service, _office_service, tmp_path = office_agent
    captured = {}

    async def fake_extract(schema, instruction, context, **kwargs):
        captured.update(schema=schema, instruction=instruction, context=json.loads(context), kwargs=kwargs)
        return SimpleNamespace(
            ok=True,
            attempts=1,
            errors=[],
            data={"fields": [
                {
                    "key": "recipient",
                    "value": "ООО «Заказчик»",
                    "status": "assumption",
                    "confidence": 0.45,
                    "evidence_ids": [],
                    "note": "Адресат не указан в основании.",
                },
                {
                    "key": "subject",
                    "value": "О согласовании замены оборудования",
                    "status": "grounded",
                    "confidence": 0.92,
                    "evidence_ids": ["E1"],
                    "note": "Основано на решении.",
                },
            ]},
        )

    result = asyncio.run(service.prepare_document_ir(
        "letter",
        dataset_id="PROJECT_Index",
        source_refs=[{"doc_id": "doc-1", "file_name": "подменённое имя.pdf"}],
        instruction="Подготовь письмо о согласованной замене",
        reader=FakeReader(),
        extractor=fake_extract,
    ))

    assert result["schema"] == "office_document_ir_v1"
    assert result["artifact_created"] is False and result["review_required"] is True
    assert result["source_refs"][0]["file_name"] == "Основание.pdf"
    fields = {item["key"]: item for item in result["fields"]}
    assert fields["subject"]["status"] == "grounded"
    assert fields["subject"]["evidence"][0]["point_id"] == "p-7"
    assert fields["body"]["status"] == "missing"
    assert not (tmp_path / "list_office").exists()
    assert captured["schema"]["properties"]["fields"]["items"]["additionalProperties"] is False
    assert captured["context"]["operator_instruction"] == "Подготовь письмо о согласованной замене"


def test_invalid_model_evidence_is_visible_assumption(office_agent):
    service, _office_service, _tmp_path = office_agent

    async def fake_extract(*_args, **_kwargs):
        return SimpleNamespace(ok=True, attempts=1, errors=[], data={"fields": [
            {
                "key": key,
                "value": "Черновое значение",
                "status": "grounded",
                "confidence": 0.8,
                "evidence_ids": ["E999"],
                "note": "",
            }
            for key in ("recipient", "subject", "body")
        ]})

    result = asyncio.run(service.prepare_document_ir(
        "letter",
        dataset_id="PROJECT_Index",
        source_refs=[{"doc_id": "doc-1"}],
        reader=FakeReader(),
        extractor=fake_extract,
    ))
    assert {item["status"] for item in result["fields"]} == {"assumption"}
    assert len(result["warnings"]) == 3


def test_agent_requires_selected_exact_document_and_surfaces_model_failure(office_agent):
    service, _office_service, _tmp_path = office_agent

    with pytest.raises(ValueError, match="хотя бы один"):
        asyncio.run(service.prepare_document_ir("letter", reader=FakeReader()))

    async def failed_extract(*_args, **_kwargs):
        return SimpleNamespace(ok=False, attempts=3, errors=["provider error: offline"], data=None)

    with pytest.raises(service.OfficeAgentUnavailable, match="offline"):
        asyncio.run(service.prepare_document_ir(
            "letter",
            dataset_id="PROJECT_Index",
            source_refs=[{"doc_id": "doc-1"}],
            reader=FakeReader(),
            extractor=failed_extract,
        ))


def test_render_requires_review_and_preserves_ir_in_manifest(office_agent):
    _agent_service, office_service, _tmp_path = office_agent
    office_ir = {
        "schema": "office_document_ir_v1",
        "form_id": "letter",
        "fields": [{"key": "subject", "value": "Тема", "status": "grounded", "evidence": []}],
        "review_required": True,
        "artifact_created": False,
    }
    with pytest.raises(ValueError, match="ручную проверку"):
        office_service.create_draft("letter", "docx", office_ir=office_ir)

    manifest = office_service.create_draft(
        "letter",
        "docx",
        manual={"subject": "Тема после проверки"},
        office_ir=office_ir,
        review_confirmed=True,
    )
    assert manifest["agent_assisted"] is True
    assert manifest["review_confirmed"] is True
    assert manifest["office_document_ir"]["artifact_created"] is False
    assert next(item for item in manifest["fields"] if item["key"] == "subject")["value"] == "Тема после проверки"


def test_agent_route_precedes_generic_form_route():
    from proxy.routers.forms import router

    paths = [route.path for route in router.routes]
    assert "/api/forms/agent-draft" in paths
    assert paths.index("/api/forms/agent-draft") < paths.index("/api/forms/{form_id}/fields")
