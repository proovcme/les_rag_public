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
