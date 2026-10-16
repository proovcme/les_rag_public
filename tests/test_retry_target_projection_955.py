"""Explicit retry projects exact identities; empty or legacy scope remains literal."""

import copy

import pytest

from proxy.services.lsr_result_readiness_service import build_lsr_result_readiness
from sovushka.pages.chat import lsr_explicit_resume_reopen_payload, merge_lsr_resume_payload
from tests.lsr_citation_support import cited_all


def _job(status="complete", **changes):
    return {"job_id": "own-job", "status": status,
            "identity": {"session_id": "own-chat", "attachment_id": "own-source"},
            "remaining": [], "accepted_rows": [], "held_packet": {}, **changes}


def _resume(**changes):
    return {"job_id": "own-job", "session_id": "own-chat", "question": "Literal original task", **changes}


def _work(source, operation_id, *, norm_status="EXACT", norm_code="ГЭСН01-01-001-01"):
    return {"source_row": source, "operation_id": operation_id, "row_role": "work",
            "title": "Literal model work", "unit": "м", "quantity": 2,
            "norm_code": norm_code, "norm_status": norm_status,
            **{field: "yes" for field in ("action_match", "object_match", "condition_match",
                                           "unit_compatible", "composition_covers")}}


def test_fresh_explicit_empty_retry_scope_clears_stale_resume_targets():
    old = _resume(research_locators=["S!R2"], research_operation_ids=["old-op"])
    ready = {"research_locators": [], "research_operation_ids": []}
    before = copy.deepcopy(old)
    merged = merge_lsr_resume_payload(old, ready)
    assert merged["research_locators"] == merged["research_operation_ids"] == []
    assert lsr_explicit_resume_reopen_payload(merged, _job()) is None
    assert old == before


@pytest.mark.parametrize("ids", [None, [], ["open-op"]])
def test_retry_operation_none_empty_and_explicit_identity_remain_distinct(ids):
    ready = {"research_locators": ["S!R2"], "research_operation_ids": ids}
    merged = merge_lsr_resume_payload(_resume(research_operation_ids=["stale-op"]), ready)
    assert merged["research_operation_ids"] == ids
    reopened = lsr_explicit_resume_reopen_payload(merged, _job())
    assert reopened["research_operation_ids"] == ids
    assert reopened["preserve_accepted"] is True


def test_absent_readiness_scope_preserves_legacy_resume_values():
    old = _resume(research_locators=["S!R2"], research_operation_ids=["existing-op"])
    assert merge_lsr_resume_payload(old, {})["research_operation_ids"] == ["existing-op"]
    assert merge_lsr_resume_payload(_resume(remaining_locators=["S!R4"]), {})["research_operation_ids"] is None


@pytest.mark.parametrize("status", ["complete", "failed"])
def test_explicit_terminal_legacy_retry_does_not_require_a_terminal_packet_snapshot(status):
    current = _job(status, accepted_rows=[_work("S!R2", "open-op", norm_status="MISSING", norm_code="")])
    before = copy.deepcopy(current)
    reopened = lsr_explicit_resume_reopen_payload(
        _resume(research_locators=["S!R2"], research_operation_ids=["open-op"]), current)
    assert reopened["reopen_locators"] == ["S!R2"]
    assert reopened["research_operation_ids"] == ["open-op"]
    assert current == before


def test_active_native_cursor_is_not_reopened_by_the_new_legacy_terminal_rule():
    current = _job("paused", remaining=["S!R2"], held_packet={"locators": ["S!R2"], "model_read_pending": True})
    assert lsr_explicit_resume_reopen_payload(
        _resume(research_locators=["S!R2"], research_operation_ids=[]), current) is None


def test_empty_current_pending_scope_overrides_a_historical_reopened_marker():
    current = _job(task_context={"pending_research_locators": []},
                   held_packet={"reopened_locators": ["S!R2"]})
    result = lsr_explicit_resume_reopen_payload(_resume(research_locators=["S!R2"]), current)
    assert result["reopen_locators"] == ["S!R2"]


def test_norm_not_found_retry_keeps_exact_raw_operation_identity_from_projection():
    rows = cited_all([_work("S!R2", "unknown-op"), _work("S!R2", "closed-op"),
                      _work("S!R4", "another-gap", norm_status="MISSING", norm_code="")])
    before = copy.deepcopy(rows)
    readiness = build_lsr_result_readiness(packaged=True, rows=rows,
        missing=["row:S!R2:norm_not_found"], job_status="complete",
        row_projection=[{"locator": "S!R2", "operation_id": "op:unknown-op", "status": "norm_not_found"},
                        {"locator": "S!R2", "operation_id": "op:closed-op", "status": "complete"}])
    assert set(readiness["research_operation_ids"]) == {"unknown-op", "another-gap"}
    assert "closed-op" not in readiness["research_operation_ids"]
    missing_norm = [gap for gap in readiness["dimensions"]["norms"]["gaps"]
                    if gap["kind"] == "cipher_not_in_base"]
    assert len(missing_norm) == 1 and missing_norm[0]["operation_id"] == "unknown-op"
    assert rows == before


def test_norm_not_found_and_another_work_gap_on_same_source_are_both_targeted():
    rows = cited_all([_work("S!R2", "unknown-op"),
                      _work("S!R2", "missing-op", norm_status="MISSING", norm_code="")])
    readiness = build_lsr_result_readiness(packaged=True, rows=rows,
        missing=["row:S!R2:norm_not_found"], job_status="complete",
        row_projection=[{"locator": "S!R2", "operation_id": "op:unknown-op", "status": "norm_not_found"},
                        {"locator": "S!R2", "operation_id": "op:missing-op", "status": "norm_selection_required"}])
    assert set(readiness["research_operation_ids"]) == {"unknown-op", "missing-op"}
    assert len(readiness["dimensions"]["norms"]["gaps"]) == 2


def test_legacy_locator_only_diagnostic_maps_single_work_without_targeting_its_material():
    rows = cited_all([_work("S!R2", "unique-work"),
                      {"source_row": "S!R2", "operation_id": "material", "row_role": "material",
                       "title": "Literal supply", "unit": "м", "quantity": 2, "work_row": "unique-work"}])
    readiness = build_lsr_result_readiness(packaged=True, rows=rows,
        missing=["row:S!R2:norm_not_found"], job_status="complete")
    assert readiness["research_operation_ids"] == ["unique-work"]


def test_ambiguous_legacy_diagnostic_does_not_invent_which_sibling_work_is_missing():
    rows = cited_all([_work("S!R2", "one"), _work("S!R2", "two")])
    readiness = build_lsr_result_readiness(packaged=True, rows=rows,
        missing=["row:S!R2:norm_not_found"], job_status="complete")
    assert readiness["research_operation_ids"] == []
    assert readiness["dimensions"]["norms"]["gaps"][0]["operation_id"] == ""

@pytest.mark.parametrize("reason", ["insufficient_source_data", "no_suitable_candidate"])
@pytest.mark.parametrize("with_projection", [False, True])
def test_calculator_missing_norm_does_not_replace_explicit_model_gap_reason(reason, with_projection):
    row = _work("S!R2", "model-op", norm_status="NEEDS_RESEARCH")
    row.update(gap_reason=reason, open_gap="Literal professional reason")
    before = copy.deepcopy(row)
    readiness = build_lsr_result_readiness(packaged=True, rows=[row],
        missing=["row:S!R2:norm_not_found"], job_status="complete",
        row_projection=[{"locator": "S!R2", "operation_id": "op:model-op", "status": "norm_not_found"}]
        if with_projection else [])
    gaps = readiness["dimensions"]["norms"]["gaps"]
    assert len(gaps) == 1 and gaps[0]["kind"] == reason
    assert gaps[0]["operation_id"] == "model-op"
    assert "Literal professional reason" in gaps[0]["action"]
    assert readiness["research_operation_ids"] == ["model-op"]
    assert row == before


def test_calculator_missing_norm_can_replace_an_unsubstantiated_citation_question():
    row = _work("S!R2", "uncited-op")
    before = copy.deepcopy(row)
    readiness = build_lsr_result_readiness(packaged=True, rows=[row],
        missing=["row:S!R2:norm_not_found"], job_status="complete",
        row_projection=[{"locator": "S!R2", "operation_id": "op:uncited-op", "status": "norm_not_found"}])
    gaps = readiness["dimensions"]["norms"]["gaps"]
    assert len(gaps) == 1 and gaps[0]["kind"] == "cipher_not_in_base"
    assert gaps[0]["operation_id"] == "uncited-op"
    assert readiness["research_operation_ids"] == ["uncited-op"]
    assert row == before
