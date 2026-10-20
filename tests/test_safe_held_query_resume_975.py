"""Cached history cannot authorize new searches on the model's behalf."""
from __future__ import annotations

import copy
from dataclasses import replace
import json

import openpyxl
import pytest

from proxy.services import chat_evidence_application_service as app
from proxy.services.model_research_tool_service import ModelResearchToolService
from proxy.services.openai_compatible_transport_service import InferenceResponse
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests.test_chat_model_source_frame import _frames
from tests import test_model_rag_sheet_evidence_reads as fixture
from tests.test_model_query_packet_failure_boundary import _unsupported_declaration


OLD = ["historical original Ω", "historical derived zero-hit Ж", "historical unknown"]
CURRENT = "smeta_literal_query_v1"
NEW_HELD = "S!R3 — model-authored fresh query Ω"
NEW_LATER = "S!R4 — model-authored later query Ж"


def _response(text):
    return InferenceResponse(text=text, tool_calls=(), finish_reason="stop", usage={})


def _answer(locator, title, quantity):
    return json.dumps({"artifact_kind": "lsr", "rows": [{
        "source_row": locator, "row_role": "work", "work_row": locator, "title": title,
        "unit": "m", "quantity": quantity, "norm_code": "", "norm_status": "MISSING",
        "gap_reason": "insufficient_source_data", "open_gap": "Literal model-owned unresolved condition",
        "evidence_refs": [],
    }]}, ensure_ascii=False)


async def _seeded_run(tmp_path, monkeypatch, case):
    """Reuse real attachment/ledger/tool/Governor/export; control only historical state and model replies."""
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "owned-resume.sqlite"))
    monkeypatch.setenv("LES_LSR_SYSTEM_CANDIDATE_QUERIES", "off")
    state, calls, searches, histories, questions = {}, [], [], [], []
    later = case != "cached"
    original_attachment = fixture.preserve_read_attachment
    original_begin = WorkbookResearchJobService.begin_or_resume
    original_application = app.run_chat_evidence_application
    original_search = ModelResearchToolService.execute
    if case == "failure":
        replies = [_response(_unsupported_declaration()), _response(_unsupported_declaration())]
    else:
        replies = ([] if case == "cached" else [_response(json.dumps({
            "artifact_kind": "lsr", "queries": [NEW_HELD]}, ensure_ascii=False))])
        replies.append(_response(_answer("S!R3", "Cable B", 3)))
        if later:
            replies.extend([_response(json.dumps({"artifact_kind": "lsr", "queries": [NEW_LATER]},
                                                ensure_ascii=False)), _response(_answer("S!R4", "Cable C", 9))])

    def attachment(path, **kwargs):
        if later:
            workbook = openpyxl.load_workbook(path)
            workbook.active.append(["Cable C", "m", 9])
            workbook.save(path)
            workbook.close()
        return original_attachment(path, **kwargs)

    def begin(self, identity, **kwargs):
        job = original_begin(self, identity, **kwargs)
        if state:
            return job
        assert kwargs["source_locators"] == (["S!R2", "S!R3", "S!R4"] if later else ["S!R2", "S!R3"])
        job = self.record_artifact_kind(job["job_id"], declaration=app.decode_model_artifact_kind("artifact_kind: lsr"))
        prior = {"source_row": "S!R2", "row_role": "work", "work_row": "S!R2", "title": "Cable A",
                 "unit": "m", "quantity": 12, "norm_code": "", "norm_status": "MISSING",
                 "open_gap": "Previously authored condition", "operation_id": "prior-operation", "revision": 1,
                 "evidence_refs": ["Q7.H1"], "evidence_bindings": {"Q7.H1": "prior-global"}}
        prior_evidence = {"global_evidence_id": "prior-global", "model_evidence_ref": "Q7.H1",
            "content": "PREVIOUS_CITED_WHOLE_BODY Ω", "doc_id": "prior-doc", "doc_name": "prior source",
            "meta": {"global_evidence_id": "prior-global", "model_evidence_ref": "Q7.H1",
                     "model_delivery_status": "delivered", "body_status": "full", "source_ref": "fixture#prior"}}
        proposal = {"schema": "les.model-result-unapplied-proposal.v1", "proposal_id": "prior-proposal",
            "reason": "outside_packet_without_identity", "source_row": "S!R2", "packet_locators": ["Other!R1"],
            "decision": {"source_row": "S!R2", "title": "UNCHANGED_PROPOSAL Ж", "quantity": 99}}
        remaining = ["S!R3", "S!R4"] if later else ["S!R3"]
        job = self.record_packet(job["job_id"], sheet="S", packet_locators=["S!R2"], accepted_rows=[prior],
            evidence=[prior_evidence], unapplied_proposals=[proposal], remaining=remaining)
        hit = {"content": "CACHED_WHOLE_BODY Ω", "doc_id": "cache-doc", "doc_name": "cached source",
               "score": 1.0, "meta": {"dataset_id": "selected", "source_ref": "fixture#cache"}}
        cache = {OLD[0]: [hit], OLD[2]: []}
        if case == "cached":
            cache[OLD[1]] = []  # Current zero-hit is complete cache, not a reason for a fresh search.
        job = self.record_search_cache(job["job_id"], cache, cache_contract=CURRENT)
        if case == "stale":
            job = self.record_search_cache(job["job_id"], {OLD[1]: [hit]}, cache_contract="obsolete-query-contract")
        held = {"sheet": "S", "locators": ["S!R3"], "queries": OLD, "query_offset": 12,
                "query_addresses": {q: ["S!R3"] for q in OLD}, "literal_legacy_extension": {"text": "KEEP_RAW Ω"}}
        if case != "failure":
            held["query_provenance"] = {OLD[0]: "original", OLD[1]: "derived"}  # Third is explicitly unproven.
        # This real checkpoint makes S!R3 more offered than S!R4; a naive adaptive fallback picks the wrong scope.
        job = self.record_packet(job["job_id"], sheet="S", packet_locators=["S!R3"], accepted_rows=[],
                                evidence=[], remaining=remaining, held_packet=held)
        state.update(store=self, identity=identity, before=copy.deepcopy(job), held=copy.deepcopy(held))
        return job

    async def controlled(request, runtime, boundary):
        questions.append(request.req.question)
        factory, env_int = runtime.model_connection_transport, runtime.env_int
        def transport(client, secret_store):
            selected = factory(client, secret_store)
            async def complete(_connection, wire_request):
                calls.append(copy.deepcopy(wire_request))
                assert replies, "the existing held packet must not add a model loop"
                return replies.pop(0)
            selected.complete = complete
            return selected
        return await original_application(request, replace(runtime, model_connection_transport=transport,
            env_int=lambda key, default=0: 1 if key == "LES_CHAT_SOURCE_FRAME_ROWS" else env_int(key, default)),
            replace(boundary, save_chat_history=lambda **row: histories.append(row) or "history-owned"))

    async def observed_search(self, call):
        searches.append(copy.deepcopy(call))
        return await original_search(self, call)

    async def forbidden_refresh(*_args, **_kwargs):
        pytest.fail("active resume entered the legacy search-on-cache-miss helper")

    monkeypatch.setattr(fixture, "preserve_read_attachment", attachment)
    monkeypatch.setattr(WorkbookResearchJobService, "begin_or_resume", begin)
    monkeypatch.setattr(app, "run_chat_evidence_application", controlled)
    monkeypatch.setattr(app, "restore_or_refresh_held_query_hits", forbidden_refresh)
    monkeypatch.setattr(ModelResearchToolService, "execute", observed_search)
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant="B1_CANDIDATE")
    assert not replies
    state.update(run=run, calls=calls, searches=searches, histories=histories, question=questions[0])
    return state


def _preserved(state):
    before, store = state["before"], state["store"]
    after = store.get(before["job_id"])
    prior_id = before["accepted_rows"][0]["operation_id"]
    previous = next(row for row in after["accepted_rows"] if row["operation_id"] == prior_id)
    assert previous == before["accepted_rows"][0]
    assert after["unapplied_proposals"] == before["unapplied_proposals"]
    evidence = {row["global_evidence_id"]: row for row in after["evidence"]}
    for row in before["evidence"]:
        actual = evidence[row["global_evidence_id"]]
        assert {key: actual[key] for key in row if key != "meta"} == {key: value for key, value in row.items() if key != "meta"}
        assert all(actual.get("meta", {}).get(key) == value for key, value in row.get("meta", {}).items())
    for query, cached in before["query_cache"].items():
        assert after["query_cache"][query] == cached
    # Shape contract only; the implementation may choose its descriptive event name.
    audits = [event["payload"] for event in store.list_events(before["job_id"])
              if event["payload"].get("held_packet") == state["held"]]
    assert audits, "full raw old held state must survive success and failed redeclaration in the durable event ledger"
    return after


@pytest.mark.asyncio
async def test_complete_mixed_cache_including_zero_hit_reuses_without_a_search_or_query_round(tmp_path, monkeypatch):
    state = await _seeded_run(tmp_path, monkeypatch, "cached")
    assert len(state["calls"]) == 1 and state["searches"] == []
    assert _frames(state["calls"][0])[0]["requested_source_rows"] == ["S!R3"]
    assert "CACHED_WHOLE_BODY Ω" in str(state["calls"][0].messages)
    assert state["run"].queries == []
    groups = state["run"].result["retrieval_trace"]["query_measurement"]["groups"]
    assert groups.get("model", {}).get("queries", 0) == 0, "missing historical authorship cannot become model ownership"
    assert groups["original"]["queries"] == groups["derived"]["queries"] == 1
    assert sum(group["queries"] for group in groups.values()) == len(OLD)
    _preserved(state)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["stale", "missing"])
async def test_stale_or_missing_cache_redeclares_exact_held_packet_and_preserves_history(tmp_path, monkeypatch, case):
    state = await _seeded_run(tmp_path, monkeypatch, case)
    assert len(state["calls"]) == 4
    frames = [_frames(request)[0] for request in state["calls"]]
    assert [frame["requested_source_rows"] for frame in frames] == [["S!R3"], ["S!R3"], ["S!R4"], ["S!R4"]]
    assert [call["args"]["q"] for call in state["searches"] if call["tool"] == "search_sources"] == [NEW_HELD, NEW_LATER]
    assert state["run"].queries == [NEW_HELD, NEW_LATER]
    assert all(state["question"] in str(request.messages) for request in state["calls"])
    _preserved(state)


@pytest.mark.asyncio
async def test_unproven_plan_and_failed_redeclaration_keep_full_old_audit_and_prior_decisions(tmp_path, monkeypatch):
    state = await _seeded_run(tmp_path, monkeypatch, "failure")
    assert "query_provenance" not in state["held"]  # No ownership schema or provenance may be invented.
    assert len(state["calls"]) == 2 and state["searches"] == []
    assert all(_frames(request)[0]["requested_source_rows"] == ["S!R3"] for request in state["calls"])
    after = _preserved(state)
    assert after["phase"] == "model_query_format_pending" and after["status"] == "paused"
    assert after["held_packet"]["model_query_output_missing"] is True
    assert after["held_packet"]["locators"] == ["S!R3"]
    assert after["accepted_rows"] == state["before"]["accepted_rows"]
    assert after["remaining"] == state["before"]["remaining"]
