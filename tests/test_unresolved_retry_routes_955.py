"""Retry a delivered partial estimate without discarding its closed operations."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from proxy.routers import chat
from proxy.services import chat_evidence_application_service as application
from proxy.services.attachment_source_catalog_service import AttachmentSourceCatalog, CatalogRow
from proxy.services.lsr_result_readiness_service import build_lsr_result_readiness
from sovushka.pages import chat as chat_page
from tests.lsr_citation_support import cited_all
from tests.test_workbook_gap_followup_955 import SOURCE, baseline, identity


def partial_readiness():
    rows = cited_all([
        {"source_row": "Лист!R2", "operation_id": "closed", "row_role": "work",
         "norm_code": "ГЭСН12-01-034-02", "norm_status": "EXACT", "title": "Закрытая работа"},
        {"source_row": "Лист!R2", "operation_id": "missing", "row_role": "work",
         "norm_code": "", "norm_status": "MISSING", "title": "Требуется добор нормы"},
    ])
    before = deepcopy(rows)
    ready = build_lsr_result_readiness(packaged=True, rows=rows, catalog_locators=["Лист!R2"],
        remaining_locators=[], document_state="ready", job_status="complete", pricing_status="priced_partial")
    assert rows == before
    return ready


def test_completed_partial_estimate_exposes_only_unclosed_operation_targets():
    ready = partial_readiness()
    assert ready["research_locators"] == ["Лист!R2"]
    assert ready["research_operation_ids"] == ["missing"]
    assert ready["remaining_locators"] == []
    assert "resume" in {item["id"] for item in ready["actions"]}
    assert ready["estimate_complete"] is False


def test_ui_continue_uses_research_targets_even_when_completed_queue_is_empty():
    ready = partial_readiness()
    current = {"job_id": "j", "status": "complete", "identity": {"session_id": "s", "attachment_id": "src"},
               "remaining": [], "accepted_rows": [{"source_row": "Лист!R2", "operation_id": "closed"}],
               "held_packet": {"terminal_packets": [{"locators": ["Лист!R2"]}]}}
    before = deepcopy(current)
    payload = chat_page.lsr_explicit_resume_reopen_payload({"job_id": "j", "session_id": "s", **ready}, current)
    assert payload["reopen_locators"] == ["Лист!R2"]
    assert payload["research_operation_ids"] == ["missing"]
    assert payload["preserve_accepted"] is True and payload["repack"] is False
    assert current == before


@pytest.mark.asyncio
async def test_api_shared_anchor_retry_preserves_closed_sibling_and_exact_pending_scope(tmp_path, monkeypatch):
    store, original = baseline(tmp_path)
    conflict = original["accepted_rows"][1]
    monkeypatch.setattr(chat, "WorkbookResearchJobService", lambda: store)
    result = await chat.patch_lsr_rows(chat.LsrPatchRequest(session_id="same-session", job_id=original["job_id"],
        attachment_id="read_955-source", reopen_locators=[SOURCE], preserve_accepted=True,
        research_operation_ids=[conflict["operation_id"]], repack=False), _user=SimpleNamespace())
    current = result["job"]
    assert result["model_called"] is False
    assert current["accepted_rows"] == original["accepted_rows"]
    assert store.pending_research_operation_ids(current) == {conflict["operation_id"]}
    assert store.chat_review_context(current["job_id"])["prior_rows"] == [conflict]


@pytest.mark.asyncio
@pytest.mark.parametrize("guard", ["session", "attachment", "running", "unknown_operation"])
async def test_api_retry_refuses_foreign_or_active_state_without_losing_decisions(tmp_path, monkeypatch, guard):
    store, original = baseline(tmp_path)
    conflict = original["accepted_rows"][1]
    if guard == "running":
        store.reopen_locators(original["job_id"], [SOURCE], preserve_accepted=True,
                              operation_ids=[conflict["operation_id"]])
        store.begin_or_resume(identity(store))
    before = store.get(original["job_id"])
    monkeypatch.setattr(chat, "WorkbookResearchJobService", lambda: store)
    with pytest.raises(HTTPException) as failure:
        await chat.patch_lsr_rows(chat.LsrPatchRequest(
            session_id="other-chat" if guard == "session" else "same-session", job_id=original["job_id"],
            attachment_id="other-source" if guard == "attachment" else "read_955-source",
            reopen_locators=[SOURCE], preserve_accepted=True,
            research_operation_ids=["unknown" if guard == "unknown_operation" else conflict["operation_id"]],
            repack=False), _user=SimpleNamespace())
    assert failure.value.status_code == 409
    current = store.get(original["job_id"])
    assert current["accepted_rows"] == before["accepted_rows"]
    assert current["task_context"] == before["task_context"]


def test_scheduler_treats_only_pending_research_sources_as_unsettled(tmp_path):
    store, original = baseline(tmp_path)
    conflict = original["accepted_rows"][1]
    catalog = AttachmentSourceCatalog(original_name="Разный ВОР.xlsx", sheets=(("Лист", 2),), rows=tuple(
        CatalogRow(locator=source, sheet=source.rsplit("!", 1)[0], excel_row=index,
                   values=("Авторская строка",), line=f"{source}: Авторская строка", numbers=())
        for index, source in enumerate([SOURCE, "Другой лист!R9"], start=1)))
    before = application.research_settled_source_keys(original["accepted_rows"], catalog, original)
    assert SOURCE in before
    current = store.reopen_locators(original["job_id"], [SOURCE], preserve_accepted=True,
                                   operation_ids=[conflict["operation_id"]])
    after = application.research_settled_source_keys(current["accepted_rows"], catalog, current)
    assert after == before - {SOURCE}
    context = application.model_rag_research_target_context(current, [SOURCE])
    assert context["research_target_operation_ids"] == [conflict["operation_id"]]
    assert context["research_target_source_rows"] == [SOURCE]
    assert application.model_rag_research_target_context(current, ["Другой лист!R9"]) == {}
