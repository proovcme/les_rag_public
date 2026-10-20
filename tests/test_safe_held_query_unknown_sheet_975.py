"""A mismatched saved sheet cannot select a different source packet."""
from __future__ import annotations

import pytest

from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from tests.test_safe_held_query_edges_975 import _edge_run


@pytest.mark.asyncio
async def test_unknown_held_sheet_stops_before_model_dispatch_and_retains_raw_audit(tmp_path, monkeypatch):
    original_record = WorkbookResearchJobService.record_packet

    def seed_mismatched_sheet(self, job_id, **kwargs):
        held = kwargs.get("held_packet")
        if isinstance(held, dict) and held.get("literal_legacy_extension") == {"text": "KEEP_RAW Ж"}:
            # One otherwise valid real source locator: the sheet mismatch is the only scope defect.
            # Mutate the fixture's same held object so its independent audit expectation is literal.
            held["sheet"] = "Other"
            held["locators"] = ["S!R3"]
        return original_record(self, job_id, **kwargs)

    monkeypatch.setattr(WorkbookResearchJobService, "record_packet", seed_mismatched_sheet)
    state = await _edge_run(tmp_path, monkeypatch, invalid_scope=True)
    assert state["before"]["held_packet"]["sheet"] == "Other"
    assert state["before"]["held_packet"]["locators"] == ["S!R3"]
    assert state["calls"] == state["searches"] == []
    assert state["after"]["held_packet"] == state["held"]
    assert state["run"].result["retrieval_trace"]["held_query_admission"] == {
        "disposition": "invalid_scope", "fresh_search_authorized": False}
