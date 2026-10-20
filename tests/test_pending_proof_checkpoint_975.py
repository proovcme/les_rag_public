"""A durable pending proof preserves the answer without accepting operations."""
from copy import deepcopy
import asyncio
import json

import pytest

from proxy.routers.chat import workbook_research_transport_view
from proxy.routers import chat
from proxy.services import chat_evidence_application_service as app
from proxy.services.openai_compatible_transport_service import InferenceResponse
from proxy.services.workbook_research_job_service import WorkbookResearchJobError, WorkbookResearchJobService
from tests.test_model_rag_sheet_evidence_reads import _run_sheet, _native, NORM_CODE, NORM_CODE_B
from tests.test_sheet_proof_context_admission_967 import WORK_ANSWER, _group_book
from tests.test_norm_card_proof_request_930 import SECOND_NORM_ANSWER


OPAQUE = "SYNTHETIC_PRIOR_NATIVE_REASONING_MUST_NOT_BE_SAVED_975"
PRIOR = {"source_row": "S!R2", "row_role": "work", "title": "Existing authored work",
         "unit": "m", "quantity": 12, "norm_status": "MISSING", "open_gap": "Existing authored question"}
NEW = {"source_row": "S!R3", "row_role": "work", "title": 'Literal author text "reasoning_content" stays data',
       "unit": "m", "quantity": "0", "norm_code": "literal-model-code", "norm_status": "NEEDS_RESEARCH",
       "open_gap": "Literal model question", "evidence_refs": ["Q1.H1"],
       "evidence_bindings": {"Q1.H1": "global-proof-975"}}
EVIDENCE = {"global_evidence_id": "global-proof-975", "model_evidence_ref": "Q1.H1",
            "content": "Literal complete source/card bytes Ω", "doc_id": "owned-card", "doc_name": "owned",
            "score": 1.0, "meta": {"global_evidence_id": "global-proof-975", "model_evidence_ref": "Q1.H1"}}
PRESET = {"input_token_limit": 100000, "generation_reserve_tokens": 8192,
          "safety_reserve_tokens": 100, "reasoning_enabled": False}


def _job(tmp_path):
    store = WorkbookResearchJobService(tmp_path / "owned-pending-proof.sqlite")
    identity = store.identity(session_id="pending-proof-owner", attachment_id="read_123456abcdef",
        source_sha256="a" * 64, dataset_ids=["selected"], profile_revision_id="profile:r1",
        model_identity="model", model_connection_revision_id="conn:r1", question="Literal original task")
    current = store.begin_or_resume(identity, source_locators=["S!R2", "S!R3"])
    current = store.record_packet(current["job_id"], sheet="S", packet_locators=["S!R2"],
        accepted_rows=[deepcopy(PRIOR)], evidence=[], remaining=["S!R3"])
    return store, identity, current


def _checkpoint(current):
    return {"schema": "les.pending-workbook-proof.v1", "purpose": "sheet_pass_norm_proof",
        "scope": {"packet_id": "owned-packet-S-R3", "locators": ["S!R3"],
                  "source_sha256": current["identity"]["source_sha256"], "dataset_ids": ["selected"],
                  "profile_revision_id": "profile:r1", "model_connection_revision_id": "conn:r1"},
        "execution_preset": deepcopy(PRESET), "proof_previous_model_answer": json.dumps({"artifact_kind": "lsr", "rows": [NEW]}, ensure_ascii=False),
        "proof_request": "Literal existing proof request Ω", "finish_reason": "stop", "attempt": 1,
        "admitted_evidence_refs": [{"evidence_ref": "Q1.H1", "global_evidence_id": "global-proof-975"}]}


def _writer(store):
    writer = getattr(store, "record_pending_proof", None)
    assert callable(writer), "pending proof needs a non-pausing held-only checkpoint seam"
    return writer


def _held(pending):
    return {"sheet": "S", "locators": ["S!R3"], "packet_id": "owned-packet-S-R3",
        "queries": ["literal model query"], "query_offset": 0,
        "query_provenance": {"literal model query": "model"},
        "pending_proof": {**deepcopy(pending), "query_hits": [["literal model query", [deepcopy(EVIDENCE)]]]}}


def test_completed_answer_is_durable_before_proof_without_status_ids_or_counter_changes_975(tmp_path):
    store, identity, before = _job(tmp_path)
    writer = _writer(store)
    pending = _checkpoint(before)
    frozen = deepcopy(pending)
    held = _held(pending)
    writer(before["job_id"], held_packet=held, evidence=[deepcopy(EVIDENCE)])
    current = store.get(before["job_id"])
    assert current["status"] == before["status"] == "running"
    assert current["accepted_rows"] == before["accepted_rows"] and current["remaining"] == before["remaining"]
    assert current["stall_guard"] == before["stall_guard"]
    assert current["held_packet"]["pending_proof"]["proof_previous_model_answer"] == pending["proof_previous_model_answer"]
    assert current["held_packet"]["pending_proof"] == held["pending_proof"]
    assert current["evidence"] == [EVIDENCE] and pending == frozen
    assert NEW["norm_status"] == "NEEDS_RESEARCH" and "operation_id" not in NEW
    assert not any(event["event_type"] == "model_evidence_read" for event in store.list_events(before["job_id"]))
    store.pause(before["job_id"])
    restarted = WorkbookResearchJobService(store.db_path)
    resumed = restarted.begin_or_resume(identity, source_locators=["S!R2", "S!R3"])
    assert resumed["held_packet"]["pending_proof"] == held["pending_proof"]
    assert resumed["accepted_rows"] == before["accepted_rows"]


@pytest.mark.parametrize("field,value", [("packet_id", "another-packet"), ("locators", ["S!R2"]),
    ("source_sha256", "b" * 64), ("dataset_ids", ["another-selected-dataset"]),
    ("profile_revision_id", "profile:r2"), ("model_connection_revision_id", "conn:r2")])
def test_pending_proof_cannot_be_loaded_for_another_packet_or_immutable_scope_975(tmp_path, field, value):
    store, _, before = _job(tmp_path)
    writer = _writer(store)
    pending = _checkpoint(before)
    held = _held(pending)
    writer(before["job_id"], held_packet=held, evidence=[EVIDENCE])
    changed = deepcopy(held)
    changed["pending_proof"]["scope"][field] = value
    with pytest.raises(WorkbookResearchJobError, match="PENDING_PROOF_SCOPE_CHANGED"):
        writer(before["job_id"], held_packet=changed, evidence=[EVIDENCE])
    assert store.get(before["job_id"])["held_packet"]["pending_proof"] == held["pending_proof"]
    assert store.get(before["job_id"])["accepted_rows"] == before["accepted_rows"]


def test_pending_proof_rejects_changed_preset_without_rewriting_or_clearing_it_975(tmp_path):
    store, _, before = _job(tmp_path)
    writer = _writer(store)
    pending = _checkpoint(before)
    held = _held(pending)
    writer(before["job_id"], held_packet=held, evidence=[EVIDENCE])
    changed = deepcopy(held)
    changed["pending_proof"]["execution_preset"]["generation_reserve_tokens"] = 8193
    with pytest.raises(WorkbookResearchJobError, match="PENDING_PROOF_PRESET_CHANGED"):
        writer(before["job_id"], held_packet=changed, evidence=[EVIDENCE])
    assert store.get(before["job_id"])["held_packet"]["pending_proof"] == held["pending_proof"]


@pytest.mark.parametrize("field,value", [("reasoning_content", OPAQUE),
    ("native_exchanges", [{"role": "assistant", "reasoning_content": OPAQUE}])])
def test_checkpoint_never_persists_prior_native_reasoning_or_protocol_chain_975(tmp_path, field, value):
    store, _, before = _job(tmp_path)
    writer = _writer(store)
    held = _held(_checkpoint(before))
    held["pending_proof"][field] = value
    with pytest.raises(WorkbookResearchJobError, match="PENDING_PROOF_FIELDS_INVALID"):
        writer(before["job_id"], held_packet=held, evidence=[EVIDENCE])
    public = store.get(before["job_id"])
    assert OPAQUE not in json.dumps(public, ensure_ascii=False)
    assert OPAQUE not in json.dumps(store.list_events(before["job_id"]), ensure_ascii=False)
    for view in ("full", "progress"):
        assert OPAQUE not in json.dumps(workbook_research_transport_view(public, view=view), ensure_ascii=False)
    assert public["accepted_rows"] == before["accepted_rows"]


def test_normal_packet_admission_clears_pending_proof_once_and_preserves_prior_operations_975(tmp_path):
    store, _, before = _job(tmp_path)
    writer = _writer(store)
    pending = _checkpoint(before)
    writer(before["job_id"], held_packet=_held(pending), evidence=[EVIDENCE])
    after = store.record_packet(before["job_id"], sheet="S", packet_locators=["S!R3"],
        accepted_rows=[deepcopy(NEW)], evidence=[EVIDENCE], remaining=[], held_packet={}, enforce_packet_scope=True)
    assert "pending_proof" not in after["held_packet"]
    assert len(after["accepted_rows"]) == 2
    assert after["accepted_rows"][0] == before["accepted_rows"][0]
    added = after["accepted_rows"][1]
    assert {key: added[key] for key in NEW} == NEW
    assert type(added["quantity"]) is str and added["quantity"] == "0"
    ids = [row["operation_id"] for row in after["accepted_rows"]]
    assert len(set(ids)) == 2 and added["norm_status"] == "NEEDS_RESEARCH"


def test_saved_evidence_reconstructs_the_same_exact_global_binding_without_alias_reassignment_975(tmp_path):
    store, _, before = _job(tmp_path)
    writer = _writer(store)
    pending = _checkpoint(before)
    writer(before["job_id"], held_packet=_held(pending), evidence=[EVIDENCE])
    restored = store.get(before["job_id"])["held_packet"]["pending_proof"]
    chunks = [app.evidence_chunk_from_record(record) for record in store.get(before["job_id"])["evidence"]]
    assert chunks[0].content == EVIDENCE["content"]
    assert chunks[0].meta["model_evidence_ref"] == "Q1.H1"
    assert chunks[0].meta["global_evidence_id"] == restored["admitted_evidence_refs"][0]["global_evidence_id"]
    assert json.loads(restored["proof_previous_model_answer"])["rows"][0]["evidence_bindings"] == NEW["evidence_bindings"]


def _proof_payload(request):
    for message in request.messages:
        for line in str(message.get("content") or "").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and "proof_previous_model_answer" in value:
                return value
    return None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,stop_at", [("norm", 3), ("resource_group", 5)])
async def test_cloud_budget_pause_preserves_completed_answer_for_pending_proof_975(tmp_path, monkeypatch, kind, stop_at):
    is_group = kind == "resource_group"
    if is_group:
        _group_book(monkeypatch)
    answer = WORK_ANSWER if is_group else SECOND_NORM_ANSWER
    run = await _run_sheet(tmp_path, monkeypatch, reads=is_group, distinct_norms=not is_group,
        group_char_budget=None if is_group else 7000, final_answer=answer, budget_stop_at=stop_at,
        proof_replies=[InferenceResponse(text=answer, tool_calls=(), finish_reason="stop", usage={})])
    assert run.result["status"] == 429
    store = WorkbookResearchJobService()
    current = store.get(run.result["error"]["job_id"])
    assert current["status"] == "paused"
    assert current["held_packet"]["pending_proof"]["proof_previous_model_answer"] == answer
    queries, calls = list(run.queries), len(run.requests)
    resumed = await run.resume_same_request(question="Продолжи это же задание по тому же прикреплённому документу.")
    assert run.queries == queries and len(run.requests) == calls + 1
    assert "pending_proof" not in store.get(resumed["retrieval_trace"]["workbook_research_job"]["job_id"])["held_packet"]
    assert len(run.executions) == 1 and not run.responses


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["norm", "resource_group"])
async def test_invalid_native_terminal_keeps_preproof_answer_for_explicit_resume_975(tmp_path, monkeypatch, kind):
    is_group = kind == "resource_group"
    if is_group:
        _group_book(monkeypatch)
    answer = WORK_ANSWER if is_group else SECOND_NORM_ANSWER
    invalid = InferenceResponse(text="", tool_calls=(_native("build_lsr_workbook",
        attachment_id="read_foreign", decisions=[]),), finish_reason="tool_calls", usage={})
    run = await _run_sheet(tmp_path, monkeypatch, reads=is_group, distinct_norms=not is_group,
        group_char_budget=None if is_group else 7000, final_answer=answer,
        proof_replies=[invalid, InferenceResponse(text=answer, tool_calls=(), finish_reason="stop", usage={})])
    store = WorkbookResearchJobService()
    current = store.get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert current["status"] == "paused" and current["accepted_rows"] == []
    assert current["held_packet"]["pending_proof"]["proof_previous_model_answer"] == answer
    queries, calls = list(run.queries), len(run.requests)
    await run.resume_same_request(question="Продолжи это же задание по тому же прикреплённому документу.")
    assert run.queries == queries and len(run.requests) == calls + 1
    assert len(run.executions) == 1 and not run.responses


async def _pause_during_proof(tmp_path, monkeypatch, kind, *, after_read=False):
    entered, cleaned = asyncio.Event(), asyncio.Event()
    seen, hung = [], []
    original = app.BoundModelChatRunner.complete
    async def complete(self, **kwargs):
        request = kwargs["request"]
        seen.append(request)
        has_read_reply = any(message.get("tool_call_id") == "proof-read-975" for message in request.messages)
        if _proof_payload(request) and not hung and (not after_read or has_read_reply):
            hung.append(request)
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()
        return await original(self, **kwargs)
    monkeypatch.setattr(app.BoundModelChatRunner, "complete", complete)
    is_group = kind == "resource_group"
    if is_group:
        _group_book(monkeypatch)
    answer = WORK_ANSWER if is_group else SECOND_NORM_ANSWER
    if after_read:
        answer = ("artifact_kind: lsr\n\n"
            "| source_row | row_role | title | unit | quantity | norm_code | evidence_refs |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            f"| S!R2 | work | Literal A | m | 12 | {NORM_CODE} | Q1.H1 |\n"
            f"| S!R3 | work | Literal B | m | 3 | {NORM_CODE_B} | Q2.H1 |")
    replies = []
    if after_read:
        # Exact provider identity matters; this is an actual supplied provider
        # call, not a synthetic read inserted by the application.
        replies.append(InferenceResponse(text="", tool_calls=({"id": "proof-read-975", "type": "function",
            "function": {"name": "read_norm_card", "arguments": '{"evidence_ref":"Q1.H1"}'}},),
            finish_reason="tool_calls", usage={}))
    replies.append(InferenceResponse(text=answer, tool_calls=(), finish_reason="stop", usage={}))
    task = asyncio.create_task(_run_sheet(tmp_path, monkeypatch, reads=is_group, distinct_norms=not is_group,
        group_char_budget=None if is_group else 7000, final_answer=answer, proof_replies=replies,
        reasoning_enabled=after_read, native_reasoning=OPAQUE if after_read else None))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        store = WorkbookResearchJobService()
        current = store.latest(session_id="sheet-session", attachment_id="read_123456abcdef")
        before_pause = deepcopy(current)
        await chat.pause_workbook_research(current["job_id"])
        run = await asyncio.wait_for(task, 5)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert cleaned.is_set()
    return run, store, before_pause, seen, hung[0], answer


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,after_read", [("norm", False), ("resource_group", False), ("norm", True)])
async def test_actual_completed_answer_resumes_only_its_pending_proof_after_pause_975(
        tmp_path, monkeypatch, kind, after_read):
    run, store, before, seen, interrupted, answer = await _pause_during_proof(
        tmp_path, monkeypatch, kind, after_read=after_read)
    pending = before["held_packet"].get("pending_proof")
    assert pending, "the complete original answer must be durable before the next proof await"
    assert before["accepted_rows"] == [] and run.executions == []
    assert pending["proof_previous_model_answer"] == answer and pending["finish_reason"] == "stop"
    assert isinstance(pending["proof_request"], str) and pending["proof_request"]
    assert _proof_payload(interrupted) == {"proof_previous_model_answer": answer}
    phase_message = {"role": "user", "content": pending["proof_request"]}
    assert sum(message == phase_message for message in interrupted.messages) == 1
    if after_read:
        phase_index = next(index for index, message in enumerate(interrupted.messages)
                           if message == phase_message)
        native_indices = [index for index, message in enumerate(interrupted.messages)
                          if message["role"] in {"assistant", "tool"}]
        assert native_indices and phase_index < min(native_indices)
    else:
        assert interrupted.messages[-1] == phase_message
    assert pending["purpose"] == ("sheet_pass_resource_group_proof" if kind == "resource_group" else "sheet_pass_norm_proof")
    assert pending["scope"]["locators"] == ["S!R2", "S!R3"]
    for field in ("source_sha256", "dataset_ids", "profile_revision_id", "model_connection_revision_id"):
        assert pending["scope"][field] == before["identity"][field]
    assert pending["execution_preset"]["generation_reserve_tokens"] == interrupted.max_output_tokens
    assert pending["query_hits"], "resume must reuse the exact owned query groups without redeclaration"
    saved_ids = {record["global_evidence_id"] for record in before["evidence"]}
    assert pending["admitted_evidence_refs"]
    assert all(ref["global_evidence_id"] in saved_ids for ref in pending["admitted_evidence_refs"])
    assert not {"native_exchanges", "reasoning_content"}.intersection(pending)
    assert OPAQUE not in json.dumps(before, ensure_ascii=False)
    assert OPAQUE not in json.dumps(store.list_events(before["job_id"]), ensure_ascii=False)
    queries_before, requests_before = list(run.queries), len(seen)
    # A new service object and explicit new human continuation resume the same
    # proof, with completed reads as evidence and no previous-turn reasoning.
    store = WorkbookResearchJobService(store.db_path)
    resumed = await run.resume_same_request(question="Продолжи это же задание по тому же прикреплённому документу.")
    assert run.queries == queries_before, "no fresh search or query model turn is allowed for this pending packet"
    assert len(seen) == requests_before + 1, "one existing pending proof, no initial answer or extra automatic proof loop"
    resumed_request = seen[-1]
    assert _proof_payload(resumed_request) == {"proof_previous_model_answer": answer}
    assert resumed_request.messages[-1] == phase_message
    assert sum(message == phase_message for message in resumed_request.messages) == 1
    assert not any(message.get("role") in {"assistant", "tool"} for message in resumed_request.messages)
    assert OPAQUE not in str(resumed_request.messages)
    assert (resumed_request.max_output_tokens, resumed_request.temperature, resumed_request.reasoning_enabled) == (
        interrupted.max_output_tokens, interrupted.temperature, interrupted.reasoning_enabled)
    current = store.get(resumed["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert "pending_proof" not in current["held_packet"]
    assert len(current["accepted_rows"]) == 2 and len({row["operation_id"] for row in current["accepted_rows"]}) == 2
    authored = app.parse_model_rag_result(answer)[1]
    for actual, original_row in zip(current["accepted_rows"], authored, strict=True):
        assert {key: actual[key] for key in original_row} == original_row
    assert len(run.executions) == 1 and not run.responses


@pytest.mark.asyncio
async def test_resume_keeps_original_evidence_identity_when_page_capacity_changes_975(tmp_path, monkeypatch):
    run, store, before, seen, interrupted, answer = await _pause_during_proof(tmp_path, monkeypatch, "norm")
    original = {record["model_evidence_ref"]: record["global_evidence_id"] for record in before["evidence"]}
    monkeypatch.setattr(app, "model_rag_group_char_budget", lambda **kwargs: 300000)
    resumed = await run.resume_same_request(question="Продолжи это же задание по тому же прикреплённому документу.")
    current = store.get(resumed["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert len(current["accepted_rows"]) == 2
    for row in current["accepted_rows"]:
        for ref, identity in row.get("evidence_bindings", {}).items():
            assert identity == original[ref], "a saved alias must not be rebound to a newly projected body"
    wire = json.dumps(seen[-1].messages, ensure_ascii=False)
    previous_wire = json.dumps(interrupted.messages, ensure_ascii=False)
    # Compact unread pointers expose their Q aliases, not every internal ID.
    assert all(ref in wire for ref in original)
    assert all(identity in wire for identity in original.values() if identity in previous_wire)


@pytest.mark.asyncio
async def test_pending_answer_replay_never_reenters_initial_evidence_projection_975(tmp_path, monkeypatch):
    run, store, before, seen, interrupted, answer = await _pause_during_proof(tmp_path, monkeypatch, "norm")
    async def forbidden_projection(**kwargs):
        pytest.fail("a completed saved answer cannot re-project its original evidence page")
    monkeypatch.setattr(app, "govern_model_rag_initial_messages", forbidden_projection)
    await run.resume_same_request(question="Продолжи это же задание по тому же прикреплённому документу.")
    assert len(run.executions) == 1 and not run.responses


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["cloud", "capacity"])
async def test_resume_admission_failure_keeps_pending_answer_and_evidence_975(tmp_path, monkeypatch, failure):
    run, store, before, seen, interrupted, answer = await _pause_during_proof(tmp_path, monkeypatch, "norm")
    original_govern = app.govern_model_read_messages_bound
    async def blocked_initial_admission(**kwargs):
        if kwargs.get("phase_instruction") is None:
            if failure == "cloud":
                raise app.CloudBudgetStop("CLOUD_TURN_TOKEN_BUDGET: owned resumed admission")
            raise app.ContextRequiredSectionOverflow(object_ids=("saved-owned-evidence",), budget=1, required_tokens=2)
        return await original_govern(**kwargs)
    monkeypatch.setattr(app, "govern_model_read_messages_bound", blocked_initial_admission)
    prior_calls, prior_searches = len(seen), list(run.queries)
    try:
        resumed = await run.resume_same_request(question="Продолжи это же задание по тому же прикреплённому документу.")
        resumed_job_id = resumed["retrieval_trace"]["workbook_research_job"]["job_id"]
    except app.HTTPException as error:
        assert failure == "cloud" and error.status_code == 429
        resumed_job_id = error.detail["job_id"]
    current = store.get(resumed_job_id)
    assert current["status"] == "paused" and current["accepted_rows"] == []
    assert current["held_packet"]["pending_proof"] == before["held_packet"]["pending_proof"]
    assert len(seen) == prior_calls and run.queries == prior_searches
