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


@pytest.mark.parametrize("damage", ["marker_only", "snapshot_only", "invalid_snapshot"])
def test_pending_model_revision_protocol_and_snapshot_are_an_atomic_valid_pair_983(tmp_path, damage):
    store, _, before = _job(tmp_path)
    pending = _checkpoint(before)
    pending["revision_transport"] = "application_snapshot_v1"
    pending["model_revision_snapshot"] = {"schema": "les.model-revision-snapshot.v1",
        "packet_id": pending["scope"]["packet_id"], "packet_locators": ["S!R3"], "operations": []}
    if damage == "marker_only":
        pending.pop("model_revision_snapshot")
    elif damage == "snapshot_only":
        pending.pop("revision_transport")
    else:
        pending["model_revision_snapshot"]["packet_id"] = "foreign-packet"
    with pytest.raises(WorkbookResearchJobError, match="PENDING_PROOF_FIELDS_INVALID"):
        _writer(store)(before["job_id"], held_packet=_held(pending), evidence=[EVIDENCE])
    assert store.get(before["job_id"])["held_packet"] == before["held_packet"]
    assert store.get(before["job_id"])["accepted_rows"] == before["accepted_rows"]


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


@pytest.mark.parametrize("damage", ["missing_map_entry", "moved_source", "missing_rows",
    "native_context", "nonempty_original_id", "invented_base_revision"])
def test_proof_address_snapshot_rejects_inconsistent_or_protocol_state_atomically_982(tmp_path, damage):
    from proxy.services.proof_operation_identity_service import (
        proof_operation_context,
        stage_proof_operations,
    )

    store, _, before = _job(tmp_path)
    pending = _checkpoint(before)
    rows, issued = stage_proof_operations([deepcopy(NEW)])
    pending.update(proof_rows=rows, proof_operation_identities=issued,
                   proof_operation_identity=proof_operation_context(rows, issued, before["accepted_rows"]))
    identifier = next(iter(issued))
    if damage == "missing_map_entry":
        pending["proof_operation_identities"] = {}
    elif damage == "moved_source":
        issued[identifier]["source_row"] = "S!R99"
    elif damage == "missing_rows":
        pending.pop("proof_rows")
    elif damage == "native_context":
        pending["proof_operation_identity"]["native_exchanges"] = [{"role": "assistant", "content": OPAQUE}]
    elif damage == "nonempty_original_id":
        issued[identifier].update(operation_id_present=True, original_operation_id="op_foreign")
    else:
        pending["proof_operation_identity"]["operations"][0]["expected_revision"] = 2

    with pytest.raises(WorkbookResearchJobError, match="PENDING_PROOF_FIELDS_INVALID"):
        _writer(store)(before["job_id"], held_packet=_held(pending), evidence=[EVIDENCE])

    after = store.get(before["job_id"])
    assert after["held_packet"] == before["held_packet"]
    assert after["accepted_rows"] == before["accepted_rows"]
    assert OPAQUE not in json.dumps(after, ensure_ascii=False)


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


def _assert_staged_terminal_schema_matches_proof_context(request, *, expected_ids=None):
    from proxy.services.model_evidence_read_contract import model_evidence_read_tool_schemas
    from proxy.services.structured_extract import validate

    payload = _proof_payload(request)
    assert payload is not None
    operations = payload["proof_operation_identity"]["operations"]
    issued = {row["operation_id"] for row in operations if row["identity_status"] == "uncommitted"}
    durable = {row["operation_id"] for row in operations if row["identity_status"] == "committed"}
    assert issued and all(identifier.startswith("proof_") for identifier in issued)
    if expected_ids is not None:
        assert issued == expected_ids
    readers = model_evidence_read_tool_schemas()
    assert list(request.tools[:len(readers)]) == readers
    terminals = [tool for tool in request.tools if tool["function"]["name"] == "build_lsr_workbook"]
    assert len(terminals) == 1
    params = terminals[0]["function"]["parameters"]
    row = params["properties"]["decisions"]["items"]
    assert issued | durable <= set(row["properties"]["operation_id"]["enum"])
    for field in ("work_row", "covered_by_work_id"):
        assert issued.isdisjoint(row["properties"][field].get("enum", []))
        for identifier in issued:
            authored = {"source_row": operations[0]["source_row"], "row_role": "work",
                        "title": "Literal independent operation", "operation_id": "",
                        "expected_revision": None, field: identifier}
            args = {"attachment_id": params["properties"]["attachment_id"]["enum"][0],
                    "decisions": [authored]}
            assert validate(args, params), "a proof address must not become a parent reference"
    return issued


@pytest.mark.asyncio
async def test_actual_norm_proof_terminal_advertises_staged_ids_before_and_after_native_read_984(tmp_path, monkeypatch):
    from tests.test_model_rag_sheet_evidence_reads import RESOURCE_A

    # A mismatched citation needs proof without forcing an unrelated admitted
    # pointer read. The provider chooses one real price read in that same turn.
    answer = SECOND_NORM_ANSWER.replace("Q2.H1", "Q1.H1")
    read = _native("read_resource_price", code=RESOURCE_A)
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, distinct_norms=True,
        group_char_budget=7000, final_answer=answer, proof_replies=[
            InferenceResponse(text="", tool_calls=(read,), finish_reason="tool_calls", usage={}),
            InferenceResponse(text=answer, tool_calls=(), finish_reason="stop", usage={}),
        ])
    proof_requests = [request for request in run.requests if _proof_payload(request) is not None]
    assert len(run.requests) == 4 and len(proof_requests) == 2 and not run.responses
    ids = _assert_staged_terminal_schema_matches_proof_context(proof_requests[0])
    _assert_staged_terminal_schema_matches_proof_context(proof_requests[1], expected_ids=ids)
    assert any(message.get("tool_call_id") == read["id"] for message in proof_requests[1].messages)


@pytest.mark.asyncio
async def test_actual_proof_native_terminal_captures_and_restores_the_advertised_addresses_984(tmp_path, monkeypatch):
    from proxy.services.model_evidence_read_contract import model_evidence_read_tool_schemas
    from proxy.services.model_lsr_result_contract import BASE_FIELDS, MATCH_FIELDS, SELECTED_NORM_FIELDS
    from proxy.services.structured_extract import validate

    captured, authored = [], []
    original = app.BoundModelChatRunner.complete

    async def observe(self, **kwargs):
        request = kwargs["request"]
        if _proof_payload(request) is not None:
            captured.append(request)
        return await original(self, **kwargs)

    monkeypatch.setattr(app.BoundModelChatRunner, "complete", observe)
    answer = SECOND_NORM_ANSWER.replace("Q2.H1", "Q1.H1")

    def native_proof_reply():
        request = captured[-1]
        payload = _proof_payload(request)
        issued_rows = payload["proof_operation_identity"]["operations"]
        rows = deepcopy(app.parse_model_rag_result(answer)[1])
        for row, identity in zip(rows, issued_rows, strict=True):
            assert row["source_row"] == identity["source_row"]
            row.update(operation_id=identity["operation_id"], work_row=row["source_row"],
                       norm_status="NEEDS_RESEARCH", open_gap="Literal unresolved proof condition",
                       coverage="Literal model source basis", nr_sp_rule_id="",
                       **{field: "unknown" for field in MATCH_FIELDS})
        args = {"attachment_id": "read_123456abcdef", "decisions": rows}
        terminal = next(tool for tool in request.tools if tool["function"]["name"] == "build_lsr_workbook")
        assert validate(args, terminal["function"]["parameters"]) == []
        authored.extend(deepcopy(rows))
        return InferenceResponse(text="", tool_calls=(_native("build_lsr_workbook", **args),),
                                 finish_reason="tool_calls", usage={})

    run = await _run_sheet(tmp_path, monkeypatch, reads=False, distinct_norms=True,
        group_char_budget=7000, final_answer=answer, proof_replies=[native_proof_reply])
    assert len(run.requests) == 3 and len(captured) == 1 and not run.responses
    # The query did not declare a kind. Only the authored LSR answer promotes
    # the two compact carriers to one complete LSR carrier for its proof.
    readers = model_evidence_read_tool_schemas()
    initial_tools = list(run.requests[1].tools)
    assert initial_tools[:len(readers)] == readers
    assert [tool["function"]["name"] for tool in initial_tools[len(readers):]] == [
        "build_vor_workbook", "build_lsr_workbook"]
    initial_lsr = initial_tools[-1]["function"]["parameters"]["properties"]["decisions"]["items"]
    assert "norm_code" not in initial_lsr["properties"]
    proof_tools = list(captured[0].tools)
    assert proof_tools[:len(readers)] == readers
    assert [tool["function"]["name"] for tool in proof_tools[len(readers):]] == ["build_lsr_workbook"]
    proof_row = proof_tools[-1]["function"]["parameters"]["properties"]["decisions"]["items"]
    assert set(BASE_FIELDS + SELECTED_NORM_FIELDS) <= set(proof_row["properties"])
    assert any(set(BASE_FIELDS + SELECTED_NORM_FIELDS) <= set(clause.get("then", {}).get("required", []))
               for clause in proof_row["allOf"])
    ids = _assert_staged_terminal_schema_matches_proof_context(captured[0])
    terminal_trace = [item for item in run.result["retrieval_trace"]["workbook_terminal_transport"]
                      if item["purpose"] == "sheet_pass_norm_proof"]
    assert len(terminal_trace) == 1 and terminal_trace[0]["transport_complete"] is True
    assert {row["operation_id"] for row in json.loads(terminal_trace[0]["raw_arguments"])["decisions"]} == ids
    job = WorkbookResearchJobService().get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert len(job["accepted_rows"]) == 2 and not job["unapplied_proposals"]
    for actual, returned in zip(job["accepted_rows"], authored, strict=True):
        assert actual["operation_id"] not in ids and actual["revision"] == 1
        assert {field: actual[field] for field in returned if field != "operation_id"} == {
            field: value for field, value in returned.items() if field != "operation_id"}


@pytest.mark.asyncio
async def test_actual_pending_proof_terminal_reuses_issued_ids_after_restart_984(tmp_path, monkeypatch):
    run, store, before, seen, interrupted, _ = await _pause_during_proof(tmp_path, monkeypatch, "resource_group")
    ids = _assert_staged_terminal_schema_matches_proof_context(interrupted)
    pending = before["held_packet"]["pending_proof"]
    assert set(pending["proof_operation_identities"]) == ids
    assert before["accepted_rows"] == []
    resumed = await run.resume_same_request(question="Продолжи это же задание по тому же прикреплённому документу.")
    _assert_staged_terminal_schema_matches_proof_context(seen[-1], expected_ids=ids)
    assert _proof_payload(seen[-1]) == _proof_payload(interrupted)
    current = WorkbookResearchJobService(store.db_path).get(resumed["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert len(current["accepted_rows"]) == 2
    assert all(row["operation_id"] not in ids for row in current["accepted_rows"])
    assert "pending_proof" not in current["held_packet"] and not run.responses


@pytest.mark.asyncio
async def test_direct_baseline_does_not_invent_staged_proof_or_remove_native_read_carriers_984(tmp_path, monkeypatch):
    from proxy.services.model_evidence_read_contract import model_evidence_read_tool_schemas

    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant="B0_DIRECT", distinct_norms=True,
        group_char_budget=7000, final_answer=SECOND_NORM_ANSWER)
    assert len(run.requests) == 2 and not run.responses
    assert not any(_proof_payload(request) for request in run.requests)
    readers = model_evidence_read_tool_schemas()
    assert list(run.requests[-1].tools[:len(readers)]) == readers
    terminal = next(tool for tool in run.requests[-1].tools if tool["function"]["name"] == "build_lsr_workbook")
    identity = terminal["function"]["parameters"]["properties"]["decisions"]["items"]["properties"]["operation_id"]
    assert not any(isinstance(value, str) and value.startswith("proof_") for value in identity["enum"])


async def _revision_snapshot_review(tmp_path, monkeypatch):
    """Use the real owned job and a human requeue, not a fake admission result."""
    kind = "vor"
    initial = json.dumps({"artifact_kind": kind, "rows": [
        {"source_row": "S!R2", "row_role": "work", "title": "Original operation A", "unit": "m",
         "quantity": 12, "coverage": "Original model source basis A", "open_gap": ""},
        {"source_row": "S!R3", "row_role": "work", "title": "Original operation B", "unit": "m",
         "quantity": 3, "coverage": "Original model source basis B", "open_gap": ""},
    ]})
    run = await _run_sheet(tmp_path, monkeypatch, reads=False,
        query_declaration=json.dumps({"artifact_kind": kind, "queries": []}), final_answer=initial)
    store = WorkbookResearchJobService()
    job_id = run.result["retrieval_trace"]["workbook_research_job"]["job_id"]
    before = deepcopy(store.get(job_id)["accepted_rows"])
    assert len(before) == 2 and all(row["revision"] == 1 for row in before)
    store.reopen_locators(job_id, [row["source_row"] for row in before], preserve_accepted=True,
        operation_ids=[row["operation_id"] for row in before], chat_review={
            "message": "Engineer requested a new model review of these exact operations.",
            "decision_author": "user", "review_scope": "locators", "prior_artifact_kind": kind})
    authored = app.parse_model_rag_result(initial)[1]
    by_source = {row["source_row"]: row for row in before}
    for row in authored:
        row.update(operation_id=by_source[row["source_row"]]["operation_id"], expected_revision=2)
    authored[0]["coverage"] = "Literal revised model basis, not an application confirmation"
    return run, store, job_id, before, authored, kind


def _revision_binding_audit(result, store, job_id, operation_id):
    wrappers = result["retrieval_trace"].get("model_revision_bindings", [])
    matching = [(wrapper, item) for wrapper in wrappers for item in wrapper["bindings"]
                if item["operation_id"] == operation_id]
    assert len(matching) == 1
    wrapper, item = matching[0]
    assert wrapper["origin"] == "application" and wrapper["packet_id"]
    assert wrapper["snapshot_schema"] == "les.model-revision-snapshot.v1"
    assert item["snapshot_revision"] == 1
    assert item["authored_revision_fields"] == {"expected_revision": 2}
    events = [event["payload"] for event in store.list_events(job_id, "model_revision_bindings")
              if any(entry["operation_id"] == operation_id and entry["authored_revision_fields"]
                     for entry in event["payload"]["bindings"])]
    assert events == [wrapper], "one durable application event per bound packet, not one event per field"
    return item


@pytest.mark.asyncio
async def test_model_transport_binds_authored_future_revision_to_the_offered_snapshot_983(tmp_path, monkeypatch):
    run, store, job_id, before, authored, kind = await _revision_snapshot_review(
        tmp_path, monkeypatch)
    raw = json.dumps({"artifact_kind": kind, "rows": authored}, ensure_ascii=False)
    frozen = deepcopy(authored)
    run.responses.extend([
        InferenceResponse(text=json.dumps({"artifact_kind": kind, "queries": []}), tool_calls=(), finish_reason="stop", usage={}),
        InferenceResponse(text=raw, tool_calls=(), finish_reason="stop", usage={}),
    ])
    calls = len(run.requests)
    result = await run.resume_same_request(question="Продолжи")
    assert "revision_transport_instruction" in str(run.requests[-1].messages)
    current = store.get(result["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert current["continues_job_id"] == job_id and not current["unapplied_proposals"]
    assert store.get(job_id)["accepted_rows"] == before
    assert len(run.requests) == calls + 2 and not run.responses
    assert [row["operation_id"] for row in current["accepted_rows"]] == [row["operation_id"] for row in before]
    assert [row["revision"] for row in current["accepted_rows"]] == [2, 1]
    for actual, decision in zip(current["accepted_rows"], authored, strict=True):
        assert {key: actual[key] for key in decision if key != "expected_revision"} == {
            key: value for key, value in decision.items() if key != "expected_revision"}
    assert app.parse_model_rag_result(raw)[1] == frozen and authored == frozen
    _revision_binding_audit(result, store, current["job_id"], before[0]["operation_id"])
    assert "application_snapshot_v1" in str(run.requests[-1].messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_fresh_packet_keeps_snapshot_transport_without_irrelevant_revision_instruction_983(tmp_path, monkeypatch, variant):
    rows = [
        {"source_row": "S!R2", "row_role": "work", "title": "Direct literal operation A", "unit": "m",
         "quantity": 12, "coverage": "Literal source basis A", "operation_id": "", "expected_revision": 2},
        {"source_row": "S!R3", "row_role": "work", "title": "Direct literal operation B", "unit": "m",
         "quantity": 3, "coverage": "Literal source basis B", "operation_id": "", "expected_revision": 2},
    ]
    raw = json.dumps({"artifact_kind": "vor", "rows": rows}, ensure_ascii=False)
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
        query_declaration='{"artifact_kind":"vor","queries":[]}', final_answer=raw)
    assert len(run.requests) == 2 and len(run.executions) == 1 and not run.responses
    if variant == "B0_DIRECT":
        assert "workbook_research_job" not in run.result["retrieval_trace"]
    else:
        assert run.result["retrieval_trace"]["workbook_research_job"]["job_id"]
    assert "revision_transport_instruction" not in str(run.requests[-1].messages)
    for actual, authored in zip(run.executions[0][0]["args"]["decisions"], rows, strict=True):
        fields = set(authored) if variant == "B0_DIRECT" else set(authored) - {"operation_id", "expected_revision"}
        assert {key: actual[key] for key in fields} == {key: authored[key] for key in fields}
    wrappers = run.result["retrieval_trace"].get("model_revision_bindings", [])
    assert len(wrappers) == 1 and wrappers[0]["origin"] == "application"
    assert wrappers[0]["snapshot_schema"] == "les.model-revision-snapshot.v1" and wrappers[0]["bindings"] == []
    assert app.parse_model_rag_result(raw)[1] == rows


@pytest.mark.asyncio
async def test_model_revision_binding_does_not_adopt_a_concurrent_store_revision_983(tmp_path, monkeypatch):
    run, store, job_id, before, authored, kind = await _revision_snapshot_review(tmp_path, monkeypatch)
    concurrent = {**before[0], "coverage": "Concurrent operator decision must survive"}
    active_ids = []
    original_begin = WorkbookResearchJobService.begin_or_resume
    def observe_begin(self, identity, **kwargs):
        current = original_begin(self, identity, **kwargs)
        if current.get("continues_job_id") == job_id:
            active_ids.append(current["job_id"])
        return current
    monkeypatch.setattr(WorkbookResearchJobService, "begin_or_resume", observe_begin)
    def complete_after_concurrent_change():
        # Observe the actual returned job; timestamp-tied latest() is not a
        # reliable way to identify the current child in this fast fixture.
        assert active_ids
        active = store.get(active_ids[-1])
        assert active["continues_job_id"] == job_id
        store.record_revision(active["job_id"], operation_id=before[0]["operation_id"], decision=concurrent,
                              base_revision=1, origin="operator")
        return InferenceResponse(text=json.dumps({"artifact_kind": kind, "rows": authored}),
                                 tool_calls=(), finish_reason="stop", usage={})
    run.responses.extend([
        InferenceResponse(text=json.dumps({"artifact_kind": kind, "queries": []}), tool_calls=(), finish_reason="stop", usage={}),
        complete_after_concurrent_change,
    ])
    result = await run.resume_same_request(question="Продолжи")
    current = store.get(result["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert current["continues_job_id"] == job_id and store.get(job_id)["accepted_rows"] == before
    target = next(row for row in current["accepted_rows"] if row["operation_id"] == before[0]["operation_id"])
    assert target["revision"] == 2 and target["coverage"] == concurrent["coverage"]
    assert before[0]["operation_id"] in store.pending_research_operation_ids(current)
    assert any(proposal["reason"] == "operation_revision_mismatch" for proposal in current["unapplied_proposals"])
    _revision_binding_audit(result, store, current["job_id"], before[0]["operation_id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["unknown_id", "foreign_source"])
async def test_model_snapshot_transport_never_repairs_an_unowned_operation_address_983(tmp_path, monkeypatch, damage):
    run, store, job_id, before, authored, kind = await _revision_snapshot_review(tmp_path, monkeypatch)
    if damage == "unknown_id":
        authored[0]["operation_id"] = "op_not_offered_to_this_model"
        reason = "unknown_operation_id"
    else:
        authored[0].update(source_row="S!R3", quantity=3)
        reason = "operation_source_mismatch"
    raw = json.dumps({"artifact_kind": kind, "rows": authored})
    run.responses.extend([
        InferenceResponse(text=json.dumps({"artifact_kind": kind, "queries": []}), tool_calls=(), finish_reason="stop", usage={}),
        InferenceResponse(text=raw, tool_calls=(), finish_reason="stop", usage={}),
    ])
    result = await run.resume_same_request(question="Продолжи")
    current = store.get(result["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert current["continues_job_id"] == job_id and store.get(job_id)["accepted_rows"] == before
    assert current["accepted_rows"] == before
    assert any(proposal["reason"] == reason and
               {key: proposal["decision"][key] for key in authored[0]} == authored[0]
               for proposal in current["unapplied_proposals"])


@pytest.mark.asyncio
async def test_actual_pending_proof_keeps_the_same_model_revision_snapshot_after_restart_983(tmp_path, monkeypatch):
    # Reuse the existing unread-card proof journey. Replaying already-read
    # group cards would correctly need no proof and would test a false lifecycle.
    run, store, paused_at, _, _, raw = await _pause_during_proof(tmp_path, monkeypatch, "norm")
    pending = paused_at["held_packet"]["pending_proof"]
    assert pending["proof_previous_model_answer"] == raw
    assert pending.get("revision_transport") == "application_snapshot_v1"
    snapshot = pending.get("model_revision_snapshot")
    assert snapshot and snapshot["schema"] == "les.model-revision-snapshot.v1"
    assert snapshot["packet_id"] == pending["scope"]["packet_id"]
    assert snapshot["packet_locators"] == pending["scope"]["locators"]
    assert snapshot["operations"] == [], "this proven fresh proof journey has no prior durable operations"
    store = WorkbookResearchJobService(store.db_path)
    assert store.get(paused_at["job_id"])["held_packet"]["pending_proof"]["model_revision_snapshot"] == snapshot
    calls, queries = len(run.requests), list(run.queries)
    resumed = await run.resume_same_request(question="Продолжи это же задание по тому же прикреплённому документу.")
    current = store.get(resumed["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert run.queries == queries and len(run.requests) == calls + 1 and not run.responses
    assert len(current["accepted_rows"]) == 2 and all(row["revision"] == 1 for row in current["accepted_rows"])
    assert not current["unapplied_proposals"] and "pending_proof" not in current["held_packet"]
    assert snapshot["operations"] == []
    assert "revision_transport_instruction" not in str(run.requests[-1].messages)


@pytest.mark.parametrize("concurrent_after_pause", [False, True])
def test_durable_pending_snapshot_binds_its_old_base_instead_of_latest_after_restart_983(tmp_path, concurrent_after_pause):
    from proxy.services.model_result_packet_service import bind_model_result_revisions

    store, identity, before = _job(tmp_path)
    previous = before["accepted_rows"][0]
    authored = {**PRIOR, "operation_id": previous["operation_id"], "expected_revision": 2,
                "coverage": "Literal changed model decision"}
    frozen = deepcopy(authored)
    snapshot = {"schema": "les.model-revision-snapshot.v1", "packet_id": "owned-packet-S-R2",
        "packet_locators": ["S!R2"], "operations": [
            {"operation_id": previous["operation_id"], "source_row": "S!R2", "revision": 1}]}
    pending = _checkpoint(before)
    pending["scope"].update(packet_id="owned-packet-S-R2", locators=["S!R2"])
    pending.update(revision_transport="application_snapshot_v1", model_revision_snapshot=deepcopy(snapshot),
        proof_previous_model_answer=json.dumps({"artifact_kind": "lsr", "rows": [authored]}))
    held = _held(pending)
    held.update(packet_id="owned-packet-S-R2", locators=["S!R2"])
    _writer(store)(before["job_id"], held_packet=held, evidence=[EVIDENCE])
    store.pause(before["job_id"])
    store = WorkbookResearchJobService(store.db_path)
    if concurrent_after_pause:
        store.record_revision(before["job_id"], operation_id=previous["operation_id"],
            decision={**PRIOR, "coverage": "Concurrent operator decision while paused"}, base_revision=1, origin="operator")
    resumed = store.begin_or_resume(identity, source_locators=["S!R2", "S!R3"])
    restored = resumed["held_packet"]["pending_proof"]
    assert restored["model_revision_snapshot"] == snapshot
    bound, audit = bind_model_result_revisions([authored], restored["model_revision_snapshot"])
    assert authored == frozen and bound[0]["expected_revision"] == 1
    assert audit[0]["authored_revision_fields"] == {"expected_revision": 2}
    current = store.record_packet(before["job_id"], sheet="S", packet_locators=["S!R2"], accepted_rows=bound,
        evidence=[EVIDENCE], remaining=["S!R3"], enforce_packet_scope=True)
    actual = current["accepted_rows"][0]
    assert actual["operation_id"] == previous["operation_id"] and actual["revision"] == 2
    if concurrent_after_pause:
        assert actual["coverage"] == "Concurrent operator decision while paused"
        assert any(item["reason"] == "operation_revision_mismatch" for item in current["unapplied_proposals"])
    else:
        assert actual["coverage"] == authored["coverage"] and not current["unapplied_proposals"]
    assert actual["quantity"] == previous["quantity"] == 12


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


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,stop_at", [("norm", 3), ("resource_group", 5)])
async def test_uncommitted_proof_addresses_are_checkpointed_and_reused_after_resume_982(
    tmp_path, monkeypatch, kind, stop_at,
):
    is_group = kind == "resource_group"
    if is_group:
        _group_book(monkeypatch)
    answer = WORK_ANSWER if is_group else SECOND_NORM_ANSWER
    run = await _run_sheet(
        tmp_path, monkeypatch, reads=is_group, distinct_norms=not is_group,
        group_char_budget=None if is_group else 7000, final_answer=answer,
        budget_stop_at=stop_at,
        proof_replies=[InferenceResponse(text=answer, tool_calls=(), finish_reason="stop", usage={})],
    )
    assert run.result["status"] == 429
    store = WorkbookResearchJobService()
    current = store.get(run.result["error"]["job_id"])
    pending = current["held_packet"]["pending_proof"]
    assert current["accepted_rows"] == [], "proof addresses do not admit decisions"
    assert pending["proof_previous_model_answer"] == answer
    staged = pending["proof_rows"]
    issued = pending["proof_operation_identities"]
    identifiers = {row["operation_id"] for row in staged}
    assert len(identifiers) == len(staged) == len(issued) == 2
    assert identifiers == set(issued)
    from proxy.services.proof_operation_identity_service import restore_proof_operations
    restored = restore_proof_operations(staged, issued)
    assert all("operation_id" not in row for row in restored)
    assert [row["source_row"] for row in restored] == ["S!R2", "S!R3"]
    queries, calls = list(run.queries), len(run.requests)

    resumed = await run.resume_same_request(question="Продолжи это же задание по тому же прикреплённому документу.")

    assert run.queries == queries and len(run.requests) == calls + 1
    delivered = _proof_payload(run.requests[-1])["proof_operation_identity"]
    assert delivered["schema"] == "les.proof-operation-identities.v1"
    assert {row["operation_id"] for row in delivered["operations"]} == identifiers
    assert all(row["committed"] is False and "expected_revision" not in row
               for row in delivered["operations"])
    final = store.get(resumed["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert "pending_proof" not in final["held_packet"]
    assert len(final["accepted_rows"]) == 2
    assert all(row["operation_id"] not in identifiers for row in final["accepted_rows"])
    assert all(row["revision"] == 1 for row in final["accepted_rows"])
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
    proof_payload = {"proof_previous_model_answer": answer,
                     "proof_operation_identity": pending["proof_operation_identity"]}
    assert _proof_payload(interrupted) == proof_payload
    assert set(proof_payload["proof_operation_identity"]) == {"schema", "instruction", "operations"}
    assert proof_payload["proof_operation_identity"]["schema"] == "les.proof-operation-identities.v1"
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
    assert _proof_payload(resumed_request) == proof_payload
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
