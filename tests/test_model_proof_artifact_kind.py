"""Completed proof replies retain document metadata as well as their rows.

Installed938 retained an LSR table from a proof reply but lost its artifact_kind.
A later source-header packet declared VOR, so it silently selected a VOR exporter.
These tests use the production sheet/proof/job/export path; no model decision is
chosen or repaired by the application.
"""
import inspect
import json

import pytest

from proxy.services import chat_evidence_application_service as app
from proxy.services.openai_compatible_transport_service import InferenceResponse
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests.test_model_rag_sheet_evidence_reads import NORM_CODE_B, _native, _run_sheet
from tests.test_norm_card_proof_request_930 import SECOND_NORM_ANSWER


INITIAL = SECOND_NORM_ANSWER.removeprefix("artifact_kind: lsr\n")
QUERY = '{"artifact_kind":"lsr","queries":["S!R2 — Cable A","S!R3 — Cable B"]}'


def _reply(text, *, finish="stop", calls=()):
    return InferenceResponse(text=text, tool_calls=calls, finish_reason=finish,
                             usage={"completion_tokens": 120})


def _group_round(monkeypatch):
    # A literal synthetic debt only makes the group proof stage reachable.
    # Target accumulation, native continuation, row merging and export are real.
    debt = {"cipher": NORM_CODE_B, "locator": "S!R3", "code": "20.4.01.01",
            "name": "Synthetic resource family", "unit": "m", "total": 1,
            "members": [{"code": "20.4.01.01-0002", "name": "Cable B", "unit": "m",
                         "price_current_eff": 200}], "truncated": False}
    monkeypatch.setattr(app, "resource_group_proof_reads_needed", lambda *a, **kw: [debt])


async def _run_proof(tmp_path, monkeypatch, *, stage, terminal, native=False,
                     initial=INITIAL, query=QUERY, partial=False):
    replies = []
    if stage == "group":
        _group_round(monkeypatch)
        replies.append(_reply(initial))  # the norm proof supplies no new target
    if native:
        replies.append(_reply("artifact_kind: vor", finish="tool_calls",
                              calls=(_native("read_norm_card", evidence_ref="Q2.H1"),)))
    replies.append(terminal)
    return await _run_sheet(tmp_path, monkeypatch, reads=False,
        distinct_norms=True, group_char_budget=7000,
        final_answer=initial, query_declaration=query,
        partial_final=partial, proof_replies=replies)


def _saved_target(run):
    job_id = run.result["retrieval_trace"]["workbook_research_job"]["job_id"]
    job = WorkbookResearchJobService().get(job_id)
    target = run.result["retrieval_trace"]["artifact_target"]
    assert job["task_context"]["artifact_kind_declaration"] == target
    return job, target


@pytest.mark.asyncio
@pytest.mark.parametrize("stage,native", [("norm", False), ("norm", True),
                                          ("group", False), ("group", True)])
async def test_completed_proof_target_is_durable_without_extra_inference(tmp_path, monkeypatch, stage, native):
    run = await _run_proof(tmp_path, monkeypatch, stage=stage, native=native,
                           terminal=_reply(SECOND_NORM_ANSWER))
    job, target = _saved_target(run)
    assert target["artifact_kind"] == "lsr" and target["authority"] == "result"
    assert job["task_context"]["model_artifact_kind"] == "lsr"
    assert [(r["source_row"], r["quantity"]) for r in job["accepted_rows"]] == [("S!R2", 12), ("S!R3", 3)]
    assert len(run.requests) == 3 + (stage == "group") + native
    assert not run.responses and len(run.executions) == 1
    assert run.executions[0][0]["tool"] == "build_lsr_workbook"


@pytest.mark.asyncio
async def test_completed_proof_can_supersede_only_a_query_proposal(tmp_path, monkeypatch):
    run = await _run_proof(tmp_path, monkeypatch, stage="norm",
        query=QUERY.replace('"lsr"', '"vor"'), terminal=_reply(SECOND_NORM_ANSWER))
    _, target = _saved_target(run)
    assert target["artifact_kind"] == "lsr" and target["authority"] == "result"
    assert target["query_declaration"]["artifact_kind"] == "vor"
    assert run.executions[0][0]["tool"] == "build_lsr_workbook"
    assert len(run.requests) == 3 and not run.responses


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["norm", "group"])
async def test_conflicting_completed_proof_keeps_rows_and_blocks_wrong_document(tmp_path, monkeypatch, stage):
    run = await _run_proof(tmp_path, monkeypatch, stage=stage,
        initial=SECOND_NORM_ANSWER,
        terminal=_reply(SECOND_NORM_ANSWER.replace("artifact_kind: lsr", "artifact_kind: vor")))
    job, target = _saved_target(run)
    assert target["status"] == "conflict" and target["artifact_kind"] == ""
    assert {"lsr", "vor"} <= set(target["declarations"])
    assert len(job["accepted_rows"]) == 2
    assert run.result["retrieval_trace"]["model_result"]["packaging_status"] == "pending"
    assert run.executions == [] and not run.responses
    assert len(run.requests) == 3 + (stage == "group")


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["norm", "group"])
async def test_terminal_proof_metadata_survives_row_fallback(tmp_path, monkeypatch, stage):
    run = await _run_proof(tmp_path, monkeypatch, stage=stage,
        terminal=_reply("artifact_kind: lsr\nNo additional row changes."))
    job, target = _saved_target(run)
    assert target["artifact_kind"] == "lsr" and target["authority"] == "result"
    assert len(job["accepted_rows"]) == 2
    assert len(run.requests) == 3 + (stage == "group") and not run.responses


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["norm", "group"])
async def test_length_stopped_proof_is_not_a_completed_document_declaration(tmp_path, monkeypatch, stage):
    run = await _run_proof(tmp_path, monkeypatch, stage=stage,
        terminal=_reply(SECOND_NORM_ANSWER.replace("artifact_kind: lsr", "artifact_kind: vor"), finish="length"))
    _, target = _saved_target(run)
    assert target["artifact_kind"] == "lsr" and target["authority"] == "query"
    assert len(run.requests) == 3 + (stage == "group") and not run.responses


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["norm", "group"])
async def test_stopped_native_proof_does_not_promote_intermediate_metadata(tmp_path, monkeypatch, stage):
    replies = []
    if stage == "group":
        _group_round(monkeypatch)
        replies.append(_reply(INITIAL))
    for index in range(3):
        call = {**_native("read_norm_card", evidence_ref="Q2.H1"), "id": f"proof-read-{index}"}
        replies.append(_reply("artifact_kind: vor", finish="tool_calls", calls=(call,)))
    run = await _run_sheet(tmp_path, monkeypatch, reads=False,
        distinct_norms=True, group_char_budget=7000,
        final_answer=INITIAL, query_declaration=QUERY, proof_replies=replies)
    _, target = _saved_target(run)
    assert run.result["retrieval_trace"]["tool_loop"]["evidence_read_stop"] == "evidence_read_repeat"
    assert target["artifact_kind"] == "lsr" and target["authority"] == "query"
    assert len(run.requests) == 5 + (stage == "group") and not run.responses


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["norm", "group"])
async def test_unknown_native_proof_tool_is_not_a_completed_target(tmp_path, monkeypatch, stage):
    run = await _run_proof(tmp_path, monkeypatch, stage=stage,
        terminal=_reply("artifact_kind: vor", finish="tool_calls",
                        calls=(_native("not_a_reader", code="literal-code"),)))
    job, target = _saved_target(run)
    assert target["artifact_kind"] == "lsr" and target["authority"] == "query"
    assert len(job["accepted_rows"]) == 2
    assert len(run.requests) == 3 + (stage == "group") and not run.responses


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["norm", "group"])
async def test_tool_stopped_proof_without_a_valid_call_is_not_terminal(tmp_path, monkeypatch, stage):
    run = await _run_proof(tmp_path, monkeypatch, stage=stage,
        terminal=_reply("artifact_kind: vor\n" + INITIAL, finish="tool_calls"))
    _, target = _saved_target(run)
    assert target["artifact_kind"] == "lsr" and target["authority"] == "query"
    assert len(run.requests) == 3 + (stage == "group") and not run.responses


@pytest.mark.asyncio
async def test_later_packet_cannot_replace_a_completed_proof_target(tmp_path, monkeypatch):
    def initial(requests):
        if len(requests) == 2:
            return INITIAL
        return json.dumps({"artifact_kind": "vor", "rows": [
            {"source_row": "S!R2", "row_role": "unresolved", "title": "Cable A", "unit": "m",
             "quantity": 12, "norm_code": "", "open_gap": "Literal unresolved decision"},
            {"source_row": "S!R3", "row_role": "unresolved", "title": "Cable B", "unit": "m",
             "quantity": 3, "norm_code": "", "open_gap": "Literal unresolved decision"}]})
    run = await _run_sheet(tmp_path, monkeypatch, reads=False,
        distinct_norms=True, group_char_budget=7000, packet_count=2,
        final_answer=initial, query_declaration=QUERY,
        proof_replies=[_reply(SECOND_NORM_ANSWER)])
    job, target = _saved_target(run)
    assert target["status"] == "conflict" and target["artifact_kind"] == ""
    assert {r["source_row"] for r in job["accepted_rows"]} == {"S!R2", "S!R3", "S!R4", "S!R5"}
    assert run.executions == [] and not run.responses
    assert len(run.requests) == 7


@pytest.mark.asyncio
async def test_plain_resume_restores_completed_proof_target_before_new_packets(tmp_path, monkeypatch):
    partial = "\n".join(SECOND_NORM_ANSWER.splitlines()[:-1])
    run = await _run_proof(tmp_path, monkeypatch, stage="norm",
        terminal=_reply(partial), partial=True)
    job, target = _saved_target(run)
    assert job["remaining"] == ["S!R3"]
    assert target["authority"] == "result"
    first_rows = json.loads(json.dumps(job["accepted_rows"]))
    initial_calls, initial_exports = len(run.requests), len(run.executions)
    request = inspect.getclosurevars(run.resume_same_request).nonlocals["request"]
    request.req.question = "Продолжи"
    run.responses[:] = [_reply('{"artifact_kind":"vor","queries":[]}'), _reply(json.dumps({
        "artifact_kind": "vor", "rows": [{"source_row": "S!R3", "row_role": "unresolved",
            "title": "Cable B", "unit": "m", "quantity": 3, "norm_code": "",
            "open_gap": "Literal unresolved decision"}]}))]
    resumed = await run.resume_same_request()
    store = WorkbookResearchJobService()
    resumed_id = resumed["retrieval_trace"]["workbook_research_job"]["job_id"]
    saved = store.get(resumed_id)
    assert resumed["retrieval_trace"]["artifact_target"]["status"] == "conflict"
    assert saved["task_context"]["artifact_kind_status"] == "conflict"
    assert saved["continues_job_id"] == job["job_id"]
    assert store.get(job["job_id"])["accepted_rows"] == first_rows
    assert saved["accepted_rows"][:1] == first_rows
    assert len(saved["accepted_rows"]) == 2
    assert len(run.requests) == initial_calls + 2 and not run.responses
    assert len(run.executions) == initial_exports
