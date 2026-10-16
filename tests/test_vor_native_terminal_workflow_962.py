"""Actual governed B0/B1 provider tool responses reach ordinary VOR packaging."""
from copy import deepcopy
import inspect
import json

import pytest

from proxy.services.openai_compatible_transport_service import InferenceResponse
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests import test_model_rag_sheet_evidence_reads as fixture


MARKER = "NATIVE_TERMINAL_FIXTURE_962"


def _rows():
    return [{"source_row": locator, "row_role": "work", "work_row": "", "title": title,
             "quantity": qty, "unit": "m", "open_gap": "", "coverage": 'Literal "scope"\nkept',
             "conversion_source": "Literal source basis"}
            for locator, title, qty in (("S!R2", "Cable A", 12), ("S!R3", "Cable B", 3))]


def _native_response(monkeypatch, *, extra=(), attachment="read_123456abcdef", finish="tool_calls", visible="Literal completed commentary", duplicate=False, artifact_kind="vor", rows=None):
    original = fixture.InferenceResponse
    decisions = _rows() if rows is None else rows
    raw = json.dumps({"attachment_id": attachment, "decisions": decisions}, ensure_ascii=False)
    if duplicate:
        raw = raw.replace('"quantity": 12', '"quantity": 12, "quantity": 13', 1)
    native = {"id": "terminal962", "type": "function", "function": {"name": f"build_{artifact_kind}_workbook", "arguments": raw}}

    def response(*args, **kwargs):
        if kwargs.get("text") == MARKER:
            return InferenceResponse(text=visible, tool_calls=(native, *extra),
                                     finish_reason=finish, usage={"completion_tokens": 120})
        return original(*args, **kwargs)
    monkeypatch.setattr(fixture, "InferenceResponse", response)
    return decisions, native


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_native_vor_terminal_is_admitted_packaged_and_does_not_call_model_again(tmp_path, monkeypatch, variant):
    decisions, native = _native_response(monkeypatch)
    before = deepcopy(decisions)
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
        query_declaration=json.dumps({"artifact_kind": "vor", "queries": []}), final_answer=MARKER)
    assert len(run.requests) == 2 and not run.responses
    assert len(run.executions) == 1
    call, result = run.executions[0]
    assert call["tool"] == "build_vor_workbook"
    assert [{key: row[key] for key in before[index]} for index, row in enumerate(call["args"]["decisions"])] == before
    assert run.result["artifact"]["revision_id"] == result["artifact"]["revision_id"]
    assert run.result["artifact"]["artifact_kind"] == "vor_workbook"
    transport = run.result["retrieval_trace"]["workbook_terminal_transport"][-1]
    assert transport["provider_finish_reason"] == "tool_calls"
    assert transport["semantic_finish_reason"] == "stop" and transport["transport_complete"] is True
    assert transport["raw_arguments"] == native["function"]["arguments"]
    schema = next(tool for tool in run.requests[1].tools if tool["function"]["name"] == "build_vor_workbook")
    assert schema["function"]["parameters"]["properties"]["decisions"]["items"]["properties"]["source_row"]["enum"] == ["S!R2", "S!R3"]
    if variant == "B1_CANDIDATE":
        job = WorkbookResearchJobService().get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
        assert len(job["accepted_rows"]) == 2 and job["remaining"] == []
        assert job["document"]["final_revision_id"] == result["artifact"]["revision_id"]
    assert native["function"]["arguments"] == json.dumps({"attachment_id": "read_123456abcdef", "decisions": before}, ensure_ascii=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.parametrize("failure", ["mixed", "attachment", "length", "duplicate"])
async def test_invalid_terminal_never_dispatches_reads_builder_or_another_model_turn(tmp_path, monkeypatch, variant, failure):
    extra = (fixture._native("read_source", evidence_ref="Q1.H1"),) if failure == "mixed" else ()
    _native_response(monkeypatch, extra=extra, attachment="read_foreign" if failure == "attachment" else "read_123456abcdef",
                     finish="length" if failure == "length" else "tool_calls", duplicate=failure == "duplicate")
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
        query_declaration=json.dumps({"artifact_kind": "vor", "queries": []}), final_answer=MARKER)
    assert len(run.requests) == 2 and not run.responses
    assert not run.executions and not run.exact_reads
    assert not run.result.get("artifact")
    diagnostic = run.result["retrieval_trace"]["workbook_terminal_transport"][-1]
    assert diagnostic["channel"] == "native_terminal_invalid"
    assert diagnostic["reason"] == {
        "mixed": "WORKBOOK_TERMINAL_MULTIPLE_CALLS", "attachment": "WORKBOOK_TERMINAL_ATTACHMENT_MISMATCH",
        "length": "WORKBOOK_TERMINAL_PROVIDER_INCOMPLETE", "duplicate": "WORKBOOK_TERMINAL_DUPLICATE_JSON_FIELD"}[failure]
    if variant == "B1_CANDIDATE":
        job = WorkbookResearchJobService().get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
        assert job["status"] == "paused" and job["accepted_rows"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_plain_vor_carrier_is_unchanged(tmp_path, monkeypatch, variant):
    before = _rows()
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
        query_declaration=json.dumps({"artifact_kind": "vor", "queries": []}),
        final_answer=json.dumps({"artifact_kind": "vor", "rows": before}))
    assert len(run.requests) == 2 and len(run.executions) == 1
    assert not run.result["retrieval_trace"].get("workbook_terminal_transport")
    assert [{key: row[key] for key in before[index]} for index, row in enumerate(run.executions[0][0]["args"]["decisions"])] == before


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_native_terminal_after_exact_reads_finishes_without_a_reply_turn(tmp_path, monkeypatch, variant):
    _native_response(monkeypatch)
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=True, variant=variant,
        query_declaration=json.dumps({"artifact_kind": "vor", "queries": ["Literal norm query"]}), final_answer=MARKER)
    assert len(run.requests) == 4 and not run.responses and len(run.executions) == 1
    assert len(run.exact_reads) == 1
    trace = run.result["retrieval_trace"]
    assert trace["workbook_terminal_transport"][-1]["provider_finish_reason"] == "tool_calls"
    assert not trace["tool_loop"].get("evidence_read_stop")


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_native_terminal_scope_keeps_catalog_rows_available_to_exact_source_reads(tmp_path, monkeypatch, variant):
    from proxy.services import chat_evidence_application_service as app

    monkeypatch.setattr(app, "configured_source_frame_rows", lambda _env: 1)
    original = fixture.InferenceResponse
    authored_rows = _rows()

    def response(*args, **kwargs):
        native = kwargs.get("tool_calls") or ()
        if native and native[0]["function"]["name"] == "read_norm_card":
            return InferenceResponse(text="", tool_calls=(fixture._native("read_source", source_row="S!R3"),),
                                     finish_reason="tool_calls", usage={})
        if kwargs.get("text") == MARKER:
            return InferenceResponse(text="", tool_calls=(fixture._native("build_vor_workbook",
                attachment_id="read_123456abcdef", decisions=authored_rows),), finish_reason="tool_calls", usage={})
        return original(*args, **kwargs)

    monkeypatch.setattr(fixture, "InferenceResponse", response)
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=True, variant=variant,
        query_declaration=json.dumps({"artifact_kind": "vor", "queries": []}), final_answer=MARKER,
        budget_stop_at=5 if variant == "B1_CANDIDATE" else None)
    receipts = run.result["retrieval_trace"]["tool_loop"]["evidence_reads"]
    source_read = next(item for item in receipts if item["call"]["tool"] == "read_source")
    assert source_read["call"]["args"] == {"source_row": "S!R3"} and source_read["status"] == "ok"
    for request in run.requests[1:4]:
        schema = next(tool for tool in request.tools if tool["function"]["name"] == "build_vor_workbook")
        fields = schema["function"]["parameters"]["properties"]["decisions"]["items"]["properties"]
        assert fields["source_row"]["enum"] == ["S!R2", "S!R3"]
        assert all(locator in fields["work_row"]["enum"] for locator in ("S!R2", "S!R3"))
    if variant == "B0_DIRECT":
        assert run.executions[0][0]["args"]["decisions"][1]["source_row"] == "S!R3"
    else:
        job = WorkbookResearchJobService().get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
        assert {row["source_row"] for row in job["accepted_rows"]} == {"S!R2", "S!R3"}
        assert job["remaining"] == []


@pytest.mark.parametrize("blocked", [
    "no_read", "failed", "incomplete", "foreign_sha", "foreign_file", "different_source",
    "not_authored", "unknown_source", "existing_operation", "closed_anchor", "review", "pending_retry",
])
def test_exact_read_scope_never_reopens_closed_rows_or_escapes_review(blocked):
    from proxy.services import chat_evidence_application_service as app
    from tests.test_model_source_frame_service import _catalog, _row

    catalog = _catalog((_row("S!R2"), _row("Other!R3")))
    rows = [{"source_row": "Other!R3", "row_role": "work", "quantity": 2.5}]
    receipts = [{"call": {"tool": "read_source", "args": {"source_row": "Other!R3"}}, "status": "ok",
                 "trace": {"source_row": "Other!R3", "body_complete": True,
                           "source_sha256": catalog.source_file_sha256, "source_file_id": catalog.source_file_id}}]
    existing, job, review = [], None, False
    if blocked == "no_read": receipts = []
    if blocked == "failed": receipts[0]["status"] = "missing"
    if blocked == "incomplete": receipts[0]["trace"]["body_complete"] = False
    if blocked == "foreign_sha": receipts[0]["trace"]["source_sha256"] = "b" * 64
    if blocked == "foreign_file": receipts[0]["trace"]["source_file_id"] = "another-file"
    if blocked == "different_source": receipts[0]["trace"]["source_row"] = "S!R2"
    if blocked == "not_authored": rows = []
    if blocked == "unknown_source": rows[0]["source_row"] = "Unknown!R3"
    if blocked == "existing_operation": rows[0]["operation_id"] = "previous-id"
    if blocked == "closed_anchor": existing = [{"source_row": "Other!R3", "operation_id": "retained-id"}]
    if blocked == "review": review = True
    if blocked == "pending_retry": job = {"task_context": {"pending_research_locators": ["S!R2"]}}
    before = deepcopy((rows, receipts, existing, job))
    assert app.model_read_result_packet_locators(["S!R2"], rows=rows, receipts=receipts,
        catalog=catalog, existing_rows=existing, review_scope=review, job=job) == ["S!R2"]
    assert (rows, receipts, existing, job) == before


def test_actual_read_of_another_sheet_preserves_only_authored_new_rows_and_source_guards():
    from proxy.services import chat_evidence_application_service as app
    from proxy.services.model_result_packet_service import admit_model_result_packet
    from tests.test_model_source_frame_service import _catalog, _row

    catalog = _catalog((_row("S!R2"), _row("Other!R3")))
    row = {"source_row": "Other!R3", "row_role": "work", "title": "Literal operation", "quantity": 2.5}
    receipt = {"call": {"tool": "read_source", "args": {"source_row": "Other!R3"}}, "status": "ok",
               "trace": {"source_row": "Other!R3", "body_complete": True,
                         "source_sha256": catalog.source_file_sha256, "source_file_id": catalog.source_file_id}}
    before = deepcopy(row)
    packet = app.model_read_result_packet_locators(["S!R2"], rows=[row], receipts=[receipt], catalog=catalog)
    assert packet == ["S!R2", "Other!R3"]
    admitted = admit_model_result_packet([row], packet_locators=packet)
    assert admitted.accepted_rows == [before] and not admitted.unapplied_proposals
    assert app.sheet_pass_keep_rows(admitted.accepted_rows, sheet="S", catalog=catalog, errors=[],
        artifact_kind="vor", additional_locators={"Other!R3"}) == [before]
    error = "source_quantity_mismatch:Other!R3"
    kept = app.sheet_pass_keep_rows([row], sheet="S", catalog=catalog, errors=[error], artifact_kind="lsr",
        additional_locators={"Other!R3"})
    assert kept == []
    proposals = app.sheet_pass_rejected_row_proposals([row], kept_rows=kept, sheet="S", catalog=catalog,
        errors=[error], packet_locators=packet, additional_locators={"Other!R3"})
    assert proposals[0]["decision"] == before and row == before


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
@pytest.mark.parametrize("shape", ["markdown", "block_text"])
async def test_second_visible_result_is_a_technical_pause_before_read_or_pack(tmp_path, monkeypatch, variant, shape):
    row = _rows()[0]
    if shape == "markdown":
        visible = "| " + " | ".join(row) + " |\n| " + " | ".join("---" for _ in row)
        visible += " |\n| " + " | ".join(str(value).replace("\n", " ") for value in row.values()) + " |"
    else:
        visible = "\n".join(f"{key}: {str(value).replace(chr(10), ' ')}" for key, value in row.items())
    _native_response(monkeypatch, visible="artifact_kind: vor\n" + visible)
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
        query_declaration=json.dumps({"artifact_kind": "vor", "queries": []}), final_answer=MARKER)
    assert len(run.requests) == 2 and not run.responses and not run.executions
    assert run.result["retrieval_trace"]["workbook_terminal_transport"][-1]["reason"] == "WORKBOOK_TERMINAL_AMBIGUOUS_VISIBLE_RESULT"


@pytest.mark.asyncio
async def test_b0_b1_project_identical_literal_schema_for_same_scope(tmp_path, monkeypatch):
    schemas = []
    for variant in ("B0_DIRECT", "B1_CANDIDATE"):
        case = tmp_path / variant
        case.mkdir()
        with monkeypatch.context() as scoped:
            run = await fixture._run_sheet(case, scoped, reads=False, variant=variant,
                query_declaration=json.dumps({"artifact_kind": "vor", "queries": []}),
                final_answer=json.dumps({"artifact_kind": "vor", "rows": _rows()}))
        schemas.append(next(tool for tool in run.requests[1].tools if tool["function"]["name"] == "build_vor_workbook"))
        prompt = "\n".join(str(item.get("content") or "") for item in run.requests[1].messages)
        assert "Если пользователь не задал формат ответа, завершённые строки ВОР можно передать" in prompt
        assert "Явный формат пользователя сохраняется" in prompt
    assert schemas[0] == schemas[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_declared_lsr_schema_never_advertises_optional_vor_terminal(tmp_path, monkeypatch, variant):
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
        query_declaration=json.dumps({"artifact_kind": "lsr", "queries": ["Literal resource search"]}))
    assert len(run.requests) == 2
    assert all(tool["function"]["name"] != "build_vor_workbook" for tool in run.requests[1].tools)
    assert any(tool["function"]["name"] == "build_lsr_workbook" for tool in run.requests[1].tools)


def _lsr_rows():
    return [{**row, "row_role": "material", "resource_code": code, "norm_code": "", "evidence_refs": [ref]}
            for row, code, ref in zip(_rows(), (fixture.RESOURCE_A, fixture.RESOURCE_B), ("Q1.H1", "Q2.H1"))]


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_native_lsr_terminal_preserves_authored_rows_and_uses_existing_packager(tmp_path, monkeypatch, variant):
    rows, native = _native_response(monkeypatch, artifact_kind="lsr", rows=_lsr_rows())
    before = deepcopy(rows)
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
        query_declaration=json.dumps({"artifact_kind": "lsr", "queries": ["Literal resource search"]}),
        final_answer=MARKER)
    assert len(run.requests) == 2 and not run.responses and len(run.executions) == 1
    call, result = run.executions[0]
    assert call["tool"] == "build_lsr_workbook" and result["artifact"]["artifact_kind"] == "lsr_workbook"
    assert [{key: row[key] for key in before[index]} for index, row in enumerate(call["args"]["decisions"])] == before
    assert run.result["artifact"]["revision_id"] == result["artifact"]["revision_id"]
    transport = run.result["retrieval_trace"]["workbook_terminal_transport"][-1]
    assert transport["raw_arguments"] == native["function"]["arguments"]
    assert transport["provider_finish_reason"] == "tool_calls" and transport["semantic_finish_reason"] == "stop"
    schema = next(tool for tool in run.requests[1].tools if tool["function"]["name"] == "build_lsr_workbook")
    assert set(schema["function"]["parameters"]["properties"]) == {"attachment_id", "decisions"}
    assert result["price_basis"]["actual_book"] == fixture.BOOK


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_opposite_native_terminal_is_a_kind_conflict_not_a_new_workflow(tmp_path, monkeypatch, variant):
    _native_response(monkeypatch)
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
        query_declaration=json.dumps({"artifact_kind": "lsr", "queries": ["Literal resource search"]}), final_answer=MARKER)
    assert len(run.requests) == 2 and not run.responses and not run.executions
    assert run.result["retrieval_trace"]["workbook_terminal_transport"][-1]["reason"] == "WORKBOOK_TERMINAL_ARTIFACT_KIND_CONFLICT"


@pytest.mark.asyncio
async def test_native_ordinary_review_preserves_previous_ids_and_admits_only_authored_revision(tmp_path, monkeypatch):
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False,
        query_declaration=json.dumps({"artifact_kind": "vor", "queries": []}),
        final_answer=json.dumps({"artifact_kind": "vor", "rows": _rows()}))
    store = WorkbookResearchJobService()
    parent_id = run.result["retrieval_trace"]["workbook_research_job"]["job_id"]
    parent = store.get(parent_id)
    old_rows = deepcopy(parent["accepted_rows"])
    request = inspect.getclosurevars(run.resume_same_request).nonlocals["request"]
    request.req.question = "Учти замечание инженера и исправь описание работ без изменения известных объёмов"
    decisions = [{**row, "expected_revision": row["revision"], "coverage": "Explicit revised scope"} for row in old_rows]
    native = fixture._native("build_vor_workbook", attachment_id="read_123456abcdef", decisions=decisions)
    run.responses.extend([
        InferenceResponse(text=json.dumps({"artifact_kind": "vor", "queries": []}), tool_calls=(), finish_reason="stop", usage={}),
        InferenceResponse(text="", tool_calls=(native,), finish_reason="tool_calls", usage={"completion_tokens": 120}),
    ])
    result = await run.resume_same_request()
    assert len(run.requests) == 4 and not run.responses
    current = store.get(result["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert current["continues_job_id"] == parent_id
    assert {row["operation_id"] for row in current["accepted_rows"]} == {row["operation_id"] for row in old_rows}
    assert all(row["revision"] == 2 and row["coverage"] == "Explicit revised scope" for row in current["accepted_rows"])
    assert store.get(parent_id)["accepted_rows"] == old_rows
    schema = next(tool for tool in run.requests[-1].tools if tool["function"]["name"] == "build_vor_workbook")
    links = schema["function"]["parameters"]["properties"]["decisions"]["items"]["properties"]["work_row"]["enum"]
    assert all(row["operation_id"] in links for row in old_rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("identity_present", [True, False])
async def test_lsr_native_review_exposes_identity_contract_and_keeps_revision_guard(tmp_path, monkeypatch, identity_present):
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False,
        query_declaration=json.dumps({"artifact_kind": "lsr", "queries": ["Literal resource search"]}),
        final_answer=json.dumps({"artifact_kind": "lsr", "rows": _lsr_rows()}))
    store = WorkbookResearchJobService()
    parent_id = run.result["retrieval_trace"]["workbook_research_job"]["job_id"]
    old_rows = deepcopy(store.get(parent_id)["accepted_rows"])
    request = inspect.getclosurevars(run.resume_same_request).nonlocals["request"]
    request.req.question = "Review the previous resource decisions and preserve the source quantities"
    decisions = [{**row, "expected_revision": row["revision"], "coverage": "Explicit revised scope",
                  "norm_status": "CONFLICT", "open_gap": "Engineer review requires another norm"} for row in old_rows]
    if not identity_present:
        for row in decisions:
            row.pop("operation_id")
            row.pop("expected_revision")
    raw_rows = deepcopy(decisions)
    native = fixture._native("build_lsr_workbook", attachment_id="read_123456abcdef", decisions=decisions)
    run.responses.extend([
        InferenceResponse(text=json.dumps({"artifact_kind": "lsr", "queries": ["Literal revised resource search"]}),
                          tool_calls=(), finish_reason="stop", usage={}),
        InferenceResponse(text="", tool_calls=(native,), finish_reason="tool_calls", usage={"completion_tokens": 120}),
    ])
    result = await run.resume_same_request()
    assert len(run.requests) == 4 and not run.responses
    current = store.get(result["retrieval_trace"]["workbook_research_job"]["job_id"])
    schema = next(tool for tool in run.requests[-1].tools if tool["function"]["name"] == "build_lsr_workbook")
    row_schema = schema["function"]["parameters"]["properties"]["decisions"]["items"]
    assert {"operation_id", "expected_revision"}.issubset(row_schema["required"])
    assert row_schema["properties"]["operation_id"]["enum"] == ["", *[row["operation_id"] for row in old_rows], None]
    assert row_schema["properties"]["expected_revision"]["type"] == ["integer", "null"]
    if identity_present:
        assert {row["operation_id"] for row in current["accepted_rows"]} == {row["operation_id"] for row in old_rows}
        assert all(row["revision"] == 2 and row["norm_status"] == "CONFLICT" for row in current["accepted_rows"])
        assert not store.pending_research_operation_ids(current)
    else:
        assert current["accepted_rows"] == old_rows
        assert store.pending_research_operation_ids(current) == {row["operation_id"] for row in old_rows}
        assert any(item.get("reason") == "missing_operation_identity" for item in current["unapplied_proposals"])
    assert store.get(parent_id)["accepted_rows"] == old_rows
    assert json.loads(native["function"]["arguments"])["decisions"] == raw_rows
