"""A provider generation limit is distinct from malformed final output."""
from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from proxy.services import chat_evidence_application_service as application
from proxy.services.openai_compatible_transport_service import InferenceResponse
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests.test_model_rag_sheet_evidence_reads import _run_sheet


@pytest.mark.parametrize("reason", ["length", "max_tokens", "length_truncated"])
def test_nonempty_generation_limit_is_reported_without_discarding_visible_output(reason):
    diagnostic = application.model_query_output_diagnostics('{"unfinished":',
        {"finish_reason": reason, "completion_tokens": 8192}, purpose="query", budget={})
    assert diagnostic["generation_limit_reached"] is True
    assert diagnostic["output_incomplete"] is False
    diagnostic["declared_parse"] = {"accepted_count": 0}
    failure = application.model_query_failure("MODEL_QUERY_GENERATION_LIMIT", trace={"model_query_outputs": [diagnostic]},
        session_id="fixture", provider="fixture", model="fixture", final_texts=['{"unfinished":'])
    assert failure.private_query_trace["model_query_outputs"][0]["generation_limit_reached"] is True


@pytest.mark.parametrize("length,accepted,code", [
    (True, 0, "MODEL_QUERY_GENERATION_LIMIT"),
    (False, 0, "MODEL_RAG_QUERY_LIST_EMPTY"),
    (True, 2, "MODEL_RAG_QUERY_LIST_EMPTY"),
])
def test_terminal_classifier_does_not_reclassify_accepted_queries_or_finished_format_failure(length, accepted, code):
    assert application.model_query_empty_failure_code({"generation_limit_reached": length,
        "declared_parse": {"accepted_count": accepted}}) == code


def _limit_transport(monkeypatch, *, rejected, continuation=False):
    original_application = application.run_chat_evidence_application
    calls = []

    async def controlled(request, runtime, boundary):
        factory = runtime.model_connection_transport

        def transport(client, secret_store):
            selected = factory(client, secret_store)
            original_complete = selected.complete

            async def complete(connection, wire_request):
                calls.append(copy.deepcopy(wire_request))
                if rejected:
                    assert len(calls) <= 2, "Only the existing one repair may run"
                    return InferenceResponse(text='{"artifact_kind":"lsr","rows":[{"title":"literal result"}]}', tool_calls=(),
                        finish_reason="length", usage={"completion_tokens": 8192})
                if continuation and len(calls) == 2:
                    return InferenceResponse(text="S!R3 — Cable B", tool_calls=(), finish_reason="stop", usage={})
                response = await original_complete(connection, wire_request)
                return replace(response, text=response.text + "\nunread cut tail", finish_reason="length",
                               usage={"completion_tokens": 8192}) if len(calls) == 1 else response

            selected.complete = complete
            return selected

        return await original_application(request, replace(runtime, model_connection_transport=transport), boundary)

    monkeypatch.setattr(application, "run_chat_evidence_application", controlled)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_zero_accepted_nonempty_length_keeps_bounded_repair_and_generation_pause(tmp_path, monkeypatch, variant):
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "jobs.sqlite"))
    snapshots = {}
    original_begin = WorkbookResearchJobService.begin_or_resume

    def begin(self, identity, **kwargs):
        job = original_begin(self, identity, **kwargs)
        snapshots.update(store=self, before=copy.deepcopy(job))
        return job

    monkeypatch.setattr(WorkbookResearchJobService, "begin_or_resume", begin)
    calls = _limit_transport(monkeypatch, rejected=True)
    with pytest.raises(application.ModelQueryFailure) as caught:
        await _run_sheet(tmp_path, monkeypatch, reads=False, variant=variant)
    assert "MODEL_QUERY_GENERATION_LIMIT" in str(caught.value.detail)
    assert len(calls) == 2
    outputs = caught.value.private_query_trace["model_query_outputs"]
    assert all(row["generation_limit_reached"] and row["declared_parse"]["accepted_count"] == 0 for row in outputs)
    if variant == "B1_CANDIDATE":
        before = snapshots["before"]
        after = snapshots["store"].get(before["job_id"])
        assert after["status"] == "paused" and after["phase"] == "model_query_generation_pending"
        for field in ("accepted_rows", "query_cache", "remaining", "evidence", "identity", "task_context"):
            assert after[field] == before[field], field
    else:
        assert snapshots == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_complete_plain_queries_are_executed_literally_despite_length(tmp_path, monkeypatch, variant):
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "jobs.sqlite"))
    calls = _limit_transport(monkeypatch, rejected=False, continuation=variant == "B1_CANDIDATE")
    run = await _run_sheet(tmp_path, monkeypatch, reads=False, variant=variant,
        query_declaration="S!R2 — Cable A\nS!R3 — Cable B\n")
    output = run.result["retrieval_trace"]["model_query_outputs"][0]
    assert output["generation_limit_reached"] is True
    assert output["declared_parse"]["accepted_count"] == 2
    assert run.queries[:2] == ["S!R2 — Cable A", "S!R3 — Cable B"]
    assert run.queries.count("S!R2 — Cable A") == run.queries.count("S!R3 — Cable B") == 1
    assert len(calls) == (3 if variant == "B1_CANDIDATE" else 2)
