"""Repack consumes saved document targets; no missing-file LSR default for jobs."""

import copy
import hashlib
import json

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


async def _actual_unpacked_job(tmp_path, monkeypatch):
    from proxy.services.lsr_workbook_adapter_service import requested_price_basis
    from proxy.services.workbook_research_job_service import WorkbookResearchJobService
    from test_model_rag_sheet_evidence_reads import _run_sheet

    run = await _run_sheet(tmp_path, monkeypatch, reads=True, malformed_first_packet=True)
    source = WorkbookResearchJobService().get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
    # A distinct, test-owned store starts before its first file, like the saved
    # production job. Its initial basis has only the user's region and period.
    store = WorkbookResearchJobService(tmp_path / "unpacked-jobs.sqlite")
    identity = store.identity(**{key: source["identity"][key] for key in (
        "session_id", "attachment_id", "source_sha256", "dataset_ids", "profile_revision_id", "model_identity")},
        question=source["task_context"]["original_question"])
    job = store.begin_or_resume(identity, task_context={
        "original_question": source["task_context"]["original_question"], "artifact_intent": "lsr",
        "price_basis": requested_price_basis(source["task_context"]["original_question"]),
    })
    store.record_packet(job["job_id"], sheet="S", packet_locators=["S!R2", "S!R3"],
        accepted_rows=source["accepted_rows"], evidence=source["evidence"], remaining=["S!R2"])
    store.pause(job["job_id"], remaining=["S!R2"])
    monkeypatch.setattr(chat, "WorkbookResearchJobService", lambda: store)
    request = chat.LsrRepackRequest(job_id=job["job_id"], session_id=identity.session_id,
        attachment_id=identity.attachment_id, dataset_ids=list(identity.dataset_ids),
        profile_revision_id=identity.profile_revision_id, model_identity=identity.model_identity)
    return run, store, identity, request


@pytest.mark.asyncio
async def test_actual_empty_question_repack_reuses_first_revision_and_pinned_prices(tmp_path, monkeypatch):
    run, store, _, request = await _actual_unpacked_job(tmp_path, monkeypatch)
    before = store.get(request.job_id)
    model_calls = len(run.requests)
    assert request.question == "" and not before["document"]["draft_revision_id"]
    assert not before["task_context"]["price_basis"].get("pricebook")

    first = await chat.repack_lsr_without_model(request, _user={})
    replay = await chat.repack_lsr_without_model(request, _user={})
    third = await chat.repack_lsr_without_model(request, _user={})

    for field in ("revision_id", "decision_checkpoint_id", "sha256"):
        assert replay["result"]["artifact"][field] == first["result"]["artifact"][field]
        assert third["result"]["artifact"][field] == first["result"]["artifact"][field]
    assert replay["result"]["price_basis"] == first["result"]["price_basis"]
    assert len(first["result"]["price_basis"]["pricebook_sha256"]) == 64
    assert replay["result"]["document_issues"] == first["result"]["document_issues"]
    assert first["result"]["status"] == replay["result"]["status"] == "partial"
    assert first["result"]["preliminary_amount"] == replay["result"]["preliminary_amount"] == 600
    assert first["result"]["confirmed_amount"] == replay["result"]["confirmed_amount"] == 0
    assert first["model_called"] is replay["model_called"] is False
    assert len(run.requests) == model_calls
    after = store.get(request.job_id)
    for field in ("status", "accepted_rows", "remaining", "operator_overrides", "unapplied_proposals"):
        assert after[field] == before[field]
    snapshot = store.list_events(request.job_id, "workbook_packaged")[-1]["payload"]["repack_request"]
    assert snapshot["arguments"]["decisions"] == before["accepted_rows"]
    assert not snapshot["arguments"]["document_price_basis"]["pricebook"]
    assert snapshot["price_basis"]["pricebook_sha256"] == first["result"]["price_basis"]["pricebook_sha256"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["decisions", "confirmed_data", "issues", "profile"])
async def test_actual_changed_repack_inputs_do_not_reuse_the_previous_calculation(tmp_path, monkeypatch, change):
    run, store, _, request = await _actual_unpacked_job(tmp_path, monkeypatch)
    before = store.get(request.job_id)
    model_calls = len(run.requests)
    first = await chat.repack_lsr_without_model(request, _user={})
    updated = request.model_copy(deep=True)
    if change == "decisions":
        updated.decisions = copy.deepcopy(before["accepted_rows"])
        updated.decisions[0]["quantity"] = 4
    elif change == "confirmed_data":
        updated.confirmed_data = {"S!R3": {"row_role": "material", "confirmed_price": 250,
                                         "price_source": "owned operator confirmation"}}
    elif change == "issues":
        store.pause(request.job_id, remaining=["S!R2", "S!R4"])
    else:
        updated.profile_revision_id = "changed-owned-profile"

    changed = await chat.repack_lsr_without_model(updated, _user={})

    assert changed["result"]["artifact"]["revision_id"] != first["result"]["artifact"]["revision_id"]
    assert changed["result"]["artifact"]["decision_checkpoint_id"] != first["result"]["artifact"]["decision_checkpoint_id"]
    assert changed["result"]["confirmed_amount"] == 0
    if change == "decisions":
        # A new quantity contrary to the literal attachment stays an open gap,
        # rather than reusing the previous 600 or silently pricing four units.
        assert changed["result"]["preliminary_amount"] == 0
        assert "row:S!R3:unconfirmed_quantity" in changed["result"]["missing"]
        assert changed["result"]["row_projection"][0]["status"] == "unconfirmed_quantity"
    elif change == "confirmed_data":
        assert changed["result"]["preliminary_amount"] == 750
    elif change == "issues":
        assert changed["result"]["document_issues"][0]["remaining_locators"] == ["S!R2", "S!R4"]
    assert store.get(request.job_id)["accepted_rows"] == before["accepted_rows"]
    assert len(run.requests) == model_calls and changed["model_called"] is False


@pytest.mark.asyncio
async def test_actual_explicit_new_price_basis_creates_revision_with_its_own_pin(tmp_path, monkeypatch):
    from proxy.services import fgis_price_service
    from test_model_rag_sheet_evidence_reads import BOOK, RESOURCE_A, RESOURCE_B

    run, store, identity, request = await _actual_unpacked_job(tmp_path, monkeypatch)
    first = await chat.repack_lsr_without_model(request, _user={})
    old_book = fgis_price_service.get_pricebook(BOOK + ".json")
    new_name = "sankt-peterburg_4kv2026"
    prices = [{"code": RESOURCE_A, "name": "Cable A", "unit": "m", "price_current": 110},
              {"code": RESOURCE_B, "name": "Cable B", "unit": "m", "price_current": 250}]
    new_book = fgis_price_service.PriceBook(prices, region="Санкт-Петербург", quarter="4 квартал 2026 г.")
    new_book.source_sha256 = hashlib.sha256(json.dumps(prices, sort_keys=True).encode()).hexdigest()
    monkeypatch.setattr(fgis_price_service, "available_pricebooks", lambda *a, **kw: [BOOK + ".json", new_name + ".json"])

    def resolve(selected=None, **kwargs):
        assert kwargs.get("explicit_only") is True
        assert selected in {BOOK, new_name}
        return selected + ".json"

    monkeypatch.setattr(fgis_price_service, "resolve_pricebook_path", resolve)
    monkeypatch.setattr(fgis_price_service, "get_pricebook", lambda name: new_book if new_name in str(name) else old_book)
    store.begin_or_resume(identity, task_context={"price_basis": {"pricebook": new_name,
        "region": "Санкт-Петербург", "quarter": "4 квартал 2026",
        "pricebook_sha256": new_book.source_sha256}})
    store.pause(request.job_id, remaining=["S!R2"])
    model_calls = len(run.requests)

    changed = await chat.repack_lsr_without_model(request, _user={})

    assert changed["result"]["artifact"]["revision_id"] != first["result"]["artifact"]["revision_id"]
    assert changed["result"]["artifact"]["decision_checkpoint_id"] != first["result"]["artifact"]["decision_checkpoint_id"]
    assert changed["result"]["price_basis"]["actual_book"] == new_name
    assert changed["result"]["price_basis"]["pricebook_sha256"] == new_book.source_sha256
    assert changed["result"]["price_basis"]["pricebook_sha256"] != first["result"]["price_basis"]["pricebook_sha256"]
    # Existing model price evidence belongs to the old book; changing the basis
    # must not silently certify it as evidence for the new bytes.
    assert changed["result"]["confirmed_amount"] == 0
    assert changed["model_called"] is False and len(run.requests) == model_calls


@pytest.mark.parametrize("incoming", [{"pricebook": "new-book"},
    {"pricebook": "old-book", "pricebook_sha256": "b" * 64}])
def test_explicit_task_book_or_hash_is_not_overridden_by_old_document_provenance(incoming):
    from proxy.services.chat_evidence_application_service import task_document_price_basis

    previous = {"pricebook": "old-book", "pricebook_sha256": "a" * 64,
                "region": "Санкт-Петербург", "quarter": "3 квартал 2026", "revision_id": "old-revision"}
    effective = task_document_price_basis({"task_context": {"price_basis": incoming}}, previous)
    assert effective["pricebook"] == incoming["pricebook"]
    assert effective.get("pricebook_sha256") == incoming.get("pricebook_sha256")


@pytest.mark.parametrize("corruption", ["unknown_schema", "missing_args", "missing_pin", "unknown_source",
    "changed_pin", "changed_decision", "missing_overlay", "newer_event"])
def test_incomplete_or_superseded_server_snapshot_does_not_replay(corruption):
    from proxy.services.chat_evidence_application_service import workbook_repack_replay_arguments

    basis = {"pricebook": "owned-book", "pricebook_sha256": "a" * 64}
    current_arguments = {"attachment_id": "read_123456abcdef", "question": "", "decisions": [copy.deepcopy(ROW)],
                         "confirmed_data": {}}
    payload = {"tool": "build_lsr_workbook", "revision_id": "owned-revision", "repack_request": {
        "schema": "les.workbook-repack-request.v1", "request_identity": "request-hash", "source_sha256": "c" * 64,
        "arguments": copy.deepcopy(current_arguments),
        "price_basis": copy.deepcopy(basis)}}
    events = [{"event_type": "workbook_packaged", "payload": payload}]
    source_sha = "c" * 64
    if corruption == "unknown_schema":
        payload["repack_request"]["schema"] = "unknown"
    elif corruption == "missing_args":
        payload["repack_request"].pop("arguments")
    elif corruption == "missing_pin":
        payload["repack_request"]["price_basis"].pop("pricebook_sha256")
    elif corruption == "unknown_source":
        source_sha = ""
    elif corruption == "changed_pin":
        basis["pricebook_sha256"] = "b" * 64
    elif corruption == "changed_decision":
        payload["repack_request"]["arguments"]["decisions"][0]["quantity"] = 99
    elif corruption == "missing_overlay":
        payload["repack_request"]["arguments"].pop("confirmed_data")
    else:
        events.append({"event_type": "workbook_packaged", "payload": {"tool": "build_lsr_workbook", "revision_id": "newer"}})
    assert workbook_repack_replay_arguments(events, tool="build_lsr_workbook", request_identity="request-hash",
        source_sha256=source_sha, document_price_basis=basis, current_arguments=current_arguments) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", ["file", "checkpoint"])
async def test_missing_actual_cache_never_rebuilds_first_unpinned_args_with_new_book_bytes(tmp_path, monkeypatch, unavailable):
    from backend.runtime_paths import mutable_path
    from proxy.services import fgis_price_service, workflow_checkpoint_service
    from proxy.services.artifact_revision_service import ArtifactRevisionStore
    from test_model_rag_sheet_evidence_reads import BOOK, RESOURCE_A, RESOURCE_B

    run, store, _, request = await _actual_unpacked_job(tmp_path, monkeypatch)
    first = await chat.repack_lsr_without_model(request, _user={})
    original_rows = copy.deepcopy(store.get(request.job_id)["accepted_rows"])
    pin = first["result"]["price_basis"]["pricebook_sha256"]
    model_calls = len(run.requests)
    prices = [{"code": RESOURCE_A, "name": "Cable A", "unit": "m", "price_current": 110},
              {"code": RESOURCE_B, "name": "Cable B", "unit": "m", "price_current": 250}]
    replacement = fgis_price_service.PriceBook(prices, region="Санкт-Петербург", quarter="3 квартал 2026 г.")
    replacement.source_sha256 = hashlib.sha256(json.dumps(prices, sort_keys=True).encode()).hexdigest()
    assert replacement.source_sha256 != pin
    reads = []
    monkeypatch.setattr(fgis_price_service, "get_pricebook", lambda name: reads.append(name) or replacement)

    # A valid immutable cache remains its original calculation, even when the
    # currently installed same-name book has different bytes.
    cached = await chat.repack_lsr_without_model(request, _user={})
    assert cached["result"]["price_basis"]["pricebook_sha256"] == pin
    assert cached["result"]["artifact"]["revision_id"] == first["result"]["artifact"]["revision_id"]
    assert cached["result"]["preliminary_amount"] == 600 and not reads
    if unavailable == "file":
        artifacts = ArtifactRevisionStore(mutable_path("storage/artifacts/meta.db"), mutable_path("storage/artifacts/files"))
        path = artifacts.resolve_path(first["result"]["artifact"]["revision_id"]).resolve()
        assert tmp_path.resolve() in path.parents
        path.unlink()  # only the explicitly verified test-owned generated file
    else:
        real_store = workflow_checkpoint_service.WorkflowCheckpointService
        lost = real_store(tmp_path / "lost-checkpoints.sqlite")
        monkeypatch.setattr(workflow_checkpoint_service, "WorkflowCheckpointService", lambda _path: lost)

    with pytest.raises(chat.HTTPException) as error:
        await chat.repack_lsr_without_model(request, _user={})

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "WORKBOOK_REPACK_CACHE_UNAVAILABLE"
    assert error.value.detail["model_called"] is False
    assert not reads and len(run.requests) == model_calls
    assert store.get(request.job_id)["accepted_rows"] == original_rows
    assert store.get(request.job_id)["task_context"]["price_basis"]["pricebook_sha256"] == pin
