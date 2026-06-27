from proxy.services.answer_contract_service import (
    check_contract,
    contract_for_payload,
    decorate_payload,
    scenario_for_payload,
    scenario_for_request,
)
from proxy.services.profile_resolver import resolve


def test_profile_trace_exposes_output_contract():
    trace = resolve(mode="smeta", question="сделай смету").as_trace()
    assert trace["profile_id"] == "object_estimate"
    assert trace["output_contract"] == "estimate_table_v1"


def test_scenario_for_request_prefers_explicit_mode():
    scenario = scenario_for_request(mode="review", question="проверь проект")
    assert scenario["id"] == "normcontrol"
    assert scenario["contract"] == "findings_table_v1"
    assert scenario["progress"]


def test_decorate_payload_adds_scenario_and_contract_from_route():
    payload = {
        "answer": "ok",
        "query_route": {
            "channel": "table",
            "profile": {"profile_id": "auto", "output_contract": "auto"},
        },
        "table_query": {"rows": 2},
    }
    decorated = decorate_payload(payload)
    assert decorated["scenario"]["id"] == "table_query"
    assert decorated["answer_contract"]["id"] == "tool_result_v1"


def test_contract_for_payload_uses_scenario_when_profile_contract_missing():
    payload = {"query_route": {"channel": "review_mode"}}
    assert scenario_for_payload(payload)["id"] == "normcontrol"
    assert contract_for_payload(payload)["id"] == "findings_table_v1"


def test_check_contract_warns_when_required_table_is_missing():
    payload = {
        "answer": "Замечаний несколько, но таблицы нет.",
        "defense": {"rulepack": "gost"},
        "normalized_remarks": [],
        "query_route": {"channel": "review_mode"},
    }
    decorated = decorate_payload(payload)

    assert decorated["answer_contract"]["id"] == "findings_table_v1"
    assert decorated["answer_contract_check"]["status"] == "warn"
    assert "normalized_remarks" in decorated["answer_contract_check"]["missing"]
    assert decorated["answer_contract_check"]["observed"]["table"] is False


def test_check_contract_passes_with_markdown_table_and_sources():
    payload = {
        "answer": "| Пункт | Вывод |\n|---|---|\n| 1 | Ок |",
        "sources": ["doc.pdf"],
        "source_map": {"Источник 1": {"file": "doc.pdf"}},
        "crag_status": "VERIFIED",
        "query_route": {"channel": "rag"},
    }
    check = check_contract(payload, {"id": "x", "expects": ["answer", "sources", "source_map"], "tables": "required", "evidence": "required"})

    assert check["status"] == "pass"
    assert check["observed"]["table"] is True
