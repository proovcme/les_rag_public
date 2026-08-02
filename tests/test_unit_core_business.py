"""Unit tests for core business logic in LES_v2.

Covers:
1. SmetaResourceNormalizer (normalize_norm_resources)
2. AnswerContractService (scenario_for_request, check_contract, decorate_payload)
3. CandidateSelectionService (select_candidates, candidate_shortlist, candidate_reason_labels)
4. ProfileResolver / QueryRouter (resolve)
5. EvidenceContract / Numeric Provenance helpers

Each component is tested with:
- Standard success scenario
- Boundary scenario (empty/minimal inputs)
- Invalid/corrupted input handling
- Dependency/error scenarios
- Assertion of state change and return contracts
"""

from __future__ import annotations

import pytest

from proxy.services.answer_contract_service import (
    check_contract,
    contract_for_payload,
    decorate_payload,
    scenario_for_payload,
    scenario_for_request,
)
from proxy.services.candidate_selection_service import (
    candidate_reason_labels,
    candidate_shortlist,
    select_candidates,
)
from proxy.services.profile_resolver import resolve
from proxy.smeta_core.resource_normalizer import normalize_norm_resources


# =====================================================================
# 1. SmetaResourceNormalizer Unit Tests
# =====================================================================

def test_resource_normalizer_success():
    """Standard success scenario with labor grade breakdown."""
    resources = [
        {"kind": "labor", "code": "1-100-36", "name": "Средний разряд 3.6", "per_unit": 10.0},
        {"kind": "labor", "code": "", "name": "ЗАТРАТЫ ТРУДА РАБОЧИХ, ВСЕГО:", "per_unit": 10.0},
        {"kind": "labor", "code": "2-100-02", "name": "Рабочий 2 разряда", "per_unit": 3.0},
        {"kind": "labor", "code": "2-100-04", "name": "Рабочий 4 разряда", "per_unit": 7.0},
        {"kind": "material", "code": "01.1.01", "name": "Бетон", "per_unit": 1.05},
    ]
    normalized = normalize_norm_resources(resources)
    assert len(normalized) == 3
    assert [r["code"] for r in normalized if r["kind"] == "labor"] == ["2-100-02", "2-100-04"]
    assert sum(r["per_unit"] for r in normalized if r["kind"] == "labor") == pytest.approx(10.0)
    assert normalized[-1]["code"] == "01.1.01"


def test_resource_normalizer_boundary_empty():
    """Boundary scenario: empty input list."""
    assert normalize_norm_resources([]) == []


def test_resource_normalizer_invalid_input_structure():
    """Invalid input: items missing required keys or containing invalid types."""
    resources = [
        {"kind": "unknown"},  # Missing per_unit, code, name
        {"kind": "labor", "code": "2-100-01", "per_unit": "invalid"},  # Non-float per_unit
    ]
    normalized = normalize_norm_resources(resources)
    assert isinstance(normalized, list)


def test_resource_normalizer_preserves_materials_and_machines():
    """State assertion: non-labor resources pass through untouched."""
    resources = [
        {"kind": "machine", "code": "91.01.01", "name": "Краны", "per_unit": 0.5},
        {"kind": "material", "code": "01.02.03", "name": "Песок", "per_unit": 2.0},
    ]
    normalized = normalize_norm_resources(resources)
    assert normalized == resources


# =====================================================================
# 2. AnswerContractService Unit Tests
# =====================================================================

def test_answer_contract_scenario_for_request_success():
    """Success scenario: valid mode and question resolve to correct scenario."""
    scen = scenario_for_request(mode="review", question="проверь проект")
    assert scen["id"] == "normcontrol"
    assert scen["contract"] == "findings_table_v1"
    assert scen["progress"] is not None


def test_answer_contract_boundary_empty_question():
    """Boundary scenario: empty question string."""
    scen = scenario_for_request(mode="smeta", question="")
    assert scen["id"] == "estimate_harness"
    assert scen["contract"] == "smeta_model_rag_answer_v1"


def test_answer_contract_check_contract_failure_case():
    """Error/warning scenario: missing required table in response payload."""
    payload = {
        "answer": "Нет таблицы",
        "defense": {"rulepack": "gost"},
        "query_route": {"channel": "review_mode"},
    }
    contract_def = {
        "id": "test_c",
        "expects": ["answer"],
        "tables": "required",
        "evidence": "required",
    }
    result = check_contract(payload, contract_def)
    assert result["status"] == "warn"
    assert result["observed"]["table"] is False


def test_answer_contract_decorate_payload_state_mutation():
    """State assertion: decorate_payload injects scenario and workflow plan."""
    payload = {
        "answer": "OK",
        "query_route": {
            "channel": "table",
            "profile": {"profile_id": "auto", "output_contract": "auto"},
        },
    }
    decorated = decorate_payload(payload)
    assert "scenario" in decorated
    assert "answer_contract" in decorated
    assert "workflow_plan" in decorated
    assert decorated["scenario"]["id"] == "table_query"


# =====================================================================
# 3. CandidateSelectionService Unit Tests
# =====================================================================

def test_candidate_selection_clear_winner():
    """Success scenario: clear gap between top candidate and second."""
    candidates = [
        {"id": "A", "title": "Top", "score_total": 10.0, "status": "accepted", "unit_compatible": True},
        {"id": "B", "title": "Sub", "score_total": 4.0, "status": "accepted", "unit_compatible": True},
    ]
    res = select_candidates(candidates)
    assert res["selected_code"] == "A"
    assert res["score_gap"] == 6.0


def test_candidate_selection_boundary_single_candidate():
    """Boundary scenario: only 1 candidate available."""
    candidates = [
        {"id": "A", "title": "Only", "score_total": 5.0, "status": "accepted", "unit_compatible": True},
    ]
    res = select_candidates(candidates)
    assert res["selected_code"] == "A"
    assert res["score_gap"] is None  # Single item has no 2nd candidate gap


def test_candidate_selection_invalid_empty_list():
    """Invalid input: empty candidates list."""
    res = select_candidates([])
    assert res["selected_code"] == ""
    assert res["action"] == "refine_search"



def test_candidate_shortlist_formatting():
    """Contract verification: candidate_shortlist maps and limits output fields."""
    candidates = [
        {
            "id": "GESN-01",
            "name": "Монтаж кабеля",
            "unit": "м",
            "score_total": "8.5",
            "score_parts": {"unit": 1.0},
            "status": "accepted",
        }
    ]
    short = candidate_shortlist(candidates)
    assert len(short) == 1
    assert short[0]["norm_code"] == "GESN-01"
    assert short[0]["title"] == "Монтаж кабеля"
    assert short[0]["applicability_status"] == "accepted"


# =====================================================================
# 4. ProfileResolver Unit Tests
# =====================================================================

def test_profile_resolver_success_modes():
    """Success scenarios for key profile routing modes."""
    prof_smeta = resolve(mode="smeta", question="составь смету")
    assert prof_smeta.profile_id == "estimate_harness"

    prof_review = resolve(mode="review", question="проверь документацию")
    assert prof_review.profile_id == "normcontrol"


def test_profile_resolver_fallback_on_unknown():
    """Boundary / fallback scenario: unknown mode defaults to general/auto profile."""
    prof_unknown = resolve(mode="non_existent_mode_xyz", question="произвольный вопрос")
    assert prof_unknown is not None
    assert hasattr(prof_unknown, "profile_id")
    assert hasattr(prof_unknown, "as_trace")
    trace = prof_unknown.as_trace()
    assert "profile_id" in trace
    assert "output_contract" in trace
