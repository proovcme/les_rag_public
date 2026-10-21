"""A new calculator contract must refresh saved LSR observations, without inference."""
from copy import deepcopy

import pytest

from proxy.routers import chat
from proxy.services import chat_evidence_application_service as app
from proxy.services import version_service
from proxy.services.trusted_executor_service import ExecutionEnvelope, TrustedExecutor
from tests.test_workbook_repack_target import ROW, _boundary


@pytest.mark.asyncio
@pytest.mark.parametrize("projection", [[], [{
    "operation_id": "literal-supply-operation", "locator": "S!R2",
    "row_role": "material", "status": "bound", "position_calculated": False,
    "open_reasons": ["supply_resource_match_unsubstantiated"],
}]])
async def test_repack_records_the_exact_calculator_projection_even_when_empty(monkeypatch, projection):
    job, calls, records = _boundary(monkeypatch, context={"artifact_intent": "lsr"},
                                   document={"final_revision_id": "old-closed-revision"})
    previous_execute = chat._execute_chat_workbook_tool

    async def execute(*args, **kwargs):
        payload = await previous_execute(*args, **kwargs)
        payload["row_projection"] = deepcopy(projection)
        return payload

    monkeypatch.setattr(chat, "_execute_chat_workbook_tool", execute)
    before = deepcopy(job)

    result = await chat.repack_lsr_without_model(
        chat.LsrRepackRequest(session_id="own-session", job_id=job["job_id"]), _user={})

    assert result["model_called"] is False and len(calls) == len(records) == 1
    assert result["result"]["row_projection"] == projection
    assert records[0].get("financial_projection") == projection
    assert job == before and calls[0][0]["args"]["decisions"] == before["accepted_rows"]


@pytest.mark.parametrize("saved_version", [None, "older-calculator", "current-calculator"])
def test_repack_argument_replay_requires_the_current_calculator_contract(monkeypatch, saved_version):
    monkeypatch.setattr(version_service, "RESOURCE_CALC_VERSION", "current-calculator")
    basis = {"pricebook": "owned-book", "pricebook_sha256": "a" * 64}
    arguments = {"attachment_id": "read_123456abcdef", "question": "",
                 "decisions": [deepcopy(ROW)], "confirmed_data": {}}
    snapshot = {"schema": "les.workbook-repack-request.v1", "request_identity": "request-hash",
                "source_sha256": "c" * 64, "arguments": deepcopy(arguments),
                "price_basis": deepcopy(basis)}
    if saved_version is not None:
        snapshot["resource_calc_version"] = saved_version
    events = [{"event_type": "workbook_packaged", "payload": {
        "tool": "build_lsr_workbook", "revision_id": "owned-revision", "repack_request": snapshot}}]
    before = deepcopy(events)

    replay = app.workbook_repack_replay_arguments(
        events, tool="build_lsr_workbook", request_identity="request-hash", source_sha256="c" * 64,
        document_price_basis=basis, current_arguments=arguments)

    assert replay == (arguments if saved_version == "current-calculator" else None)
    assert events == before


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["build_lsr_workbook", "build_vor_workbook"])
async def test_execution_identity_versions_lsr_calculation_without_changing_decisions(
    tmp_path, monkeypatch, tool,
):
    # Stop only the executor's I/O boundary. Exercise the actual server-owned
    # identity and context construction; neither a model nor adapter is called.
    monkeypatch.setattr(chat, "mutable_path", lambda path: tmp_path / path)
    requests = []

    async def capture(_self, request):
        requests.append(request)
        return ExecutionEnvelope(schema="les.execution-envelope.v1", call_id=request.call_id,
            tool_name=request.tool_name, status="ok", code="OK", result={
                "schema": "les.workbook_tool_result.v1", "status": "complete"},
            cursor=None, omitted_items=0)

    monkeypatch.setattr(TrustedExecutor, "execute", capture)
    call = {"tool": tool, "args": {"attachment_id": "read_123456abcdef", "decisions": [deepcopy(ROW)]}}
    context = {"session_id": "same-session", "attachment_id": "read_123456abcdef", "dataset_ids": [],
               "profile_revision_id": "same-profile:r1", "model_identity": "same-model"}
    original = deepcopy(call)

    for version in ("older-calculator", "older-calculator", "current-calculator"):
        monkeypatch.setattr(version_service, "RESOURCE_CALC_VERSION", version)
        await chat._execute_chat_workbook_tool(call, context, None)

    assert len(requests) == 3
    assert requests[0].idempotency_key == requests[1].idempotency_key
    if tool == "build_lsr_workbook":
        assert requests[2].idempotency_key != requests[0].idempotency_key
    else:
        assert requests[2].idempotency_key == requests[0].idempotency_key
    assert all(dict(request.arguments)["decisions"] == original["args"]["decisions"] for request in requests)
    assert call == original


@pytest.mark.asyncio
async def test_actual_calculation_stamps_its_version_and_checkpoint_replay_keeps_that_version(tmp_path, monkeypatch):
    from proxy.services.workbook_tool_service import build_lsr_workbook
    from tests.test_workbook_tool_service import _attachment, _context, _source_workbook

    attachment = _attachment(tmp_path)
    args = {"attachment_id": attachment["attachment_id"], "decisions": [deepcopy(ROW)]}
    observed = []

    def adapter(_source, decisions, output, _progress):
        observed.append(deepcopy(decisions))
        _source_workbook(output)
        return {"file_path": output, "source_rows": 1, "row_projection": []}

    monkeypatch.setattr(version_service, "RESOURCE_CALC_VERSION", "original-calculator")
    context = _context(tmp_path, lsr_adapter=adapter)
    first = await build_lsr_workbook(args, context)
    revision = context.artifacts.get_revision(first["artifact"]["revision_id"])
    assert first.get("resource_calc_version") == "original-calculator"
    assert revision.tool_calls[-1]["calculation_snapshot"].get("resource_calc_version") == "original-calculator"

    # An explicit old checkpoint remains an immutable old calculation. The
    # server-owned ordinary route must use its new execution identity to rerun.
    monkeypatch.setattr(version_service, "RESOURCE_CALC_VERSION", "new-calculator")
    replay = await build_lsr_workbook(args, _context(tmp_path, lsr_adapter=adapter))

    assert len(observed) == 1
    assert replay["artifact"]["revision_id"] == first["artifact"]["revision_id"]
    assert replay.get("resource_calc_version") == "original-calculator"
    assert args["decisions"] == [ROW]


@pytest.mark.parametrize("tool,saved_version,needs_refresh", [
    ("build_lsr_workbook", None, True),
    ("build_lsr_workbook", "old-calculator", True),
    ("build_lsr_workbook", "current-calculator", False),
    ("build_vor_workbook", "old-calculator", False),
])
def test_document_projection_preserves_the_file_and_exposes_stale_calculation(
    monkeypatch, tool, saved_version, needs_refresh,
):
    from proxy.services.packaging_recovery_service import workbook_document_from_events

    monkeypatch.setattr(version_service, "RESOURCE_CALC_VERSION", "current-calculator")
    payload = {"tool": tool, "revision_id": "immutable-existing-file", "draft": False,
               "price_basis": {"actual_book": "owned-book", "pricebook_sha256": "a" * 64}}
    if saved_version is not None:
        payload["resource_calc_version"] = saved_version
    events = [{"event_type": "workbook_packaged", "sequence": 1, "payload": payload}]
    before = deepcopy(events)

    document = workbook_document_from_events(events, status="complete", accepted_row_count=2)

    assert document["final_revision_id"] == "immutable-existing-file"
    assert document["packaged"] is True
    assert document.get("calculation_refresh_required", False) is needs_refresh
    if tool == "build_lsr_workbook":
        assert document.get("resource_calc_version", "") == (saved_version or "")
    if needs_refresh:
        assert document["needs_document"] is True
        assert document["recovery_reason"]
        assert any(item["kind"] == "repack" for item in document["actions"])
    assert events == before


@pytest.mark.parametrize("needs_refresh", [False, True])
def test_terminal_ui_prioritizes_the_existing_repack_action_over_an_old_final(needs_refresh):
    from sovushka.pages import chat as chat_page

    job = {"job_id": "owned-job", "status": "complete", "document": {
        "state": "ready", "final_revision_id": "immutable-existing-file",
        "calculation_refresh_required": needs_refresh, "needs_document": needs_refresh,
        "recovery_reason": "После обновления требуется пересобрать файл без модели." if needs_refresh else ""}}
    before = deepcopy(job)

    plan = chat_page.terminal_job_repair_plan(job)

    assert plan["mode"] == ("repack" if needs_refresh else "document")
    assert plan["job_id"] == "owned-job"
    assert job == before


def test_stale_actual_job_keeps_calculation_refresh_through_reconnect_pending_projection(tmp_path, monkeypatch):
    from sovushka.pages import chat as chat_page
    from tests.test_workbook_gap_followup_955 import baseline

    monkeypatch.setattr(version_service, "RESOURCE_CALC_VERSION", "current-calculator")
    store, original = baseline(tmp_path)
    store.record_packaging(original["job_id"], tool="build_lsr_workbook", revision_id="immutable-old-final",
        draft=False, price_basis=original["task_context"]["price_basis"],
        resource_calc_version="old-calculator")
    job = store.get(original["job_id"])
    before = deepcopy(job)
    assert job["document"]["calculation_refresh_required"] is True
    assert job["document"]["resource_calc_version"] == "old-calculator"

    pending = chat_page.workbook_job_to_pending_progress(job)

    assert pending["document"].get("calculation_refresh_required") is True
    assert pending["document"].get("resource_calc_version") == "old-calculator"
    assert pending["document"]["final_revision_id"] == "immutable-old-final"
    assert chat_page.terminal_job_repair_plan(pending)["mode"] == "repack"
    assert job == before


@pytest.mark.parametrize("saved_version", [None, "old-calculator", "current-calculator"])
def test_plain_continue_requires_technical_refresh_of_inherited_stale_lsr_before_reopen(
    tmp_path, monkeypatch, saved_version,
):
    from tests.test_plain_lsr_gap_continuation_976 import _child, _continue
    from tests.test_workbook_gap_followup_955 import baseline

    monkeypatch.setattr(version_service, "RESOURCE_CALC_VERSION", "current-calculator")
    store, original = baseline(tmp_path)
    real_append = store._append_event

    def append_saved_event(conn, job_id, event_type, payload):
        if event_type == "workbook_packaged":
            payload = deepcopy(payload)
            # Simulate bytes persisted by an older installed calculator, using
            # the existing event boundary rather than a new public API or SQL.
            for holder in (payload, payload.get("financial_feedback")):
                if isinstance(holder, dict):
                    holder.pop("resource_calc_version", None)
                    if saved_version is not None:
                        holder["resource_calc_version"] = saved_version
        return real_append(conn, job_id, event_type, payload)

    monkeypatch.setattr(store, "_append_event", append_saved_event)
    store.record_packaging(original["job_id"], tool="build_lsr_workbook", revision_id="issued-parent-file",
        draft=False, price_basis=original["task_context"]["price_basis"], financial_projection=[])
    requested, child = _child(store)
    before = deepcopy(child)
    events_before = store.list_events(child["job_id"])

    if saved_version != "current-calculator":
        def forbidden(*_args, **_kwargs):
            pytest.fail("a stale calculator observation must be refreshed before professional research")

        monkeypatch.setattr(store, "reopen_locators", forbidden)
        with pytest.raises(app.HTTPException) as error:
            _continue(store, child, requested)
        assert error.value.status_code == 409
        assert error.value.detail["code"] == "LSR_CALCULATION_REFRESH_REQUIRED"
        assert error.value.detail["model_called"] is False
        assert store.get(child["job_id"])["accepted_rows"] == before["accepted_rows"]
        assert store.list_events(child["job_id"]) == events_before
    else:
        current = _continue(store, child, requested)
        assert store.pending_research_operation_ids(current) == {
            row["operation_id"] for row in before["accepted_rows"][1:]}
        for key in ("accepted_rows", "operator_overrides", "evidence", "query_cache"):
            assert current[key] == before[key]
        assert current["task_context"]["price_basis"] == before["task_context"]["price_basis"]
