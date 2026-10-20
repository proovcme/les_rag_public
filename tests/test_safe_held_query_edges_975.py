"""A saved cursor cannot authorize search or substitute another source scope."""
from __future__ import annotations

import copy
from dataclasses import replace
import json

import pytest

from proxy.services import chat_evidence_application_service as app
from proxy.services.model_research_tool_service import ModelResearchToolService
from proxy.services.openai_compatible_transport_service import InferenceResponse
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests.test_chat_model_source_frame import _frames
from tests import test_model_rag_sheet_evidence_reads as fixture
from tests.test_model_query_packet_failure_boundary import _unsupported_declaration


async def _edge_run(tmp_path, monkeypatch, *, all_settled=False, invalid_scope=False):
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "owned-held-edge.sqlite"))
    monkeypatch.setenv("LES_LSR_SYSTEM_CANDIDATE_QUERIES", "off")
    state, calls, searches = {}, [], []
    original_begin = WorkbookResearchJobService.begin_or_resume
    original_application = app.run_chat_evidence_application
    replies = [] if invalid_scope else [
        InferenceResponse(text=_unsupported_declaration(), tool_calls=(), finish_reason="stop", usage={})
        for _ in range(2)]

    def begin(self, identity, **kwargs):
        job = original_begin(self, identity, **kwargs)
        if state:
            return job
        assert kwargs["source_locators"] == ["S!R2", "S!R3"]
        job = self.record_artifact_kind(job["job_id"], declaration=app.decode_model_artifact_kind("artifact_kind: lsr"))
        rows = [{"source_row": locator, "row_role": "work", "work_row": locator,
                 "title": title, "unit": "m", "quantity": quantity, "norm_code": "",
                 "norm_status": "MISSING", "gap_reason": "insufficient_source_data",
                 "open_gap": "Previously authored terminal gap", "evidence_refs": []}
                for locator, title, quantity in [("S!R2", "Cable A", 12), ("S!R3", "Cable B", 3)]
                if all_settled or locator == "S!R2"]
        held = {"sheet": "S", "locators": ["S!R3", "Other!R999"] if invalid_scope else ["S!R3"],
                "queries": ["historical original query Ω"],
                "literal_legacy_extension": {"text": "KEEP_RAW Ж"}}
        job = self.record_packet(job["job_id"], sheet="S", packet_locators=[row["source_row"] for row in rows],
            accepted_rows=rows, evidence=[], remaining=[] if all_settled else ["S!R3"], held_packet=held)
        state.update(store=self, before=copy.deepcopy(job), held=copy.deepcopy(held))
        return job

    async def controlled(request, runtime, boundary):
        factory, env_int = runtime.model_connection_transport, runtime.env_int

        def transport(client, secret_store):
            selected = factory(client, secret_store)

            async def complete(_connection, wire_request):
                calls.append(copy.deepcopy(wire_request))
                assert replies, "invalid held scope must not reach a model call"
                return replies.pop(0)

            selected.complete = complete
            return selected

        return await original_application(request, replace(runtime, model_connection_transport=transport,
            env_int=lambda key, default=0: 1 if key == "LES_CHAT_SOURCE_FRAME_ROWS" else env_int(key, default)), boundary)

    async def forbidden_search(_self, call):
        searches.append(copy.deepcopy(call))
        pytest.fail("neither failed redeclaration nor invalid held scope authorizes a search/read")

    async def forbidden_refresh(*_args, **_kwargs):
        pytest.fail("active resume entered legacy refresh")

    monkeypatch.setattr(WorkbookResearchJobService, "begin_or_resume", begin)
    monkeypatch.setattr(app, "run_chat_evidence_application", controlled)
    monkeypatch.setattr(app, "restore_or_refresh_held_query_hits", forbidden_refresh)
    monkeypatch.setattr(ModelResearchToolService, "execute", forbidden_search)
    run = await fixture._run_sheet(tmp_path, monkeypatch, reads=False, variant="B1_CANDIDATE")
    assert not replies
    after = state["store"].get(state["before"]["job_id"])
    assert after["accepted_rows"] == state["before"]["accepted_rows"]
    assert after["query_cache"] == state["before"]["query_cache"]
    assert any(event["payload"].get("held_packet") == state["held"]
               for event in state["store"].list_events(after["job_id"]))
    state.update(after=after, calls=calls, searches=searches, run=run)
    return state


@pytest.mark.asyncio
async def test_valid_held_packet_redeclares_even_when_all_source_rows_are_already_settled(tmp_path, monkeypatch):
    state = await _edge_run(tmp_path, monkeypatch, all_settled=True)
    assert state["before"]["remaining"] == []
    assert {row["source_row"] for row in state["before"]["accepted_rows"]} == {"S!R2", "S!R3"}
    # These prior terminal rows make the application's recomputed remainder empty too.
    assert len(state["calls"]) == 2 and state["searches"] == []
    assert all(_frames(request)[0]["requested_source_rows"] == ["S!R3"] for request in state["calls"])
    assert state["after"]["held_packet"]["locators"] == ["S!R3"]
    assert state["after"]["held_packet"]["model_query_output_missing"] is True
    assert state["after"]["phase"] == "model_query_format_pending"


@pytest.mark.asyncio
async def test_invalid_held_locator_scope_stops_before_any_model_or_search(tmp_path, monkeypatch):
    state = await _edge_run(tmp_path, monkeypatch, invalid_scope=True)
    assert state["calls"] == state["searches"] == []
    assert state["after"]["status"] == "paused"
    assert state["after"]["held_packet"] == state["held"]
    assert state["run"].result["retrieval_trace"]["held_query_admission"] == {
        "disposition": "invalid_scope", "fresh_search_authorized": False}
