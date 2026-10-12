"""Connection revisions belong to durable identity and actual model calls."""
from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as application
from proxy.services.chat_attachment_service import resolve_read_attachment
from proxy.services.model_connection_contracts import ConnectionRole
from proxy.services.workbook_research_job_service import WorkbookResearchJobError, WorkbookResearchJobService


def _identity(store, question="Собери документ", revision=None, **changes):
    fields = dict(session_id="s", attachment_id="read_123456abcdef", source_sha256="a" * 64,
                  dataset_ids=["selected"], profile_revision_id="profile:1", model_identity="same-model",
                  question=question)
    if revision is not None:
        fields["model_connection_revision_id"] = revision
    fields.update(changes)
    return store.identity(**fields)


def _seed(store, identity):
    job = store.begin_or_resume(identity, source_locators=["S!R2"], task_context={
        "original_question": "Собери документ, Москва, 3 квартал 2026",
        "price_basis": {"region": "Москва", "quarter": "3 квартал 2026"},
    })
    store.record_packet(job["job_id"], sheet="S", packet_locators=["S!R2"],
        accepted_rows=[{"source_row": "S!R2", "row_role": "work", "title": "Literal model decision"}],
        evidence=[{"global_evidence_id": "old-card", "content": "Old literal evidence"}], remaining=[])
    store.record_search_cache(job["job_id"], {"old query": [{"content": "old scoped hit"}]})
    return store.pause(job["job_id"], remaining=[])


def _rows(store):
    with sqlite3.connect(store.db_path) as connection:
        return connection.execute("SELECT * FROM workbook_research_jobs ORDER BY rowid").fetchall()


def test_empty_connection_binding_keeps_legacy_payload_hash_and_resume(tmp_path):
    store = WorkbookResearchJobService(tmp_path / "legacy.sqlite")
    legacy = _identity(store)
    expected = dict(session_id="s", attachment_id="read_123456abcdef", source_sha256="a" * 64,
                    dataset_ids=("selected",), profile_revision_id="profile:1", model_identity="same-model",
                    question_sha256=hashlib.sha256("Собери документ".encode("utf-8")).hexdigest())
    assert legacy.payload() == expected
    assert legacy.digest() == hashlib.sha256(json.dumps(
        expected, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    explicit_empty = _identity(store, revision="")
    assert explicit_empty.payload() == legacy.payload() and explicit_empty.digest() == legacy.digest()
    first = _seed(store, legacy)
    before = _rows(store)
    resumed = store.begin_or_resume(explicit_empty)
    assert resumed["job_id"] == first["job_id"] and resumed["accepted_rows"] == first["accepted_rows"]
    assert len(_rows(store)) == len(before)


@pytest.mark.parametrize("revision", ["conn:answer:r9", "conn:other-provider:r8", ""])
def test_new_full_task_in_other_connection_never_inherits_same_named_model(tmp_path, revision):
    store = WorkbookResearchJobService(tmp_path / "providers.sqlite")
    first = _seed(store, _identity(store, revision="conn:answer:r8"))
    old_rows = _rows(store)

    fresh = store.begin_or_resume(_identity(store, question="Новое полное задание", revision=revision))

    assert fresh["continues_job_id"] == ""
    assert fresh["accepted_rows"] == [] and fresh["evidence"] == [] and fresh["query_cache"] == {}
    assert fresh["task_context"] == {}
    assert _rows(store)[0] == old_rows[0]
    assert store.get(first["job_id"])["accepted_rows"] == first["accepted_rows"]


@pytest.mark.parametrize("changes", [
    {"dataset_ids": ["other"]}, {"profile_revision_id": "profile:2"}, {"model_identity": "other-model"},
])
def test_plain_continuation_rejects_changed_context_atomically(tmp_path, changes):
    store = WorkbookResearchJobService(tmp_path / "context.sqlite")
    _seed(store, _identity(store))
    before = _rows(store)

    with pytest.raises(WorkbookResearchJobError, match="^WORKBOOK_CONTINUATION_CONTEXT_CHANGED$"):
        store.begin_or_resume(_identity(store, question="Продолжи", **changes),
                              task_context={"original_question": "Продолжи"})

    assert _rows(store) == before


@pytest.mark.parametrize("old_revision,new_revision", [
    ("conn:answer:r8", "conn:answer:r9"), ("conn:answer:r8", "conn:other-provider:r8"),
    (None, "conn:answer:r8"), ("conn:answer:r8", ""),
])
def test_plain_continuation_never_backfills_legacy_or_changes_connection(tmp_path, old_revision, new_revision):
    store = WorkbookResearchJobService(tmp_path / "context.sqlite")
    _seed(store, _identity(store, revision=old_revision))
    before = _rows(store)

    with pytest.raises(WorkbookResearchJobError, match="^WORKBOOK_CONTINUATION_CONTEXT_CHANGED$"):
        store.begin_or_resume(_identity(store, question="Продолжи", revision=new_revision),
                              task_context={"original_question": "Продолжи"})

    assert _rows(store) == before


@pytest.mark.parametrize("question", ["Уточни условия", "Продолжи"])
def test_same_exact_connection_continuation_keeps_task_prices_and_checkpoint(tmp_path, question):
    store = WorkbookResearchJobService(tmp_path / "context.sqlite")
    first = _seed(store, _identity(store, revision="conn:answer:r8"))
    original = _rows(store)[0]
    continued = store.begin_or_resume(_identity(store, question=question, revision="conn:answer:r8"),
                                     task_context={"original_question": question})

    assert continued["continues_job_id"] == first["job_id"]
    for field in ("accepted_rows", "evidence", "query_cache", "task_context"):
        assert continued[field] == first[field]
    assert _rows(store)[0] == original


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.parametrize("reads", [False, True])
async def test_actual_queries_repair_answer_and_receipts_keep_resolved_revision(tmp_path, monkeypatch, variant, reads):
    from tests.test_model_rag_sheet_evidence_reads import _run_sheet
    original = application.BoundModelChatRunner.complete
    calls = []

    async def complete(self, *args, **kwargs):
        calls.append(kwargs.get("expected_connection_revision_id", ""))
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(application.BoundModelChatRunner, "complete", complete)
    run = await _run_sheet(tmp_path, monkeypatch, reads=reads, query_repair=True, variant=variant)

    assert calls and all(value == "conn:sheet:r1" for value in calls)
    trace = run.result["retrieval_trace"]
    actual = trace["actual_model_calls"]["calls"]
    assert actual and all(call["model_connection_revision_id"] == "conn:sheet:r1" for call in actual)
    assert any("repair" in call["purpose"] for call in actual)
    if variant == "B1_CANDIDATE":
        job = WorkbookResearchJobService().get(trace["workbook_research_job"]["job_id"])
        assert job["identity"]["model_connection_revision_id"] == "conn:sheet:r1"


@pytest.mark.asyncio
async def test_role_revision_changes_with_same_model_are_rejected_before_query_transport(tmp_path, monkeypatch):
    from tests.test_model_rag_sheet_evidence_reads import _run_sheet
    original = application.BoundModelChatRunner.complete
    changed = False
    transport_calls = []

    async def complete(self, *args, **kwargs):
        nonlocal changed
        if not changed:
            connection = self.resolver.resolve(ConnectionRole.ANSWER)
            connection.revision_id = "conn:sheet:r9"
            changed = True
            original_transport = self.transport.complete

            async def transport(*args, **kwargs):
                transport_calls.append(True)
                return await original_transport(*args, **kwargs)

            self.transport.complete = transport
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(application.BoundModelChatRunner, "complete", complete)
    with pytest.raises(application.HTTPException) as failure:
        await _run_sheet(tmp_path, monkeypatch, reads=False)
    assert failure.value.status_code == 502
    assert "TOKEN_COUNT_CONNECTION_CHANGED" in failure.value.detail
    assert changed and not transport_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("prior_revision", ["", "conn:sheet:r8"])
async def test_plain_legacy_continuation_fails_before_first_model_call(tmp_path, monkeypatch, prior_revision):
    from tests.test_model_rag_sheet_evidence_reads import _run_sheet
    original_application = application.run_chat_evidence_application
    captured = {}

    class Store(WorkbookResearchJobService):
        def __init__(self, *args, **kwargs):
            super().__init__(tmp_path / "guard.sqlite")

    monkeypatch.setattr(application, "WorkbookResearchJobService", Store)

    async def invoke(request, runtime, boundary):
        _path, metadata = resolve_read_attachment(request.req.attachment_id, root=tmp_path / "attachments")
        store = Store()
        prior_identity = store.identity(
            session_id=request.req.session_id, attachment_id=request.req.attachment_id,
            source_sha256=metadata["sha256"], dataset_ids=request.dataset_ids,
            profile_revision_id=request.profile_snapshot["revision_id"], model_identity="fixture-model",
            question="Исходное полное задание",
            model_connection_revision_id=prior_revision,
        )
        prior = _seed(store, prior_identity)
        captured.update(store=store, before=_rows(store), prior=copy.deepcopy(prior))
        req = SimpleNamespace(**{**vars(request.req), "question": "Продолжи"})
        return await original_application(replace(request, req=req), runtime, boundary)

    async def no_model(*args, **kwargs):
        pytest.fail("incompatible plain continuation reached the model before its scope guard")

    monkeypatch.setattr(application, "run_chat_evidence_application", invoke)
    monkeypatch.setattr(application.BoundModelChatRunner, "complete", no_model)
    with pytest.raises(application.HTTPException) as failure:
        await _run_sheet(tmp_path, monkeypatch, reads=False)
    assert failure.value.status_code == 409
    assert failure.value.detail["code"] == "WORKBOOK_CONTINUATION_CONTEXT_CHANGED"
    assert _rows(captured["store"]) == captured["before"]
