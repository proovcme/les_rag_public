"""Repack consumes saved document targets; no missing-file LSR default for jobs."""

import copy

import pytest

from proxy.routers import chat
from proxy.services import attachment_source_catalog_service


ROW = {"source_row": "S!R2", "row_role": "material", "title": "Literal item",
       "unit": "m", "quantity": 12, "resource_code": "literal-resource", "norm_code": ""}
MIXED = "Составь ВОР по документу, чтобы потом подготовить смету"


def _boundary(monkeypatch, *, context=None, document=None):
    job = {
        "job_id": "own-job", "status": "complete", "accepted_rows": [copy.deepcopy(ROW)],
        "remaining": [], "identity": {"attachment_id": "read_123456abcdef"},
        "task_context": {"original_question": MIXED, "artifact_intent": "both", **(context or {})},
        # Producer sets a default tool even when it has never produced a file.
        "document": {"tool": "build_lsr_workbook", "final_revision_id": "", "draft_revision_id": "",
                     **(document or {})},
    }
    calls = []
    records = []

    class Store:
        def get(self, job_id):
            assert job_id == job["job_id"]
            return copy.deepcopy(job)

        def list_events(self, job_id):
            return []

        def record_packaging(self, job_id, **kwargs):
            records.append(copy.deepcopy(kwargs))

        def document_state(self, job_id):
            return {"state": "ready", "final_revision_id": "rebuilt-revision"}

    async def execute(call, request_context, progress):
        calls.append((copy.deepcopy(call), copy.deepcopy(request_context)))
        return {"schema": "les.workbook_tool_result.v1", "status": "complete", "artifact": {
            "revision_id": "rebuilt-revision", "download_url": "/api/artifacts/rebuilt-revision/download",
            "artifact_kind": "vor_workbook" if call["tool"] == "build_vor_workbook" else "lsr_workbook",
            "decision_checkpoint_id": "own-checkpoint", "source_scope": ["attachment:read_123456abcdef"],
        }, "source": {"attachment_id": "read_123456abcdef"},
            "checkpoint": {"checkpoint_id": "own-checkpoint", "status": "complete"}}

    monkeypatch.setattr(chat, "WorkbookResearchJobService", Store)
    monkeypatch.setattr(chat, "_execute_chat_workbook_tool", execute)
    monkeypatch.setattr(chat, "run_chat_evidence_application", lambda *a, **kw: pytest.fail("repack called model"))
    monkeypatch.setattr(attachment_source_catalog_service, "load_catalog_from_attachment_id", lambda *a: None)
    return job, calls, records


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["vor", "lsr"])
async def test_missing_file_repack_uses_saved_literal_model_target(monkeypatch, kind):
    job, calls, records = _boundary(monkeypatch, context={
        "model_artifact_kind": kind, "artifact_kind_status": "declared",
    })
    original = copy.deepcopy(job)

    result = await chat.repack_lsr_without_model(chat.LsrRepackRequest(
        session_id="own-session", job_id=job["job_id"], question="Продолжи"), _user={})

    assert result["model_called"] is False
    assert len(calls) == len(records) == 1
    call, _ = calls[0]
    assert call["tool"] == records[0]["tool"] == f"build_{kind}_workbook"
    assert call["args"]["decisions"] == original["accepted_rows"]
    assert job == original


@pytest.mark.asyncio
@pytest.mark.parametrize("context", [
    {},
    {"artifact_kind_status": "conflict", "model_artifact_kind": "", "artifact_intent": "lsr"},
    {"artifact_kind_status": "invalid", "model_artifact_kind": "", "artifact_intent": "vor"},
    {"artifact_kind_status": "declared", "model_artifact_kind": "unknown"},
])
async def test_missing_file_unresolved_target_is_visible_409_before_executor(monkeypatch, context):
    job, calls, records = _boundary(monkeypatch, context=context)
    original = copy.deepcopy(job)

    with pytest.raises(chat.HTTPException) as error:
        await chat.repack_lsr_without_model(chat.LsrRepackRequest(
            session_id="own-session", job_id=job["job_id"], question="Собери ЛСР"), _user={})

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "ARTIFACT_KIND_UNRESOLVED"
    assert error.value.detail["packaging_status"] == "pending"
    assert error.value.detail["model_called"] is False
    assert not calls and not records
    assert job == original


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["vor", "lsr"])
async def test_legacy_saved_pure_target_is_preserved_without_a_model_declaration(monkeypatch, kind):
    job, calls, _ = _boundary(monkeypatch, context={"artifact_intent": kind})

    result = await chat.repack_lsr_without_model(chat.LsrRepackRequest(
        session_id="own-session", job_id=job["job_id"]), _user={})

    assert result["model_called"] is False and len(calls) == 1
    assert calls[0][0]["tool"] == f"build_{kind}_workbook"


@pytest.mark.asyncio
@pytest.mark.parametrize("revision_field", ["final_revision_id", "draft_revision_id"])
async def test_actual_saved_lsr_artifact_keeps_its_tool_despite_new_context_target(monkeypatch, revision_field):
    job, calls, _ = _boundary(monkeypatch, context={
        "artifact_kind_status": "conflict", "model_artifact_kind": "vor",
    }, document={revision_field: "immutable-existing-revision"})

    result = await chat.repack_lsr_without_model(chat.LsrRepackRequest(
        session_id="own-session", job_id=job["job_id"], question="Составь ВОР"), _user={})

    assert result["model_called"] is False and len(calls) == 1
    assert calls[0][0]["tool"] == "build_lsr_workbook"


@pytest.mark.asyncio
async def test_jobless_legacy_repack_keeps_lsr_default(monkeypatch):
    _, calls, records = _boundary(monkeypatch)

    result = await chat.repack_lsr_without_model(chat.LsrRepackRequest(
        session_id="own-session", attachment_id="read_123456abcdef", decisions=[copy.deepcopy(ROW)]), _user={})

    assert result["model_called"] is False and len(calls) == 1 and not records
    assert calls[0][0]["tool"] == "build_lsr_workbook"
    assert calls[0][0]["args"]["decisions"] == [ROW]
