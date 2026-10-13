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


@pytest.mark.asyncio
@pytest.mark.parametrize("jobless", [False, True])
@pytest.mark.parametrize("missing_result", [False, True])
async def test_repack_rechecks_source_coverage_without_model_or_row_changes(monkeypatch, jobless, missing_result):
    job, calls, _ = _boundary(monkeypatch, context={"artifact_intent": "lsr"})
    module = attachment_source_catalog_service
    catalog = module.AttachmentSourceCatalog(original_name="literal.xlsx", sheets=(("S", 2),), rows=tuple(
        module.CatalogRow(locator=f"S!R{i}", sheet="S", excel_row=i, values=("Literal", "12"),
                          line=f"S!R{i}: Literal 12", numbers=(12.0,), row_classification="work")
        for i in (2, 3)))
    monkeypatch.setattr(module, "load_catalog_from_attachment_id", lambda *args: catalog)
    if not missing_result:
        job["accepted_rows"].append({**ROW, "source_row": "S!R3"})
    before = copy.deepcopy(job)
    request = chat.LsrRepackRequest(session_id="own-session", job_id="" if jobless else job["job_id"],
        attachment_id="read_123456abcdef", decisions=copy.deepcopy(job["accepted_rows"]) if jobless else [])
    result = await chat.repack_lsr_without_model(request, _user={})
    assert result["model_called"] is False and len(calls) == 1 and job == before
    call, context = calls[0]
    assert call["args"]["decisions"] == before["accepted_rows"]
    issues = context["document_issues"]
    assert bool(call["args"].get("draft")) is missing_result
    assert bool(issues) is missing_result
    if missing_result:
        assert any(issue["code"] == "MODEL_RESULT_SOURCE_ROWS_UNACCOUNTED"
                   and issue["remaining_locators"] == ["S!R3"] for issue in issues)


@pytest.mark.asyncio
async def test_repack_readiness_uses_verified_source_alias_and_keeps_unclassified_prose(monkeypatch):
    from proxy.services.lsr_source_coverage_service import operation_identity

    job, calls, _ = _boundary(monkeypatch, context={"artifact_intent": "lsr"})
    module = attachment_source_catalog_service
    catalog = module.AttachmentSourceCatalog(original_name="literal.pdf", source_file_id="src_repack_identity",
        sheets=(("PDF", 1), ("PDF_TEXT", 1)), rows=(
            module.CatalogRow(locator="PDF!R2", sheet="PDF", excel_row=2, values=("Literal item",),
                line="PDF!R2: Literal item", numbers=(), row_classification="ambiguous"),
            module.CatalogRow(locator="PDF_TEXT!R1", sheet="PDF_TEXT", excel_row=1, values=("Literal prose",),
                line="PDF_TEXT!R1: Literal prose", numbers=(), row_classification="ambiguous"),
        ))
    monkeypatch.setattr(module, "load_catalog_from_attachment_id", lambda *args: catalog)
    job["accepted_rows"] = [
        {"source_row": "src_repack_identity!R2", "row_role": "work", "evidence_refs": "Q2.H3"},
        {"source_row": "PDF!R2", "row_role": "material", "work_row": "src_repack_identity!R2"},
    ]
    before = copy.deepcopy(job)
    identities = [operation_identity(row) for row in job["accepted_rows"]]
    result = await chat.repack_lsr_without_model(chat.LsrRepackRequest(
        session_id="own-session", job_id=job["job_id"]), _user={})
    assert result["model_called"] is False and len(calls) == 1
    assert job == before
    assert calls[0][0]["args"]["decisions"] == before["accepted_rows"]
    assert [operation_identity(row) for row in job["accepted_rows"]] == identities
    assert any(issue["code"] == "MODEL_RESULT_SOURCE_ROWS_UNACCOUNTED"
               and issue["remaining_locators"] == ["PDF_TEXT!R1"]
               for issue in calls[0][1]["document_issues"])
    readiness = result["harvested"]["artifact"]["result_readiness"]
    assert readiness["coverage"]["accounted"] == 1
    assert readiness["coverage"]["gap_count"] == 1
    assert readiness["remaining_locators"] == ["PDF_TEXT!R1"]


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
    assert before["status"] == "paused"
    assert before["document"]["needs_document"] is True
    recovery = before["document_recovery"]
    assert recovery["action"] == "repack" and recovery["model_called"] is False
    assert recovery["job_id"] == request.job_id
    assert recovery["remaining"] == before["remaining"]
    assert recovery["decision_count"] == len(before["accepted_rows"])

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
    for field in ("status", "identity", "accepted_rows", "remaining", "operator_overrides", "unapplied_proposals"):
        assert after[field] == before[field]
    assert {k: v for k, v in after["task_context"].items() if k != "price_basis"} == {
        k: v for k, v in before["task_context"].items() if k != "price_basis"
    }
    assert after["task_context"]["price_basis"]["pricebook"] == first["result"]["price_basis"]["actual_book"]
    assert after["task_context"]["price_basis"]["pricebook_sha256"] == first["result"]["price_basis"]["pricebook_sha256"]
    assert after["document"]["draft_revision_id"] == first["result"]["artifact"]["revision_id"]
    assert after["document"]["final_revision_id"] == ""
    assert after["document"]["needs_document"] is False
    assert "document_recovery" not in after
    incomplete = next(issue for issue in first["result"]["document_issues"]
                      if issue["code"] == "WORKBOOK_RESEARCH_INCOMPLETE")
    assert incomplete["job_status"] == "paused"
    assert incomplete["remaining_locators"] == before["remaining"]
    # Readiness also includes the accepted but financially incomplete row.
    assert first["harvested"]["artifact"]["result_readiness"]["remaining_locators"] == ["S!R2", "S!R3"]
    snapshot = store.list_events(request.job_id, "workbook_packaged")[-1]["payload"]["repack_request"]
    assert snapshot["arguments"]["decisions"] == before["accepted_rows"]
    assert not snapshot["arguments"]["document_price_basis"]["pricebook"]
    assert snapshot["price_basis"]["pricebook_sha256"] == first["result"]["price_basis"]["pricebook_sha256"]


@pytest.mark.asyncio
# Author/profile is not a calculation override for unchanged saved decisions.
# Its previous "new revision" expectation allowed relabeling another model's
# decisions; conflicting provenance now has its own explicit 409 regression.
@pytest.mark.parametrize("change", ["decisions", "confirmed_data", "issues"])
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


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit_same", [False, True])
async def test_saved_repack_inherits_author_and_scope_without_relabeling(monkeypatch, explicit_same):
    job, calls, _ = _boundary(monkeypatch, context={"artifact_intent": "lsr"})
    job["identity"].update({"model_identity": "saved-model", "profile_revision_id": "saved-profile:r3",
                            "dataset_ids": ["saved-b", "saved-a"]})
    before = copy.deepcopy(job)
    supplied = {"model_identity": "saved-model", "profile_revision_id": "saved-profile:r3",
                "dataset_ids": ["saved-a", "saved-b", "saved-a"]} if explicit_same else {}
    request = chat.LsrRepackRequest(session_id="own-session", job_id=job["job_id"], **supplied)
    request_before = request.model_dump()

    result = await chat.repack_lsr_without_model(request, _user={})

    assert result["model_called"] is False and len(calls) == 1
    assert calls[0][1]["model_identity"] == "saved-model"
    assert calls[0][1]["profile_revision_id"] == "saved-profile:r3"
    assert calls[0][1]["dataset_ids"] == ["saved-b", "saved-a"]
    assert calls[0][1]["model_preset"] == ""  # The saved identity did not record a preset.
    assert calls[0][0]["args"]["decisions"] == before["accepted_rows"]
    assert job == before and request.model_dump() == request_before


@pytest.mark.asyncio
@pytest.mark.parametrize("supplied", [
    {"model_identity": "current-model"},
    {"profile_revision_id": "current-profile"},
    {"dataset_ids": ["saved-dataset", "another-dataset"]},
    {"dataset_ids": ["another-dataset"]},
])
async def test_saved_repack_rejects_conflicting_authorship_or_scope_before_executor(monkeypatch, supplied):
    job, calls, records = _boundary(monkeypatch, context={"artifact_intent": "lsr"})
    job["identity"].update({"model_identity": "saved-model", "profile_revision_id": "saved-profile:r3",
                            "dataset_ids": ["saved-dataset"]})
    before = copy.deepcopy(job)

    with pytest.raises(chat.HTTPException) as failure:
        await chat.repack_lsr_without_model(chat.LsrRepackRequest(
            session_id="own-session", job_id=job["job_id"], **supplied), _user={})

    assert failure.value.status_code == 409
    assert failure.value.detail["code"] == "REPACK_IDENTITY_MISMATCH"
    assert failure.value.detail["model_called"] is False
    assert failure.value.detail["fields"] == list(supplied)
    assert not calls and not records and job == before


@pytest.mark.asyncio
async def test_saved_repack_does_not_widen_an_explicitly_empty_saved_scope(monkeypatch):
    job, calls, _ = _boundary(monkeypatch, context={"artifact_intent": "lsr"})
    job["identity"]["dataset_ids"] = []
    with pytest.raises(chat.HTTPException) as failure:
        await chat.repack_lsr_without_model(chat.LsrRepackRequest(
            session_id="own-session", job_id=job["job_id"], dataset_ids=["new-dataset"]), _user={})
    assert failure.value.detail["fields"] == ["dataset_ids"]
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("jobless", [False, True])
async def test_explicit_new_decisions_keep_legacy_caller_metadata(monkeypatch, jobless):
    job, calls, _ = _boundary(monkeypatch, context={"artifact_intent": "lsr"})
    job["identity"].update({"model_identity": "old-model", "profile_revision_id": "old-profile",
                            "dataset_ids": ["old-dataset"]})
    before = copy.deepcopy(job)
    request = chat.LsrRepackRequest(session_id="own-session", job_id="" if jobless else job["job_id"],
        attachment_id="read_123456abcdef", decisions=[{**ROW, "quantity": 7}],
        model_identity="new-model", profile_revision_id="new-profile", dataset_ids=["new-dataset"])

    result = await chat.repack_lsr_without_model(request, _user={})

    assert result["model_called"] is False
    assert calls[0][1]["model_identity"] == "new-model"
    assert calls[0][1]["profile_revision_id"] == "new-profile"
    assert calls[0][1]["dataset_ids"] == ["new-dataset"]
    assert calls[0][0]["args"]["decisions"] == request.decisions
    assert job == before


@pytest.mark.asyncio
async def test_historical_job_without_identity_metadata_keeps_explicit_legacy_values(monkeypatch):
    job, calls, _ = _boundary(monkeypatch, context={"artifact_intent": "lsr"})
    result = await chat.repack_lsr_without_model(chat.LsrRepackRequest(
        session_id="own-session", job_id=job["job_id"], model_identity="caller-model",
        profile_revision_id="caller-profile", dataset_ids=["caller-dataset"]), _user={})
    assert result["model_called"] is False
    assert calls[0][1]["model_identity"] == "caller-model"
    assert calls[0][1]["profile_revision_id"] == "caller-profile"
    assert calls[0][1]["dataset_ids"] == ["caller-dataset"]


@pytest.mark.asyncio
async def test_actual_job_only_repack_records_saved_provenance_and_replays_same_revision(tmp_path, monkeypatch):
    from proxy.services.artifact_revision_service import ArtifactRevisionStore
    from backend.runtime_paths import mutable_path

    run, store, identity, explicit = await _actual_unpacked_job(tmp_path, monkeypatch)
    request = explicit.model_copy(update={"dataset_ids": [], "profile_revision_id": "", "model_identity": ""})
    before = store.get(request.job_id)
    model_calls = len(run.requests)

    first = await chat.repack_lsr_without_model(request, _user={})
    replay = await chat.repack_lsr_without_model(explicit, _user={})
    again = await chat.repack_lsr_without_model(request, _user={})

    revision_id = first["result"]["artifact"]["revision_id"]
    artifact = ArtifactRevisionStore(mutable_path("storage/artifacts/meta.db"),
        mutable_path("storage/artifacts/files")).get_revision(revision_id)
    assert artifact.model_identity == identity.model_identity
    assert artifact.profile_revision_id == identity.profile_revision_id
    assert artifact.model_preset == "unknown"
    assert list(artifact.source_scope) == [f"attachment:{identity.attachment_id}"] + [
        f"dataset:{dataset_id}" for dataset_id in identity.dataset_ids]
    for response in (replay, again):
        for field in ("revision_id", "decision_checkpoint_id", "sha256"):
            assert response["result"]["artifact"][field] == first["result"]["artifact"][field]
        assert response["result"]["price_basis"] == first["result"]["price_basis"]
        assert response["model_called"] is False
    assert len(run.requests) == model_calls
    after = store.get(request.job_id)
    for field in ("identity", "accepted_rows", "remaining", "unapplied_proposals", "operator_overrides"):
        assert after[field] == before[field]
