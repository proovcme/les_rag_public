"""Every new active search belongs to the model, including under old overrides."""
import json

import pytest

from proxy.services import chat_evidence_application_service as app
from proxy.services import lsr_candidate_query_service as legacy
from proxy.services import runtime_config_registry_service as registry
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests.test_chat_model_source_frame import _frames, _run_frame


KEY = "LES_LSR_SYSTEM_CANDIDATE_QUERIES"
QUERIES = ["[S!R2] Cable A literal [variant Ω]", '"S!R3 Cable B literal"']
QUESTION = "Собери ЛСР по исходнику. Санкт-Петербург, III квартал 2026 года."
ROWS = [
    {"source_row": "S!R2", "row_role": "work", "title": "Literal model A", "unit": "m", "quantity": 12,
     "norm_code": "", "norm_status": "MISSING", "gap_reason": "insufficient_source_data",
     "open_gap": "Literal model question A", "evidence_refs": []},
    {"source_row": "S!R3", "row_role": "work", "title": "Literal model B", "unit": "m", "quantity": 3,
     "norm_code": "", "norm_status": "MISSING", "gap_reason": "insufficient_source_data",
     "open_gap": "Literal model question B", "evidence_refs": []},
]


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B1_CANDIDATE", "B0_DIRECT"])
async def test_old_on_factor_cannot_activate_a_code_query_producer(tmp_path, monkeypatch, variant):
    monkeypatch.setenv(KEY, "on")
    async def forbidden(**_kwargs):
        pytest.fail("active chat called the historical code-authored query producer")
    monkeypatch.setattr(app, "_execute_system_candidate_queries", forbidden)
    run = await _run_frame(tmp_path, monkeypatch, cap=2, reads=False, variant=variant,
        question=QUESTION, query_declaration=json.dumps({"artifact_kind": "lsr", "queries": QUERIES}, ensure_ascii=False),
        final_answer=json.dumps({"artifact_kind": "lsr", "rows": ROWS}, ensure_ascii=False))
    assert run.queries == QUERIES, "each literal model query must reach the existing search tool once"
    assert len(run.requests) == 2 and not run.responses, "retirement must not add a model cycle"
    frames = [_frames(request) for request in run.requests]
    assert all(len(items) == 1 for items in frames) and frames[0] == frames[1]
    assert frames[0][0]["requested_source_rows"] == ["S!R2", "S!R3"]
    assert all(QUESTION in str(request.messages) for request in run.requests)
    trace = run.result["retrieval_trace"]
    assert not trace.get("system_candidate_queries", {}).get("sheets")
    assert len(run.executions) == 1
    if variant == "B1_CANDIDATE":
        assert set(trace["query_measurement"]["groups"]) == {"model"}
        assert trace["query_measurement"]["groups"]["model"]["queries"] == len(QUERIES)
        job = WorkbookResearchJobService().get(trace["workbook_research_job"]["job_id"])
        for actual, authored in zip(job["accepted_rows"], ROWS, strict=True):
            assert {key: actual[key] for key in authored} == authored


def test_historical_candidate_switch_is_off_without_an_override(monkeypatch):
    monkeypatch.delenv(KEY, raising=False)
    assert legacy.system_candidate_queries_enabled() is False
    assert legacy.candidate_queries_enabled_for_turn({"mode": "estimator"}) is False


def test_registered_old_switch_discloses_the_inactive_production_boundary(monkeypatch):
    monkeypatch.delenv(KEY, raising=False)
    registry.declared_env_defaults.cache_clear()
    try:
        row = registry._factor(KEY, {})
        assert row["declared_default"] == row["effective_value"] == "off"
        assert row["secret"] is False and row["restart_required"] is False
        text = (row["label"] + " " + row["help_text"]).lower()
        assert "истор" in text and ("неактив" in text or "не используется" in text)
    finally:
        registry.declared_env_defaults.cache_clear()


def _observe_execution_payloads(monkeypatch):
    """Observe the actual typed-reader boundary, not policy flags or hit metadata."""
    import copy
    from dataclasses import replace
    from proxy.services.model_research_tool_service import ModelResearchToolService

    original = ModelResearchToolService.execute
    observed = []

    async def execute(self, call):
        result = await original(self, call)
        if call.get("tool") != "search_sources":
            return result
        trace = {**(result.retrieval_trace or {}), "returned_candidates": len(result.chunks),
                 "reranked": True, "rerank_status": "applied", "rerank_deferred": False,
                 "measurement_id": "owned-reader-result-" + str(len(observed) + 1)}
        payload = {**result.payload, "trace": trace}
        observed.append(copy.deepcopy(payload))
        return replace(result, payload=payload, retrieval_trace=trace)

    monkeypatch.setattr(ModelResearchToolService, "execute", execute)
    return observed


def _assert_execution_projection(actual, expected):
    keys = ("schema", "tool", "operation", "inputs", "status", "trace")
    assert [{k: row.get(k) for k in keys} for row in actual] == [
        {k: row.get(k) for k in keys} for row in expected]
    assert [row["result"]["count"] for row in actual] == [row["result"]["count"] for row in expected]
    assert [[hit["content"] for hit in row["result"]["hits"]] for row in actual] == [
        [hit["content"] for hit in row["result"]["hits"]] for row in expected]


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B1_CANDIDATE", "B0_DIRECT"])
async def test_model_query_execution_trace_retains_reader_measurement_without_changing_queries(
        tmp_path, monkeypatch, variant):
    observed = _observe_execution_payloads(monkeypatch)
    run = await _run_frame(tmp_path, monkeypatch, cap=2, reads=False, variant=variant,
        question=QUESTION, query_declaration=json.dumps({"artifact_kind": "lsr", "queries": QUERIES}),
        final_answer=json.dumps({"artifact_kind": "lsr", "rows": ROWS}))
    assert run.queries == QUERIES and len(run.requests) == 2 and not run.responses
    assert all("owned-reader-result-" not in str(request.messages) for request in run.requests)
    assert len(observed) == len(QUERIES)
    _assert_execution_projection(run.result["retrieval_trace"]["tool_loop"].get("results", []), observed)
    if variant == "B1_CANDIDATE":
        job = WorkbookResearchJobService().get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
        for actual, authored in zip(job["accepted_rows"], ROWS, strict=True):
            assert {key: actual[key] for key in authored} == authored


@pytest.mark.asyncio
async def test_sheet_query_trace_accumulates_execution_results_across_packets(tmp_path, monkeypatch):
    from tests.test_model_rag_sheet_evidence_reads import _run_sheet

    observed = _observe_execution_payloads(monkeypatch)
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, packet_count=2)
    assert run.queries == run.declared_queries and len(observed) == 4
    assert len(run.requests) == 8 and not run.responses
    assert all("owned-reader-result-" not in str(request.messages) for request in run.requests)
    _assert_execution_projection(run.result["retrieval_trace"]["tool_loop"].get("results", []), observed)


@pytest.mark.asyncio
async def test_cached_query_result_is_visible_without_inventing_fresh_rrf_or_rerank(tmp_path, monkeypatch):
    original = WorkbookResearchJobService.begin_or_resume

    def begin(self, identity, **kwargs):
        job = original(self, identity, **kwargs)
        return self.record_search_cache(job["job_id"], {QUERIES[0]: []},
                                        cache_contract="smeta_literal_query_v2")

    monkeypatch.setattr(WorkbookResearchJobService, "begin_or_resume", begin)
    observed = _observe_execution_payloads(monkeypatch)
    run = await _run_frame(tmp_path, monkeypatch, cap=2, reads=False,
        question=QUESTION, query_declaration=json.dumps({"artifact_kind": "lsr", "queries": QUERIES}),
        final_answer=json.dumps({"artifact_kind": "lsr", "rows": ROWS}))
    assert run.queries == QUERIES[1:] and len(run.requests) == 2 and not run.responses
    results = run.result["retrieval_trace"]["tool_loop"].get("results", [])
    assert len(results) == 2
    assert results[0] == {"schema": "les_tool_result_v1", "tool": "search_sources",
                          "status": "missing", "result": {"count": 0, "cached": True}}
    _assert_execution_projection(results[1:], observed)
    assert len(observed) == 1, "only a real reader call can supply execution measurement"


@pytest.mark.asyncio
@pytest.mark.parametrize("with_hit", [False, True], ids=["empty-result", "with-card"])
@pytest.mark.parametrize("cache_contract,replay", [
    ("smeta_literal_query_v1", False),
    ("smeta_literal_query_v2", True),
], ids=["old-ranking-contract", "current-ranking-contract"])
async def test_sheet_model_query_replays_only_the_current_norm_ranking_contract(
        tmp_path, monkeypatch, with_hit, cache_contract, replay):
    original = WorkbookResearchJobService.begin_or_resume
    stale_marker = "previous-ranking-card-body"
    cached_hits = [{
        "content": stale_marker,
        "doc_name": "Previously returned norm card",
        "score": 1.0,
        "meta": {"norm_code": "TEST-OLD", "norm_key": "TEST:OLD", "source_ref": "test-base"},
    }] if with_hit else []

    def begin(self, identity, **kwargs):
        job = original(self, identity, **kwargs)
        return self.record_search_cache(job["job_id"], {QUERIES[0]: cached_hits},
                                        cache_contract=cache_contract)

    monkeypatch.setattr(WorkbookResearchJobService, "begin_or_resume", begin)
    observed = _observe_execution_payloads(monkeypatch)
    run = await _run_frame(tmp_path, monkeypatch, cap=2, reads=False,
        question=QUESTION, query_declaration=json.dumps({"artifact_kind": "lsr", "queries": QUERIES}),
        final_answer=json.dumps({"artifact_kind": "lsr", "rows": ROWS}))

    assert run.queries == (QUERIES[1:] if replay else QUERIES), (
        "an old ranking result, including zero hits, cannot replace the model's current literal search")
    assert len(run.requests) == 2 and not run.responses, "cache invalidation must not add a model cycle"
    results = run.result["retrieval_trace"]["tool_loop"].get("results", [])
    if replay:
        assert results[0] == {"schema": "les_tool_result_v1", "tool": "search_sources",
                              "status": "ok" if with_hit else "missing",
                              "result": {"count": int(with_hit), "cached": True}}
        _assert_execution_projection(results[1:], observed)
        assert len(observed) == 1
    else:
        _assert_execution_projection(results, observed)
        assert len(observed) == len(QUERIES)
        assert all(stale_marker not in str(request.messages) for request in run.requests)

    job = WorkbookResearchJobService().get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
    for actual, authored in zip(job["accepted_rows"], ROWS, strict=True):
        assert {key: actual[key] for key in authored} == authored
    if not replay:
        entry = job["query_cache"][QUERIES[0]]
        assert entry["contract"] == "smeta_literal_query_v2"
        assert {"contract": cache_contract, "hits": cached_hits} in entry["superseded"]


@pytest.mark.parametrize("dedicated,expected", [
    (True, "smeta_literal_query_v2"),
    (False, "shared_native_query_v1"),
])
def test_norm_ranking_contract_changes_without_probing_or_changing_shared_retrieval(dedicated, expected):
    from proxy.services.model_research_tool_service import ModelResearchToolService

    def forbidden(*_args, **_kwargs):
        pytest.fail("reading the algorithm cache contract must not query an index or service")

    reader = ModelResearchToolService(
        retrieve=forbidden, frozen_dataset_ids=("selected-dataset",), retrieval_kwargs={},
        fallback=forbidden, smeta_norm_retrieve=forbidden if dedicated else None)

    assert reader.cache_contract == expected
